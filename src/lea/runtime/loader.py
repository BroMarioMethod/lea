"""Strict deterministic TOML loading for LEA runtime configuration."""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lea.runtime.contracts import (
    RUNTIME_SCHEMA_VERSION,
    ConfigurationIssue,
    ConfigurationResult,
    RuntimeConfig,
    RuntimePaths,
    RuntimeProfile,
    SecretPaths,
)

TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "profile",
        "display_timezone",
        "paths",
        "files",
        "secrets",
    }
)

REQUIRED_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "profile",
        "display_timezone",
        "paths",
        "files",
    }
)

PATH_FIELDS = frozenset(
    {
        "state_dir",
        "log_dir",
        "run_dir",
        "audit_dir",
        "proposal_dir",
        "knowledge_dir",
        "index_dir",
        "adapter_dir",
        "backup_dir",
    }
)

FILE_FIELDS = frozenset(
    {
        "audit_file",
        "log_file",
    }
)

SECRET_FIELDS = frozenset(
    {
        "telegram_token_file",
    }
)


class _ConfigurationLoadError(Exception):
    """Internal structured failure used while loading configuration."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


def load_runtime_config(
    source_path: str | Path,
) -> ConfigurationResult:
    """Load one explicit UTF-8 TOML runtime configuration."""
    path = Path(source_path)

    if not path.is_absolute():
        return _failure_result(
            code="invalid_path",
            message=("The runtime configuration path must be absolute."),
            field="source_path",
            source_path=None,
        )

    try:
        raw_data = _read_toml(path)
        config = _construct_runtime_config(
            raw_data,
            source_path=path,
        )
    except _ConfigurationLoadError as error:
        return _failure_result(
            code=error.code,
            message=error.message,
            field=error.field,
            source_path=path,
        )

    return ConfigurationResult(
        success=True,
        config=config,
        issues=(),
    )


def _read_toml(
    source_path: Path,
) -> Mapping[str, object]:
    """Read and parse one UTF-8 TOML file without mutation."""
    if not source_path.exists():
        _fail(
            code="configuration_not_found",
            message="The runtime configuration file was not found.",
        )

    if not source_path.is_file():
        _fail(
            code="configuration_not_readable",
            message=("The runtime configuration path is not a regular file."),
        )

    try:
        contents = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _fail(
            code="configuration_not_readable",
            message=("The runtime configuration file could not be read as UTF-8."),
        )

    try:
        parsed = tomllib.loads(contents)
    except tomllib.TOMLDecodeError:
        _fail(
            code="malformed_toml",
            message=("The runtime configuration does not contain valid TOML."),
        )

    return cast(Mapping[str, object], parsed)


def _construct_runtime_config(
    data: Mapping[str, object],
    *,
    source_path: Path,
) -> RuntimeConfig:
    """Validate parsed TOML and construct immutable contracts."""
    _validate_fields(
        data,
        known=TOP_LEVEL_FIELDS,
        required=REQUIRED_TOP_LEVEL_FIELDS,
        field_prefix=None,
    )

    schema_version = _require_integer(
        data["schema_version"],
        field="schema_version",
    )

    if schema_version != RUNTIME_SCHEMA_VERSION:
        _fail(
            code="unsupported_schema_version",
            message=("The runtime configuration schema version is unsupported."),
            field="schema_version",
        )

    profile = _parse_profile(data["profile"])
    display_timezone = _parse_timezone(data["display_timezone"])

    paths_data = _require_mapping(
        data["paths"],
        field="paths",
    )
    files_data = _require_mapping(
        data["files"],
        field="files",
    )

    _validate_fields(
        paths_data,
        known=PATH_FIELDS,
        required=PATH_FIELDS,
        field_prefix="paths",
    )
    _validate_fields(
        files_data,
        known=FILE_FIELDS,
        required=FILE_FIELDS,
        field_prefix="files",
    )

    secrets_value = data.get("secrets", {})
    secrets_data = _require_mapping(
        secrets_value,
        field="secrets",
    )

    _validate_fields(
        secrets_data,
        known=SECRET_FIELDS,
        required=frozenset(),
        field_prefix="secrets",
    )

    try:
        runtime_paths = RuntimePaths(
            config_file=source_path,
            state_dir=_parse_path(
                paths_data["state_dir"],
                field="paths.state_dir",
            ),
            log_dir=_parse_path(
                paths_data["log_dir"],
                field="paths.log_dir",
            ),
            run_dir=_parse_path(
                paths_data["run_dir"],
                field="paths.run_dir",
            ),
            audit_dir=_parse_path(
                paths_data["audit_dir"],
                field="paths.audit_dir",
            ),
            proposal_dir=_parse_path(
                paths_data["proposal_dir"],
                field="paths.proposal_dir",
            ),
            knowledge_dir=_parse_path(
                paths_data["knowledge_dir"],
                field="paths.knowledge_dir",
            ),
            index_dir=_parse_path(
                paths_data["index_dir"],
                field="paths.index_dir",
            ),
            adapter_dir=_parse_path(
                paths_data["adapter_dir"],
                field="paths.adapter_dir",
            ),
            backup_dir=_parse_path(
                paths_data["backup_dir"],
                field="paths.backup_dir",
            ),
            audit_file=_parse_path(
                files_data["audit_file"],
                field="files.audit_file",
            ),
            log_file=_parse_path(
                files_data["log_file"],
                field="files.log_file",
            ),
        )
    except (TypeError, ValueError) as error:
        _fail(
            code="invalid_path_relationship",
            message=str(error),
            field="paths",
        )

    telegram_token_file: Path | None = None

    if "telegram_token_file" in secrets_data:
        telegram_token_file = _parse_optional_path(
            secrets_data["telegram_token_file"],
            field="secrets.telegram_token_file",
        )

    try:
        secret_paths = SecretPaths(
            telegram_token_file=telegram_token_file,
        )
    except (TypeError, ValueError) as error:
        _fail(
            code="invalid_path",
            message=str(error),
            field="secrets.telegram_token_file",
        )

    return RuntimeConfig(
        schema_version=schema_version,
        profile=profile,
        display_timezone=display_timezone,
        paths=runtime_paths,
        secrets=secret_paths,
    )


def _validate_fields(
    data: Mapping[str, object],
    *,
    known: frozenset[str],
    required: frozenset[str],
    field_prefix: str | None,
) -> None:
    """Reject missing and unknown mapping fields."""
    supplied = set(data)

    missing = sorted(required - supplied)

    if missing:
        field = _qualified_field(
            field_prefix,
            missing[0],
        )
        _fail(
            code="missing_field",
            message=f"Required field '{field}' is missing.",
            field=field,
        )

    unknown = sorted(supplied - known)

    if unknown:
        field = _qualified_field(
            field_prefix,
            unknown[0],
        )
        _fail(
            code="unknown_field",
            message=f"Unknown field '{field}' is not permitted.",
            field=field,
        )


def _parse_profile(
    value: object,
) -> RuntimeProfile:
    """Parse one supported runtime profile."""
    if not isinstance(value, str):
        _fail(
            code="invalid_profile",
            message="profile must be a string.",
            field="profile",
        )

    try:
        return RuntimeProfile(value)
    except ValueError:
        _fail(
            code="invalid_profile",
            message=("profile must be 'system', 'development' or 'test'."),
            field="profile",
        )


def _parse_timezone(
    value: object,
) -> str:
    """Validate one canonical IANA timezone identifier."""
    if not isinstance(value, str) or not value.strip():
        _fail(
            code="invalid_timezone",
            message=("display_timezone must be a non-empty IANA timezone identifier."),
            field="display_timezone",
        )

    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        _fail(
            code="invalid_timezone",
            message=("display_timezone is not a recognised IANA timezone."),
            field="display_timezone",
        )

    return value


def _parse_path(
    value: object,
    *,
    field: str,
) -> Path:
    """Parse one required absolute path."""
    if not isinstance(value, str) or not value:
        _fail(
            code="invalid_path",
            message=f"{field} must be a non-empty path string.",
            field=field,
        )

    if "\x00" in value:
        _fail(
            code="invalid_path",
            message=f"{field} must not contain a null byte.",
            field=field,
        )

    path = Path(value)

    if not path.is_absolute():
        _fail(
            code="invalid_path",
            message=f"{field} must be an absolute path.",
            field=field,
        )

    return path


def _parse_optional_path(
    value: object,
    *,
    field: str,
) -> Path | None:
    """Parse one optional absolute path."""
    if value is None:
        return None

    return _parse_path(
        value,
        field=field,
    )


def _require_mapping(
    value: object,
    *,
    field: str,
) -> Mapping[str, object]:
    """Return a parsed TOML table or fail structurally."""
    if not isinstance(value, Mapping):
        _fail(
            code="missing_field",
            message=f"{field} must be a TOML table.",
            field=field,
        )

    for key in value:
        if not isinstance(key, str):
            _fail(
                code="unknown_field",
                message=f"{field} contains a non-string field name.",
                field=field,
            )

    return cast(Mapping[str, object], value)


def _require_integer(
    value: object,
    *,
    field: str,
) -> int:
    """Return an integer while rejecting booleans."""
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(
            code="unsupported_schema_version",
            message=f"{field} must be an integer.",
            field=field,
        )

    return value


def _qualified_field(
    prefix: str | None,
    field: str,
) -> str:
    """Return one dotted field path."""
    if prefix is None:
        return field

    return f"{prefix}.{field}"


def _failure_result(
    *,
    code: str,
    message: str,
    field: str | None,
    source_path: Path | None,
) -> ConfigurationResult:
    """Construct one deterministic failed configuration result."""
    return ConfigurationResult(
        success=False,
        config=None,
        issues=(
            ConfigurationIssue(
                code=code,
                message=message,
                field=field,
                source_path=source_path,
            ),
        ),
    )


def _fail(
    *,
    code: str,
    message: str,
    field: str | None = None,
) -> NoReturn:
    """Raise one internal structured loading failure."""
    raise _ConfigurationLoadError(
        code=code,
        message=message,
        field=field,
    )
