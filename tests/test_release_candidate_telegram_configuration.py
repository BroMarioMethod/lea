"""Tests for release-candidate Telegram configuration persistence."""

from pathlib import Path

from lea.channels import ChannelCapability
from lea.installers.release_candidate import (
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    TelegramBotIdentity,
    TelegramOnboardingConfirmation,
    TelegramOnboardingIdentity,
    TelegramOnboardingRole,
    create_telegram_configuration_plan,
    persist_telegram_configuration,
)

TOKEN = "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG"


def _request(tmp_path: Path) -> ReleaseCandidateInstallRequest:
    return ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=True,
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
    )


def _confirmation(
    *,
    role: TelegramOnboardingRole = TelegramOnboardingRole.OWNER,
) -> TelegramOnboardingConfirmation:
    capabilities = (
        (ChannelCapability.TASKS_READ,) if role is TelegramOnboardingRole.CUSTOM else ()
    )
    return TelegramOnboardingConfirmation(
        bot=TelegramBotIdentity(
            bot_id="987654321",
            username="lea_test_bot",
            display_name="LEA Test Bot",
        ),
        identity=TelegramOnboardingIdentity(
            update_id=42,
            user_id="123456789",
            chat_id="123456789",
            username="marius_example",
            display_name="Marius Example",
        ),
        confirmed=True,
        role=role,
        custom_capabilities=capabilities,
    )


def test_plan_uses_required_paths_and_modes(tmp_path: Path) -> None:
    plan = create_telegram_configuration_plan(
        _request(tmp_path),
        _confirmation(),
    )

    assert plan.runtime_config_file.name == "lea.toml"
    assert plan.telegram_config_file.name == "telegram.toml"
    assert plan.authorised_users_file.name == "authorised-users.toml"
    assert plan.worker_environment_file.name == "worker.env"
    assert plan.token_file.name == "telegram-bot-token"
    assert plan.configuration_mode == 0o640
    assert plan.token_mode == 0o600


def test_persistence_writes_and_validates_all_files(tmp_path: Path) -> None:
    plan = create_telegram_configuration_plan(
        _request(tmp_path),
        _confirmation(),
    )
    ownership: list[tuple[Path, str, str]] = []

    result = persist_telegram_configuration(
        plan,
        token=TOKEN,
        approve_replacement=False,
        apply_ownership=lambda path, owner, group: ownership.append(
            (path, owner, group)
        ),
    )

    assert result.success is True
    assert set(result.changed_files) == {
        plan.runtime_config_file,
        plan.telegram_config_file,
        plan.authorised_users_file,
        plan.worker_environment_file,
        plan.token_file,
    }
    assert plan.token_file.read_text(encoding="utf-8") == TOKEN + "\n"
    assert TOKEN not in plan.telegram_config_file.read_text(encoding="utf-8")
    assert len(ownership) == 5


def test_second_run_is_idempotent(tmp_path: Path) -> None:
    plan = create_telegram_configuration_plan(
        _request(tmp_path),
        _confirmation(),
    )

    first = persist_telegram_configuration(
        plan,
        token=TOKEN,
        approve_replacement=False,
    )
    second = persist_telegram_configuration(
        plan,
        token=TOKEN,
        approve_replacement=False,
    )

    assert first.success is True
    assert second.success is True
    assert second.changed_files == ()
    assert second.backups_created == ()


def test_differing_file_requires_approval(tmp_path: Path) -> None:
    plan = create_telegram_configuration_plan(
        _request(tmp_path),
        _confirmation(),
    )
    plan.telegram_config_file.parent.mkdir(parents=True)
    plan.telegram_config_file.write_text("different\n", encoding="utf-8")

    result = persist_telegram_configuration(
        plan,
        token=TOKEN,
        approve_replacement=False,
    )

    assert result.success is False
    assert plan.telegram_config_file.read_text(encoding="utf-8") == "different\n"


def test_approved_replacement_creates_backup(tmp_path: Path) -> None:
    plan = create_telegram_configuration_plan(
        _request(tmp_path),
        _confirmation(),
    )
    plan.telegram_config_file.parent.mkdir(parents=True)
    plan.telegram_config_file.write_text("different\n", encoding="utf-8")

    result = persist_telegram_configuration(
        plan,
        token=TOKEN,
        approve_replacement=True,
    )

    assert result.success is True
    assert result.backups_created
    assert any(
        path.read_text(encoding="utf-8") == "different\n"
        for path in result.backups_created
    )


def test_custom_role_renders_explicit_capabilities(tmp_path: Path) -> None:
    plan = create_telegram_configuration_plan(
        _request(tmp_path),
        _confirmation(role=TelegramOnboardingRole.CUSTOM),
    )

    assert 'role = "read_only"' in plan.authorised_users_contents
    assert '"Tasks.Read"' in plan.authorised_users_contents
