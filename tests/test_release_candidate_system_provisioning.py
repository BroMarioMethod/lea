"""Tests for release-candidate system account and filesystem provisioning."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from lea.installers.release_candidate import (
    ManagedDirectory,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    SystemProvisioningPlan,
    create_system_provisioning_plan,
    provision_system_layout,
)


def _request(tmp_path: Path) -> ReleaseCandidateInstallRequest:
    """Return one isolated provisioning request."""
    return ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=True,
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
    )


@pytest.fixture(autouse=True)
def _stub_managed_file_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent isolated provisioning tests from writing system paths."""
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._ensure_managed_file",
        lambda _managed: False,
    )


def test_plan_uses_canonical_directory_layout(tmp_path: Path) -> None:
    """The provisioning plan should contain LEA's required paths."""
    request = _request(tmp_path)
    plan = create_system_provisioning_plan(request)

    paths = {directory.path for directory in plan.directories}

    assert request.configuration_root in paths
    assert request.configuration_root / "secrets" in paths
    assert request.configuration_root / "telegram" in paths
    assert request.state_root / "audit" in paths
    assert request.state_root / "proposals" in paths
    assert request.state_root / "knowledge" in paths
    assert request.state_root / "indexes" in paths
    assert request.state_root / "adapters" in paths
    assert request.state_root / "backups" in paths
    assert request.state_root / "telegram" in paths
    assert Path("/run/lea") in paths
    assert request.log_root in paths


def test_plan_uses_expected_modes(tmp_path: Path) -> None:
    """Sensitive and collaborative paths should use deliberate modes."""
    plan = create_system_provisioning_plan(_request(tmp_path))
    modes = {directory.path.name: directory.mode for directory in plan.directories}

    assert modes["secrets"] == 0o750
    assert modes["telegram"] in {0o750}
    assert modes["audit"] == 0o775
    assert modes["backups"] == 0o775

    run_directory = next(
        directory
        for directory in plan.directories
        if directory.path == Path("/run/lea")
    )
    assert run_directory.owner == "lea"
    assert run_directory.group == "lea"
    assert run_directory.mode == 0o750


def test_managed_directory_requires_absolute_path() -> None:
    """Managed directory paths must be absolute."""
    with pytest.raises(
        ValueError,
        match="path must be an absolute path",
    ):
        ManagedDirectory(
            path=Path("var/lib/lea"),
            owner="lea",
            group="lea",
            mode=0o750,
        )


def test_plan_rejects_duplicate_paths(tmp_path: Path) -> None:
    """A provisioning plan must not contain duplicate paths."""
    directory = ManagedDirectory(
        path=tmp_path / "state",
        owner="lea",
        group="lea",
        mode=0o750,
    )

    baseline = create_system_provisioning_plan(_request(tmp_path))

    with pytest.raises(
        ValueError,
        match="duplicate paths",
    ):
        SystemProvisioningPlan(
            service_user="lea",
            service_group="lea",
            directories=(directory, directory),
            tmpfiles_configuration=baseline.tmpfiles_configuration,
            systemd_tmpfiles=baseline.systemd_tmpfiles,
        )


def test_provisioning_creates_group_then_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing service identities should be created with exact commands."""
    plan = create_system_provisioning_plan(_request(tmp_path))
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._group_exists",
        lambda name: False,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._user_exists",
        lambda name: False,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._ensure_directory",
        lambda directory: False,
    )

    def run(command: tuple[str, ...], **kwargs: Any) -> Any:
        commands.append(command)
        return type("Completed", (), {"returncode": 0})()

    result = provision_system_layout(plan, command_runner=run)

    assert result.success is True
    assert result.group_created is True
    assert result.user_created is True
    assert commands[0] == (
        "/usr/sbin/groupadd",
        "--system",
        "lea",
    )
    assert commands[1] == (
        "/usr/sbin/useradd",
        "--system",
        "--gid",
        "lea",
        "--home-dir",
        "/nonexistent",
        "--no-create-home",
        "--shell",
        "/usr/sbin/nologin",
        "lea",
    )


def test_existing_identity_skips_account_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing service identities should not be recreated."""
    plan = create_system_provisioning_plan(_request(tmp_path))
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._group_exists",
        lambda name: True,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._user_exists",
        lambda name: True,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._ensure_directory",
        lambda directory: False,
    )

    def run(command: tuple[str, ...], **kwargs: Any) -> Any:
        commands.append(command)
        return type("Completed", (), {"returncode": 0})()

    result = provision_system_layout(plan, command_runner=run)

    assert result.success is True
    assert result.group_created is False
    assert result.user_created is False
    assert commands == [
        (
            str(plan.systemd_tmpfiles),
            "--create",
            str(plan.tmpfiles_configuration.path),
        ),
    ]


