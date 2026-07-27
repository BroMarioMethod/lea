"""Tests for non-mutating release-candidate host preflight."""

from pathlib import Path

import pytest

from lea.installers.release_candidate import (
    HostFacts,
    HostPreflightCheckState,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    collect_host_facts,
    evaluate_host_preflight,
)


def _request(
    mode: ReleaseCandidateInstallMode = ReleaseCandidateInstallMode.FRESH_INSTALL,
) -> ReleaseCandidateInstallRequest:
    """Return one valid preflight request."""
    return ReleaseCandidateInstallRequest(
        mode=mode,
        display_timezone="Africa/Gaborone",
        enable_telegram=True,
    )


def _facts(
    *,
    operating_system_id: str = "debian",
    architecture: str = "aarch64",
    python_version: tuple[int, int, int] = (3, 13, 5),
    systemd_available: bool = True,
    dietpi_available: bool = True,
    missing_executables: tuple[Path, ...] = (),
    libuuid_available: bool = True,
    service_user_exists: bool = False,
    service_group_exists: bool = False,
    managed_paths_present: tuple[Path, ...] = (),
) -> HostFacts:
    """Return supported host facts with selected overrides."""
    required = (
        Path("/usr/bin/bash"),
        Path("/usr/bin/cargo"),
        Path("/usr/bin/cmake"),
        Path("/usr/bin/c++"),
        Path("/usr/bin/git"),
        Path("/usr/bin/make"),
        Path("/usr/bin/pkg-config"),
        Path("/usr/bin/python3"),
        Path("/usr/bin/rustc"),
        Path("/usr/bin/sudo"),
        Path("/usr/bin/systemctl"),
    )
    return HostFacts(
        operating_system_id=operating_system_id,
        operating_system_version="13",
        architecture=architecture,
        python_version=python_version,
        systemd_available=systemd_available,
        dietpi_available=dietpi_available,
        required_executables=required,
        missing_executables=missing_executables,
        libuuid_available=libuuid_available,
        service_user_exists=service_user_exists,
        service_group_exists=service_group_exists,
        managed_paths_present=managed_paths_present,
    )


def test_supported_clean_host_passes() -> None:
    """A supported clean DietPi host should pass preflight."""
    result = evaluate_host_preflight(_request(), _facts())

    assert result.supported is True
    assert result.issues == ()
    assert all(check.state is HostPreflightCheckState.PASSED for check in result.checks)


@pytest.mark.parametrize(
    ("field", "facts"),
    (
        ("operating_system_id", _facts(operating_system_id="ubuntu")),
        ("architecture", _facts(architecture="x86_64")),
        ("python_version", _facts(python_version=(3, 11, 9))),
        ("systemd_available", _facts(systemd_available=False)),
        ("dietpi_available", _facts(dietpi_available=False)),
    ),
)
def test_unsupported_host_fact_fails(
    field: str,
    facts: HostFacts,
) -> None:
    """Each unsupported platform fact should fail explicitly."""
    result = evaluate_host_preflight(_request(), facts)

    assert result.supported is False
    assert any(issue.field == field for issue in result.issues)


def test_missing_required_executable_fails() -> None:
    """A missing exact prerequisite executable should fail."""
    missing = Path("/usr/bin/git")
    result = evaluate_host_preflight(
        _request(),
        _facts(missing_executables=(missing,)),
    )

    assert result.supported is False
    assert any(issue.path == missing for issue in result.issues)


def test_executable_elsewhere_in_path_does_not_satisfy_exact_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matching executable elsewhere in PATH must not satisfy the exact path."""
    path_directory = tmp_path / "bin"
    path_directory.mkdir()

    substitute = path_directory / "git"
    substitute.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    substitute.chmod(0o755)

    monkeypatch.setenv("PATH", str(path_directory))

    missing = tmp_path / "required" / "git"

    monkeypatch.setattr(
        "lea.installers.release_candidate.preflight._REQUIRED_EXECUTABLES",
        (missing,),
    )

    facts = collect_host_facts()

    assert facts.required_executables == (missing,)
    assert facts.missing_executables == (missing,)


def test_source_checkout_is_not_a_managed_installation_marker() -> None:
    """The installer checkout must remain separate from installed state."""
    from lea.installers.release_candidate import preflight

    assert Path("/opt/lea") not in preflight._MANAGED_PATHS


def test_fresh_install_allows_source_checkout_without_installation_markers() -> None:
    """A repository checkout must not count as an installed LEA system."""
    result = evaluate_host_preflight(
        _request(),
        _facts(
            managed_paths_present=(),
            service_user_exists=False,
            service_group_exists=False,
        ),
    )

    assert result.supported is True
    assert result.issues == ()
    assert any(
        check.name == "existing_installation"
        and check.state is HostPreflightCheckState.PASSED
        for check in result.checks
    )


def test_fresh_install_rejects_existing_markers() -> None:
    """Fresh-install mode must not overwrite an existing LEA installation."""
    result = evaluate_host_preflight(
        _request(),
        _facts(
            service_user_exists=True,
            managed_paths_present=(Path("/etc/lea"),),
        ),
    )

    assert result.supported is False
    assert any(issue.field == "mode" for issue in result.issues)


@pytest.mark.parametrize(
    "mode",
    (
        ReleaseCandidateInstallMode.UPGRADE,
        ReleaseCandidateInstallMode.REPAIR,
    ),
)
def test_existing_markers_warn_for_non_fresh_modes(
    mode: ReleaseCandidateInstallMode,
) -> None:
    """Upgrade and repair modes may inspect an existing installation."""
    result = evaluate_host_preflight(
        _request(mode),
        _facts(
            service_user_exists=True,
            service_group_exists=True,
            managed_paths_present=(Path("/opt/lea"), Path("/etc/lea")),
        ),
    )

    assert result.supported is True
    assert result.issues == ()
    assert any(
        check.name == "existing_installation"
        and check.state is HostPreflightCheckState.WARNING
        for check in result.checks
    )


def test_missing_executables_must_be_required() -> None:
    """Collected facts must not report unrelated missing paths."""
    with pytest.raises(
        ValueError,
        match="must be a subset",
    ):
        _facts(missing_executables=(Path("/usr/bin/curl"),))


def test_missing_native_build_prerequisites_are_reported_together() -> None:
    """All missing Taskwarrior build prerequisites should fail preflight."""
    missing = (
        Path("/usr/bin/cargo"),
        Path("/usr/bin/rustc"),
        Path("/usr/bin/pkg-config"),
    )
    facts = _facts(
        missing_executables=missing,
        libuuid_available=False,
    )

    result = evaluate_host_preflight(_request(), facts)

    assert result.supported is False

    issue_fields = {issue.field for issue in result.issues}

    assert "cargo" not in issue_fields
    assert "rustc" not in issue_fields
    assert "pkg-config" not in issue_fields
    assert "libuuid" in issue_fields

    issue_paths = {issue.path for issue in result.issues}

    assert Path("/usr/bin/cargo") in issue_paths
    assert Path("/usr/bin/rustc") in issue_paths
    assert Path("/usr/bin/pkg-config") in issue_paths

    failed_names = {
        check.name
        for check in result.checks
        if check.state is HostPreflightCheckState.FAILED
    }

    assert "executable:cargo" in failed_names
    assert "executable:rustc" in failed_names
    assert "executable:pkg-config" in failed_names
    assert "library:libuuid" in failed_names
