"""Tests for strict deterministic runtime TOML loading."""

from pathlib import Path

import pytest

from lea.runtime import (
    RuntimeProfile,
    load_runtime_config,
)


def valid_toml(
    root: Path,
    *,
    profile: str = "development",
    timezone: str = "Africa/Gaborone",
) -> str:
    """Return one valid deterministic runtime configuration."""
    state_dir = root / "state"
    log_dir = root / "log"
    run_dir = root / "run"

    return f"""
schema_version = 1
profile = "{profile}"
display_timezone = "{timezone}"

[paths]
state_dir = "{state_dir}"
log_dir = "{log_dir}"
run_dir = "{run_dir}"
audit_dir = "{state_dir / "audit"}"
proposal_dir = "{state_dir / "proposals"}"
knowledge_dir = "{state_dir / "knowledge"}"
index_dir = "{state_dir / "indexes"}"
adapter_dir = "{state_dir / "adapters"}"
backup_dir = "{state_dir / "backups"}"

[files]
audit_file = "{state_dir / "audit" / "actions-integrity.jsonl"}"
log_file = "{log_dir / "lea.log"}"

[secrets]
telegram_token_file = "{root / "secrets" / "telegram-token"}"
""".strip()


def write_config(
    tmp_path: Path,
    contents: str,
) -> Path:
    """Write one explicit UTF-8 TOML configuration."""
    path = tmp_path / "lea.toml"
    path.write_text(contents, encoding="utf-8")
    return path


def test_valid_development_configuration(
    tmp_path: Path,
) -> None:
    """A complete development configuration should load."""
    path = write_config(
        tmp_path,
        valid_toml(tmp_path),
    )

    result = load_runtime_config(path)

    assert result.success is True
    assert result.config is not None
    assert result.config.profile is RuntimeProfile.DEVELOPMENT
    assert result.config.display_timezone == "Africa/Gaborone"
    assert result.config.paths.config_file == path
    assert result.issues == ()


def test_valid_system_profile(
    tmp_path: Path,
) -> None:
    """The system profile should use the stable enum value."""
    path = write_config(
        tmp_path,
        valid_toml(tmp_path, profile="system"),
    )

    result = load_runtime_config(path)

    assert result.success is True
    assert result.config is not None
    assert result.config.profile is RuntimeProfile.SYSTEM


def test_valid_test_profile(
    tmp_path: Path,
) -> None:
    """The test profile should load explicitly."""
    path = write_config(
        tmp_path,
        valid_toml(tmp_path, profile="test"),
    )

    result = load_runtime_config(path)

    assert result.success is True
    assert result.config is not None
    assert result.config.profile is RuntimeProfile.TEST


def test_missing_configuration_file(
    tmp_path: Path,
) -> None:
    """A missing explicit file should return a structured issue."""
    path = tmp_path / "missing.toml"

    result = load_runtime_config(path)

    assert result.success is False
    assert result.config is None
    assert result.issues[0].code == "configuration_not_found"
    assert result.issues[0].source_path == path


def test_relative_configuration_path_is_rejected() -> None:
    """The loader must not depend on the current directory."""
    result = load_runtime_config(Path("lea.toml"))

    assert result.success is False
    assert result.issues[0].code == "invalid_path"
    assert result.issues[0].field == "source_path"
    assert result.issues[0].source_path is None


def test_directory_configuration_path_is_rejected(
    tmp_path: Path,
) -> None:
    """The explicit source must be a regular file."""
    result = load_runtime_config(tmp_path)

    assert result.success is False
    assert result.issues[0].code == "configuration_not_readable"


def test_malformed_toml(
    tmp_path: Path,
) -> None:
    """Malformed TOML should fail without raising publicly."""
    path = write_config(
        tmp_path,
        "schema_version = [",
    )

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "malformed_toml"


def test_unsupported_schema_version(
    tmp_path: Path,
) -> None:
    """Unknown schema versions should fail closed."""
    contents = valid_toml(tmp_path).replace(
        "schema_version = 1",
        "schema_version = 2",
    )
    path = write_config(tmp_path, contents)

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "unsupported_schema_version"
    assert result.issues[0].field == "schema_version"


def test_boolean_schema_version_is_rejected(
    tmp_path: Path,
) -> None:
    """TOML booleans must not be accepted as integers."""
    contents = valid_toml(tmp_path).replace(
        "schema_version = 1",
        "schema_version = true",
    )
    path = write_config(tmp_path, contents)

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "unsupported_schema_version"


def test_missing_required_top_level_field(
    tmp_path: Path,
) -> None:
    """Missing required fields should identify the field."""
    contents = valid_toml(tmp_path).replace(
        'profile = "development"\n',
        "",
    )
    path = write_config(tmp_path, contents)

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "missing_field"
    assert result.issues[0].field == "profile"


