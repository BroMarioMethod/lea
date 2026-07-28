"""Tests for release-candidate base configuration generation."""

from datetime import UTC, datetime
from pathlib import Path

from lea.installers.release_candidate import (
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    create_base_configuration_plan,
    create_installation_record,
    install_base_configuration,
    read_installation_record,
    render_installation_record,
)
from lea.runtime import ConfigurationIssue, ConfigurationResult, load_runtime_config


def _request(tmp_path: Path) -> ReleaseCandidateInstallRequest:
    """Return one isolated release-candidate request."""
    return ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=False,
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
    )


def _failed_configuration(path: Path) -> ConfigurationResult:
    return ConfigurationResult(
        success=False,
        config=None,
        issues=(
            ConfigurationIssue(
                code="invalid",
                message="Invalid generated configuration.",
                source_path=path,
            ),
        ),
    )


def test_base_plan_includes_telegram_token_file_when_enabled(
    tmp_path: Path,
) -> None:
    """Telegram-enabled installs must create the final runtime configuration."""
    request = ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=True,
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
    )

    plan = create_base_configuration_plan(request)

    assert (
        str(request.configuration_root / "secrets" / "telegram-bot-token")
        in plan.rendered_configuration
    )


def test_base_plan_omits_telegram_token_file_when_disabled(
    tmp_path: Path,
) -> None:
    """Non-Telegram installs must not reference a Telegram secret."""
    request = ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=False,
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
    )

    plan = create_base_configuration_plan(request)

    assert "telegram-bot-token" not in plan.rendered_configuration


def test_plan_uses_canonical_paths_and_metadata(tmp_path: Path) -> None:
    """Base configuration plans should use canonical managed paths."""
    request = _request(tmp_path)
    plan = create_base_configuration_plan(request)

    assert plan.configuration_file == request.configuration_root / "lea.toml"
    assert plan.installation_record == (
        request.state_root / "install" / "release-candidate.json"
    )
    assert plan.owner == "root"
    assert plan.group == "lea"
    assert plan.mode == 0o640


def test_rendered_configuration_loads_successfully(tmp_path: Path) -> None:
    """Generated TOML should pass the existing runtime loader."""
    request = _request(tmp_path)
    plan = create_base_configuration_plan(request)
    plan.configuration_file.parent.mkdir(parents=True)
    plan.configuration_file.write_text(
        plan.rendered_configuration,
        encoding="utf-8",
    )

    result = load_runtime_config(plan.configuration_file)

    assert result.success is True
    assert result.config is not None
    assert result.config.display_timezone == "Africa/Gaborone"


def test_installation_record_is_deterministic(tmp_path: Path) -> None:
    """Installation records should render stable sorted JSON."""
    record = create_installation_record(
        request=_request(tmp_path),
        lea_version="0.1.1",
        clock=lambda: datetime(2026, 7, 24, 12, 30, tzinfo=UTC),
    )

    rendered = render_installation_record(record)

    assert '"lea_version": "0.1.1"' in rendered
    assert '"installed_at_utc": "2026-07-24T12:30:00+00:00"' in rendered
    assert rendered.endswith("\n")


def test_installation_record_reader_reuses_real_contract(tmp_path: Path) -> None:
    record = create_installation_record(
        request=_request(tmp_path),
        lea_version="0.1.1",
        clock=lambda: datetime(2026, 7, 24, 12, 30, tzinfo=UTC),
    )
    path = (tmp_path / "record.json").resolve()
    path.write_text(render_installation_record(record), encoding="utf-8")

    assert read_installation_record(path) == record

    path.write_text('{"schema_version": 1}\n', encoding="utf-8")
    assert read_installation_record(path) is None


def test_install_is_atomic_and_idempotent(tmp_path: Path) -> None:
    """Repeated installation should avoid unnecessary rewrites."""
    request = _request(tmp_path)
    plan = create_base_configuration_plan(request)
    record = create_installation_record(
        request=request,
        lea_version="0.1.1",
        clock=lambda: datetime(2026, 7, 24, 12, 30, tzinfo=UTC),
    )

    first = install_base_configuration(plan, record)
    second = install_base_configuration(plan, record)

    assert first.success is True
    assert first.configuration_changed is True
    assert first.record_changed is True
    assert second.success is True
    assert second.configuration_changed is False
    assert second.record_changed is False
    assert second.backups_created == ()


