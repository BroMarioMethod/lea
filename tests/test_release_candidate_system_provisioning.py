"""Tests for release-candidate system account and filesystem provisioning."""

import subprocess
from dataclasses import replace
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
from lea.installers.release_candidate.provisioning import (
    _ensure_managed_file as _real_ensure_managed_file,
)
from lea.installers.release_candidate.provisioning import _ensure_runtime_audit_file
from lea.installers.release_candidate.provisioning import (
    _repair_managed_proposal_documents as _real_repair_managed_proposal_documents,
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
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning."
        "_repair_managed_proposal_documents",
        lambda _directory: (),
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._ensure_runtime_audit_file",
        lambda _directory: None,
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
    assert modes["audit"] == 0o2770
    assert modes["backups"] == 0o2770

    install_directory = next(
        directory for directory in plan.directories if directory.path.name == "install"
    )
    assert install_directory.owner == "root"
    assert install_directory.group == "lea"
    assert install_directory.mode == 0o750

    run_directory = next(
        directory
        for directory in plan.directories
        if directory.path == Path("/run/lea")
    )
    assert run_directory.owner == "lea"
    assert run_directory.group == "lea"
    assert run_directory.mode == 0o2770


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
    assert managed.contents == "d /run/lea 2770 lea lea -\n"
    assert managed.legacy_contents == ("d /run/lea 0750 lea lea -\n",)
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


def test_existing_proposal_permissions_are_repaired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repair must normalise canonical proposal ownership and mode."""
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning."
        "_repair_managed_proposal_documents",
        _real_repair_managed_proposal_documents,
    )

    plan = create_system_provisioning_plan(_request(tmp_path))
    proposal_directory = next(
        directory
        for directory in plan.directories
        if directory.path.name == "proposals"
    )
    proposal_directory.path.mkdir(parents=True)

    proposal = proposal_directory.path / "11111111-1111-4111-8111-111111111111.md"
    proposal.write_text("# Proposal\n", encoding="utf-8")
    proposal.chmod(0o600)

    ignored = proposal_directory.path / "notes.md"
    ignored.write_text("not managed\n", encoding="utf-8")

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
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.pwd.getpwnam",
        lambda _name: type("User", (), {"pw_uid": 123})(),
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.grp.getgrnam",
        lambda _name: type("Group", (), {"gr_gid": 456})(),
    )

    ownership: list[tuple[Path, int, int]] = []
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.os.chown",
        lambda path, uid, gid: ownership.append((Path(path), uid, gid)),
    )

    result = provision_system_layout(
        plan,
        command_runner=lambda *_args, **_kwargs: type(
            "Completed",
            (),
            {"returncode": 0},
        )(),
    )

    assert result.success is True
    assert proposal in result.files_changed
    assert proposal.stat().st_mode & 0o7777 == 0o640
    assert ownership == [(proposal, 123, 456)]
    assert ignored.stat().st_mode & 0o7777 != 0o640


def test_provisioning_migrates_recognised_tmpfiles_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repair must migrate the previous canonical tmpfiles rule."""
    baseline = create_system_provisioning_plan(_request(tmp_path))
    managed_path = tmp_path / "etc" / "tmpfiles.d" / "lea.conf"
    managed = replace(
        baseline.tmpfiles_configuration,
        path=managed_path,
    )
    plan = replace(
        baseline,
        tmpfiles_configuration=managed,
    )

    managed_path.parent.mkdir(parents=True)
    managed_path.write_text(
        "d /run/lea 0750 lea lea -\n",
        encoding="utf-8",
    )
    managed_path.chmod(0o600)

    uid = managed_path.stat().st_uid
    gid = managed_path.stat().st_gid

    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._ensure_managed_file",
        _real_ensure_managed_file,
    )
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
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.pwd.getpwnam",
        lambda _name: type("User", (), {"pw_uid": uid})(),
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.grp.getgrnam",
        lambda _name: type("Group", (), {"gr_gid": gid})(),
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.os.chown",
        lambda *_args: None,
    )

    commands: list[tuple[str, ...]] = []

    def _record_command(
        command: tuple[str, ...],
        **_kwargs: Any,
    ) -> Any:
        commands.append(command)
        return type("Completed", (), {"returncode": 0})()

    result = provision_system_layout(
        plan,
        command_runner=_record_command,
    )

    assert result.success is True
    assert result.files_changed == (managed_path,)
    assert managed_path.read_text(encoding="utf-8") == ("d /run/lea 2770 lea lea -\n")
    assert managed_path.stat().st_mode & 0o7777 == 0o644
    assert tuple(managed_path.parent.glob(".lea.conf.*.managed")) == ()
    assert commands == [
        (
            str(plan.systemd_tmpfiles),
            "--create",
            str(managed_path),
        )
    ]


