"""Tests for release-candidate Telegram configuration persistence."""

from pathlib import Path

from lea.channels import (
    ChannelCapability,
    load_authorised_channel_users,
    resolve_channel_capabilities,
)
from lea.installers.release_candidate import (
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    TelegramBotIdentity,
    TelegramConfigurationPlan,
    TelegramOnboardingConfirmation,
    TelegramOnboardingIdentity,
    TelegramOnboardingRole,
    create_base_configuration_plan,
    create_installation_record,
    create_telegram_configuration_plan,
    install_base_configuration,
    persist_telegram_configuration,
)

TOKEN = "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG"
REPLACEMENT_TOKEN = "987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefg"


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


def _contents(plan: TelegramConfigurationPlan) -> dict[Path, str]:
    paths = (
        plan.runtime_config_file,
        plan.telegram_config_file,
        plan.authorised_users_file,
        plan.worker_environment_file,
        plan.token_file,
    )
    return {path: path.read_text(encoding="utf-8") for path in paths if path.exists()}


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
    request = _request(tmp_path)
    base_result = install_base_configuration(
        create_base_configuration_plan(request),
        create_installation_record(
            request=request,
            lea_version="0.1.0",
        ),
    )
    plan = create_telegram_configuration_plan(
        request,
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

    assert base_result.success is True
    assert result.success is True
    assert set(result.changed_files) == {
        plan.telegram_config_file,
        plan.authorised_users_file,
        plan.worker_environment_file,
        plan.token_file,
    }
    assert plan.token_file.read_text(encoding="utf-8") == TOKEN + "\n"
    assert TOKEN not in plan.telegram_config_file.read_text(encoding="utf-8")
    assert len(ownership) == 5


def test_fresh_base_configuration_does_not_require_telegram_replacement(
    tmp_path: Path,
) -> None:
    """Telegram persistence must accept the base file from the same install."""
    request = _request(tmp_path)
    base = install_base_configuration(
        create_base_configuration_plan(request),
        create_installation_record(
            request=request,
            lea_version="0.1.0",
        ),
    )
    plan = create_telegram_configuration_plan(
        request,
        _confirmation(),
    )

    result = persist_telegram_configuration(
        plan,
        token=TOKEN,
        approve_replacement=False,
    )

    assert base.success is True
    assert result.success is True
    assert plan.runtime_config_file not in result.changed_files
    assert plan.runtime_config_file.read_text(encoding="utf-8") == (
        plan.runtime_contents
    )


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


def test_differing_file_requires_approval_before_any_mutation(
    tmp_path: Path,
) -> None:
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
    assert result.changed_files == ()
    assert not plan.runtime_config_file.exists()
    assert plan.telegram_config_file.read_text(encoding="utf-8") == "different\n"


def test_approved_replacement_creates_restricted_backup(tmp_path: Path) -> None:
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
        and (path.stat().st_mode & 0o777) == 0o640
        for path in result.backups_created
    )


def test_token_backup_uses_secret_mode_and_ownership(tmp_path: Path) -> None:
    plan = create_telegram_configuration_plan(
        _request(tmp_path),
        _confirmation(),
    )
    first = persist_telegram_configuration(
        plan,
        token=TOKEN,
        approve_replacement=False,
    )
    ownership: list[tuple[Path, str, str]] = []

    second = persist_telegram_configuration(
        plan,
        token=REPLACEMENT_TOKEN,
        approve_replacement=True,
        apply_ownership=lambda path, owner, group: ownership.append(
            (path, owner, group)
        ),
    )

    token_backups = tuple(
        path
        for path in second.backups_created
        if path.read_text(encoding="utf-8") == TOKEN + "\n"
    )

    assert first.success is True
    assert second.success is True
    assert len(token_backups) == 1
    assert (token_backups[0].stat().st_mode & 0o777) == 0o600
    assert (token_backups[0], "lea", "lea") in ownership


def test_validation_failure_restores_all_previous_files(tmp_path: Path) -> None:
    request = _request(tmp_path)
    original = create_telegram_configuration_plan(
        request,
        _confirmation(),
    )
    first = persist_telegram_configuration(
        original,
        token=TOKEN,
        approve_replacement=False,
    )
    before = _contents(original)

    replacement = create_telegram_configuration_plan(
        request,
        _confirmation(role=TelegramOnboardingRole.TESTER),
    )

    def reject(_plan: object) -> None:
        raise ValueError("Injected validation failure.")

    result = persist_telegram_configuration(
        replacement,
        token=REPLACEMENT_TOKEN,
        approve_replacement=True,
        validate_generated_files=reject,
    )

    assert first.success is True
    assert result.success is False
    assert result.changed_files == ()
    assert _contents(replacement) == before


def test_custom_role_resolves_to_exact_selected_capabilities(
    tmp_path: Path,
) -> None:
    plan = create_telegram_configuration_plan(
        _request(tmp_path),
        _confirmation(role=TelegramOnboardingRole.CUSTOM),
    )
    plan.authorised_users_file.parent.mkdir(parents=True)
    plan.authorised_users_file.write_text(
        plan.authorised_users_contents,
        encoding="utf-8",
    )

    loaded = load_authorised_channel_users(plan.authorised_users_file)

    assert loaded.success is True
    assert len(loaded.users) == 1
    assert loaded.users[0].role.value == "read_only"
    assert resolve_channel_capabilities(loaded.users[0]) == (
        ChannelCapability.TASKS_READ.value,
    )
