"""Tests for deterministic LEA runtime report formatting."""

from pathlib import Path

from lea.runtime import (
    ConfigurationIssue,
    ConfigurationResult,
    RuntimeBootstrapResult,
    RuntimeConfig,
    RuntimeHealthIssue,
    RuntimeHealthResult,
    RuntimeHealthStatus,
    RuntimeInitialisationResult,
    RuntimeInitialisationStatus,
    RuntimeInspectionResult,
    RuntimePathResult,
    RuntimePathStatus,
    RuntimeSetupResult,
    RuntimeSetupVerificationResult,
    format_bootstrap_result,
    format_configuration_result,
    format_health_result,
    format_initialisation_result,
    format_inspection_result,
    format_runtime_config,
    format_setup_result,
    format_setup_verification_result,
    isolated_test_runtime_config,
)


def create_config() -> RuntimeConfig:
    """Create one deterministic runtime configuration."""
    return isolated_test_runtime_config(
        Path("/tmp/lea-test"),
        display_timezone="Africa/Gaborone",
        telegram_token_file=Path("/tmp/lea-test/secrets/telegram-token"),
    )


def successful_configuration_result() -> ConfigurationResult:
    """Return one successful configuration result."""
    return ConfigurationResult(
        success=True,
        config=create_config(),
        issues=(),
    )


def failed_configuration_result() -> ConfigurationResult:
    """Return one failed configuration result."""
    return ConfigurationResult(
        success=False,
        config=None,
        issues=(
            ConfigurationIssue(
                code="configuration_not_found",
                message="The runtime configuration file is missing.",
                field="source_path",
                source_path=Path("/etc/lea/lea.toml"),
            ),
        ),
    )


def successful_initialisation_result(
    *,
    dry_run: bool,
) -> RuntimeInitialisationResult:
    """Return one successful initialisation result."""
    return RuntimeInitialisationResult(
        success=True,
        dry_run=dry_run,
        status=(
            RuntimeInitialisationStatus.WOULD_CREATE
            if dry_run
            else RuntimeInitialisationStatus.CREATED
        ),
        destination=Path("/etc/lea/lea.toml"),
        message=(
            "The runtime configuration would be created."
            if dry_run
            else "The runtime configuration was created."
        ),
    )


def successful_bootstrap_result(
    *,
    dry_run: bool,
) -> RuntimeBootstrapResult:
    """Return one successful bootstrap result."""
    return RuntimeBootstrapResult(
        success=True,
        dry_run=dry_run,
        paths=(
            RuntimePathResult(
                path=Path("/var/lib/lea"),
                status=(
                    RuntimePathStatus.WOULD_CREATE
                    if dry_run
                    else RuntimePathStatus.CREATED
                ),
                message=(
                    "Runtime directory would be created."
                    if dry_run
                    else "Runtime directory was created."
                ),
            ),
        ),
    )


def healthy_result() -> RuntimeHealthResult:
    """Return one healthy runtime result."""
    return RuntimeHealthResult(
        healthy=True,
        issues=(
            RuntimeHealthIssue(
                code="runtime_path_available",
                message="The runtime directory is available.",
                status=RuntimeHealthStatus.PASSED,
                path=Path("/var/lib/lea"),
                field="paths.state_dir",
            ),
        ),
    )


def test_runtime_config_report_contains_profile_and_paths() -> None:
    """Configuration reports should expose canonical information."""
    report = format_runtime_config(create_config())

    assert "Runtime configuration\n" in report
    assert "Schema version: 1\n" in report
    assert "Profile: test\n" in report
    assert "Display timezone: Africa/Gaborone\n" in report
    assert "State: /tmp/lea-test/state\n" in report
    assert ("Telegram token file: /tmp/lea-test/secrets/telegram-token\n") in report


def test_runtime_config_report_handles_missing_secret() -> None:
    """Unused secret references should be explicit."""
    config = isolated_test_runtime_config(
        Path("/tmp/lea-test"),
    )

    report = format_runtime_config(config)

    assert "Telegram token file: not configured\n" in report


def test_configuration_success_report_contains_config() -> None:
    """Successful loading should include the loaded configuration."""
    report = format_configuration_result(successful_configuration_result())

    assert report.startswith("Configuration load: SUCCESS\n\n")
    assert "Runtime configuration\n" in report
    assert report.endswith("\n")


def test_configuration_failure_report_contains_issue_details() -> None:
    """Failed loading should preserve structured issue context."""
    report = format_configuration_result(failed_configuration_result())

    assert report.startswith("Configuration load: FAILED\n")
    assert "configuration_not_found" in report
    assert "field=source_path" in report
    assert "path=/etc/lea/lea.toml" in report


def test_bootstrap_report_contains_status_and_path() -> None:
    """Bootstrap reports should expose each path result."""
    report = format_bootstrap_result(successful_bootstrap_result(dry_run=False))

    assert report.startswith("Runtime bootstrap: SUCCESS\n")
    assert "Mode: LIVE\n" in report
    assert "[created] /var/lib/lea" in report


def test_dry_run_bootstrap_report_is_explicit() -> None:
    """Dry-run bootstrap must not look like live mutation."""
    report = format_bootstrap_result(successful_bootstrap_result(dry_run=True))

    assert "Mode: DRY RUN\n" in report
    assert "[would_create] /var/lib/lea" in report


def test_empty_bootstrap_report_is_explicit() -> None:
    """Empty bootstrap results should not produce an empty section."""
    result = RuntimeBootstrapResult(
        success=True,
        dry_run=True,
        paths=(),
    )

    report = format_bootstrap_result(result)

    assert "Paths: none\n" in report