def test_managed_file_migration_rejects_unknown_contents(
    tmp_path: Path,
) -> None:
    """Administrator-modified contents must still fail closed."""
    baseline = create_system_provisioning_plan(_request(tmp_path))
    path = tmp_path / "lea.conf"
    managed = replace(
        baseline.tmpfiles_configuration,
        path=path,
    )
    original = "# administrator-managed rule\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(
        PermissionError,
        match="conflicting contents",
    ):
        _real_ensure_managed_file(managed)

    assert path.read_text(encoding="utf-8") == original


def test_managed_file_migration_preserves_old_file_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed activation must leave the previous canonical file intact."""
    baseline = create_system_provisioning_plan(_request(tmp_path))
    path = tmp_path / "lea.conf"
    managed = replace(
        baseline.tmpfiles_configuration,
        path=path,
    )
    previous = "d /run/lea 0750 lea lea -\n"
    path.write_text(previous, encoding="utf-8")

    uid = path.stat().st_uid
    gid = path.stat().st_gid

    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.pwd.getpwnam",
        lambda _name: type("User", (), {"pw_uid": uid})(),
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.grp.getgrnam",
        lambda _name: type("Group", (), {"gr_gid": gid})(),
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.os.chown",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.os.replace",
        lambda *_args: (_ for _ in ()).throw(
            PermissionError("synthetic replacement failure")
        ),
    )

    with pytest.raises(
        PermissionError,
        match="synthetic replacement failure",
    ):
        _real_ensure_managed_file(managed)

    assert path.read_text(encoding="utf-8") == previous
    assert tuple(path.parent.glob(".lea.conf.*.managed")) == ()


def _test_audit_directory(
    tmp_path: Path,
) -> ManagedDirectory:
    plan = create_system_provisioning_plan(_request(tmp_path))
    audit_directory = next(
        directory for directory in plan.directories if directory.path.name == "audit"
    )
    return replace(
        audit_directory,
        path=tmp_path / "audit",
    )


def _stub_current_identity(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_stat = path.stat()

    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.pwd.getpwnam",
        lambda _name: type(
            "User",
            (),
            {"pw_uid": current_stat.st_uid},
        )(),
    )
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning.grp.getgrnam",
        lambda _name: type(
            "Group",
            (),
            {"gr_gid": current_stat.st_gid},
        )(),
    )


def test_runtime_audit_file_is_created_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh provisioning should create one empty shared audit file."""
    directory = _test_audit_directory(tmp_path)
    directory.path.mkdir(parents=True)
    _stub_current_identity(
        directory.path,
        monkeypatch,
    )

    expected = directory.path / "actions-integrity.jsonl"

    assert _ensure_runtime_audit_file(directory) == expected
    assert expected.read_bytes() == b""
    assert expected.stat().st_mode & 0o7777 == 0o660
    assert _ensure_runtime_audit_file(directory) is None


def test_runtime_audit_file_repair_preserves_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metadata repair must preserve every existing audit byte."""
    directory = _test_audit_directory(tmp_path)
    directory.path.mkdir(parents=True)
    path = directory.path / "actions-integrity.jsonl"
    contents = b'{"integrity_version":1,"evidence":"preserve"}\n'
    path.write_bytes(contents)
    path.chmod(0o600)
    _stub_current_identity(
        directory.path,
        monkeypatch,
    )

    assert _ensure_runtime_audit_file(directory) == path
    assert path.read_bytes() == contents
    assert path.stat().st_mode & 0o7777 == 0o660


def test_runtime_audit_file_rejects_symbolic_link(
    tmp_path: Path,
) -> None:
    """Audit evidence must not be followed through a symbolic link."""
    directory = _test_audit_directory(tmp_path)
    directory.path.mkdir(parents=True)
    target = tmp_path / "target.jsonl"
    target.write_text(
        "unchanged\n",
        encoding="utf-8",
    )
    path = directory.path / "actions-integrity.jsonl"
    path.symlink_to(target)

    with pytest.raises(
        OSError,
        match="symbolic link",
    ):
        _ensure_runtime_audit_file(directory)

    assert (
        target.read_text(
            encoding="utf-8",
        )
        == "unchanged\n"
    )


def test_runtime_audit_file_rejects_non_regular_path(
    tmp_path: Path,
) -> None:
    """A directory must not be accepted as an audit evidence file."""
    directory = _test_audit_directory(tmp_path)
    directory.path.mkdir(parents=True)
    path = directory.path / "actions-integrity.jsonl"
    path.mkdir()

    with pytest.raises(
        OSError,
        match="not a regular file",
    ):
        _ensure_runtime_audit_file(directory)


def test_runtime_audit_file_change_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provisioning results should report audit metadata changes."""
    plan = create_system_provisioning_plan(_request(tmp_path))
    expected = tmp_path / "audit" / "actions-integrity.jsonl"

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
    monkeypatch.setattr(
        "lea.installers.release_candidate.provisioning._ensure_runtime_audit_file",
        lambda _directory: expected,
    )

    result = provision_system_layout(
        plan,
        command_runner=lambda *_args, **_kwargs: type(
            "Completed",
            (),
            {"returncode": 0},
        )(),
    )

    assert result.success is True
    assert expected in result.files_changed
