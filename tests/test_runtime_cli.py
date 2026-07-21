"""Tests for LEA runtime command-line handling."""

from io import StringIO
from pathlib import Path

from lea.runtime import (
    bootstrap_runtime,
    initialise_runtime_config,
    isolated_test_runtime_config,
)
from lea.runtime_cli import (
    EXIT_CONFIGURATION_ERROR,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    create_runtime_parser,
    execute_runtime_cli,
)


def prepare_configuration(
    tmp_path: Path,
    *,
    complete_runtime: bool,
) -> Path:
    """Create one runtime configuration for CLI tests."""
    config = isolated_test_runtime_config(
        tmp_path / "runtime",
        display_timezone="Africa/Gaborone",
    )
    config.paths.config_file.parent.mkdir(parents=True)

    initialisation = initialise_runtime_config(config)
    assert initialisation.success is True

    if complete_runtime:
        bootstrap = bootstrap_runtime(config.paths)
        assert bootstrap.success is True

    return config.paths.config_file


def test_parser_uses_runtime_program_name() -> None:
    """Runtime help should identify the nested command."""
    parser = create_runtime_parser()

    assert parser.prog == "lea runtime"


def test_inspect_configuration_only_succeeds(
    tmp_path: Path,
) -> None:
    """Inspect should load valid configuration without health."""
    config_path = prepare_configuration(
        tmp_path,
        complete_runtime=False,
    )
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_runtime_cli(
        [
            "inspect",
            "--config",
            str(config_path),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_SUCCESS
    assert "Runtime inspection: SUCCESS\n" in stdout.getvalue()
    assert "Profile: test\n" in stdout.getvalue()
    assert "Runtime health: NOT REQUESTED\n" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_inspect_with_health_succeeds_for_complete_runtime(
    tmp_path: Path,
) -> None:
    """Inspect with health should pass for complete runtime state."""
    config_path = prepare_configuration(
        tmp_path,
        complete_runtime=True,
    )
    stdout = StringIO()

    exit_code = execute_runtime_cli(
        [
            "inspect",
            "--config",
            str(config_path),
            "--health",
        ],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS
    assert "Runtime inspection: SUCCESS\n" in stdout.getvalue()
    assert "Runtime health: HEALTHY\n" in stdout.getvalue()


def test_inspect_with_health_fails_for_incomplete_runtime(
    tmp_path: Path,
) -> None:
    """Unhealthy runtime state should return runtime-error status."""
    config_path = prepare_configuration(
        tmp_path,
        complete_runtime=False,
    )
    stdout = StringIO()

    exit_code = execute_runtime_cli(
        [
            "inspect",
            "--config",
            str(config_path),
            "--health",
        ],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == EXIT_RUNTIME_ERROR
    assert "Runtime inspection: FAILED\n" in stdout.getvalue()
    assert "Runtime health: UNHEALTHY\n" in stdout.getvalue()


def test_inspect_missing_configuration_returns_config_error(
    tmp_path: Path,
) -> None:
    """Loader failure should use configuration-error status."""
    stdout = StringIO()

    exit_code = execute_runtime_cli(
        [
            "inspect",
            "--config",
            str(tmp_path / "missing.toml"),
        ],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == EXIT_CONFIGURATION_ERROR
    assert "Configuration load: FAILED\n" in stdout.getvalue()
    assert "configuration_not_found" in stdout.getvalue()


def test_health_succeeds_for_complete_runtime(
    tmp_path: Path,
) -> None:
    """Health command should return success for valid runtime state."""
    config_path = prepare_configuration(
        tmp_path,
        complete_runtime=True,
    )
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_runtime_cli(
        [
            "health",
            "--config",
            str(config_path),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_SUCCESS
    assert "Runtime health: HEALTHY\n" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_health_returns_runtime_error_when_unhealthy(
    tmp_path: Path,
) -> None:
    """Missing runtime directories should produce status one."""
    config_path = prepare_configuration(
        tmp_path,
        complete_runtime=False,
    )
    stdout = StringIO()

    exit_code = execute_runtime_cli(
        [
            "health",
            "--config",
            str(config_path),
        ],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == EXIT_RUNTIME_ERROR
    assert "Runtime health: UNHEALTHY\n" in stdout.getvalue()
    assert "runtime_path_missing" in stdout.getvalue()


def test_health_loader_failure_is_written_to_stderr(
    tmp_path: Path,
) -> None:
    """Configuration failures should be separated from health output."""
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_runtime_cli(
        [
            "health",
            "--config",
            str(tmp_path / "missing.toml"),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == EXIT_CONFIGURATION_ERROR
    assert stdout.getvalue() == ""
    assert "Configuration load: FAILED\n" in stderr.getvalue()
    assert "configuration_not_found" in stderr.getvalue()


def test_relative_configuration_path_returns_config_error() -> None:
    """Runtime commands must reject relative configuration paths."""
    stdout = StringIO()

    exit_code = execute_runtime_cli(
        [
            "inspect",
            "--config",
            "lea.toml",
        ],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == EXIT_CONFIGURATION_ERROR
    assert "invalid_path" in stdout.getvalue()


def test_missing_required_config_argument_returns_usage_error() -> None:
    """Argparse should return status two for missing arguments."""
    exit_code = execute_runtime_cli(
        ["inspect"],
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == 2


def test_missing_runtime_subcommand_returns_usage_error() -> None:
    """A runtime operation must always be selected."""
    exit_code = execute_runtime_cli(
        [],
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == 2


def test_cli_execution_is_read_only_for_inspection(
    tmp_path: Path,
) -> None:
    """Inspect should not create missing runtime directories."""
    config_path = prepare_configuration(
        tmp_path,
        complete_runtime=False,
    )
    runtime_root = tmp_path / "runtime"

    execute_runtime_cli(
        [
            "inspect",
            "--config",
            str(config_path),
            "--health",
        ],
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert (runtime_root / "state").exists() is False
    assert (runtime_root / "log").exists() is False
    assert (runtime_root / "run").exists() is False


def test_initialise_dry_run_reports_without_writing(
    tmp_path: Path,
) -> None:
    """Initialise dry-run should report configuration creation."""
    root = tmp_path / "runtime"
    config_parent = root / "config"
    config_parent.mkdir(parents=True)
    stdout = StringIO()

    exit_code = execute_runtime_cli(
        [
            "initialise",
            "--profile",
            "test",
            "--root",
            str(root),
            "--display-timezone",
            "Africa/Gaborone",
            "--dry-run",
        ],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS
    assert "Configuration initialisation: SUCCESS\n" in (stdout.getvalue())
    assert "Mode: DRY RUN\n" in stdout.getvalue()
    assert "Status: would_create\n" in stdout.getvalue()
    assert (config_parent / "lea.toml").exists() is False


def test_initialise_creates_test_configuration(
    tmp_path: Path,
) -> None:
    """Initialise should create a canonical test configuration."""
    root = tmp_path / "runtime"
    config_parent = root / "config"
    config_parent.mkdir(parents=True)

    exit_code = execute_runtime_cli(
        [
            "initialise",
            "--profile",
            "test",
            "--root",
            str(root),
            "--display-timezone",
            "Africa/Gaborone",
        ],
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS
    assert (config_parent / "lea.toml").is_file()
    assert (root / "state").exists() is False


def test_initialise_requires_root_for_test_profile() -> None:
    """Non-system canonical profiles require an explicit root."""
    stderr = StringIO()

    exit_code = execute_runtime_cli(
        [
            "initialise",
            "--profile",
            "test",
        ],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == EXIT_CONFIGURATION_ERROR
    assert "--root is required" in stderr.getvalue()


def test_system_profile_rejects_root(
    tmp_path: Path,
) -> None:
    """The fixed system layout must not accept a custom root."""
    stderr = StringIO()

    exit_code = execute_runtime_cli(
        [
            "initialise",
            "--profile",
            "system",
            "--root",
            str(tmp_path),
            "--dry-run",
        ],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == EXIT_CONFIGURATION_ERROR
    assert "--root must not be supplied" in stderr.getvalue()


def test_initialise_rejects_invalid_timezone(
    tmp_path: Path,
) -> None:
    """Invalid template timezone input should use status two."""
    stderr = StringIO()

    exit_code = execute_runtime_cli(
        [
            "initialise",
            "--profile",
            "test",
            "--root",
            str(tmp_path / "runtime"),
            "--display-timezone",
            "Invalid/Timezone",
            "--dry-run",
        ],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == EXIT_CONFIGURATION_ERROR
    assert "recognised IANA timezone" in stderr.getvalue()


def test_bootstrap_dry_run_reports_missing_paths(
    tmp_path: Path,
) -> None:
    """Bootstrap dry-run should load configuration without mutation."""
    config_path = prepare_configuration(
        tmp_path,
        complete_runtime=False,
    )
    stdout = StringIO()

    exit_code = execute_runtime_cli(
        [
            "bootstrap",
            "--config",
            str(config_path),
            "--dry-run",
        ],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS
    assert "Runtime bootstrap: SUCCESS\n" in stdout.getvalue()
    assert "Mode: DRY RUN\n" in stdout.getvalue()
    assert "[would_create]" in stdout.getvalue()
    assert (tmp_path / "runtime" / "state").exists() is False


def test_bootstrap_creates_configured_directories(
    tmp_path: Path,
) -> None:
    """Live bootstrap should create configured runtime paths."""
    config_path = prepare_configuration(
        tmp_path,
        complete_runtime=False,
    )

    exit_code = execute_runtime_cli(
        [
            "bootstrap",
            "--config",
            str(config_path),
        ],
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS
    assert (tmp_path / "runtime" / "state").is_dir()
    assert (tmp_path / "runtime" / "log").is_dir()
    assert (tmp_path / "runtime" / "run").is_dir()


def test_bootstrap_missing_configuration_uses_status_two(
    tmp_path: Path,
) -> None:
    """Bootstrap must preserve configuration-loading failures."""
    stderr = StringIO()

    exit_code = execute_runtime_cli(
        [
            "bootstrap",
            "--config",
            str(tmp_path / "missing.toml"),
        ],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == EXIT_CONFIGURATION_ERROR
    assert "Configuration load: FAILED\n" in stderr.getvalue()


def test_setup_dry_run_reports_both_operations(
    tmp_path: Path,
) -> None:
    """Setup dry-run should report configuration and directories."""
    root = tmp_path / "runtime"
    (root / "config").mkdir(parents=True)
    stdout = StringIO()

    exit_code = execute_runtime_cli(
        [
            "setup",
            "--profile",
            "test",
            "--root",
            str(root),
            "--dry-run",
        ],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS
    assert "Runtime setup: SUCCESS\n" in stdout.getvalue()
    assert "Configuration initialisation: SUCCESS\n" in (stdout.getvalue())
    assert "Runtime bootstrap: SUCCESS\n" in stdout.getvalue()
    assert (root / "config" / "lea.toml").exists() is False
    assert (root / "state").exists() is False


def test_setup_creates_configuration_and_directories(
    tmp_path: Path,
) -> None:
    """Live setup should perform both coordinated operations."""
    root = tmp_path / "runtime"
    (root / "config").mkdir(parents=True)

    exit_code = execute_runtime_cli(
        [
            "setup",
            "--profile",
            "test",
            "--root",
            str(root),
        ],
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS
    assert (root / "config" / "lea.toml").is_file()
    assert (root / "state").is_dir()
    assert (root / "log").is_dir()
    assert (root / "run").is_dir()


def test_verify_dry_run_returns_successful_plan(
    tmp_path: Path,
) -> None:
    """Verification dry-run should succeed without claiming health."""
    root = tmp_path / "runtime"
    (root / "config").mkdir(parents=True)
    stdout = StringIO()

    exit_code = execute_runtime_cli(
        [
            "verify",
            "--profile",
            "test",
            "--root",
            str(root),
            "--dry-run",
        ],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS
    assert "Runtime setup verification: NOT VERIFIED\n" in stdout.getvalue()
    assert "Mode: DRY RUN\n" in stdout.getvalue()
    assert "Runtime health: NOT RUN\n" in stdout.getvalue()


def test_verify_creates_and_verifies_runtime(
    tmp_path: Path,
) -> None:
    """Live verification should create and health-check runtime."""
    root = tmp_path / "runtime"
    (root / "config").mkdir(parents=True)
    stdout = StringIO()

    exit_code = execute_runtime_cli(
        [
            "verify",
            "--profile",
            "test",
            "--root",
            str(root),
            "--display-timezone",
            "Africa/Gaborone",
        ],
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == EXIT_SUCCESS
    assert "Runtime setup verification: VERIFIED\n" in stdout.getvalue()
    assert "Runtime health: HEALTHY\n" in stdout.getvalue()


def test_setup_refuses_existing_configuration(
    tmp_path: Path,
) -> None:
    """Setup should not overwrite an existing configuration."""
    root = tmp_path / "runtime"
    config_path = root / "config" / "lea.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "existing configuration\n",
        encoding="utf-8",
    )

    exit_code = execute_runtime_cli(
        [
            "setup",
            "--profile",
            "test",
            "--root",
            str(root),
        ],
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == EXIT_RUNTIME_ERROR
    assert config_path.read_text(encoding="utf-8") == "existing configuration\n"
    assert (root / "state").exists() is False