def test_initialisation_report_contains_destination() -> None:
    """Initialisation reports should identify their destination."""
    result = successful_initialisation_result(dry_run=False)

    report = format_initialisation_result(result)

    assert "Configuration initialisation: SUCCESS\n" in report
    assert "Status: created\n" in report
    assert "Destination: /etc/lea/lea.toml\n" in report


def test_health_report_contains_check_status() -> None:
    """Health reports should expose status, code and context."""
    report = format_health_result(healthy_result())

    assert report.startswith("Runtime health: HEALTHY\n")
    assert "[passed] runtime_path_available" in report
    assert "field=paths.state_dir" in report
    assert "path=/var/lib/lea" in report


def test_empty_healthy_report_is_explicit() -> None:
    """An empty healthy result should identify no checks."""
    result = RuntimeHealthResult(
        healthy=True,
        issues=(),
    )

    report = format_health_result(result)

    assert report == "Runtime health: HEALTHY\nChecks: none\n"


def test_setup_report_contains_both_operations() -> None:
    """Setup reports should preserve both underlying results."""
    result = RuntimeSetupResult(
        success=True,
        dry_run=False,
        initialisation=successful_initialisation_result(dry_run=False),
        bootstrap=successful_bootstrap_result(dry_run=False),
    )

    report = format_setup_result(result)

    assert report.startswith("Runtime setup: SUCCESS\n")
    assert "Configuration initialisation: SUCCESS\n" in report
    assert "Runtime bootstrap: SUCCESS\n" in report


def test_setup_report_marks_skipped_bootstrap() -> None:
    """Failed initialisation should report bootstrap as not run."""
    initialisation = RuntimeInitialisationResult(
        success=False,
        dry_run=False,
        status=RuntimeInitialisationStatus.FAILED,
        destination=Path("/etc/lea/lea.toml"),
        message="The configuration could not be created.",
    )
    result = RuntimeSetupResult(
        success=False,
        dry_run=False,
        initialisation=initialisation,
        bootstrap=None,
    )

    report = format_setup_result(result)

    assert "Runtime setup: FAILED\n" in report
    assert "Runtime bootstrap: NOT RUN\n" in report


def test_verified_setup_report_contains_health() -> None:
    """Verified setup reports should include health details."""
    setup = RuntimeSetupResult(
        success=True,
        dry_run=False,
        initialisation=successful_initialisation_result(dry_run=False),
        bootstrap=successful_bootstrap_result(dry_run=False),
    )
    result = RuntimeSetupVerificationResult(
        verified=True,
        dry_run=False,
        setup=setup,
        health=healthy_result(),
    )

    report = format_setup_verification_result(result)

    assert report.startswith("Runtime setup verification: VERIFIED\n")
    assert "Runtime setup: SUCCESS\n" in report
    assert "Runtime health: HEALTHY\n" in report


def test_dry_run_verification_report_marks_health_not_run() -> None:
    """Dry-run verification should clearly omit live health checks."""
    setup = RuntimeSetupResult(
        success=True,
        dry_run=True,
        initialisation=successful_initialisation_result(dry_run=True),
        bootstrap=successful_bootstrap_result(dry_run=True),
    )
    result = RuntimeSetupVerificationResult(
        verified=False,
        dry_run=True,
        setup=setup,
        health=None,
    )

    report = format_setup_verification_result(result)

    assert "Runtime setup verification: NOT VERIFIED\n" in report
    assert "Mode: DRY RUN\n" in report
    assert "Runtime health: NOT RUN\n" in report


def test_configuration_only_inspection_report() -> None:
    """Inspection should identify health as unrequested."""
    result = RuntimeInspectionResult(
        success=True,
        configuration=successful_configuration_result(),
        health=None,
    )

    report = format_inspection_result(result)

    assert report.startswith("Runtime inspection: SUCCESS\n")
    assert "Configuration load: SUCCESS\n" in report
    assert "Runtime health: NOT REQUESTED\n" in report


def test_unhealthy_inspection_report_contains_health_failure() -> None:
    """Inspection failure should preserve unhealthy details."""
    health = RuntimeHealthResult(
        healthy=False,
        issues=(
            RuntimeHealthIssue(
                code="runtime_path_missing",
                message="The runtime directory is missing.",
                status=RuntimeHealthStatus.FAILED,
                path=Path("/var/lib/lea"),
            ),
        ),
    )
    result = RuntimeInspectionResult(
        success=False,
        configuration=successful_configuration_result(),
        health=health,
    )

    report = format_inspection_result(result)

    assert report.startswith("Runtime inspection: FAILED\n")
    assert "Runtime health: UNHEALTHY\n" in report
    assert "[failed] runtime_path_missing" in report


def test_all_reports_end_with_exactly_one_newline() -> None:
    """Reports should have stable trailing-newline behaviour."""
    reports = (
        format_runtime_config(create_config()),
        format_configuration_result(successful_configuration_result()),
        format_bootstrap_result(successful_bootstrap_result(dry_run=True)),
        format_initialisation_result(successful_initialisation_result(dry_run=True)),
        format_health_result(healthy_result()),
    )

    for report in reports:
        assert report.endswith("\n")
        assert not report.endswith("\n\n")


def test_report_formatting_is_deterministic() -> None:
    """Identical inputs should always produce identical reports."""
    result = successful_bootstrap_result(dry_run=True)

    assert format_bootstrap_result(result) == format_bootstrap_result(result)
