"""Tests for release-candidate post-install health and acceptance."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def _prepare(
    tmp_path: Path,
    *,
    telegram: bool = False,
) -> tuple[PostInstallHealthPlan, RuntimeConfig]:
    request = _request(tmp_path, telegram=telegram)
    plan = create_post_install_health_plan(
        request,
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