def test_rerun_preserves_initial_installation_timestamp(tmp_path: Path) -> None:
    request = _request(tmp_path)
    plan = create_base_configuration_plan(request)
    first_record = create_installation_record(
        request=request,
        lea_version="0.1.1",
        clock=lambda: datetime(2026, 7, 24, 12, 30, tzinfo=UTC),
    )
    later_record = create_installation_record(
        request=request,
        lea_version="0.1.1",
        clock=lambda: datetime(2026, 7, 24, 13, 30, tzinfo=UTC),
    )

    first = install_base_configuration(plan, first_record)
    second = install_base_configuration(plan, later_record)
    installed = read_installation_record(plan.installation_record)

    assert first.success is True
    assert second.success is True
    assert second.record_changed is False
    assert installed is not None
    assert installed.installed_at_utc == first_record.installed_at_utc


def test_install_applies_planned_ownership(tmp_path: Path) -> None:
    request = _request(tmp_path)
    plan = create_base_configuration_plan(request)
    ownership: list[tuple[Path, str, str]] = []

    result = install_base_configuration(
        plan,
        create_installation_record(
            request=request,
            lea_version="0.1.1",
        ),
        apply_ownership=lambda path, owner, group: ownership.append(
            (path, owner, group)
        ),
    )

    assert result.success is True
    assert ownership == [
        (plan.configuration_file, "root", "lea"),
        (plan.installation_record, "root", "lea"),
    ]


def test_changed_files_are_backed_up(tmp_path: Path) -> None:
    """Replacing managed files should preserve their previous contents."""
    request = _request(tmp_path)
    plan = create_base_configuration_plan(request)
    plan.configuration_file.parent.mkdir(parents=True)
    plan.installation_record.parent.mkdir(parents=True)
    plan.configuration_file.write_text("old configuration\n", encoding="utf-8")
    plan.installation_record.write_text("{}\n", encoding="utf-8")

    record = create_installation_record(
        request=request,
        lea_version="0.1.1",
        clock=lambda: datetime(2026, 7, 24, 12, 30, tzinfo=UTC),
    )

    result = install_base_configuration(plan, record)

    assert result.success is True
    assert len(result.backups_created) == 2
    assert all(
        (path.stat().st_mode & 0o777) == 0o640 for path in result.backups_created
    )
    assert any(
        path.read_text(encoding="utf-8") == "old configuration\n"
        for path in result.backups_created
    )
    assert any(
        path.read_text(encoding="utf-8") == "{}\n" for path in result.backups_created
    )


def test_validation_failure_restores_previous_files(tmp_path: Path) -> None:
    request = _request(tmp_path)
    plan = create_base_configuration_plan(request)
    plan.configuration_file.parent.mkdir(parents=True)
    plan.installation_record.parent.mkdir(parents=True)
    plan.configuration_file.write_text("old configuration\n", encoding="utf-8")
    plan.installation_record.write_text("old record\n", encoding="utf-8")

    result = install_base_configuration(
        plan,
        create_installation_record(
            request=request,
            lea_version="0.1.1",
        ),
        runtime_loader=_failed_configuration,
    )

    assert result.success is False
    assert result.configuration_changed is False
    assert result.record_changed is False
    assert plan.configuration_file.read_text(encoding="utf-8") == (
        "old configuration\n"
    )
    assert plan.installation_record.read_text(encoding="utf-8") == "old record\n"


def test_unsafe_symlink_is_rejected(tmp_path: Path) -> None:
    """Managed configuration paths must not follow symlinks."""
    request = _request(tmp_path)
    plan = create_base_configuration_plan(request)
    plan.configuration_file.parent.mkdir(parents=True)
    target = tmp_path / "outside.toml"
    target.write_text("outside\n", encoding="utf-8")
    plan.configuration_file.symlink_to(target)

    record = create_installation_record(
        request=request,
        lea_version="0.1.1",
    )

    result = install_base_configuration(plan, record)

    assert result.success is False
    assert target.read_text(encoding="utf-8") == "outside\n"
