"""Tests for release-candidate post-install health and acceptance."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.records import (
    CalendarToolchainInstallationRecord,
)
from lea.installers.calendar.smoke_test import (
    CalendarToolchainSmokeStepResult,
    CalendarToolchainSmokeTestResult,
)
from lea.installers.calendar.version_check import (
    CalendarToolchainVersionCheckResult,
    CalendarToolchainVersionStepResult,
)
from lea.installers.release_candidate import (
    PostInstallCheck,
    PostInstallCheckState,
    PostInstallHealthPlan,
    PostInstallHealthResult,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    SystemCommandResult,
    create_installation_record,
    create_post_install_health_plan,
    render_installation_record,
    run_post_install_health,
    run_release_candidate_acceptance,
)
from lea.installers.release_candidate.post_install import (
    _check_installation_record,
)
from lea.installers.release_candidate.telegram_onboarding import (
    TelegramBotIdentity,
    TelegramBotValidationResult,
)
from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    TaskwarriorSmokeTestResult,
)
from lea.runtime import (
    ConfigurationIssue,
    ConfigurationResult,
    RuntimeConfig,
    RuntimeHealthResult,
)
from lea.runtime.telegram import TelegramRuntimeConfig
from lea.runtime.templates import isolated_test_runtime_config
from lea.tasks import (
    TaskProviderInspectionResult,
    TaskProviderIssue,
)


def _request(
    tmp_path: Path, *, telegram: bool = False
) -> ReleaseCandidateInstallRequest:
    return ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=telegram,
        installation_root=tmp_path / "opt" / "lea",
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
    )


def _record(tmp_path: Path) -> TaskwarriorInstallationRecord:
    return TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode="source-build",
        platform="linux-aarch64",
        executable=tmp_path / "tools" / "3.4.2" / "bin" / "task",
        sha256="a" * 64,
        taskrc=tmp_path / "taskwarrior" / "taskrc",
        home=tmp_path / "taskwarrior" / "home",
        data=tmp_path / "taskwarrior" / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 24, tzinfo=UTC),
    )


def _calendar_record(
    tmp_path: Path,
) -> CalendarToolchainInstallationRecord:
    return CalendarToolchainInstallationRecord(
        schema_version=2,
        component="calendar-toolchain",
        toolchain_version="1.0.0",
        installation_mode=(CalendarToolchainInstallMode.EXTERNAL_EXECUTABLES),
        platform="linux-aarch64",
        python_version=None,
        khal_version="0.11.4",
        vdirsyncer_version="0.20.0",
        khal_executable=tmp_path / "calendar" / "bin" / "khal",
        vdirsyncer_executable=(tmp_path / "calendar" / "bin" / "vdirsyncer"),
        lock_or_manifest_sha256=None,
        khal_executable_sha256="b" * 64,
        vdirsyncer_executable_sha256="c" * 64,
        smoke_test="passed",
        installed_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _calendar_version_result(
    record: CalendarToolchainInstallationRecord,
) -> CalendarToolchainVersionCheckResult:
    return CalendarToolchainVersionCheckResult(
        passed=True,
        khal_version=record.khal_version,
        vdirsyncer_version=record.vdirsyncer_version,
        steps=(
            CalendarToolchainVersionStepResult(
                tool="khal",
                command=(str(record.khal_executable), "--version"),
                returncode=0,
                stdout=f"khal, version {record.khal_version}\n",
                stderr="",
                duration_seconds=0.01,
                timed_out=False,
                discovered_version=record.khal_version,
            ),
            CalendarToolchainVersionStepResult(
                tool="vdirsyncer",
                command=(
                    str(record.vdirsyncer_executable),
                    "--version",
                ),
                returncode=0,
                stdout=f"vdirsyncer, version {record.vdirsyncer_version}\n",
                stderr="",
                duration_seconds=0.01,
                timed_out=False,
                discovered_version=record.vdirsyncer_version,
            ),
        ),
        issues=(),
    )


def _calendar_smoke_result(
    record: CalendarToolchainInstallationRecord,
) -> CalendarToolchainSmokeTestResult:
    phases = (
        "discover",
        "sync",
        "list",
        "create",
        "verify",
    )

    return CalendarToolchainSmokeTestResult(
        passed=True,
        steps=tuple(
            CalendarToolchainSmokeStepResult(
                phase=phase,
                command=(
                    str(
                        record.vdirsyncer_executable
                        if phase in {"discover", "sync"}
                        else record.khal_executable
                    ),
                    phase,
                ),
                returncode=0,
                stdout="",
                stderr="",
                duration_seconds=0.01,
                timed_out=False,
            )
            for phase in phases
        ),
        issues=(),
    )


def _prepare(
    tmp_path: Path,
    *,
    telegram: bool = False,
    calendar: bool = False,
) -> tuple[PostInstallHealthPlan, RuntimeConfig]:
    request = _request(tmp_path, telegram=telegram)
    plan = create_post_install_health_plan(
        request,
        calendar_enabled=calendar,
        systemctl=tmp_path / "usr" / "bin" / "systemctl",
    )
    runtime = isolated_test_runtime_config(
        tmp_path / "runtime",
        telegram_token_file=(
            request.configuration_root / "secrets" / "telegram-bot-token"
            if telegram
            else None
        ),
    )
    plan.installation_record_file.parent.mkdir(parents=True)
    plan.installation_record_file.write_text(
        render_installation_record(
            create_installation_record(
                request=request,
                lea_version="0.1.0",
            )
        ),
        encoding="utf-8",
    )
    return plan, runtime


def _failed_configuration(path: Path) -> ConfigurationResult:
    """Return one valid configuration-loading failure."""
    return ConfigurationResult(
        success=False,
        config=None,
        issues=(
            ConfigurationIssue(
                code="configuration_not_found",
                message="The runtime configuration was not found.",
                source_path=path,
            ),
        ),
    )


def test_plan_omits_calendar_paths_when_not_selected(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)

    plan = create_post_install_health_plan(request)

    assert plan.calendar_record_file is None
    assert plan.calendar_acceptance_work_directory is None


def test_plan_includes_canonical_calendar_paths_when_selected(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)

    plan = create_post_install_health_plan(
        request,
        calendar_enabled=True,
    )

    assert plan.calendar_record_file == (
        request.state_root / "install" / "calendar-toolchain.json"
    )
    assert plan.calendar_acceptance_work_directory == (
        request.state_root / "acceptance" / "calendar"
    )


def test_calendar_health_validates_record_and_exact_versions(
    tmp_path: Path,
) -> None:
    plan, runtime = _prepare(tmp_path, calendar=True)
    taskwarrior_record = _record(tmp_path)
    calendar_record = _calendar_record(tmp_path)
    captured: dict[str, object] = {}

    def validate_versions(
        **arguments: object,
    ) -> CalendarToolchainVersionCheckResult:
        captured.update(arguments)
        return _calendar_version_result(calendar_record)

    result = run_post_install_health(
        plan,
        runtime_loader=lambda _path: ConfigurationResult(
            success=True,
            config=runtime,
            issues=(),
        ),
        runtime_health_checker=lambda _config: RuntimeHealthResult(
            healthy=True,
            issues=(),
        ),
        taskwarrior_record_reader=lambda _path: (
            taskwarrior_record,
            (),
        ),
        taskwarrior_inspector=lambda _config: TaskProviderInspectionResult(
            available=True,
            provider="taskwarrior",
            version="3.4.2",
            issues=(),
        ),
        calendar_record_reader=lambda _path: (
            calendar_record,
            (),
        ),
        calendar_version_validator=validate_versions,
    )

    assert result.healthy is True

    checks = {check.code: check for check in result.checks}

    assert checks["calendar_record_valid"].state is PostInstallCheckState.PASSED
    assert checks["calendar_versions"].state is PostInstallCheckState.PASSED
    assert captured == {
        "khal_executable": calendar_record.khal_executable,
        "expected_khal_version": calendar_record.khal_version,
        "vdirsyncer_executable": (calendar_record.vdirsyncer_executable),
        "expected_vdirsyncer_version": (calendar_record.vdirsyncer_version),
        "working_directory": runtime.paths.run_dir,
        "timeout_seconds": 10.0,
    }


def test_calendar_health_fails_for_invalid_record(
    tmp_path: Path,
) -> None:
    plan, runtime = _prepare(tmp_path, calendar=True)
    taskwarrior_record = _record(tmp_path)

    def unexpected_version_check(
        **_arguments: object,
    ) -> CalendarToolchainVersionCheckResult:
        raise AssertionError("The version check must not run for an invalid record.")

    result = run_post_install_health(
        plan,
        runtime_loader=lambda _path: ConfigurationResult(
            success=True,
            config=runtime,
            issues=(),
        ),
        runtime_health_checker=lambda _config: RuntimeHealthResult(
            healthy=True,
            issues=(),
        ),
        taskwarrior_record_reader=lambda _path: (
            taskwarrior_record,
            (),
        ),
        taskwarrior_inspector=lambda _config: TaskProviderInspectionResult(
            available=True,
            provider="taskwarrior",
            version="3.4.2",
            issues=(),
        ),
        calendar_record_reader=lambda _path: (
            None,
            (object(),),
        ),
        calendar_version_validator=unexpected_version_check,
    )

    assert result.healthy is False

    checks = {check.code: check for check in result.checks}

    assert checks["calendar_record_invalid"].state is PostInstallCheckState.FAILED
    assert "calendar_versions" not in checks


def test_health_accepts_canonical_release_candidate_record(
    tmp_path: Path,
) -> None:
    """Health must accept the record produced by the installer writer."""
    request = ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.REPAIR,
        display_timezone="Africa/Gaborone",
        enable_telegram=False,
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
    )
    record_path = request.state_root / "install" / "release-candidate.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(
        render_installation_record(
            create_installation_record(
                request=request,
                lea_version="0.1.0",
            )
        ),
        encoding="utf-8",
    )
    checks: list[PostInstallCheck] = []

    _check_installation_record(
        record_path,
        checks=checks,
    )

    assert len(checks) == 1
    assert checks[0].code == "installation_record"
    assert checks[0].state is PostInstallCheckState.PASSED


def test_health_rejects_invalid_release_candidate_record(
    tmp_path: Path,
) -> None:
    """Health must reject malformed or incompatible record documents."""
    record_path = tmp_path / "release-candidate.json"
    record_path.write_text(
        '{"schema_version": 1, "component": "lea"}\n',
        encoding="utf-8",
    )
    checks: list[PostInstallCheck] = []

    _check_installation_record(
        record_path,
        checks=checks,
    )

    assert len(checks) == 1
    assert checks[0].code == "installation_record"
    assert checks[0].state is PostInstallCheckState.FAILED


def test_plan_uses_canonical_paths(tmp_path: Path) -> None:
    request = _request(tmp_path, telegram=True)
    plan = create_post_install_health_plan(request)

    assert plan.runtime_config_file == request.configuration_root / "lea.toml"
    assert plan.taskwarrior_record_file == (
        request.state_root / "install" / "taskwarrior.json"
    )
    assert plan.acceptance_work_directory == (
        request.state_root / "acceptance" / "taskwarrior"
    )
    assert plan.systemctl == Path("/usr/bin/systemctl")


def test_health_reuses_runtime_and_taskwarrior_boundaries(tmp_path: Path) -> None:
    plan, runtime = _prepare(tmp_path)
    record = _record(tmp_path)
    inspected: list[Any] = []

    def inspect(config: Any) -> TaskProviderInspectionResult:
        inspected.append(config)
        return TaskProviderInspectionResult(
            available=True,
            provider="taskwarrior",
            version="3.4.2",
            issues=(),
        )

    result = run_post_install_health(
        plan,
        runtime_loader=lambda _path: ConfigurationResult(
            success=True,
            config=runtime,
            issues=(),
        ),
        runtime_health_checker=lambda _config: RuntimeHealthResult(
            healthy=True,
            issues=(),
        ),
        taskwarrior_record_reader=lambda _path: (record, ()),
        taskwarrior_inspector=inspect,
    )

    assert result.healthy is True
    assert inspected[0].executable == record.executable
    assert all(check.state is PostInstallCheckState.PASSED for check in result.checks)


def test_runtime_failure_stops_health_check(tmp_path: Path) -> None:
    plan, _runtime = _prepare(tmp_path)

    result = run_post_install_health(
        plan,
        runtime_loader=_failed_configuration,
    )

    assert result.healthy is False
    assert result.checks[0].code == "runtime_configuration_invalid"


def test_telegram_health_checks_config_users_token_and_service(
    tmp_path: Path,
) -> None:
    plan, runtime = _prepare(tmp_path, telegram=True)
    record = _record(tmp_path)
    token = runtime.secrets.telegram_token_file
    assert token is not None
    token.parent.mkdir(parents=True)
    token.write_text("not-read", encoding="utf-8")
    token.chmod(0o600)

    users = tmp_path / "users.toml"
    users.write_text(
        """schema_version = 1