def test_directory_changes_are_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changed managed directories should be returned exactly once."""
    plan = create_system_provisioning_plan(_request(tmp_path))
    changed_path = plan.directories[0].path

    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._group_exists",
        lambda name: True,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._user_exists",
        lambda name: True,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._ensure_directory",
        lambda directory: directory.path == changed_path,
    )

    def run(command: tuple[str, ...], **kwargs: Any) -> Any:
        return type("Completed", (), {"returncode": 0})()

    result = provision_system_layout(
        plan,
        command_runner=run,
    )

    assert result.success is True
    assert result.directories_changed == (changed_path,)


def test_plan_contains_boot_persistent_runtime_directory_rule(
    tmp_path: Path,
) -> None:
    """The provisioning plan should recreate /run/lea after every boot."""
    plan = create_system_provisioning_plan(_request(tmp_path))
    managed = plan.tmpfiles_configuration

    assert managed.path == Path("/etc/tmpfiles.d/lea.conf")
    assert managed.contents == "d /run/lea 0750 lea lea -\n"
    assert managed.owner == "root"
    assert managed.group == "root"
    assert managed.mode == 0o644
    assert plan.systemd_tmpfiles == Path("/usr/bin/systemd-tmpfiles")


def test_managed_file_requires_absolute_path() -> None:
    """Managed files must use explicit absolute paths."""
    from lea.installers.release_candidate import ManagedFile

    with pytest.raises(
        ValueError,
        match="path must be an absolute path",
    ):
        ManagedFile(
            path=Path("etc/tmpfiles.d/lea.conf"),
            contents="d /run/lea 0750 lea lea -\n",
            owner="root",
            group="root",
            mode=0o644,
        )


def test_provisioning_installs_and_activates_tmpfiles_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provisioning should install and activate the persistent runtime rule."""
    plan = create_system_provisioning_plan(_request(tmp_path))
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._group_exists",
        lambda _name: True,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._user_exists",
        lambda _name: True,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._ensure_managed_file",
        lambda managed: managed == plan.tmpfiles_configuration,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._ensure_directory",
        lambda _directory: False,
    )

    def run(command: tuple[str, ...], **kwargs: Any) -> Any:
        commands.append(command)
        return type("Completed", (), {"returncode": 0})()

    result = provision_system_layout(
        plan,
        command_runner=run,
    )

    assert result.success is True
    assert result.files_changed == (plan.tmpfiles_configuration.path,)
    assert commands == [
        (
            str(plan.systemd_tmpfiles),
            "--create",
            str(plan.tmpfiles_configuration.path),
        ),
    ]


def test_tmpfiles_activation_failure_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed systemd-tmpfiles invocation should fail provisioning."""
    plan = create_system_provisioning_plan(_request(tmp_path))

    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._group_exists",
        lambda _name: True,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._user_exists",
        lambda _name: True,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._ensure_directory",
        lambda _directory: False,
    )

    def run(command: tuple[str, ...], **kwargs: Any) -> Any:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            stderr="synthetic tmpfiles failure",
        )

    result = provision_system_layout(
        plan,
        command_runner=run,
    )

    assert result.success is False
    assert result.issues[0].code.value == ("release_candidate_install_step_failed")


def test_deployment_asset_matches_canonical_tmpfiles_rule(
    tmp_path: Path,
) -> None:
    """The shipped tmpfiles asset must match the privileged provisioning plan."""
    plan = create_system_provisioning_plan(_request(tmp_path))
    repository_root = Path(__file__).resolve().parents[1]
    asset = repository_root / "deploy" / "tmpfiles.d" / "lea.conf"

    assert asset.is_file()
    assert asset.read_text(encoding="utf-8") == (plan.tmpfiles_configuration.contents)
