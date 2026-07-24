#!/usr/bin/env python3
"""Validate committed Telegram deployment assets without reading secrets."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = REPOSITORY_ROOT / "deploy/systemd/lea-telegram.service"
ENV_EXAMPLE_PATH = REPOSITORY_ROOT / "config/examples/lea-telegram-worker.env"
TELEGRAM_EXAMPLE_PATH = REPOSITORY_ROOT / "config/examples/lea.telegram.example.toml"
USERS_EXAMPLE_PATH = (
    REPOSITORY_ROOT / "config/examples/telegram-authorised-users.example.toml"
)

_REQUIRED_SERVICE_LINES = frozenset(
    {
        "Type=simple",
        "User=lea",
        "Group=lea",
        "WorkingDirectory=/opt/lea",
        "EnvironmentFile=/etc/lea/telegram/worker.env",
        "ExecStart=/opt/lea/.venv/bin/lea-telegram",
        "Restart=on-failure",
        "KillSignal=SIGTERM",
        "UMask=0077",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ReadWritePaths=/var/lib/lea /var/log/lea /run/lea",
        "ReadOnlyPaths=/etc/lea /opt/lea",
    }
)

_FORBIDDEN_SERVICE_PARTS = (
    "Type=forking",
    "ExecStartPre=/bin/sh",
    "bash -c",
    "sudo ",
    "--token",
    "BOT_TOKEN=",
)

_REQUIRED_ENV_LINES = frozenset(
    {
        "LEA_RUNTIME_CONFIG=/etc/lea/lea.toml",
        "LEA_TELEGRAM_CONFIG=/etc/lea/telegram/telegram.toml",
    }
)

_FORBIDDEN_EXAMPLE_PARTS = (
    "123456:",
    "bot_token =",
    "telegram_bot_token =",
    "api_key =",
)


@dataclass(frozen=True, slots=True)
class DeploymentValidationIssue:
    """One deterministic deployment-asset validation issue."""

    code: str
    message: str
    path: Path

    def __post_init__(self) -> None:
        """Validate safe issue fields."""
        if not self.code.strip():
            raise ValueError("Validation issue code must be non-empty.")
        if not self.message.strip():
            raise ValueError("Validation issue message must be non-empty.")
        if not self.path.is_absolute():
            raise ValueError("Validation issue path must be absolute.")


def validate_telegram_deployment(
    *,
    service_path: Path = SERVICE_PATH,
    environment_example_path: Path = ENV_EXAMPLE_PATH,
    telegram_example_path: Path = TELEGRAM_EXAMPLE_PATH,
    authorised_users_example_path: Path = USERS_EXAMPLE_PATH,
) -> tuple[DeploymentValidationIssue, ...]:
    """Validate committed deployment assets without runtime mutation."""
    issues: list[DeploymentValidationIssue] = []

    service = _read(service_path, issues)
    environment = _read(environment_example_path, issues)
    telegram = _read(telegram_example_path, issues)
    users = _read(authorised_users_example_path, issues)

    if service is not None:
        supplied = frozenset(
            line.strip()
            for line in service.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        for required in sorted(_REQUIRED_SERVICE_LINES - supplied):
            issues.append(
                DeploymentValidationIssue(
                    code="service_directive_missing",
                    message=f"Required systemd directive is missing: {required}",
                    path=service_path,
                )
            )

        for forbidden in _FORBIDDEN_SERVICE_PARTS:
            if forbidden in service:
                issues.append(
                    DeploymentValidationIssue(
                        code="service_content_forbidden",
                        message=(
                            "The systemd asset contains a forbidden shell, "
                            "secret or incompatible service pattern."
                        ),
                        path=service_path,
                    )
                )

        if "[Install]" not in service or "WantedBy=multi-user.target" not in service:
            issues.append(
                DeploymentValidationIssue(
                    code="service_install_target_missing",
                    message="The systemd asset lacks its multi-user install target.",
                    path=service_path,
                )
            )

    if environment is not None:
        supplied_env = frozenset(
            line.strip()
            for line in environment.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        for required in sorted(_REQUIRED_ENV_LINES - supplied_env):
            issues.append(
                DeploymentValidationIssue(
                    code="environment_reference_missing",
                    message=f"Required environment reference is missing: {required}",
                    path=environment_example_path,
                )
            )

    for path, contents in (
        (environment_example_path, environment),
        (telegram_example_path, telegram),
        (authorised_users_example_path, users),
    ):
        if contents is None:
            continue

        for forbidden in _FORBIDDEN_EXAMPLE_PARTS:
            if forbidden.casefold() in contents.casefold():
                issues.append(
                    DeploymentValidationIssue(
                        code="example_secret_pattern_detected",
                        message=(
                            "A committed deployment example appears to contain "
                            "a secret value or secret field."
                        ),
                        path=path,
                    )
                )

    if telegram is not None:
        for required in (
            "enabled = false",
            'authorised_users_file = "/etc/lea/telegram/authorised-users.toml"',
            'offset_file = "/var/lib/lea/telegram/offset.json"',
        ):
            if required not in telegram:
                issues.append(
                    DeploymentValidationIssue(
                        code="telegram_example_setting_missing",
                        message=(
                            f"Required Telegram example setting is missing: {required}"
                        ),
                        path=telegram_example_path,
                    )
                )

    if users is not None:
        for required in (
            'channel = "telegram"',
            'role = "owner"',
            "enabled = true",
        ):
            if required not in users:
                issues.append(
                    DeploymentValidationIssue(
                        code="authorisation_example_setting_missing",
                        message=(
                            "Required authorised-user example setting is missing: "
                            f"{required}"
                        ),
                        path=authorised_users_example_path,
                    )
                )

    return tuple(issues)


def main() -> int:
    """Validate committed Telegram deployment assets."""
    issues = validate_telegram_deployment()

    if issues:
        print("Telegram deployment validation: FAILED", file=sys.stderr)
        for issue in issues:
            relative = issue.path.relative_to(REPOSITORY_ROOT)
            print(
                f"{issue.code}: {issue.message} | path={relative}",
                file=sys.stderr,
            )
        return 1

    print("Telegram deployment validation: PASSED")
    return 0


def _read(
    path: Path,
    issues: list[DeploymentValidationIssue],
) -> str | None:
    if not path.is_absolute():
        raise ValueError("Deployment validation paths must be absolute.")

    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        issues.append(
            DeploymentValidationIssue(
                code="deployment_asset_missing",
                message="Required Telegram deployment asset is missing.",
                path=path,
            )
        )
    except (OSError, UnicodeError):
        issues.append(
            DeploymentValidationIssue(
                code="deployment_asset_unreadable",
                message="Telegram deployment asset could not be read as UTF-8.",
                path=path,
            )
        )

    return None


if __name__ == "__main__":
    raise SystemExit(main())
