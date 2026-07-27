"""Pinned-source Taskwarrior installation workflow."""

from dataclasses import dataclass

from lea.installers.taskwarrior.activation import activate_staged_taskwarrior
from lea.installers.taskwarrior.build_execution import (
    TaskwarriorBuildProgressReporter,
    TaskwarriorSourceBuildExecutionResult,
    execute_taskwarrior_source_build,
)
from lea.installers.taskwarrior.build_plan import (
    TaskwarriorBuildTools,
    create_taskwarrior_source_build_plan,
    default_taskwarrior_build_tools,
    validate_taskwarrior_build_dependencies,
)
from lea.installers.taskwarrior.contracts import (
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
)
from lea.installers.taskwarrior.preflight import (
    calculate_sha256,
    run_taskwarrior_installer_preflight,
)
from lea.installers.taskwarrior.records import (
    TaskwarriorInstallationRecord,
    installation_record_matches,
    read_taskwarrior_installation_record,
)
from lea.installers.taskwarrior.runtime_layout import (
    provision_taskwarrior_runtime_layout,
)
from lea.installers.taskwarrior.smoke_test import (
    validate_staged_taskwarrior_binary,
)
from lea.installers.taskwarrior.source_archive import (
    extract_taskwarrior_source_archive,
    remove_taskwarrior_extracted_source,
)
from lea.installers.taskwarrior.source_network import (
    TaskwarriorSourceNetworkConfig,
    validate_taskwarrior_source_network,
)
from lea.installers.taskwarrior.staging import (
    remove_taskwarrior_staging,
    stage_taskwarrior_binary,
)
from lea.installers.taskwarrior.validation import (
    validate_taskwarrior_installer_config,
)

