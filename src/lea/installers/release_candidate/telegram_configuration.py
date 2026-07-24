"""Telegram configuration persistence for release-candidate installation."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.channels import (
    AuthorisedChannelUser,
    ChannelName,
    ChannelRole,
    load_authorised_channel_users,
)
from lea.installers.release_candidate.configuration import _write_if_changed
from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
    ReleaseCandidateInstallRequest,
)
from lea.installers.release_candidate.telegram_onboarding import (
    TelegramOnboardingConfirmation,
    TelegramOnboardingRole,
    validate_bot_token_shape,
)
from lea.runtime import load_runtime_config
from lea.runtime.serialisation import render_runtime_config
from lea.runtime.templates import system_runtime_config
from lea.telegram_main import load_telegram_runtime_config

OwnershipApplier = Callable[[Path, str, str], None]


@dataclass(frozen=True, slots=True)
class TelegramConfigurationPlan:
    """Immutable plan for persisted Telegram configuration."""

    runtime_config_file: Path
    telegram_config_file: Path
    authorised_users_file: Path
    worker_environment_file: Path
    token_file: Path
    backup_directory: Path
    configuration_owner: str
    configuration_group: str
    configuration_mode: int
    token_owner: str
    token_group: str
    token_mode: int
    runtime_contents: str
    telegram_contents: str
    authorised_users_contents: str
    worker_environment_contents: str

    def __post_init__(self) -> None:
        """Validate configuration-plan fields."""
        for field_name, path in (
            ("runtime_config_file", self.runtime_config_file),
            ("telegram_config_file", self.telegram_config_file),
            ("authorised_users_file", self.authorised_users_file),
            ("worker_environment_file", self.worker_environment_file),
            ("token_file", self.token_file),
            ("backup_directory", self.backup_directory),
        ):
            _validate_absolute_path(path, field_name=field_name)

        for field_name, value in (
            ("configuration_owner", self.configuration_owner),
            ("configuration_group", self.configuration_group),
            ("token_owner", self.token_owner),
            ("token_group", self.token_group),
            ("runtime_contents", self.runtime_contents),
            ("telegram_contents", self.telegram_contents),
            ("authorised_users_contents", self.authorised_users_contents),
            ("worker_environment_contents", self.worker_environment_contents),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty.")

        for field_name, mode in (
            ("configuration_mode", self.configuration_mode),
            ("token_mode", self.token_mode),
        ):
            if mode < 0 or mode > 0o7777:
                raise ValueError(f"{field_name} must be a valid Unix mode.")


@dataclass(frozen=True, slots=True)
class TelegramConfigurationResult:
    """Result of persisting Telegram configuration."""

    success: bool
    changed_files: tuple[Path, ...]
    backups_created: tuple[Path, ...]
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate persistence-result consistency."""
        for field_name, paths in (
            ("changed_files", self.changed_files),
            ("backups_created", self.backups_created),
        ):
            for path in paths:
                _validate_absolute_path(path, field_name=field_name)

            if len(set(paths)) != len(paths):
                raise ValueError(f"{field_name} must not contain duplicates.")

        if self.success:
            if self.issues:
                raise ValueError("A successful result must not contain issues.")
            return

        if not self.issues:
            raise ValueError("A failed result must contain at least one issue.")


def create_telegram_configuration_plan(
    request: ReleaseCandidateInstallRequest,
    confirmation: TelegramOnboardingConfirmation,
) -> TelegramConfigurationPlan:
    """Create deterministic Telegram configuration documents."""
    if not request.enable_telegram:
        raise ValueError("Telegram configuration requires enable_telegram=True.")

    if not confirmation.confirmed or confirmation.role is None:
        raise ValueError("Telegram identity must be confirmed before persistence.")

    telegram_root = request.configuration_root / "telegram"
    token_file = request.configuration_root / "secrets" / "telegram-bot-token"
    users_file = telegram_root / "authorised-users.toml"
    telegram_file = telegram_root / "telegram.toml"
    worker_file = telegram_root / "worker.env"

    runtime = system_runtime_config(
        display_timezone=request.display_timezone,
        telegram_token_file=token_file,
    )

    return TelegramConfigurationPlan(
        runtime_config_file=request.configuration_root / "lea.toml",
        telegram_config_file=telegram_file,
        authorised_users_file=users_file,
        worker_environment_file=worker_file,
        token_file=token_file,
        backup_directory=request.state_root / "backups" / "telegram",
        configuration_owner="root",
        configuration_group=request.service_group,
        configuration_mode=0o640,
        token_owner=request.service_user,
        token_group=request.service_group,
        token_mode=0o600,
        runtime_contents=render_runtime_config(runtime),
        telegram_contents=_render_telegram_runtime(
            bot_username=confirmation.bot.username,
            authorised_users_file=users_file,
            offset_file=request.state_root / "telegram" / "offset.json",
        ),
        authorised_users_contents=_render_authorised_user(confirmation),
        worker_environment_contents=_render_worker_environment(
            runtime_file=request.configuration_root / "lea.toml",
            telegram_file=telegram_file,
        ),
    )


