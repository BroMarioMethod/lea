"""Tests for Telegram runtime configuration and construction."""

from pathlib import Path

import pytest

from lea.adapters.telegram import (
    FakeTelegramTransport,
    TelegramOffsetStore,
    TelegramTransport,
)
from lea.runtime import (
    TelegramRuntimeConfig,
    TelegramRuntimeDependencies,
    TelegramRuntimeIssue,
    TelegramRuntimeResult,
    build_telegram_runtime,
    isolated_test_runtime_config,
)

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghi"


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    token = (tmp_path / "secrets" / "telegram-token").resolve()
    users = (tmp_path / "telegram" / "authorised-users.toml").resolve()
    offset = (tmp_path / "state" / "telegram" / "offset.json").resolve()

    token.parent.mkdir(parents=True)
    users.parent.mkdir(parents=True)
    offset.parent.mkdir(parents=True)
    token.write_text(TOKEN + "\n", encoding="utf-8")
    token.chmod(0o600)
    users.write_text(
        """
schema_version = 1

[[users]]
name = "Owner"
channel = "telegram"
user_id = 123456789
conversation_id = 123456789
role = "owner"
enabled = true
add_capabilities = []
remove_capabilities = []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    users.chmod(0o600)
    return token, users, offset


def _telegram(users: Path, offset: Path) -> TelegramRuntimeConfig:
    return TelegramRuntimeConfig(
        enabled=True,
        bot_username="lea_test_bot",
        authorised_users_file=users,
        offset_file=offset,
        poll_timeout_seconds=30,
        fetch_limit=100,
    )


def test_runtime_construction_assembles_dependencies_without_network(
    tmp_path: Path,
) -> None:
    token, users, offset = _files(tmp_path)
    runtime = isolated_test_runtime_config(
        tmp_path.resolve(),
        telegram_token_file=token,
    )
    received: list[str] = []

    def factory(bot_token: str) -> TelegramTransport:
        received.append(bot_token)
        return FakeTelegramTransport()

    result = build_telegram_runtime(
        runtime,
        _telegram(users, offset),
        transport_factory=factory,
        offset_fsync=False,
    )

    assert result.success is True
    assert result.dependencies is not None
    assert received == [TOKEN]
    assert result.dependencies.config.bot_username == "lea_test_bot"
    assert len(result.dependencies.authorised_users) == 1
    assert isinstance(result.dependencies.offset_store, TelegramOffsetStore)
    assert isinstance(result.dependencies.transport, TelegramTransport)
    assert not offset.exists()


def test_disabled_runtime_fails_before_reading_files(tmp_path: Path) -> None:
    missing = (tmp_path / "missing").resolve()
    runtime = isolated_test_runtime_config(tmp_path.resolve())

    result = build_telegram_runtime(
        runtime,
        TelegramRuntimeConfig(
            enabled=False,
            bot_username="lea_test_bot",
            authorised_users_file=missing,
            offset_file=missing,
        ),
        transport_factory=lambda _token: FakeTelegramTransport(),
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_runtime_disabled"


def test_missing_token_configuration_is_rejected(tmp_path: Path) -> None:
    _token, users, offset = _files(tmp_path)
    runtime = isolated_test_runtime_config(tmp_path.resolve())

    result = build_telegram_runtime(
        runtime,
        _telegram(users, offset),
        transport_factory=lambda _token: FakeTelegramTransport(),
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_token_not_configured"


@pytest.mark.parametrize(
    ("contents", "code"),
    [
        ("", "telegram_token_empty"),
        ("not-a-token\n", "telegram_token_malformed"),
        (TOKEN + "\nextra\n", "telegram_token_multiline"),
    ],
)
def test_invalid_token_contents_fail_closed(
    tmp_path: Path,
    contents: str,
    code: str,
) -> None:
    token, users, offset = _files(tmp_path)
    token.write_text(contents, encoding="utf-8")
    token.chmod(0o600)
    runtime = isolated_test_runtime_config(
        tmp_path.resolve(),
        telegram_token_file=token,
    )

    result = build_telegram_runtime(
        runtime,
        _telegram(users, offset),
        transport_factory=lambda _token: FakeTelegramTransport(),
    )

    assert result.success is False
    assert result.issues[0].code == code


def test_invalid_utf8_token_is_rejected(tmp_path: Path) -> None:
    token, users, offset = _files(tmp_path)
    token.write_bytes(b"\xff")
    token.chmod(0o600)
    runtime = isolated_test_runtime_config(
        tmp_path.resolve(),
        telegram_token_file=token,
    )

    result = build_telegram_runtime(
        runtime,
        _telegram(users, offset),
        transport_factory=lambda _token: FakeTelegramTransport(),
    )

    assert result.issues[0].code == "telegram_token_invalid_utf8"


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o666])
def test_insecure_token_permissions_are_rejected(
    tmp_path: Path,
    mode: int,
) -> None:
    token, users, offset = _files(tmp_path)
    token.chmod(mode)
    runtime = isolated_test_runtime_config(
        tmp_path.resolve(),
        telegram_token_file=token,
    )

    result = build_telegram_runtime(
        runtime,
        _telegram(users, offset),
        transport_factory=lambda _token: FakeTelegramTransport(),
    )

    assert result.issues[0].code == "telegram_token_insecure_permissions"


def test_symlink_token_is_rejected(tmp_path: Path) -> None:
    token, users, offset = _files(tmp_path)
    real = token.with_name("real-token")
    token.rename(real)
    token.symlink_to(real)
    runtime = isolated_test_runtime_config(
        tmp_path.resolve(),
        telegram_token_file=token,
    )

    result = build_telegram_runtime(
        runtime,
        _telegram(users, offset),
        transport_factory=lambda _token: FakeTelegramTransport(),
    )

    assert result.issues[0].code == "telegram_token_symlink_rejected"


def test_authorised_user_failures_are_preserved(tmp_path: Path) -> None:
    token, _users, offset = _files(tmp_path)
    missing = (tmp_path / "telegram" / "missing.toml").resolve()
    runtime = isolated_test_runtime_config(
        tmp_path.resolve(),
        telegram_token_file=token,
    )

    result = build_telegram_runtime(
        runtime,
        _telegram(missing, offset),
        transport_factory=lambda _token: FakeTelegramTransport(),
    )

    assert result.success is False
    assert result.issues[0].code == "authorised_users_not_found"


def test_no_enabled_authorised_users_is_rejected(tmp_path: Path) -> None:
    token, users, offset = _files(tmp_path)
    contents = users.read_text(encoding="utf-8").replace(
        "enabled = true",
        "enabled = false",
    )
    users.write_text(contents, encoding="utf-8")
    runtime = isolated_test_runtime_config(
        tmp_path.resolve(),
        telegram_token_file=token,
    )

    result = build_telegram_runtime(
        runtime,
        _telegram(users, offset),
        transport_factory=lambda _token: FakeTelegramTransport(),
    )

    assert result.issues[0].code == "telegram_authorised_users_empty"


def test_transport_factory_failure_is_redacted(tmp_path: Path) -> None:
    token, users, offset = _files(tmp_path)
    runtime = isolated_test_runtime_config(
        tmp_path.resolve(),
        telegram_token_file=token,
    )

    def factory(_token: str) -> TelegramTransport:
        raise RuntimeError("secret internal detail")

    result = build_telegram_runtime(
        runtime,
        _telegram(users, offset),
        transport_factory=factory,
    )

    assert result.issues[0].code == "telegram_transport_construction_failed"
    assert "secret internal detail" not in result.issues[0].message


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bot_username", "@lea_test_bot"),
        ("bot_username", "lea"),
        ("poll_timeout_seconds", 0),
        ("poll_timeout_seconds", 51),
        ("fetch_limit", 0),
        ("fetch_limit", 101),
    ],
)
def test_invalid_telegram_configuration_is_rejected(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    _token, users, offset = _files(tmp_path)
    values: dict[str, object] = {
        "enabled": True,
        "bot_username": "lea_test_bot",
        "authorised_users_file": users,
        "offset_file": offset,
        "poll_timeout_seconds": 30,
        "fetch_limit": 100,
    }
    values[field] = value

    with pytest.raises((TypeError, ValueError)):
        TelegramRuntimeConfig(**values)  # type: ignore[arg-type]


def test_result_contracts_enforce_consistency() -> None:
    issue = TelegramRuntimeIssue(
        code="failed",
        message="Construction failed.",
    )

    with pytest.raises(ValueError, match="must contain dependencies"):
        TelegramRuntimeResult(
            success=True,
            dependencies=None,
            issues=(),
        )

    with pytest.raises(ValueError, match="at least one issue"):
        TelegramRuntimeResult(
            success=False,
            dependencies=None,
            issues=(),
        )

    assert issue.code == "failed"


def test_dependency_contract_rejects_disabled_configuration(
    tmp_path: Path,
) -> None:
    _token, users, offset = _files(tmp_path)

    with pytest.raises(ValueError, match="enabled configuration"):
        TelegramRuntimeDependencies(
            config=TelegramRuntimeConfig(
                enabled=False,
                bot_username="lea_test_bot",
                authorised_users_file=users,
                offset_file=offset,
            ),
            authorised_users=(),
            offset_store=pytest.importorskip(
                "lea.adapters.telegram"
            ).FileTelegramOffsetStore(offset),
            transport=FakeTelegramTransport(),
        )
