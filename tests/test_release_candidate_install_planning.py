"""Tests for release-candidate aggregate plan creation and rendering."""

from pathlib import Path

from lea.installers.release_candidate import (
    InstallerMutationKind,
    InstallerStepId,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    ReleaseCandidateTaskwarriorInputs,
    create_release_candidate_install_plan,
    render_release_candidate_install_plan,
)


def _request(
    tmp_path: Path,
    *,
    enable_telegram: bool,
) -> ReleaseCandidateInstallRequest:
    return ReleaseCandidateInstallRequest(
        mode=ReleaseCandidateInstallMode.FRESH_INSTALL,
        display_timezone="Africa/Gaborone",
        enable_telegram=enable_telegram,
        installation_root=tmp_path / "opt" / "lea",
        configuration_root=tmp_path / "etc" / "lea",
        state_root=tmp_path / "var" / "lib" / "lea",
        log_root=tmp_path / "var" / "log" / "lea",
    )


def _inputs(tmp_path: Path) -> ReleaseCandidateTaskwarriorInputs:
    return ReleaseCandidateTaskwarriorInputs(
        version="3.4.2",
        platform="linux-aarch64",
        source_archive=tmp_path / "task-3.4.2.tar.gz",
        expected_sha256="a" * 64,
        build_directory=tmp_path / "taskwarrior-build",
        build_concurrency=1,
    )


def test_non_telegram_plan_uses_required_step_order(
    tmp_path: Path,
) -> None:
    plan = create_release_candidate_install_plan(
        _request(tmp_path, enable_telegram=False),
        _inputs(tmp_path),
    )

    assert tuple(step.step for step in plan.steps) == (
        InstallerStepId.PREFLIGHT,
        InstallerStepId.SYSTEM_ACCOUNT,
        InstallerStepId.FILESYSTEM,
        InstallerStepId.BASE_CONFIGURATION,
        InstallerStepId.TASKWARRIOR,
        InstallerStepId.HEALTH,
        InstallerStepId.ACCEPTANCE,
    )


def test_telegram_plan_contains_complete_channel_sequence(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, enable_telegram=True)
    plan = create_release_candidate_install_plan(
        request,
        _inputs(tmp_path),
    )

    assert tuple(step.step for step in plan.steps) == (
        InstallerStepId.PREFLIGHT,
        InstallerStepId.SYSTEM_ACCOUNT,
        InstallerStepId.FILESYSTEM,
        InstallerStepId.BASE_CONFIGURATION,
        InstallerStepId.TASKWARRIOR,
        InstallerStepId.TELEGRAM_ONBOARDING,
        InstallerStepId.TELEGRAM_CONFIGURATION,
        InstallerStepId.SYSTEMD_SERVICE,
        InstallerStepId.HEALTH,
        InstallerStepId.ACCEPTANCE,
    )

    telegram_configuration = next(
        step
        for step in plan.steps
        if step.step is InstallerStepId.TELEGRAM_CONFIGURATION
    )
    targets = {mutation.target for mutation in telegram_configuration.mutations}

    assert request.configuration_root / "telegram" / "telegram.toml" in targets
    assert (
        request.configuration_root / "telegram" / "authorised-users.toml"
    ) in targets
    assert (request.configuration_root / "secrets" / "telegram-bot-token") in targets


def test_plan_reuses_component_paths(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, enable_telegram=False)
    inputs = _inputs(tmp_path)
    plan = create_release_candidate_install_plan(
        request,
        inputs,
    )

    filesystem = next(
        step for step in plan.steps if step.step is InstallerStepId.FILESYSTEM
    )
    filesystem_targets = {mutation.target for mutation in filesystem.mutations}
    assert request.configuration_root in filesystem_targets
    assert request.state_root in filesystem_targets
    assert request.log_root in filesystem_targets

    taskwarrior = next(
        step for step in plan.steps if step.step is InstallerStepId.TASKWARRIOR
    )
    install_mutation = next(
        mutation
        for mutation in taskwarrior.mutations
        if mutation.kind is InstallerMutationKind.INSTALL_COMPONENT
    )
    assert install_mutation.target == Path("/opt/lea-tools/taskwarrior/3.4.2/bin/task")
    assert str(inputs.source_archive) in install_mutation.summary


def test_rendering_is_stable_and_contains_no_secret_value(
    tmp_path: Path,
) -> None:
    plan = create_release_candidate_install_plan(
        _request(tmp_path, enable_telegram=True),
        _inputs(tmp_path),
    )

    first = render_release_candidate_install_plan(plan)
    second = render_release_candidate_install_plan(plan)

    assert first == second
    assert first.endswith("\n")
    assert "Mode: fresh-install" in first
    assert "Display timezone: Africa/Gaborone" in first
    assert "Telegram: enabled" in first
    assert "telegram-bot-token" in first
    assert "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG" not in first


def test_read_only_steps_report_no_mutation(
    tmp_path: Path,
) -> None:
    plan = create_release_candidate_install_plan(
        _request(tmp_path, enable_telegram=False),
        _inputs(tmp_path),
    )
    rendered = render_release_candidate_install_plan(plan)

    assert "1. preflight" in rendered
    assert "6. health" in rendered
    assert "7. acceptance" in rendered
    assert rendered.count("   - No mutation.") == 3