def test_unknown_top_level_field(
    tmp_path: Path,
) -> None:
    """Unknown top-level fields should be rejected."""
    contents = valid_toml(tmp_path) + "\nunexpected = true\n"
    path = write_config(tmp_path, contents)

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "unknown_field"


def test_unknown_nested_path_field(
    tmp_path: Path,
) -> None:
    """Unknown nested path fields should fail closed."""
    contents = valid_toml(tmp_path).replace(
        "[files]",
        'unexpected_dir = "/tmp/unexpected"\n\n[files]',
    )
    path = write_config(tmp_path, contents)

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "unknown_field"
    assert result.issues[0].field == "paths.unexpected_dir"


def test_missing_nested_path_field(
    tmp_path: Path,
) -> None:
    """Every canonical directory field should be required."""
    contents = valid_toml(tmp_path).replace(
        f'backup_dir = "{tmp_path / "state" / "backups"}"\n',
        "",
    )
    path = write_config(tmp_path, contents)

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "missing_field"
    assert result.issues[0].field == "paths.backup_dir"


def test_invalid_profile(
    tmp_path: Path,
) -> None:
    """Unknown deployment profiles should fail explicitly."""
    path = write_config(
        tmp_path,
        valid_toml(tmp_path, profile="production"),
    )

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "invalid_profile"


def test_invalid_timezone(
    tmp_path: Path,
) -> None:
    """Unknown IANA timezone identifiers should fail."""
    path = write_config(
        tmp_path,
        valid_toml(
            tmp_path,
            timezone="Invalid/Timezone",
        ),
    )

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "invalid_timezone"


def test_utc_timezone_is_valid(
    tmp_path: Path,
) -> None:
    """UTC should be accepted as an IANA timezone."""
    path = write_config(
        tmp_path,
        valid_toml(tmp_path, timezone="UTC"),
    )

    result = load_runtime_config(path)

    assert result.success is True
    assert result.config is not None
    assert result.config.display_timezone == "UTC"


def test_relative_runtime_path_is_rejected(
    tmp_path: Path,
) -> None:
    """Configured runtime paths must be absolute."""
    contents = valid_toml(tmp_path).replace(
        f'state_dir = "{tmp_path / "state"}"',
        'state_dir = "state"',
    )
    path = write_config(tmp_path, contents)

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "invalid_path"
    assert result.issues[0].field == "paths.state_dir"


def test_invalid_audit_file_relationship(
    tmp_path: Path,
) -> None:
    """The configured audit file must be inside audit_dir."""
    contents = valid_toml(tmp_path).replace(
        str(tmp_path / "state" / "audit" / "actions-integrity.jsonl"),
        str(tmp_path / "outside" / "actions.jsonl"),
    )
    path = write_config(tmp_path, contents)

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "invalid_path_relationship"


def test_invalid_log_file_relationship(
    tmp_path: Path,
) -> None:
    """The configured log file must be inside log_dir."""
    contents = valid_toml(tmp_path).replace(
        str(tmp_path / "log" / "lea.log"),
        str(tmp_path / "outside" / "lea.log"),
    )
    path = write_config(tmp_path, contents)

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "invalid_path_relationship"


def test_secrets_table_may_be_omitted(
    tmp_path: Path,
) -> None:
    """Unused secret references should remain optional."""
    contents = valid_toml(tmp_path)
    contents = contents[: contents.index("[secrets]")].rstrip()
    path = write_config(tmp_path, contents)

    result = load_runtime_config(path)

    assert result.success is True
    assert result.config is not None
    assert result.config.secrets.telegram_token_file is None


def test_unknown_secret_field_is_rejected(
    tmp_path: Path,
) -> None:
    """Unknown secret references should fail closed."""
    contents = valid_toml(tmp_path) + '\napi_key_file = "/tmp/key"\n'
    path = write_config(tmp_path, contents)

    result = load_runtime_config(path)

    assert result.success is False
    assert result.issues[0].code == "unknown_field"
    assert result.issues[0].field == "secrets.api_key_file"


def test_loader_creates_no_runtime_directories(
    tmp_path: Path,
) -> None:
    """Pure configuration loading must not bootstrap paths."""
    runtime_root = tmp_path / "runtime"
    config_root = tmp_path / "config"
    config_root.mkdir()

    path = write_config(
        config_root,
        valid_toml(runtime_root),
    )

    result = load_runtime_config(path)

    assert result.success is True
    assert runtime_root.exists() is False


def test_loading_is_independent_of_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absolute source path should work from another directory."""
    config_root = tmp_path / "config"
    other_root = tmp_path / "other"
    config_root.mkdir()
    other_root.mkdir()

    path = write_config(
        config_root,
        valid_toml(tmp_path / "runtime"),
    )

    monkeypatch.chdir(other_root)

    result = load_runtime_config(path)

    assert result.success is True
    assert result.config is not None
    assert result.config.paths.config_file == path
