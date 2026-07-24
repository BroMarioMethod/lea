"""Telegram configuration persistence for release-candidate installation."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lea.channels import (
    AuthorisedChannelUser,
    ChannelCapability,
    ChannelName,
    ChannelRole,
    default_channel_role_policies,
    load_authorised_channel_users,
)
from lea.installers.release_candidate.configuration import (
    _capture_snapshot,
    _FileSnapshot,
    _restore_snapshot,
    _write_if_changed,
)
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


@dataclass(frozen=True, slots=True)
class _ManagedTelegramFile:
    """One managed Telegram file and its required metadata."""

    destination: Path
    contents: str
    mode: int
    owner: str
    group: str


GeneratedFilesValidator = Callable[[TelegramConfigurationPlan], None]


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
    validate_generated_files: GeneratedFilesValidator | None = None,
) -> TelegramConfigurationResult:
    """Persist Telegram files as one validated transaction."""
    validate_bot_token_shape(token)
    managed = _managed_files(plan, token)

    changed: list[Path] = []
    backups: list[Path] = []
    snapshots: dict[Path, _FileSnapshot] = {}
    rollback_failed = False

    try:
        plan.backup_directory.mkdir(parents=True, exist_ok=True)

        # Check every replacement before mutating the first file.
        for item in managed:
            item.destination.parent.mkdir(parents=True, exist_ok=True)

            if item.destination.exists():
                if item.destination.is_symlink() or not item.destination.is_file():
                    raise OSError(f"Unsafe managed file path: {item.destination}")

                existing = item.destination.read_text(encoding="utf-8")
                if existing != item.contents and not approve_replacement:
                    raise PermissionError(
                        f"Replacement approval required for {item.destination}."
                    )

        snapshots = {
            item.destination: _capture_snapshot(item.destination) for item in managed
        }

        for item in managed:
            was_changed, backup = _write_if_changed(
                destination=item.destination,
                contents=item.contents,
                backup_directory=plan.backup_directory,
                mode=item.mode,
                backup_mode=item.mode,
            )
            apply_ownership(
                item.destination,
                item.owner,
                item.group,
            )

            if was_changed:
                changed.append(item.destination)

            if backup is not None:
                backups.append(backup)
                apply_ownership(
                    backup,
                    item.owner,
                    item.group,
                )

        validator = validate_generated_files or _validate_generated_files
        validator(plan)

    except (KeyError, OSError, PermissionError, RuntimeError, ValueError) as error:
        try:
            for item in reversed(managed):
                snapshot = snapshots.get(item.destination)
                if snapshot is None:
                    continue

                _restore_snapshot(item.destination, snapshot)
                if snapshot.existed:
                    apply_ownership(
                        item.destination,
                        item.owner,
                        item.group,
                    )
        except (KeyError, OSError, RuntimeError, ValueError):
            rollback_failed = True

        issues = [
            InstallerIssue(
                code=InstallerIssueCode.STEP_FAILED,
                message=(
                    "Telegram configuration persistence failed: "
                    f"{type(error).__name__}."
                ),
                step=InstallerStepId.TELEGRAM_CONFIGURATION,
            )
        ]
        if rollback_failed:
            issues.append(
                InstallerIssue(
                    code=InstallerIssueCode.ROLLBACK_FAILED,
                    message="Telegram configuration rollback failed.",
                    step=InstallerStepId.TELEGRAM_CONFIGURATION,
                )
            )

        return TelegramConfigurationResult(
            success=False,
            changed_files=tuple(changed) if rollback_failed else (),
            backups_created=tuple(backups),
            issues=tuple(issues),
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


def _managed_files(
    plan: TelegramConfigurationPlan,
    token: str,
) -> tuple[_ManagedTelegramFile, ...]:
    return (
        _ManagedTelegramFile(
            destination=plan.runtime_config_file,
            contents=plan.runtime_contents,
            mode=plan.configuration_mode,
            owner=plan.configuration_owner,
            group=plan.configuration_group,
        ),
        _ManagedTelegramFile(
            destination=plan.telegram_config_file,
            contents=plan.telegram_contents,
            mode=plan.configuration_mode,
            owner=plan.configuration_owner,
            group=plan.configuration_group,
        ),
        _ManagedTelegramFile(
            destination=plan.authorised_users_file,
            contents=plan.authorised_users_contents,
            mode=plan.configuration_mode,
            owner=plan.configuration_owner,
            group=plan.configuration_group,
        ),
        _ManagedTelegramFile(
            destination=plan.worker_environment_file,
            contents=plan.worker_environment_contents,
            mode=plan.configuration_mode,
            owner=plan.configuration_owner,
            group=plan.configuration_group,
        ),
        _ManagedTelegramFile(
            destination=plan.token_file,
            contents=token + "\n",
            mode=plan.token_mode,
            owner=plan.token_owner,
            group=plan.token_group,
        ),
    )


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
    additions: tuple[ChannelCapability, ...] = ()
    removals: tuple[ChannelCapability, ...] = ()

    if confirmation.role is TelegramOnboardingRole.CUSTOM:
        selected = set(confirmation.custom_capabilities)
        baseline = _read_only_capabilities()
        additions = tuple(sorted(selected - baseline, key=str))
        removals = tuple(sorted(baseline - selected, key=str))

    user = AuthorisedChannelUser(
        name=confirmation.identity.display_name,
        channel=ChannelName.TELEGRAM,
        user_id=confirmation.identity.user_id,
        conversation_id=confirmation.identity.chat_id,
        role=role,
        enabled=True,
        add_capabilities=additions,
        remove_capabilities=removals,
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


def _read_only_capabilities() -> set[ChannelCapability]:
    matching = tuple(
        policy
        for policy in default_channel_role_policies()
        if policy.role is ChannelRole.READ_ONLY
    )
    if len(matching) != 1:
        raise RuntimeError("Exactly one read-only channel policy is required.")

    return set(matching[0].capabilities)


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
