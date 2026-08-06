"""Tests for explicit Radicale service and state removal."""

from pathlib import Path

import pytest

from lea.installers.radicale import (
    RadicaleRemovalRequest,
    RadicaleRuntimeLayout,
    RadicaleServiceConfig,
    ServiceCommandResult,
    remove_radicale,
)


def _request(tmp_path: Path, *, purge: bool = False) -> RadicaleRemovalRequest:
    layout = RadicaleRuntimeLayout(
        tmp_path / "etc" / "radicale",
        tmp_path / "etc" / "radicale" / "config",
        tmp_path / "secrets" / "radicale",
        tmp_path / "secrets" / "radicale" / "users",
        tmp_path / "state" / "radicale" / "collections",
    )
    service = RadicaleServiceConfig(
        tmp_path / "bin" / "radicale",
        layout,
        tmp_path / "systemd" / "lea-radicale.service",
        Path("/usr/bin/systemctl"),
    )
    return RadicaleRemovalRequest(
        service,
        tmp_path / "install" / "radicale.json",
        tmp_path / "tools" / "radicale" / "3.5.4",
        purge=purge,
        confirmed=purge,
    )


def _populate(request: RadicaleRemovalRequest) -> None:
    for path in (
        request.service.unit_file,
        request.service.layout.configuration_file,
        request.service.layout.users_file,
        request.installation_record,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("managed\n", encoding="utf-8")
    request.service.layout.storage_directory.mkdir(parents=True)
    (request.service.layout.storage_directory / "event.ics").write_text(
        "event\n", encoding="utf-8"
    )
    request.distribution_root.mkdir(parents=True)
    (request.distribution_root / "radicale").write_text("binary\n", encoding="utf-8")


def test_default_removal_preserves_configuration_secrets_and_storage(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    _populate(request)
    commands: list[tuple[str, ...]] = []

    def execute(command: tuple[str, ...]) -> ServiceCommandResult:
        commands.append(command)
        return ServiceCommandResult(0)

    result = remove_radicale(request, execute=execute)

    assert result.success is True
    assert result.service_removed is True
    assert result.state_purged is False
    assert not request.service.unit_file.exists()
    assert request.service.layout.configuration_file.exists()
    assert request.service.layout.users_file.exists()
    assert request.service.layout.storage_directory.exists()
    assert [command[1] for command in commands] == ["stop", "disable", "daemon-reload"]


def test_confirmed_purge_removes_only_exact_managed_state(tmp_path: Path) -> None:
    request = _request(tmp_path, purge=True)
    _populate(request)
    unrelated = tmp_path / "state" / "keep.txt"
    unrelated.parent.mkdir(exist_ok=True)
    unrelated.write_text("keep\n", encoding="utf-8")

    result = remove_radicale(request, execute=lambda _command: ServiceCommandResult(0))

    assert result.success is True
    assert result.state_purged is True
    assert not request.service.layout.configuration_file.exists()
    assert not request.service.layout.users_file.exists()
    assert not request.service.layout.storage_directory.exists()
    assert not request.installation_record.exists()
    assert not request.distribution_root.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep\n"


def test_purge_requires_explicit_confirmation(tmp_path: Path) -> None:
    request = _request(tmp_path)
    with pytest.raises(ValueError, match="explicit confirmation"):
        RadicaleRemovalRequest(
            request.service,
            request.installation_record,
            request.distribution_root,
            purge=True,
            confirmed=False,
        )


def test_unsafe_symlink_fails_before_service_commands(tmp_path: Path) -> None:
    request = _request(tmp_path, purge=True)
    _populate(request)
    request.service.layout.users_file.unlink()
    request.service.layout.users_file.symlink_to(tmp_path / "outside")
    commands: list[tuple[str, ...]] = []

    def execute(command: tuple[str, ...]) -> ServiceCommandResult:
        commands.append(command)
        return ServiceCommandResult(0)

    result = remove_radicale(
        request,
        execute=execute,
    )

    assert result.success is False
    assert result.issues[0].code == "radicale_removal_path_unsafe"
    assert commands == []
