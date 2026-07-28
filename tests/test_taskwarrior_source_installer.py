"""Tests for the pinned-source Taskwarrior installer."""

import hashlib
import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    TaskwarriorInstallerConfig,
    TaskwarriorInstallMode,
    write_taskwarrior_installation_record,
)
from lea.installers.taskwarrior.source_installer import (
    TaskwarriorSourceInstallResult,
    install_source_taskwarrior,
)


def _executable(path: Path) -> Path:
    """Create one executable regular file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"taskwarrior-built")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _source_config(tmp_path: Path) -> TaskwarriorInstallerConfig:
    """Return one source-build configuration."""
    archive = tmp_path / "task-3.4.2.tar.gz"
    archive.write_bytes(b"source archive")
    return TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.SOURCE_BUILD,
        version="3.4.2",
        platform="arm64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install" / "taskwarrior.json",
        service_user="lea",
        service_group="lea",
        source_archive=archive,
        expected_sha256=hashlib.sha256(b"source archive").hexdigest(),
        build_directory=tmp_path / "build",
        build_concurrency=1,
    )


def test_wrong_mode_is_rejected(tmp_path: Path) -> None:
    """The source installer should reject bundled mode."""
    artefact = tmp_path / "task"
    artefact.write_bytes(b"task")
    config = TaskwarriorInstallerConfig(
        mode=TaskwarriorInstallMode.BUNDLED_BINARY,
        version="3.4.2",
        platform="arm64",
        tools_root=tmp_path / "tools",
        configuration_dir=tmp_path / "config",
        state_root=tmp_path / "state",
        installation_record=tmp_path / "install" / "taskwarrior.json",
        service_user="lea",
        service_group="lea",
        artefact_path=artefact,
        expected_sha256=hashlib.sha256(b"task").hexdigest(),
    )

    result = install_source_taskwarrior(config)

    assert result.success is False
    assert result.record is None
    assert result.build is None


def test_existing_source_installation_skips_rebuild(tmp_path: Path) -> None:
    """A matching source installation should return immediately."""
    config = _source_config(tmp_path)
    executable = _executable(config.tools_root / config.version / "bin" / "task")
    sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    record = TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode=TaskwarriorInstallMode.SOURCE_BUILD.value,
        platform="linux-aarch64",
        executable=executable,
        sha256=sha256,
        taskrc=config.configuration_dir / "taskrc",
        home=config.state_root / "home",
        data=config.state_root / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 22, 8, 0, tzinfo=UTC),
    )
    assert (
        write_taskwarrior_installation_record(
            record,
            destination=config.installation_record,
        )
        == ()
    )

    result = install_source_taskwarrior(config)

    assert result.success is True
    assert result.already_installed is True
    assert result.record == record
    assert result.build is None


def test_existing_other_mode_is_rejected(tmp_path: Path) -> None:
    """Idempotency must not reuse an installation from another mode."""
    config = _source_config(tmp_path)
    executable = _executable(config.tools_root / config.version / "bin" / "task")
    sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    record = TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode=TaskwarriorInstallMode.BUNDLED_BINARY.value,
        platform="linux-aarch64",
        executable=executable,
        sha256=sha256,
        taskrc=config.configuration_dir / "taskrc",
        home=config.state_root / "home",
        data=config.state_root / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 22, 8, 0, tzinfo=UTC),
    )
    assert (
        write_taskwarrior_installation_record(
            record,
            destination=config.installation_record,
        )
        == ()
    )

    result = install_source_taskwarrior(config)

    assert result.success is False
    assert result.record is None
    assert result.issues


def test_success_result_requires_record() -> None:
    """Successful source-install results must contain a record."""
    try:
        TaskwarriorSourceInstallResult(
            success=True,
            already_installed=False,
            record=None,
            build=None,
            issues=(),
        )
    except ValueError as error:
        assert "must contain a record" in str(error)
    else:
        raise AssertionError("Expected invalid success result rejection.")


def test_failed_build_preserves_artefacts_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opt-in failures should retain the extracted build tree and summary."""
    from lea.installers.taskwarrior import (
        TaskwarriorBuildDependencyResult,
        TaskwarriorBuildStepResult,
        TaskwarriorBuildTools,
        TaskwarriorInstallerIssue,
        TaskwarriorInstallFailureCode,
        TaskwarriorSourceBuildExecutionResult,
        TaskwarriorSourceExtractionResult,
    )
    from lea.installers.taskwarrior.source_archive import (
        TaskwarriorExtractedSource,
    )
    from lea.installers.taskwarrior.source_network import (
        TaskwarriorSourceNetworkResult,
    )

    config = _source_config(tmp_path)

    executable = _executable(tmp_path / "fake-tools" / "tool")
    tools = TaskwarriorBuildTools(
        cmake=executable,
        cxx=executable,
        make=executable,
        cargo=executable,
        rustc=executable,
        pkg_config=executable,
    )

    extraction_root = tmp_path / "transient-extraction"
    source_root = extraction_root / "task-3.4.2"
    source_root.mkdir(parents=True)
    (source_root / "source.txt").write_text(
        "preserve me\n",
        encoding="utf-8",
    )

    extracted = TaskwarriorExtractedSource(
        extraction_root=extraction_root,
        source_root=source_root,
        archive_sha256=config.expected_sha256 or ("a" * 64),
    )

    issue = TaskwarriorInstallerIssue(
        code=TaskwarriorInstallFailureCode.BUILD_FAILED,
        message="Synthetic source-build failure.",
        field="build_directory",
        path=extraction_root,
    )
    build = TaskwarriorSourceBuildExecutionResult(
        success=False,
        installation_prefix=None,
        steps=(
            TaskwarriorBuildStepResult(
                phase="build",
                command=("cmake", "--build", "."),
                returncode=2,
                stdout="synthetic stdout\n",
                stderr="synthetic stderr\n",
                duration_seconds=1.0,
                timed_out=False,
            ),
        ),
        issues=(issue,),
    )

    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "run_taskwarrior_installer_preflight",
        lambda _config: (),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "validate_taskwarrior_source_network",
        lambda *_args, **_kwargs: TaskwarriorSourceNetworkResult(
            valid=True,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "validate_taskwarrior_build_dependencies",
        lambda *_args, **_kwargs: TaskwarriorBuildDependencyResult(
            tools=tools,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "extract_taskwarrior_source_archive",
        lambda *_args, **_kwargs: TaskwarriorSourceExtractionResult(
            extracted=extracted,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer.execute_taskwarrior_source_build",
        lambda *_args, **_kwargs: build,
    )

    result = install_source_taskwarrior(
        config,
        preserve_failed_artefacts=True,
    )

    assert result.success is False
    assert result.build == build
    assert not extraction_root.exists()

    diagnostics_parent = config.installation_record.parent / "failed" / "taskwarrior"
    attempts = tuple(diagnostics_parent.glob("attempt-*"))

    assert diagnostics_parent == (
        config.installation_record.parent / "failed" / "taskwarrior"
    )
    assert len(attempts) == 1

    preserved_source = attempts[0] / "source-build" / "task-3.4.2" / "source.txt"
    assert preserved_source.read_text(encoding="utf-8") == "preserve me\n"

    assert (attempts[0] / "failure.json").is_file()
    assert any(
        result_issue.field == "failure_diagnostics" and result_issue.path == attempts[0]
        for result_issue in result.issues
    )


def test_failed_build_cleans_transient_source_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default source-installer callers should retain cleanup semantics."""
    from lea.installers.taskwarrior import (
        TaskwarriorBuildDependencyResult,
        TaskwarriorBuildStepResult,
        TaskwarriorBuildTools,
        TaskwarriorInstallerIssue,
        TaskwarriorInstallFailureCode,
        TaskwarriorSourceBuildExecutionResult,
        TaskwarriorSourceExtractionResult,
    )
    from lea.installers.taskwarrior.source_archive import (
        TaskwarriorExtractedSource,
    )
    from lea.installers.taskwarrior.source_network import (
        TaskwarriorSourceNetworkResult,
    )

    config = _source_config(tmp_path)

    executable = _executable(tmp_path / "fake-tools" / "tool")
    tools = TaskwarriorBuildTools(
        cmake=executable,
        cxx=executable,
        make=executable,
        cargo=executable,
        rustc=executable,
        pkg_config=executable,
    )

    extraction_root = tmp_path / "transient-extraction"
    source_root = extraction_root / "task-3.4.2"
    source_root.mkdir(parents=True)

    extracted = TaskwarriorExtractedSource(
        extraction_root=extraction_root,
        source_root=source_root,
        archive_sha256=config.expected_sha256 or ("a" * 64),
    )

    issue = TaskwarriorInstallerIssue(
        code=TaskwarriorInstallFailureCode.BUILD_FAILED,
        message="Synthetic source-build failure.",
    )
    build = TaskwarriorSourceBuildExecutionResult(
        success=False,
        installation_prefix=None,
        steps=(
            TaskwarriorBuildStepResult(
                phase="build",
                command=("cmake", "--build", "."),
                returncode=2,
                stdout="",
                stderr="failed\n",
                duration_seconds=1.0,
                timed_out=False,
            ),
        ),
        issues=(issue,),
    )

    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "run_taskwarrior_installer_preflight",
        lambda _config: (),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "validate_taskwarrior_source_network",
        lambda *_args, **_kwargs: TaskwarriorSourceNetworkResult(
            valid=True,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "validate_taskwarrior_build_dependencies",
        lambda *_args, **_kwargs: TaskwarriorBuildDependencyResult(
            tools=tools,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "extract_taskwarrior_source_archive",
        lambda *_args, **_kwargs: TaskwarriorSourceExtractionResult(
            extracted=extracted,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer.execute_taskwarrior_source_build",
        lambda *_args, **_kwargs: build,
    )

    result = install_source_taskwarrior(config)

    assert result.success is False
    assert result.build == build
    assert not extraction_root.exists()

    diagnostics_parent = config.installation_record.parent / "failed" / "taskwarrior"
    assert not diagnostics_parent.exists()
    assert all(
        result_issue.field != "failure_diagnostics" for result_issue in result.issues
    )


def test_failed_smoke_test_preserves_staged_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke failures should preserve the staged executable and build tree."""
    from lea.installers.taskwarrior import (
        TaskwarriorBuildDependencyResult,
        TaskwarriorBuildStepResult,
        TaskwarriorBuildTools,
        TaskwarriorInstallerIssue,
        TaskwarriorInstallFailureCode,
        TaskwarriorSmokeTestResult,
        TaskwarriorSourceBuildExecutionResult,
        TaskwarriorSourceExtractionResult,
    )
    from lea.installers.taskwarrior.source_archive import (
        TaskwarriorExtractedSource,
    )
    from lea.installers.taskwarrior.source_network import (
        TaskwarriorSourceNetworkResult,
    )

    config = _source_config(tmp_path)

    tool = _executable(tmp_path / "fake-tools" / "tool")
    tools = TaskwarriorBuildTools(
        cmake=tool,
        cxx=tool,
        make=tool,
        cargo=tool,
        rustc=tool,
        pkg_config=tool,
    )

    extraction_root = tmp_path / "transient-extraction"
    source_root = extraction_root / "task-3.4.2"
    source_root.mkdir(parents=True)
    (source_root / "source.txt").write_text(
        "preserve source\n",
        encoding="utf-8",
    )

    installation_prefix = extraction_root / "install"
    built_executable = _executable(installation_prefix / "bin" / "task")
    built_executable.write_text(
        "#!/bin/sh\nexit 127\n",
        encoding="utf-8",
    )
    built_executable.chmod(built_executable.stat().st_mode | stat.S_IXUSR)

    extracted = TaskwarriorExtractedSource(
        extraction_root=extraction_root,
        source_root=source_root,
        archive_sha256=config.expected_sha256 or ("a" * 64),
    )

    build = TaskwarriorSourceBuildExecutionResult(
        success=True,
        installation_prefix=installation_prefix,
        steps=tuple(
            TaskwarriorBuildStepResult(
                phase=phase,
                command=("synthetic-build", phase),
                returncode=0,
                stdout=f"{phase} stdout\n",
                stderr="",
                duration_seconds=1.0,
                timed_out=False,
            )
            for phase in ("configure", "build", "install")
        ),
        issues=(),
    )

    smoke_issue = TaskwarriorInstallerIssue(
        code=TaskwarriorInstallFailureCode.SMOKE_TEST_FAILED,
        message=(
            "The staged Taskwarrior executable failed version inspection. "
            "[taskwarrior_process_failed] Process failed; "
            "exit status 127."
        ),
    )

    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "run_taskwarrior_installer_preflight",
        lambda _config: (),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "validate_taskwarrior_source_network",
        lambda *_args, **_kwargs: TaskwarriorSourceNetworkResult(
            valid=True,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "validate_taskwarrior_build_dependencies",
        lambda *_args, **_kwargs: TaskwarriorBuildDependencyResult(
            tools=tools,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "extract_taskwarrior_source_archive",
        lambda *_args, **_kwargs: TaskwarriorSourceExtractionResult(
            extracted=extracted,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer.execute_taskwarrior_source_build",
        lambda *_args, **_kwargs: build,
    )
    monkeypatch.setattr(
        "lea.installers.taskwarrior.source_installer."
        "validate_staged_taskwarrior_binary",
        lambda *_args, **_kwargs: TaskwarriorSmokeTestResult(
            passed=False,
            version=None,
            issues=(smoke_issue,),
        ),
    )

    result = install_source_taskwarrior(
        config,
        preserve_failed_artefacts=True,
    )

    assert result.success is False
    assert result.build == build
    assert result.issues[0] == smoke_issue
    assert not extraction_root.exists()

    diagnostics_parent = config.installation_record.parent / "failed" / "taskwarrior"
    attempts = tuple(diagnostics_parent.glob("attempt-*"))

    assert len(attempts) == 1

    attempt = attempts[0]
    preserved_source = attempt / "source-build" / "task-3.4.2" / "source.txt"
    preserved_staged = attempt / "staging" / "bin" / "task"

    assert preserved_source.read_text(encoding="utf-8") == "preserve source\n"
    assert preserved_staged.is_file()
    assert preserved_staged.stat().st_mode & stat.S_IXUSR
    assert preserved_staged.read_text(encoding="utf-8") == "#!/bin/sh\nexit 127\n"

    summary = json.loads((attempt / "failure.json").read_text(encoding="utf-8"))

    assert summary["staged_binary"] == str(preserved_staged)
    assert summary["issues"][0]["code"] == ("taskwarrior_install_smoke_test_failed")
    assert "exit status 127" in summary["issues"][0]["message"]

    assert any(
        issue.field == "failure_diagnostics" and issue.path == attempt
        for issue in result.issues
    )
