"""Tests for ordered fail-closed Radicale installer orchestration."""

from pathlib import Path

from lea.installers.radicale import (
    RadicaleAcceptanceAccount,
    RadicaleBinaryConfig,
    RadicaleBinaryIssue,
    RadicaleBinaryResult,
    RadicaleCredential,
    RadicaleCredentialProvisionResult,
    RadicaleHealthResult,
    RadicaleInstallationRecord,
    RadicaleInstallerDependencies,
    RadicaleInstallRequest,
    RadicaleIsolationResult,
    RadicaleProvisionIssue,
    RadicaleProvisionResult,
    RadicaleRuntimeLayout,
    RadicaleServerConfig,
    RadicaleServiceConfig,
    RadicaleServiceResult,
    RadicaleUnitProvisionResult,
    install_radicale,
)

HASH = "$2b$12$" + "A" * 53


def _request(
    tmp_path: Path,
    *,
    activate: bool = True,
    health_attempts: int = 1,
) -> RadicaleInstallRequest:
    layout = RadicaleRuntimeLayout(
        tmp_path / "config",
        tmp_path / "config" / "config",
        tmp_path / "secrets",
        tmp_path / "secrets" / "users",
        tmp_path / "storage",
    )
    executable = tmp_path / "radicale"
    binary = RadicaleBinaryConfig(
        executable,
        "3.5.4",
        "a" * 64,
        tmp_path / "record.json",
        tmp_path,
    )
    return RadicaleInstallRequest(
        binary=binary,
        server=RadicaleServerConfig(layout, "127.0.0.1"),
        service=RadicaleServiceConfig(
            executable,
            layout,
            tmp_path / "lea-radicale.service",
            tmp_path / "systemctl",
        ),
        credentials=(
            RadicaleCredential("alice", HASH),
            RadicaleCredential("bob", HASH),
        ),
        base_url="http://127.0.0.1:5232",
        activate=activate,
        acceptance_accounts=(
            RadicaleAcceptanceAccount("alice", "first"),
            RadicaleAcceptanceAccount("bob", "second"),
        )
        if activate
        else (),
        health_attempts=health_attempts,
    )


def _binary_success(
    config: RadicaleBinaryConfig, register: bool
) -> RadicaleBinaryResult:
    return RadicaleBinaryResult(
        True,
        register,
        RadicaleInstallationRecord(
            1,
            "radicale",
            "3.5.4",
            str(config.executable),
            "a" * 64,
            "2026-08-04T00:00:00+00:00",
        ),
        (),
    )


def _dependencies(tmp_path: Path, calls: list[str]) -> RadicaleInstallerDependencies:
    def binary(config: RadicaleBinaryConfig, register: bool) -> RadicaleBinaryResult:
        calls.append("binary.register" if register else "binary.verify")
        return _binary_success(config, register)

    def runtime(_config: RadicaleServerConfig) -> RadicaleProvisionResult:
        calls.append("runtime")
        return RadicaleProvisionResult(True, (), ())

    def credentials(
        path: Path, _credentials: tuple[RadicaleCredential, ...]
    ) -> RadicaleCredentialProvisionResult:
        calls.append("credentials")
        return RadicaleCredentialProvisionResult(True, path, 2, True, ())

    def unit(_config: RadicaleServiceConfig) -> RadicaleUnitProvisionResult:
        calls.append("unit")
        return RadicaleUnitProvisionResult(True, True, ())

    def activate(_config: RadicaleServiceConfig) -> RadicaleServiceResult:
        calls.append("activate")
        return RadicaleServiceResult(True, True, True, (), ())

    def health(_url: str) -> RadicaleHealthResult:
        calls.append("health")
        return RadicaleHealthResult(True, True, ())

    def isolation(
        _url: str,
        _first: RadicaleAcceptanceAccount,
        _second: RadicaleAcceptanceAccount,
    ) -> RadicaleIsolationResult:
        calls.append("isolation")
        return RadicaleIsolationResult(True, True, True, 4, ())

    return RadicaleInstallerDependencies(
        verify_binary=binary,
        provision_runtime=runtime,
        provision_credentials=credentials,
        provision_unit=unit,
        activate_service=activate,
        inspect_health=health,
        verify_isolation=isolation,
    )