[[users]]
name = "Owner"
channel = "telegram"
user_id = 123456789
conversation_id = 123456789
role = "owner"
enabled = true
add_capabilities = []
remove_capabilities = []
""",
        encoding="utf-8",
    )
    users.chmod(0o640)

    telegram = TelegramRuntimeConfig(
        enabled=True,
        bot_username="lea_test_bot",
        authorised_users_file=users,
        offset_file=tmp_path / "offset.json",
    )

    result = run_post_install_health(
        plan,
        runtime_loader=lambda _path: ConfigurationResult(
            success=True,
            config=runtime,
            issues=(),
        ),
        runtime_health_checker=lambda _config: RuntimeHealthResult(
            healthy=True,
            issues=(),
        ),
        taskwarrior_record_reader=lambda _path: (record, ()),
        taskwarrior_inspector=lambda _config: TaskProviderInspectionResult(
            available=True,
            provider="taskwarrior",
            version="3.4.2",
            issues=(),
        ),
        telegram_config_loader=lambda _path: telegram,
        systemd_execute=lambda _command: SystemCommandResult(0),
    )

    assert result.healthy is True
    codes = {check.code for check in result.checks}
    assert "telegram_token_permissions" in codes
    assert "telegram_service_is-active" in codes


def test_calendar_acceptance_runs_disposable_lifecycle(
    tmp_path: Path,
) -> None:
    plan, _runtime = _prepare(tmp_path, calendar=True)
    taskwarrior_record = _record(tmp_path)
    calendar_record = _calendar_record(tmp_path)
    captured: dict[str, object] = {}

    def accept_taskwarrior(
        _executable: Path,
        *,
        temporary_parent: Path,
        timeout_seconds: float,
    ) -> TaskwarriorSmokeTestResult:
        assert temporary_parent == plan.acceptance_work_directory
        assert timeout_seconds == 15.0
        return TaskwarriorSmokeTestResult(
            passed=True,
            version="3.4.2",
            issues=(),
        )

    def accept_calendar(
        **arguments: object,
    ) -> CalendarToolchainSmokeTestResult:
        captured.update(arguments)
        return _calendar_smoke_result(calendar_record)

    result = run_release_candidate_acceptance(
        plan,
        PostInstallHealthResult(
            healthy=True,
            checks=(),
            issues=(),
        ),
        taskwarrior_record_reader=lambda _path: (
            taskwarrior_record,
            (),
        ),
        taskwarrior_acceptance=accept_taskwarrior,
        calendar_record_reader=lambda _path: (
            calendar_record,
            (),
        ),
        calendar_acceptance=accept_calendar,
    )

    assert result.accepted is True

    checks = {check.code: check for check in result.checks}

    assert checks["calendar_lifecycle"].state is PostInstallCheckState.PASSED
    assert captured == {
        "khal_executable": calendar_record.khal_executable,
        "vdirsyncer_executable": (calendar_record.vdirsyncer_executable),
        "working_directory": (plan.calendar_acceptance_work_directory),
        "timeout_seconds": 15.0,
    }

    working_directory = plan.calendar_acceptance_work_directory

    assert working_directory is not None
    assert working_directory.is_dir()
    assert not working_directory.is_symlink()
    assert working_directory.stat().st_mode & 0o777 == 0o700


def test_calendar_acceptance_fails_when_record_cannot_be_reloaded(
    tmp_path: Path,
) -> None:
    plan, _runtime = _prepare(tmp_path, calendar=True)
    taskwarrior_record = _record(tmp_path)

    result = run_release_candidate_acceptance(
        plan,
        PostInstallHealthResult(
            healthy=True,
            checks=(),
            issues=(),
        ),
        taskwarrior_record_reader=lambda _path: (
            taskwarrior_record,
            (),
        ),
        taskwarrior_acceptance=lambda *_args, **_kwargs: TaskwarriorSmokeTestResult(
            passed=True,
            version="3.4.2",
            issues=(),
        ),
        calendar_record_reader=lambda _path: (
            None,
            (object(),),
        ),
    )

    assert result.accepted is False
    assert result.checks[0].code == "calendar_record_invalid"
    assert (
        result.checks[0].message
        == "Calendar acceptance could not load the installation record."
    )


def test_calendar_acceptance_contains_boundary_exceptions(
    tmp_path: Path,
) -> None:
    plan, _runtime = _prepare(tmp_path, calendar=True)
    taskwarrior_record = _record(tmp_path)
    calendar_record = _calendar_record(tmp_path)

    def fail_calendar(
        **_arguments: object,
    ) -> CalendarToolchainSmokeTestResult:
        raise RuntimeError("sensitive calendar boundary detail")

    result = run_release_candidate_acceptance(
        plan,
        PostInstallHealthResult(
            healthy=True,
            checks=(),
            issues=(),
        ),
        taskwarrior_record_reader=lambda _path: (
            taskwarrior_record,
            (),
        ),
        taskwarrior_acceptance=lambda *_args, **_kwargs: TaskwarriorSmokeTestResult(
            passed=True,
            version="3.4.2",
            issues=(),
        ),
        calendar_record_reader=lambda _path: (
            calendar_record,
            (),
        ),
        calendar_acceptance=fail_calendar,
    )

    assert result.accepted is False

    checks = {check.code: check for check in result.checks}

    assert checks["calendar_lifecycle"].state is PostInstallCheckState.FAILED
    assert (
        checks["calendar_lifecycle"].message
        == "The disposable calendar lifecycle failed."
    )
    assert "sensitive calendar boundary detail" not in result.summary


def test_acceptance_runs_disposable_taskwarrior_and_telegram(
    tmp_path: Path,
) -> None:
    plan, _runtime = _prepare(tmp_path, telegram=True)
    record = _record(tmp_path)
    plan.taskwarrior_record_file.write_text("{}", encoding="utf-8")

    health = PostInstallHealthResult(
        healthy=True,
        checks=(),
        issues=(),
    )

    calls: list[tuple[Path, Path, float]] = []

    def accept_taskwarrior(
        executable: Path,
        *,
        temporary_parent: Path,
        timeout_seconds: float,
    ) -> TaskwarriorSmokeTestResult:
        calls.append((executable, temporary_parent, timeout_seconds))
        return TaskwarriorSmokeTestResult(
            passed=True,
            version="3.4.2",
            issues=(),
        )

    result = run_release_candidate_acceptance(
        plan,
        health,
        taskwarrior_record_reader=lambda _path: (record, ()),
        taskwarrior_acceptance=accept_taskwarrior,
        telegram_validation=lambda: TelegramBotValidationResult(
            success=True,
            bot=TelegramBotIdentity(
                bot_id="987654321",
                username="lea_test_bot",
                display_name="LEA Test Bot",
            ),
            issues=(),
        ),
        notifier=lambda _message: True,
    )

    assert result.accepted is True
    assert calls == [(record.executable, plan.acceptance_work_directory, 15.0)]
    assert plan.acceptance_work_directory != record.data.parent
    assert "acceptance: PASSED" in result.summary
    assert any(check.code == "taskwarrior_lifecycle" for check in result.checks)


def test_acceptance_boundary_exceptions_are_structured(
    tmp_path: Path,
) -> None:
    plan, _runtime = _prepare(tmp_path, telegram=True)
    record = _record(tmp_path)

    def fail_taskwarrior(
        _executable: Path,
        *,
        temporary_parent: Path,
        timeout_seconds: float,
    ) -> TaskwarriorSmokeTestResult:
        assert temporary_parent == plan.acceptance_work_directory
        assert timeout_seconds == 15.0
        raise RuntimeError("sensitive Taskwarrior detail")

    failed = run_release_candidate_acceptance(
        plan,
        PostInstallHealthResult(healthy=True, checks=(), issues=()),
        taskwarrior_record_reader=lambda _path: (record, ()),
        taskwarrior_acceptance=fail_taskwarrior,
        telegram_validation=lambda: TelegramBotValidationResult(
            success=True,
            bot=TelegramBotIdentity(
                bot_id="987654321",
                username="lea_test_bot",
                display_name="LEA Test Bot",
            ),
            issues=(),
        ),
        notifier=lambda _message: True,
    )

    assert failed.accepted is False
    assert failed.checks[0].state is PostInstallCheckState.FAILED
    assert "sensitive" not in failed.summary

    def fail_telegram() -> TelegramBotValidationResult:
        raise RuntimeError("sensitive Telegram detail")

    telegram_failed = run_release_candidate_acceptance(
        plan,
        PostInstallHealthResult(healthy=True, checks=(), issues=()),
        taskwarrior_record_reader=lambda _path: (record, ()),
        taskwarrior_acceptance=lambda *_args, **_kwargs: TaskwarriorSmokeTestResult(
            passed=True,
            version="3.4.2",
            issues=(),
        ),
        telegram_validation=fail_telegram,
        notifier=lambda _message: True,
    )

    checks = {check.code: check for check in telegram_failed.checks}
    assert telegram_failed.accepted is False
    assert checks["telegram_get_me"].state is PostInstallCheckState.FAILED
    assert checks["telegram_completion_message"].state is PostInstallCheckState.WARNING
    assert "skipped" in checks["telegram_completion_message"].message
    assert "sensitive" not in telegram_failed.summary


def test_optional_notification_exception_is_warning(tmp_path: Path) -> None:
    plan, _runtime = _prepare(tmp_path, telegram=True)
    record = _record(tmp_path)

    def notify(_message: str) -> bool:
        raise RuntimeError("sensitive notifier detail")

    result = run_release_candidate_acceptance(
        plan,
        PostInstallHealthResult(healthy=True, checks=(), issues=()),
        taskwarrior_record_reader=lambda _path: (record, ()),
        taskwarrior_acceptance=lambda *_args, **_kwargs: TaskwarriorSmokeTestResult(
            passed=True,
            version="3.4.2",
            issues=(),
        ),
        telegram_validation=lambda: TelegramBotValidationResult(
            success=True,
            bot=TelegramBotIdentity(
                bot_id="987654321",
                username="lea_test_bot",
                display_name="LEA Test Bot",
            ),
            issues=(),
        ),
        notifier=notify,
    )

    checks = {check.code: check for check in result.checks}
    assert result.accepted is True
    assert checks["telegram_completion_message"].state is PostInstallCheckState.WARNING
    assert "sensitive" not in result.summary


def test_acceptance_requires_healthy_installation(tmp_path: Path) -> None:
    plan, _runtime = _prepare(tmp_path)
    unhealthy = run_post_install_health(
        plan,
        runtime_loader=_failed_configuration,
    )

    result = run_release_candidate_acceptance(plan, unhealthy)

    assert result.accepted is False
    assert result.issues[0].step is not None


def test_health_preserves_taskwarrior_inspection_diagnostics(
    tmp_path: Path,
) -> None:
    """Health output should expose the structured inspection reason."""
    plan, runtime = _prepare(tmp_path)
    record = _record(tmp_path)

    result = run_post_install_health(
        plan,
        runtime_loader=lambda _path: ConfigurationResult(
            success=True,
            config=runtime,
            issues=(),
        ),
        runtime_health_checker=lambda _config: RuntimeHealthResult(
            healthy=True,
            issues=(),
        ),
        taskwarrior_record_reader=lambda _path: (record, ()),
        taskwarrior_inspector=lambda _config: TaskProviderInspectionResult(
            available=False,
            provider="taskwarrior",
            version=None,
            issues=(
                TaskProviderIssue(
                    code="taskwarrior_working_directory_unavailable",
                    message="The configured working directory is unavailable.",
                ),
            ),
        ),
    )

    inspection = next(
        check for check in result.checks if check.code == "taskwarrior_inspection"
    )

    assert inspection.state is PostInstallCheckState.FAILED
    assert "taskwarrior_working_directory_unavailable" in inspection.message
    assert "working directory is unavailable" in inspection.message