_DEFAULT_BUILD_TIMEOUT_SECONDS = 7200.0
_DEFAULT_SMOKE_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class TaskwarriorSourceInstallResult:
    """Result of one pinned-source Taskwarrior installation."""

    success: bool
    already_installed: bool
    record: TaskwarriorInstallationRecord | None
    build: TaskwarriorSourceBuildExecutionResult | None
    issues: tuple[TaskwarriorInstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate source-install result consistency."""
        if self.success:
            if self.record is None:
                raise ValueError(
                    "A successful source installation must contain a record."
                )
            if self.issues:
                raise ValueError(
                    "A successful source installation must not contain issues."
                )
            if self.already_installed and self.build is not None:
                raise ValueError(
                    "An already-installed result must not contain a new build."
                )
            return

        if self.already_installed:
            raise ValueError(
                "A failed source installation must not be already installed."
            )
        if self.record is not None:
            raise ValueError("A failed source installation must not contain a record.")
        if not self.issues:
            raise ValueError(
                "A failed source installation must contain at least one issue."
            )


def install_source_taskwarrior(
    config: TaskwarriorInstallerConfig,
    *,
    build_tools: TaskwarriorBuildTools | None = None,
    source_network: TaskwarriorSourceNetworkConfig | None = None,
    build_timeout_seconds: float = _DEFAULT_BUILD_TIMEOUT_SECONDS,
    dependency_timeout_seconds: float = 10.0,
    network_timeout_seconds: float = 30.0,
    smoke_timeout_seconds: float = _DEFAULT_SMOKE_TIMEOUT_SECONDS,
    fsync: bool = False,
    progress: TaskwarriorBuildProgressReporter | None = None,
) -> TaskwarriorSourceInstallResult:
    """Build, validate and atomically install pinned Taskwarrior source."""
    if config.mode is not TaskwarriorInstallMode.SOURCE_BUILD:
        return _failure(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
                message="The source installer requires source-build mode.",
                field="mode",
            )
        )

    for field_name, timeout in (
        ("build_timeout_seconds", build_timeout_seconds),
        ("dependency_timeout_seconds", dependency_timeout_seconds),
        ("network_timeout_seconds", network_timeout_seconds),
        ("smoke_timeout_seconds", smoke_timeout_seconds),
    ):
        if timeout <= 0:
            raise ValueError(f"{field_name} must be greater than zero.")

    validation = validate_taskwarrior_installer_config(config)
    if not validation.valid or validation.config is None:
        return TaskwarriorSourceInstallResult(
            success=False,
            already_installed=False,
            record=None,
            build=None,
            issues=validation.issues,
        )

    normalised = validation.config
    existing = _inspect_existing_source_installation(normalised)
    if existing is not None:
        return existing

    source_archive = normalised.source_archive
    expected_sha256 = normalised.expected_sha256
    build_directory = normalised.build_directory
    if source_archive is None:
        return _missing("source_archive", "The source archive path is missing.")
    if expected_sha256 is None:
        return _missing("expected_sha256", "The source checksum is missing.")
    if build_directory is None:
        return _missing("build_directory", "The build directory is missing.")

    preflight_issues = run_taskwarrior_installer_preflight(normalised)
    if preflight_issues:
        return TaskwarriorSourceInstallResult(
            success=False,
            already_installed=False,
            record=None,
            build=None,
            issues=preflight_issues,
        )

    network = validate_taskwarrior_source_network(
        source_network or TaskwarriorSourceNetworkConfig(),
        timeout_seconds=network_timeout_seconds,
    )
    if not network.valid:
        return TaskwarriorSourceInstallResult(
            success=False,
            already_installed=False,
            record=None,
            build=None,
            issues=network.issues,
        )

    tools = build_tools or default_taskwarrior_build_tools()
    dependencies = validate_taskwarrior_build_dependencies(
        tools,
        timeout_seconds=dependency_timeout_seconds,
    )
    if dependencies.tools is None:
        return TaskwarriorSourceInstallResult(
            success=False,
            already_installed=False,
            record=None,
            build=None,
            issues=dependencies.issues,
        )

    extraction = extract_taskwarrior_source_archive(
        source_archive,
        expected_sha256=expected_sha256,
        build_directory=build_directory,
    )
    if extraction.extracted is None:
        return TaskwarriorSourceInstallResult(
            success=False,
            already_installed=False,
            record=None,
            build=None,
            issues=extraction.issues,
        )

    extracted = extraction.extracted
    staged = None
    try:
        plan = create_taskwarrior_source_build_plan(
            tools=dependencies.tools,
            source_root=extracted.source_root,
            cmake_build_directory=extracted.extraction_root / "cmake-build",
            installation_prefix=extracted.extraction_root / "install",
            build_concurrency=normalised.build_concurrency,
            timeout_seconds=build_timeout_seconds,
        )
        build = execute_taskwarrior_source_build(
            plan,
            progress=progress,
        )
        if not build.success or build.installation_prefix is None:
            return TaskwarriorSourceInstallResult(
                success=False,
                already_installed=False,
                record=None,
                build=build,
                issues=build.issues,
            )

        built_executable = build.installation_prefix / "bin" / "task"
        try:
            built_sha256 = calculate_sha256(built_executable)
        except OSError as error:
            return TaskwarriorSourceInstallResult(
                success=False,
                already_installed=False,
                record=None,
                build=build,
                issues=(
                    TaskwarriorInstallerIssue(
                        code=TaskwarriorInstallFailureCode.BUILD_FAILED,
                        message=(
                            "The built executable could not be read: "
                            f"{error.strerror or type(error).__name__}."
                        ),
                        field="build_directory",
                        path=built_executable,
                    ),
                ),
            )

        staging = stage_taskwarrior_binary(
            built_executable,
            expected_sha256=built_sha256,
            staging_parent=normalised.tools_root,
        )
        if staging.staged is None:
            return TaskwarriorSourceInstallResult(
                success=False,
                already_installed=False,
                record=None,
                build=build,
                issues=staging.issues,
            )
        staged = staging.staged

        smoke = validate_staged_taskwarrior_binary(
            staged,
            timeout_seconds=smoke_timeout_seconds,
        )
        if not smoke.passed:
            cleanup = remove_taskwarrior_staging(staged)
            staged = None
            return TaskwarriorSourceInstallResult(
                success=False,
                already_installed=False,
                record=None,
                build=build,
                issues=(*smoke.issues, *cleanup),
            )
        if smoke.version != normalised.version:
            cleanup = remove_taskwarrior_staging(staged)
            staged = None
            return TaskwarriorSourceInstallResult(
                success=False,
                already_installed=False,
                record=None,
                build=build,
                issues=(
                    TaskwarriorInstallerIssue(
                        code=TaskwarriorInstallFailureCode.UNSUPPORTED_VERSION,
                        message=(
                            "The built version does not match the requested "
                            "pinned version."
                        ),
                        field="version",
                        path=built_executable,
                    ),
                    *cleanup,
                ),
            )

        layout = provision_taskwarrior_runtime_layout(normalised, fsync=fsync)
        if not layout.success:
            cleanup = remove_taskwarrior_staging(staged)
            staged = None
            return TaskwarriorSourceInstallResult(
                success=False,
                already_installed=False,
                record=None,
                build=build,
                issues=(*layout.issues, *cleanup),
            )

        activation = activate_staged_taskwarrior(staged, normalised, fsync=fsync)
        if not activation.success:
            cleanup = remove_taskwarrior_staging(staged)
            staged = None
            return TaskwarriorSourceInstallResult(
                success=False,
                already_installed=False,
                record=None,
                build=build,
                issues=(*activation.issues, *cleanup),
            )

        staged = None
        if activation.record is None:
            return _failure(
                TaskwarriorInstallerIssue(
                    code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
                    message=("Activation succeeded without an installation record."),
                ),
                build=build,
            )

        return TaskwarriorSourceInstallResult(
            success=True,
            already_installed=activation.already_installed,
            record=activation.record,
            build=build,
            issues=(),
        )
    finally:
        if staged is not None:
            remove_taskwarrior_staging(staged)
        remove_taskwarrior_extracted_source(extracted)


def _inspect_existing_source_installation(
    config: TaskwarriorInstallerConfig,
) -> TaskwarriorSourceInstallResult | None:
    """Return an idempotent result before starting an expensive build."""
    executable = config.tools_root / config.version / "bin" / "task"
    record_path = config.installation_record
    if not executable.exists() and not record_path.exists():
        return None
    if not executable.is_file():
        return _failure(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
                message="The existing source installation has no executable.",
                field="tools_root",
                path=executable,
            )
        )

    try:
        sha256 = calculate_sha256(executable)
    except OSError as error:
        return _failure(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.ACTIVATION_FAILED,
                message=(
                    "The existing executable could not be verified: "
                    f"{error.strerror or type(error).__name__}."
                ),
                field="tools_root",
                path=executable,
            )
        )

    record, issues = read_taskwarrior_installation_record(record_path)
    if issues or record is None:
        return TaskwarriorSourceInstallResult(
            success=False,
            already_installed=False,
            record=None,
            build=None,
            issues=issues,
        )
    if record.mode != TaskwarriorInstallMode.SOURCE_BUILD.value:
        return _failure(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.RECORD_FAILED,
                message="The existing installation uses a different mode.",
                field="installation_record",
                path=record_path,
            )
        )
    if not installation_record_matches(
        record,
        version=config.version,
        platform=config.platform,
        executable=executable,
        sha256=sha256,
    ):
        return _failure(
            TaskwarriorInstallerIssue(
                code=TaskwarriorInstallFailureCode.RECORD_FAILED,
                message=(
                    "The existing source installation record does not match "
                    "the installed executable."
                ),
                field="installation_record",
                path=record_path,
            )
        )

    return TaskwarriorSourceInstallResult(
        success=True,
        already_installed=True,
        record=record,
        build=None,
        issues=(),
    )


def _missing(field: str, message: str) -> TaskwarriorSourceInstallResult:
    """Return one missing-field failure."""
    return _failure(
        TaskwarriorInstallerIssue(
            code=TaskwarriorInstallFailureCode.INVALID_ARGUMENT,
            message=message,
            field=field,
        )
    )


def _failure(
    issue: TaskwarriorInstallerIssue,
    *,
    build: TaskwarriorSourceBuildExecutionResult | None = None,
) -> TaskwarriorSourceInstallResult:
    """Return one failed source-install result."""
    return TaskwarriorSourceInstallResult(
        success=False,
        already_installed=False,
        record=None,
        build=build,
        issues=(issue,),
    )
