"""Tests for the shared Local CLI task-provider loader."""

from datetime import UTC, datetime
from pathlib import Path

from lea.cli import CliResult, LocalCliExitCode
from lea.cli.task_provider import TaskProviderDependencies, load_task_provider
from lea.installers.taskwarrior import TaskwarriorInstallationRecord
from lea.runtime import (
    ConfigurationIssue,
    ConfigurationResult,
    RuntimeProfile,
    isolated_test_runtime_config,
)
from lea.tasks import (
    TaskCreateRequest,
    TaskCreateResult,
    TaskListQuery,
    TaskListResult,
    TaskModifyRequest,
    TaskMutationResult,
    TaskProviderInspectionResult,
)


class RecordingProvider:
    """Minimal provider used to test loading."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def inspect(self) -> TaskProviderInspectionResult:
        return TaskProviderInspectionResult(
            available=self.available,
            provider="test",
            version="1.0" if self.available else None,
            issues=()
            if self.available
            else (
                type(
                    "Issue",
                    (),
                    {
                        "code": "provider_unavailable",
                        "message": "Provider unavailable.",
                        "field": None,
                    },
                )(),
            ),
        )

    def create_task(self, request: TaskCreateRequest) -> TaskCreateResult:
        raise AssertionError

    def list_tasks(self, query: TaskListQuery) -> TaskListResult:
        raise AssertionError

    def modify_task(self, request: TaskModifyRequest) -> TaskMutationResult:
        raise AssertionError

    def complete_task(self, task_uuid: str) -> TaskMutationResult:
        raise AssertionError

    def delete_task(self, task_uuid: str) -> TaskMutationResult:
        raise AssertionError


def _configuration(tmp_path: Path) -> ConfigurationResult:
    return ConfigurationResult(
        success=True,
        config=isolated_test_runtime_config(tmp_path / "runtime"),
        issues=(),
    )


def _record(tmp_path: Path) -> TaskwarriorInstallationRecord:
    root = tmp_path / "taskwarrior"
    return TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode="local",
        platform="linux-aarch64",
        executable=root / "bin" / "task",
        taskrc=root / "taskrc",
        home=root / "home",
        data=root / "data",
        sha256="0" * 64,
        smoke_test="passed",
        installed_at=datetime(2026, 7, 22, tzinfo=UTC),
    )


def test_load_task_provider_returns_inspected_provider(tmp_path: Path) -> None:
    provider = RecordingProvider()

    result = load_task_provider(
        config_path=tmp_path / "lea.toml",
        expected_profile=RuntimeProfile.TEST,
        dependencies=TaskProviderDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            read_installation_record=lambda path: (_record(tmp_path), ()),
            create_provider=lambda config: provider,
        ),
    )

    assert result is provider


def test_configuration_failure_is_preserved(tmp_path: Path) -> None:
    result = load_task_provider(
        config_path=tmp_path / "missing.toml",
        expected_profile=None,
        dependencies=TaskProviderDependencies(
            load_configuration=lambda path: ConfigurationResult(
                success=False,
                config=None,
                issues=(
                    ConfigurationIssue(
                        code="configuration_not_found",
                        message="Configuration not found.",
                        source_path=tmp_path / "missing.toml",
                    ),
                ),
            ),
        ),
    )

    assert isinstance(result, CliResult)
    assert result.exit_code is LocalCliExitCode.CONFIGURATION_ERROR
    assert result.issues[0].code == "configuration_not_found"


def test_missing_installation_record_maps_to_provider_unavailable(
    tmp_path: Path,
) -> None:
    result = load_task_provider(
        config_path=tmp_path / "lea.toml",
        expected_profile=None,
        dependencies=TaskProviderDependencies(
            load_configuration=lambda path: _configuration(tmp_path),
            read_installation_record=lambda path: (None, ()),
        ),
    )

    assert isinstance(result, CliResult)
    assert result.exit_code is LocalCliExitCode.PROVIDER_UNAVAILABLE
    assert result.issues[0].code == "taskwarrior_install_record_failed"