def test_install_runs_all_stages_in_safe_order(tmp_path: Path) -> None:
    calls: list[str] = []

    result = install_radicale(
        _request(tmp_path), dependencies=_dependencies(tmp_path, calls)
    )

    assert result.success is True
    assert result.activated is True
    assert result.healthy is True
    assert result.isolation_verified is True
    assert calls == [
        "binary.verify",
        "runtime",
        "credentials",
        "unit",
        "binary.register",
        "activate",
        "health",
        "isolation",
    ]


def test_install_retries_health_within_explicit_readiness_bound(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    dependencies = _dependencies(tmp_path, calls)
    health_results = iter(
        (
            RadicaleHealthResult(
                False,
                False,
                (),
            ),
            RadicaleHealthResult(True, True, ()),
        )
    )
    dependencies = RadicaleInstallerDependencies(
        verify_binary=dependencies.verify_binary,
        provision_runtime=dependencies.provision_runtime,
        provision_credentials=dependencies.provision_credentials,
        provision_unit=dependencies.provision_unit,
        activate_service=dependencies.activate_service,
        inspect_health=lambda _url: next(health_results),
        verify_isolation=dependencies.verify_isolation,
        pause=lambda seconds: calls.append(f"pause:{seconds}"),
    )

    result = install_radicale(
        _request(tmp_path, health_attempts=2),
        dependencies=dependencies,
    )

    assert result.success is True
    assert "pause:0.25" in calls


def test_failed_preverification_prevents_every_mutation(tmp_path: Path) -> None:
    calls: list[str] = []
    dependencies = _dependencies(tmp_path, calls)
    dependencies = RadicaleInstallerDependencies(
        verify_binary=lambda _config, _register: RadicaleBinaryResult(
            False,
            False,
            None,
            (RadicaleBinaryIssue("radicale_digest_mismatch", "Digest mismatch."),),
        ),
        provision_runtime=dependencies.provision_runtime,
        provision_credentials=dependencies.provision_credentials,
        provision_unit=dependencies.provision_unit,
        activate_service=dependencies.activate_service,
        inspect_health=dependencies.inspect_health,
        verify_isolation=dependencies.verify_isolation,
    )

    result = install_radicale(_request(tmp_path), dependencies=dependencies)

    assert result.success is False
    assert result.completed_stages == ()
    assert calls == []


def test_runtime_failure_prevents_credentials_unit_record_and_service(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    dependencies = _dependencies(tmp_path, calls)
    dependencies = RadicaleInstallerDependencies(
        verify_binary=dependencies.verify_binary,
        provision_runtime=lambda _config: RadicaleProvisionResult(
            False,
            (),
            (
                RadicaleProvisionIssue(
                    "radicale_parent_invalid", "Parent unavailable.", tmp_path
                ),
            ),
        ),
        provision_credentials=dependencies.provision_credentials,
        provision_unit=dependencies.provision_unit,
        activate_service=dependencies.activate_service,
        inspect_health=dependencies.inspect_health,
        verify_isolation=dependencies.verify_isolation,
    )

    result = install_radicale(_request(tmp_path), dependencies=dependencies)

    assert result.success is False
    assert result.completed_stages == ("binary.verify",)
    assert calls == ["binary.verify"]


def test_provision_only_run_never_activates_or_probes_network(tmp_path: Path) -> None:
    calls: list[str] = []

    result = install_radicale(
        _request(tmp_path, activate=False),
        dependencies=_dependencies(tmp_path, calls),
    )

    assert result.success is True
    assert result.activated is False
    assert result.healthy is False
    assert calls[-1] == "binary.register"
