"""Tests for the bundled Taskwarrior installation coordinator."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lea.installers.taskwarrior import (
    TaskwarriorActivationResult,
    TaskwarriorBundledInstallResult,
    TaskwarriorInstallationRecord,
    TaskwarriorInstallerConfig,
    TaskwarriorInstallerIssue,
    TaskwarriorInstallerValidationResult,
    TaskwarriorInstallFailureCode,
    TaskwarriorInstallMode,
    TaskwarriorRuntimeLayout,
    TaskwarriorRuntimeLayoutResult,
    TaskwarriorSmokeTestResult,
    TaskwarriorStagedBinary,
    TaskwarriorStagingResult,
    install_bundled_taskwarrior,
)

INSTALLED_AT = datetime(2026, 7, 21, 18, 30, tzinfo=UTC)


def make_config(tmp_path: Path) -> TaskwarriorInstallerConfig:
    """Return one bundled-binary installer configuration."""
    artefact = tmp_path / "source-task"
    artefact.write_bytes(b"taskwarrior")

    return TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        version="3.4.2",
        platform="arm64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install" / "taskwarrior.json",
        service_user="lea",
        service_group="lea",
        artefact_path=artefact,
        expected_sha256=hashlib.sha256(b"taskwarrior").hexdigest(),
    )


def make_staged(tmp_path: Path) -> TaskwarriorStagedBinary:
    """Return one deterministic staged binary contract."""
    root = tmp_path / "tools" / ".taskwarrior-stage"
    executable = root / "bin" / "task"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"taskwarrior")

    return TaskwarriorStagedBinary(
        staging_root=root,
        executable=executable,
        sha256="a" * 64,
    )


def make_record(
    config: TaskwarriorInstallerConfig,
) -> TaskwarriorInstallationRecord:
    """Return one deterministic installation record."""
    return TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version=config.version,
        mode=config.mode.value,
        platform="linux-aarch64",
        executable=config.tools_root / config.version / "bin" / "task",
        sha256="a" * 64,
        taskrc=config.configuration_dir / "taskrc",
        home=config.state_root / "home",
        data=config.state_root / "data",
        smoke_test="passed",
        installed_at=INSTALLED_AT,
    )


def test_successful_workflow_runs_phases_in_order(
    tmp_path: Path,
) -> None:
    """The coordinator should run every validated phase in order."""
    config = make_config(tmp_path)
    staged = make_staged(tmp_path)
    calls: list[str] = []

    def validate(
        value: TaskwarriorInstallerConfig,
    ) -> TaskwarriorInstallerValidationResult:
        calls.append("validate")
        return TaskwarriorInstallerValidationResult(
            valid=True,
            config=TaskwarriorInstallerConfig(
                mode=value.mode,
                version=value.version,
                platform="linux-aarch64",
                tools_root=value.tools_root,
                configuration_dir=value.configuration_dir,
                state_root=value.state_root,
                installation_record=value.installation_record,
                service_user=value.service_user,
                service_group=value.service_group,
                artefact_path=value.artefact_path,
                expected_sha256=value.expected_sha256,
            ),
            issues=(),
        )

    def preflight(
        value: TaskwarriorInstallerConfig,
    ) -> tuple[TaskwarriorInstallerIssue, ...]:
        calls.append("preflight")
        return ()

    def stage(*args: Any, **kwargs: Any) -> TaskwarriorStagingResult:
        calls.append("stage")
        return TaskwarriorStagingResult(staged=staged, issues=())

    def smoke(
        value: TaskwarriorStagedBinary,
    ) -> TaskwarriorSmokeTestResult:
        calls.append("smoke")
        return TaskwarriorSmokeTestResult(
            passed=True,
            version="3.4.2",
            issues=(),
        )

    def layout(
        value: TaskwarriorInstallerConfig,
        *,
        fsync: bool,
        apply_ownership: object,
    ) -> TaskwarriorRuntimeLayoutResult:
        calls.append("layout")
        return TaskwarriorRuntimeLayoutResult(
            success=True,
            layout=TaskwarriorRuntimeLayout(
                taskrc=value.configuration_dir / "taskrc",
                home=value.state_root / "home",
                data=value.state_root / "data",
            ),
            issues=(),
        )

    def activate(
        value: TaskwarriorStagedBinary,
        normalised: TaskwarriorInstallerConfig,
        *,
        fsync: bool,
        apply_ownership: object,
    ) -> TaskwarriorActivationResult:
        calls.append("activate")
        return TaskwarriorActivationResult(
            success=True,
            already_installed=False,
            record=make_record(normalised),
            issues=(),
        )

    result = install_bundled_taskwarrior(
        config,
        validate_config=validate,
        run_preflight=preflight,
        stage_binary=stage,
        run_smoke_test=smoke,
        provision_layout=layout,
        activate=activate,
    )

    assert result.success is True
    assert result.already_installed is False
    assert result.record is not None
    assert calls == [
        "validate",
        "preflight",
        "stage",
        "smoke",
        "layout",
        "activate",
    ]


def test_preflight_failure_stops_before_staging(
    tmp_path: Path,
) -> None:
    """Preflight issues should prevent all mutation phases."""
    config = make_config(tmp_path)
    issue = TaskwarriorInstallerIssue(
        code=TaskwarriorInstallFailureCode.PERMISSION_DENIED,
        message="No write access.",
    )
    staged_called = False

    def preflight(
        value: TaskwarriorInstallerConfig,
    ) -> tuple[TaskwarriorInstallerIssue, ...]:
        return (issue,)

    def stage(*args: Any, **kwargs: Any) -> TaskwarriorStagingResult:
        nonlocal staged_called
        staged_called = True
        raise AssertionError("Staging must not run.")

    result = install_bundled_taskwarrior(
        config,
        run_preflight=preflight,
        stage_binary=stage,
    )

    assert result.success is False
    assert result.issues == (issue,)
    assert staged_called is False


def test_smoke_failure_removes_staging(
    tmp_path: Path,
) -> None:
    """Failed staged validation should trigger cleanup."""
    config = make_config(tmp_path)
    staged = make_staged(tmp_path)
    removed: list[TaskwarriorStagedBinary] = []

    def stage(*args: Any, **kwargs: Any) -> TaskwarriorStagingResult:
        return TaskwarriorStagingResult(staged=staged, issues=())

    def smoke(
        value: TaskwarriorStagedBinary,
    ) -> TaskwarriorSmokeTestResult:
        return TaskwarriorSmokeTestResult(
            passed=False,
            version=None,
            issues=(
                TaskwarriorInstallerIssue(
                    code=(TaskwarriorInstallFailureCode.SMOKE_TEST_FAILED),
                    message="Smoke test failed.",
                ),
            ),
        )

    def remove(
        value: TaskwarriorStagedBinary,
    ) -> tuple[TaskwarriorInstallerIssue, ...]:
        removed.append(value)
        return ()

    result = install_bundled_taskwarrior(
        config,
        stage_binary=stage,
        run_smoke_test=smoke,
        remove_staging=remove,
    )

    assert result.success is False
    assert removed == [staged]


def test_already_installed_cleans_unused_staging(
    tmp_path: Path,
) -> None:
    """Idempotent activation should remove its unused staged copy."""
    config = make_config(tmp_path)
    staged = make_staged(tmp_path)
    removed: list[TaskwarriorStagedBinary] = []

    def stage(*args: Any, **kwargs: Any) -> TaskwarriorStagingResult:
        return TaskwarriorStagingResult(staged=staged, issues=())

    def smoke(
        value: TaskwarriorStagedBinary,
    ) -> TaskwarriorSmokeTestResult:
        return TaskwarriorSmokeTestResult(
            passed=True,
            version="3.4.2",
            issues=(),
        )

    def layout(
        value: TaskwarriorInstallerConfig,
        *,
        fsync: bool,
        apply_ownership: object,
    ) -> TaskwarriorRuntimeLayoutResult:
        return TaskwarriorRuntimeLayoutResult(
            success=True,
            layout=TaskwarriorRuntimeLayout(
                taskrc=value.configuration_dir / "taskrc",
                home=value.state_root / "home",
                data=value.state_root / "data",
            ),
            issues=(),
        )

    def activate(
        value: TaskwarriorStagedBinary,
        normalised: TaskwarriorInstallerConfig,
        *,
        fsync: bool,
        apply_ownership: object,
    ) -> TaskwarriorActivationResult:
        return TaskwarriorActivationResult(
            success=True,
            already_installed=True,
            record=make_record(normalised),
            issues=(),
        )

    def remove(
        value: TaskwarriorStagedBinary,
    ) -> tuple[TaskwarriorInstallerIssue, ...]:
        removed.append(value)
        return ()

    result = install_bundled_taskwarrior(
        config,
        stage_binary=stage,
        run_smoke_test=smoke,
        provision_layout=layout,
        activate=activate,
        remove_staging=remove,
    )

    assert result.success is True
    assert result.already_installed is True
    assert removed == [staged]


def test_non_bundled_mode_is_rejected(
    tmp_path: Path,
) -> None:
    """The bundled coordinator should reject other install modes."""
    executable = tmp_path / "task"
    executable.write_bytes(b"task")

    config = TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.EXTERNAL_EXECUTABLE,
        version="3.4.2",
        platform="arm64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install" / "taskwarrior.json",
        service_user="lea",
        service_group="lea",
        external_executable=executable,
    )

    result = install_bundled_taskwarrior(config)

    assert result.success is False
    assert result.issues[0].code is TaskwarriorInstallFailureCode.INVALID_ARGUMENT


def test_result_contract_requires_record_on_success() -> None:
    """Successful coordinator results must contain a record."""
    try:
        TaskwarriorBundledInstallResult(
            success=True,
            already_installed=False,
            record=None,
            issues=(),
        )
    except ValueError as error:
        assert "must contain a record" in str(error)
    else:
        raise AssertionError("Expected an invalid result to be rejected.")
