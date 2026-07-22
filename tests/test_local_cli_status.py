"""Tests for the read-only Local CLI status command."""

from pathlib import Path
from typing import cast

from lea.cli import LocalCliExitCode
from lea.cli.status import StatusDependencies, execute_status
from lea.installers.taskwarrior import TaskwarriorInstallationRecord
from lea.proposals import ProposalVerificationResult
from lea.runtime import (
    ConfigurationIssue,
    ConfigurationResult,
    RuntimeHealthIssue,
    RuntimeHealthResult,
    RuntimeHealthStatus,
    RuntimeProfile,
    isolated_test_runtime_config,
)
from lea.tasks import (
    TaskProviderInspectionResult,
    TaskProviderIssue,
)


def _configuration(tmp_path: Path) -> ConfigurationResult:
    config = isolated_test_runtime_config(tmp_path / "runtime")
    return ConfigurationResult(success=True, config=config, issues=())


def _healthy(config: object) -> RuntimeHealthResult:
    return RuntimeHealthResult(healthy=True, issues=())


def _valid_proposals(config: object) -> ProposalVerificationResult:
    return ProposalVerificationResult(
        valid=True,
        checked_documents=0,
        issues=(),
    )


def _record(tmp_path: Path) -> TaskwarriorInstallationRecord:
    from datetime import UTC, datetime

    root = tmp_path / "runtime"
    return TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode="bundled-binary",
        platform="linux-aarch64",
        executable=root / "tools" / "task",
        sha256="a" * 64,
        taskrc=root / "taskrc",
        home=root / "home",
        data=root / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 22, tzinfo=UTC),
    )


def test_status_success_returns_all_component_data(tmp_path: Path) -> None:
    record = _record(tmp_path)
    result = execute_status(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=RuntimeProfile.TEST,
        dependencies=StatusDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            check_health=_healthy,
            verify_proposals=_valid_proposals,
            read_installation_record=lambda path: (record, ()),
            inspect_provider=lambda config: TaskProviderInspectionResult(
                available=True,
                provider="taskwarrior",
                version="3.4.2",
                issues=(),
            ),
        ),
    )

    assert result.success is True
    assert result.exit_code is LocalCliExitCode.SUCCESS
    assert isinstance(result.data, dict)

    data = cast(dict[str, object], result.data)
    task_provider = data["task_provider"]
    assert isinstance(task_provider, dict)

    provider_data = cast(dict[str, object], task_provider)
    assert provider_data["version"] == "3.4.2"


def test_status_configuration_failure_stops_path_dependent_checks(
    tmp_path: Path,
) -> None:
    called = False

    def unexpected_health(config: object) -> RuntimeHealthResult:
        nonlocal called
        called = True
        raise AssertionError

    result = execute_status(
        config_path=tmp_path / "missing.toml",
        expected_profile=None,
        dependencies=StatusDependencies(
            load_configuration=lambda path: ConfigurationResult(
                success=False,
                config=None,
                issues=(
                    ConfigurationIssue(
                        code="configuration_not_found",
                        message="The runtime configuration file was not found.",
                        source_path=tmp_path / "missing.toml",
                    ),
                ),
            ),
            check_health=unexpected_health,
        ),
    )

    assert result.exit_code is LocalCliExitCode.CONFIGURATION_ERROR
    assert called is False


def test_status_profile_mismatch_is_configuration_error(
    tmp_path: Path,
) -> None:
    result = execute_status(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=RuntimeProfile.SYSTEM,
        dependencies=StatusDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
        ),
    )

    assert result.exit_code is LocalCliExitCode.CONFIGURATION_ERROR
    assert result.issues[0].code == "configuration_profile_mismatch"


def test_status_provider_unavailable_has_precedence(tmp_path: Path) -> None:
    record = _record(tmp_path)
    unhealthy = RuntimeHealthResult(
        healthy=False,
        issues=(
            RuntimeHealthIssue(
                code="runtime_path_missing",
                message="A required runtime directory is missing.",
                status=RuntimeHealthStatus.FAILED,
                path=tmp_path / "runtime" / "state",
            ),
        ),
    )

    result = execute_status(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        dependencies=StatusDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            check_health=lambda config: unhealthy,
            verify_proposals=_valid_proposals,
            read_installation_record=lambda path: (record, ()),
            inspect_provider=lambda config: TaskProviderInspectionResult(
                available=False,
                provider="taskwarrior",
                version=None,
                issues=(
                    TaskProviderIssue(
                        code="taskwarrior_process_failed",
                        message="Taskwarrior could not be executed.",
                        provider="taskwarrior",
                        operation="inspect",
                    ),
                ),
            ),
        ),
    )

    assert result.exit_code is LocalCliExitCode.PROVIDER_UNAVAILABLE
    assert {issue.code for issue in result.issues} == {
        "runtime_path_missing",
        "taskwarrior_process_failed",
    }


def test_status_invalid_proposal_repository_is_application_error(
    tmp_path: Path,
) -> None:
    from lea.proposals import ProposalRepositoryIssue

    record = _record(tmp_path)
    proposals = ProposalVerificationResult(
        valid=False,
        checked_documents=0,
        issues=(
            ProposalRepositoryIssue(
                code="proposal_directory_missing",
                message="The proposal repository directory does not exist.",
                path=tmp_path / "runtime" / "state" / "proposals",
            ),
        ),
    )

    result = execute_status(
        config_path=tmp_path / "runtime" / "config" / "lea.toml",
        expected_profile=None,
        dependencies=StatusDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            check_health=_healthy,
            verify_proposals=lambda config: proposals,
            read_installation_record=lambda path: (record, ()),
            inspect_provider=lambda config: TaskProviderInspectionResult(
                available=True,
                provider="taskwarrior",
                version="3.4.2",
                issues=(),
            ),
        ),
    )

    assert result.exit_code is LocalCliExitCode.APPLICATION_ERROR
    assert result.issues[0].code == "proposal_directory_missing"
