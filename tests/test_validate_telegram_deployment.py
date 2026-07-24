"""Tests for committed Telegram deployment validation."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

_VALIDATOR_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "validate_telegram_deployment.py"
)

DeploymentValidator = Callable[..., tuple[Any, ...]]


def _load_validator_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "lea_validate_telegram_deployment",
        _VALIDATOR_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError("Telegram deployment validator could not be loaded.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_validator = _load_validator_module()
validate_telegram_deployment = cast(
    DeploymentValidator,
    _validator.validate_telegram_deployment,
)


def _write(path: Path, contents: str) -> Path:
    path.write_text(contents, encoding="utf-8")
    return path.resolve()


def _valid_assets(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    service = _write(
        tmp_path / "lea-telegram.service",
        """[Unit]
Description=LEA Telegram foreground worker

[Service]
Type=simple
User=lea
Group=lea
WorkingDirectory=/opt/lea
RuntimeDirectory=lea
RuntimeDirectoryMode=0750
EnvironmentFile=/etc/lea/telegram/worker.env
ExecStart=/opt/lea/.venv/bin/lea-telegram
Restart=on-failure
KillSignal=SIGTERM
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/lea /var/log/lea /run/lea
ReadOnlyPaths=/etc/lea /opt/lea

[Install]
WantedBy=multi-user.target
""",
    )
    environment = _write(
        tmp_path / "worker.env",
        """LEA_RUNTIME_CONFIG=/etc/lea/lea.toml
LEA_TELEGRAM_CONFIG=/etc/lea/telegram/telegram.toml
""",
    )
    telegram = _write(
        tmp_path / "telegram.toml",
        """[telegram]
enabled = false
bot_username = "lea_example_bot"
authorised_users_file = "/etc/lea/telegram/authorised-users.toml"
offset_file = "/var/lib/lea/telegram/offset.json"
poll_timeout_seconds = 30
fetch_limit = 100
""",
    )
    users = _write(
        tmp_path / "users.toml",
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
    )
    return service, environment, telegram, users


def test_valid_assets_pass(tmp_path: Path) -> None:
    service, environment, telegram, users = _valid_assets(tmp_path)

    issues = validate_telegram_deployment(
        service_path=service,
        environment_example_path=environment,
        telegram_example_path=telegram,
        authorised_users_example_path=users,
    )

    assert issues == ()


def test_missing_hardening_directive_fails(tmp_path: Path) -> None:
    service, environment, telegram, users = _valid_assets(tmp_path)
    service.write_text(
        service.read_text(encoding="utf-8").replace(
            "NoNewPrivileges=true\n",
            "",
        ),
        encoding="utf-8",
    )

    issues = validate_telegram_deployment(
        service_path=service,
        environment_example_path=environment,
        telegram_example_path=telegram,
        authorised_users_example_path=users,
    )

    assert any(issue.code == "service_directive_missing" for issue in issues)


def test_missing_runtime_directory_directive_fails(
    tmp_path: Path,
) -> None:
    service, environment, telegram, users = _valid_assets(tmp_path)
    service.write_text(
        service.read_text(encoding="utf-8").replace(
            "RuntimeDirectory=lea\n",
            "",
        ),
        encoding="utf-8",
    )

    issues = validate_telegram_deployment(
        service_path=service,
        environment_example_path=environment,
        telegram_example_path=telegram,
        authorised_users_example_path=users,
    )

    assert any(
        issue.code == "service_directive_missing"
        and "RuntimeDirectory=lea" in issue.message
        for issue in issues
    )


def test_secret_pattern_in_example_fails(tmp_path: Path) -> None:
    service, environment, telegram, users = _valid_assets(tmp_path)
    telegram.write_text(
        telegram.read_text(encoding="utf-8")
        + 'bot_token = "123456:abcdefghijklmnopqrstuvwxyz"\n',
        encoding="utf-8",
    )

    issues = validate_telegram_deployment(
        service_path=service,
        environment_example_path=environment,
        telegram_example_path=telegram,
        authorised_users_example_path=users,
    )

    assert any(issue.code == "example_secret_pattern_detected" for issue in issues)


def test_missing_asset_is_reported(tmp_path: Path) -> None:
    service, environment, telegram, users = _valid_assets(tmp_path)
    telegram.unlink()

    issues = validate_telegram_deployment(
        service_path=service,
        environment_example_path=environment,
        telegram_example_path=telegram,
        authorised_users_example_path=users,
    )

    assert any(issue.code == "deployment_asset_missing" for issue in issues)
