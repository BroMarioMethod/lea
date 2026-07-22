"""Deterministic TOML serialisation for LEA runtime configuration."""

import json
from pathlib import Path

from lea.runtime.contracts import RuntimeConfig


def render_runtime_config(
    config: RuntimeConfig,
) -> str:
    """Render one runtime configuration as deterministic TOML."""
    paths = config.paths
    component_records = config.component_records
    secrets = config.secrets

    lines = [
        f"schema_version = {config.schema_version}",
        f"profile = {_toml_string(config.profile.value)}",
        (f"display_timezone = {_toml_string(config.display_timezone)}"),
        "",
        "[paths]",
        f"state_dir = {_toml_path(paths.state_dir)}",
        f"log_dir = {_toml_path(paths.log_dir)}",
        f"run_dir = {_toml_path(paths.run_dir)}",
        f"audit_dir = {_toml_path(paths.audit_dir)}",
        f"proposal_dir = {_toml_path(paths.proposal_dir)}",
        f"knowledge_dir = {_toml_path(paths.knowledge_dir)}",
        f"index_dir = {_toml_path(paths.index_dir)}",
        f"adapter_dir = {_toml_path(paths.adapter_dir)}",
        f"backup_dir = {_toml_path(paths.backup_dir)}",
        "",
        "[files]",
        f"audit_file = {_toml_path(paths.audit_file)}",
        f"log_file = {_toml_path(paths.log_file)}",
        "",
        "[component_records]",
        f"taskwarrior = {_toml_path(component_records.taskwarrior)}",
    ]

    if secrets.telegram_token_file is not None:
        lines.extend(
            [
                "",
                "[secrets]",
                (f"telegram_token_file = {_toml_path(secrets.telegram_token_file)}"),
            ]
        )

    return "\n".join(lines) + "\n"


def write_runtime_config(
    config: RuntimeConfig,
    *,
    destination: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Write deterministic TOML without overwriting by default."""
    target = config.paths.config_file if destination is None else destination

    _validate_destination(target)

    mode = "w" if overwrite else "x"

    with target.open(
        mode=mode,
        encoding="utf-8",
        newline="\n",
    ) as stream:
        stream.write(render_runtime_config(config))

    return target


def _toml_path(
    path: Path,
) -> str:
    """Render one path as a TOML basic string."""
    return _toml_string(str(path))


def _toml_string(
    value: str,
) -> str:
    """Render one string using TOML-compatible JSON escaping."""
    return json.dumps(
        value,
        ensure_ascii=False,
    )


def _validate_destination(
    destination: Path,
) -> None:
    """Validate an explicit configuration destination."""
    if not isinstance(destination, Path):
        raise TypeError("destination must be a pathlib.Path value.")

    if not destination.is_absolute():
        raise ValueError("destination must be an absolute path.")

    if "\x00" in str(destination):
        raise ValueError("destination must not contain a null byte.")

    if not destination.parent.is_dir():
        raise FileNotFoundError(
            "The configuration destination parent directory does not exist."
        )
