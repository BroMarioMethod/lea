"""Tests for release-candidate Telegram systemd deployment."""

from pathlib import Path

from lea.installers.release_candidate import (
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    SystemCommandResult,
    TelegramSystemdServicePlan,
    create_telegram_systemd_service_plan,
    deploy_telegram_systemd_service,
)


class CommandSequence:
    """Deterministic exact-command executor."""

    def __init__(self, return_codes: tuple[int, ...]) -> None:
        self.return_codes = list(return_codes)
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: tuple[str, ...]) -> SystemCommandResult:
        self.commands.append(command)
        return SystemCommandResult(self.return_codes.pop(0))


def _request(tmp_path: Path) -> ReleaseCandidateInstallRequest:
    installation = tmp_path / "opt" / "lea"
    service_source = installation / "deploy" / "systemd" / "lea-telegram.service"
    service_source.parent.mkdir(parents=True)
    service_source.write_text(
        "[Unit]\nDescription=LEA Telegram foreground worker\n"
        "[Service]\nExecStart=/opt/lea/.venv/bin/lea-telegram\n"
        "[Install]\nWantedBy=multi-user.target\n",
        encoding="utf-8",
    )

    return ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=True,
        installation_root=installation,
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
    )


def _plan(tmp_path: Path) -> TelegramSystemdServicePlan:
    return create_telegram_systemd_service_plan(
        _request(tmp_path),
        systemd_directory=tmp_path / "etc" / "systemd" / "system",
        systemctl=tmp_path / "usr" / "bin" / "systemctl",
    )


def test_plan_uses_exact_production_defaults(tmp_path: Path) -> None:
    request = _request(tmp_path)
    plan = create_telegram_systemd_service_plan(request)

    assert plan.destination_file == Path("/etc/systemd/system/lea-telegram.service")
    assert plan.systemctl == Path("/usr/bin/systemctl")
    assert plan.service_name == "lea-telegram.service"


def test_new_unit_is_reloaded_enabled_started_and_verified(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    commands = CommandSequence((0, 1, 0, 1, 0, 0, 0))
    ownership: list[tuple[Path, str, str]] = []

    result = deploy_telegram_systemd_service(
        plan,
        approve_replacement=False,
        execute=commands,
        apply_ownership=lambda path, owner, group: ownership.append(
            (path, owner, group)
        ),
        fsync=False,
    )

    assert result.success is True
    assert result.unit_changed is True
    assert result.enabled is True
    assert result.active is True
    assert result.backup_created is None
    assert ownership == [(plan.destination_file, "root", "root")]
    assert commands.commands == [
        (str(plan.systemctl), "daemon-reload"),
        (str(plan.systemctl), "is-enabled", plan.service_name),
        (str(plan.systemctl), "enable", plan.service_name),
        (str(plan.systemctl), "is-active", plan.service_name),
        (str(plan.systemctl), "start", plan.service_name),
        (str(plan.systemctl), "is-enabled", plan.service_name),
        (str(plan.systemctl), "is-active", plan.service_name),
    ]


def test_existing_active_service_is_idempotent(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    plan.destination_file.parent.mkdir(parents=True)
    plan.destination_file.write_text(
        plan.source_file.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    commands = CommandSequence((0, 0, 0, 0))

    result = deploy_telegram_systemd_service(
        plan,
        approve_replacement=False,
        execute=commands,
        apply_ownership=lambda _path, _owner, _group: None,
        fsync=False,
    )

    assert result.success is True
    assert result.unit_changed is False
    assert result.backup_created is None
    assert all("daemon-reload" not in command for command in result.commands)
    assert all("enable" not in command for command in result.commands)
    assert all("start" not in command for command in result.commands)


def test_differing_unit_requires_approval(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    plan.destination_file.parent.mkdir(parents=True)
    plan.destination_file.write_text("different\n", encoding="utf-8")

    result = deploy_telegram_systemd_service(
        plan,
        approve_replacement=False,
        execute=CommandSequence(()),
        apply_ownership=lambda _path, _owner, _group: None,
        fsync=False,
    )

    assert result.success is False
    assert result.commands == ()
    assert plan.destination_file.read_text(encoding="utf-8") == "different\n"


def test_approved_replacement_creates_backup(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    plan.destination_file.parent.mkdir(parents=True)
    plan.destination_file.write_text("different\n", encoding="utf-8")
    commands = CommandSequence((0, 0, 0, 0, 0))

    result = deploy_telegram_systemd_service(
        plan,
        approve_replacement=True,
        execute=commands,
        apply_ownership=lambda _path, _owner, _group: None,
        fsync=False,
    )

    assert result.success is True
    assert result.backup_created is not None
    assert result.backup_created.read_text(encoding="utf-8") == "different\n"


def test_command_failure_is_redacted(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def failed(command: tuple[str, ...]) -> SystemCommandResult:
        return SystemCommandResult(
            return_code=5,
            standard_output="sensitive standard output",
            standard_error="sensitive standard error",
        )

    result = deploy_telegram_systemd_service(
        plan,
        approve_replacement=False,
        execute=failed,
        apply_ownership=lambda _path, _owner, _group: None,
        fsync=False,
    )

    assert result.success is False
    assert "sensitive" not in result.issues[0].message
    assert result.issues[0].step is not None
    assert result.issues[0].step.value == "systemd-service"