def persist_telegram_configuration(
    plan: TelegramConfigurationPlan,
    *,
    token: str,
    approve_replacement: bool,
    apply_ownership: OwnershipApplier = lambda _path, _owner, _group: None,
) -> TelegramConfigurationResult:
    """Persist validated Telegram files atomically and idempotently."""
    validate_bot_token_shape(token)

    managed = (
        (
            plan.runtime_config_file,
            plan.runtime_contents,
            plan.configuration_mode,
            plan.configuration_owner,
            plan.configuration_group,
        ),
        (
            plan.telegram_config_file,
            plan.telegram_contents,
            plan.configuration_mode,
            plan.configuration_owner,
            plan.configuration_group,
        ),
        (
            plan.authorised_users_file,
            plan.authorised_users_contents,
            plan.configuration_mode,
            plan.configuration_owner,
            plan.configuration_group,
        ),
        (
            plan.worker_environment_file,
            plan.worker_environment_contents,
            plan.configuration_mode,
            plan.configuration_owner,
            plan.configuration_group,
        ),
        (
            plan.token_file,
            token + "\n",
            plan.token_mode,
            plan.token_owner,
            plan.token_group,
        ),
    )

    changed: list[Path] = []
    backups: list[Path] = []

    try:
        plan.backup_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        for destination, contents, mode, owner, group in managed:
            destination.parent.mkdir(parents=True, exist_ok=True)

            if destination.exists():
                if destination.is_symlink() or not destination.is_file():
                    raise OSError(f"Unsafe managed file path: {destination}")

                existing = destination.read_text(encoding="utf-8")
                if existing != contents and not approve_replacement:
                    raise PermissionError(
                        f"Replacement approval required for {destination}."
                    )

            was_changed, backup = _write_if_changed(
                destination=destination,
                contents=contents,
                backup_directory=plan.backup_directory,
                mode=mode,
            )
            apply_ownership(destination, owner, group)

            if was_changed:
                changed.append(destination)
            if backup is not None:
                backups.append(backup)

        _validate_generated_files(plan)

    except (OSError, PermissionError, ValueError) as error:
        return TelegramConfigurationResult(
            success=False,
            changed_files=tuple(changed),
            backups_created=tuple(backups),
            issues=(
                InstallerIssue(
                    code=InstallerIssueCode.STEP_FAILED,
                    message=(
                        "Telegram configuration persistence failed: "
                        f"{type(error).__name__}."
                    ),
                    step=InstallerStepId.TELEGRAM_CONFIGURATION,
                ),
            ),
        )

    return TelegramConfigurationResult(
        success=True,
        changed_files=tuple(changed),
        backups_created=tuple(backups),
        issues=(),
    )


def apply_posix_ownership(path: Path, owner: str, group: str) -> None:
    """Apply explicit POSIX ownership using local account databases."""
    import grp
    import pwd

    user = pwd.getpwnam(owner)
    group_record = grp.getgrnam(group)
    os.chown(path, user.pw_uid, group_record.gr_gid)


def _validate_generated_files(plan: TelegramConfigurationPlan) -> None:
    runtime = load_runtime_config(plan.runtime_config_file)
    if not runtime.success:
        raise ValueError("Generated runtime configuration failed validation.")

    load_telegram_runtime_config(plan.telegram_config_file)

    users = load_authorised_channel_users(plan.authorised_users_file)
    if not users.success:
        raise ValueError("Generated authorised-user configuration failed validation.")

    environment = dict(
        line.split("=", 1)
        for line in plan.worker_environment_file.read_text(
            encoding="utf-8"
        ).splitlines()
        if line
    )
    if environment != {
        "LEA_RUNTIME_CONFIG": str(plan.runtime_config_file),
        "LEA_TELEGRAM_CONFIG": str(plan.telegram_config_file),
    }:
        raise ValueError("Generated worker environment failed validation.")


def _render_telegram_runtime(
    *,
    bot_username: str,
    authorised_users_file: Path,
    offset_file: Path,
) -> str:
    return (
        "[telegram]\n"
        "enabled = true\n"
        f'bot_username = "{bot_username}"\n'
        f'authorised_users_file = "{authorised_users_file}"\n'
        f'offset_file = "{offset_file}"\n'
        "poll_timeout_seconds = 30\n"
        "fetch_limit = 100\n"
    )


def _render_authorised_user(
    confirmation: TelegramOnboardingConfirmation,
) -> str:
    if confirmation.role is None:
        raise ValueError("Confirmed Telegram onboarding must contain a role.")

    role = _channel_role(confirmation.role)
    additions = (
        confirmation.custom_capabilities
        if confirmation.role is TelegramOnboardingRole.CUSTOM
        else ()
    )
    user = AuthorisedChannelUser(
        name=confirmation.identity.display_name,
        channel=ChannelName.TELEGRAM,
        user_id=confirmation.identity.user_id,
        conversation_id=confirmation.identity.chat_id,
        role=role,
        enabled=True,
        add_capabilities=additions,
    )

    additions_text = ", ".join(
        f'"{capability.value}"' for capability in user.add_capabilities
    )
    removals_text = ", ".join(
        f'"{capability.value}"' for capability in user.remove_capabilities
    )

    return (
        "schema_version = 1\n\n"
        "[[users]]\n"
        f'name = "{_escape_toml(user.name)}"\n'
        'channel = "telegram"\n'
        f'user_id = "{user.user_id}"\n'
        f'conversation_id = "{user.conversation_id}"\n'
        f'role = "{user.role.value}"\n'
        "enabled = true\n"
        f"add_capabilities = [{additions_text}]\n"
        f"remove_capabilities = [{removals_text}]\n"
    )


def _channel_role(role: TelegramOnboardingRole) -> ChannelRole:
    if role is TelegramOnboardingRole.OWNER:
        return ChannelRole.OWNER
    if role is TelegramOnboardingRole.TESTER:
        return ChannelRole.TESTER
    return ChannelRole.READ_ONLY


def _render_worker_environment(
    *,
    runtime_file: Path,
    telegram_file: Path,
) -> str:
    return f"LEA_RUNTIME_CONFIG={runtime_file}\nLEA_TELEGRAM_CONFIG={telegram_file}\n"


def _escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _validate_absolute_path(path: Path, *, field_name: str) -> None:
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")
    if not path.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")
    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
