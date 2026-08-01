"""Tests for deterministic release-candidate orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from lea.installers.calendar.contracts import (
    CalendarToolchainInstallMode,
)
from lea.installers.calendar.records import (
    CalendarToolchainInstallationRecord,
)
from lea.installers.release_candidate import (
    BaseConfigurationResult,
    HostFacts,
    HostPreflightCheck,
    HostPreflightCheckState,
    HostPreflightResult,
    InstallerInteractionKind,
    InstallerIssue,
    InstallerIssueCode,
    InstallerProgressReporter,
    InstallerStepId,
    InstallerStepState,
    PostInstallHealthResult,
    ReleaseCandidateAcceptanceResult,
    ReleaseCandidateCalendarInputs,
    ReleaseCandidateCalendarResult,
    ReleaseCandidateInstallMode,
    ReleaseCandidateInstallRequest,
    ReleaseCandidateOrchestrationDependencies,
    ReleaseCandidateOrchestrationRequest,
    ReleaseCandidateOrchestrationState,
    ReleaseCandidateTaskwarriorInputs,
    ReleaseCandidateTaskwarriorResult,
    SystemProvisioningResult,
    TelegramBotIdentity,
    TelegramConfigurationResult,
    TelegramOnboardingConfirmation,
    TelegramOnboardingIdentity,
    TelegramOnboardingRole,
    TelegramSystemdServiceResult,
    create_calendar_toolchain_installation_plan,
    create_release_candidate_install_plan,
    create_release_candidate_orchestration_dependencies,
    run_release_candidate_orchestration,
)
from lea.installers.taskwarrior import (
    TaskwarriorInstallationRecord,
    TaskwarriorInstallMode,
)


def _installation(
    tmp_path: Path,
    *,
    enable_telegram: bool = False,
    mode: ReleaseCandidateInstallMode = (ReleaseCandidateInstallMode.FRESH_INSTALL),
    non_interactive: bool = False,
) -> ReleaseCandidateInstallRequest:
    return ReleaseCandidateInstallRequest(
        mode=mode,
        display_timezone="Africa/Gaborone",
        enable_telegram=enable_telegram,
        non_interactive=non_interactive,
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
    )


def _request(
    tmp_path: Path,
    *,
    enable_telegram: bool = False,
    mode: ReleaseCandidateInstallMode = (ReleaseCandidateInstallMode.FRESH_INSTALL),
    plan_approved: bool = True,
    replacement_approved: bool = False,
    non_interactive: bool = False,
) -> ReleaseCandidateOrchestrationRequest:
    return ReleaseCandidateOrchestrationRequest(
        installation=_installation(
            tmp_path,
            enable_telegram=enable_telegram,
            mode=mode,
            non_interactive=non_interactive,
        ),
        taskwarrior=_inputs(tmp_path),
        lea_version="0.1.0",
        plan_approved=plan_approved,
        replacement_approved=replacement_approved,
    )


def _facts() -> HostFacts:
    return HostFacts(
        operating_system_id="debian",
        operating_system_version="13",
        architecture="aarch64",
        python_version=(3, 13, 5),
        systemd_available=True,
        dietpi_available=True,
        required_executables=(),
        missing_executables=(),
        libuuid_available=True,
        service_user_exists=False,
        service_group_exists=False,
        managed_paths_present=(),
    )


def _record(tmp_path: Path) -> TaskwarriorInstallationRecord:
    return TaskwarriorInstallationRecord(
        schema_version=1,
        component="taskwarrior",
        version="3.4.2",
        mode=TaskwarriorInstallMode.SOURCE_BUILD.value,
        platform="linux-aarch64",
        executable=Path("/opt/lea-tools/taskwarrior/3.4.2/bin/task"),
        sha256="b" * 64,
        taskrc=tmp_path / "etc" / "lea" / "taskwarrior" / "taskrc",
        home=tmp_path / "var" / "lib" / "lea" / "taskwarrior" / "home",
        data=tmp_path / "var" / "lib" / "lea" / "taskwarrior" / "data",
        smoke_test="passed",
        installed_at=datetime(2026, 7, 25, tzinfo=UTC),
    )


def _confirmation(
    *,
    confirmed: bool = True,
) -> TelegramOnboardingConfirmation:
    return TelegramOnboardingConfirmation(
        bot=TelegramBotIdentity(
            bot_id="987654321",
            username="lea_test_bot",
            display_name="LEA Test Bot",
        ),
        identity=TelegramOnboardingIdentity(
            update_id=42,
            user_id="123456789",
            chat_id="123456789",
            username="marius_example",
            display_name="Marius Example",
        ),
        confirmed=confirmed,
        role=TelegramOnboardingRole.OWNER if confirmed else None,
    )


def _dependencies(
    tmp_path: Path,
    calls: list[str],
) -> ReleaseCandidateOrchestrationDependencies:
    record = _record(tmp_path)

    def preflight(
        _request: ReleaseCandidateInstallRequest,
    ) -> HostPreflightResult:
        calls.append("preflight")
        return HostPreflightResult(
            supported=True,
            facts=_facts(),
            checks=(),
            issues=(),
        )

    def provisioning(
        _request: ReleaseCandidateInstallRequest,
    ) -> SystemProvisioningResult:
        calls.append("provisioning")
        return SystemProvisioningResult(
            success=True,
            user_created=True,
            group_created=True,
            directories_changed=(tmp_path / "var" / "lib" / "lea",),
            files_changed=(),
            issues=(),
        )

    def base(
        _request: ReleaseCandidateInstallRequest,
        _version: str,
    ) -> BaseConfigurationResult:
        calls.append("base")
        return BaseConfigurationResult(
            success=True,
            configuration_changed=True,
            record_changed=True,
            backups_created=(),
            issues=(),
        )

    def taskwarrior(
        _request: ReleaseCandidateInstallRequest,
        _inputs: ReleaseCandidateTaskwarriorInputs,
        _progress: InstallerProgressReporter,
    ) -> ReleaseCandidateTaskwarriorResult:
        calls.append("taskwarrior")
        return ReleaseCandidateTaskwarriorResult(
            success=True,
            already_installed=False,
            executable=record.executable,
            record=record,
            issues=(),
        )

    def onboarding(
        _token: str,
        _confirmation: TelegramOnboardingConfirmation,
    ) -> tuple[InstallerIssue, ...]:
        calls.append("onboarding")
        return ()

    def telegram_configuration(
        _request: ReleaseCandidateInstallRequest,
        _confirmation: TelegramOnboardingConfirmation,
        _token: str,
        _replacement_approved: bool,
    ) -> TelegramConfigurationResult:
        calls.append("telegram-configuration")
        return TelegramConfigurationResult(
            success=True,
            changed_files=(tmp_path / "etc" / "lea" / "telegram.toml",),
            backups_created=(),
            issues=(),
        )

    def systemd(
        _request: ReleaseCandidateInstallRequest,
        _replacement_approved: bool,
    ) -> TelegramSystemdServiceResult:
        calls.append("systemd")
        return TelegramSystemdServiceResult(
            success=True,
            unit_changed=True,
            backup_created=None,
            enabled=True,
            active=True,
            commands=(),
            issues=(),
        )

    def health(
        _request: ReleaseCandidateInstallRequest,
    ) -> PostInstallHealthResult:
        calls.append("health")
        return PostInstallHealthResult(
            healthy=True,
            checks=(),
            issues=(),
        )

    def acceptance(
        _request: ReleaseCandidateInstallRequest,
        _health: PostInstallHealthResult,
    ) -> ReleaseCandidateAcceptanceResult:
        calls.append("acceptance")
        return ReleaseCandidateAcceptanceResult(
            accepted=True,
            checks=(),
            summary="LEA release-candidate acceptance: PASSED\n",
            issues=(),
        )

    return ReleaseCandidateOrchestrationDependencies(
        preflight=preflight,
        provisioning=provisioning,
        base_configuration=base,
        taskwarrior=taskwarrior,
        telegram_onboarding=onboarding,
        telegram_configuration=telegram_configuration,
        systemd_service=systemd,
        health=health,
        acceptance=acceptance,
    )


def test_default_dependencies_are_constructible() -> None:
    dependencies = create_release_candidate_orchestration_dependencies()

    assert callable(dependencies.preflight)
    assert callable(dependencies.acceptance)


def test_unapproved_plan_waits_before_preflight(tmp_path: Path) -> None:
    calls: list[str] = []

    result = run_release_candidate_orchestration(
        _request(
            tmp_path,
            plan_approved=False,
        ),
        dependencies=_dependencies(tmp_path, calls),
    )

    assert result.state is (ReleaseCandidateOrchestrationState.WAITING_FOR_INTERACTION)
    assert result.pending_interaction is not None
    assert result.pending_interaction.kind is InstallerInteractionKind.PLAN_APPROVAL
    assert calls == []


def test_preflight_failure_stops_before_mutation(tmp_path: Path) -> None:
    calls: list[str] = []
    dependencies = _dependencies(tmp_path, calls)
    issue = InstallerIssue(
        code=InstallerIssueCode.PREFLIGHT_FAILED,
        message="Unsupported host.",
        step=InstallerStepId.PREFLIGHT,
    )
    dependencies = replace(
        dependencies,
        preflight=lambda _request: HostPreflightResult(
            supported=False,
            facts=_facts(),
            checks=(
                HostPreflightCheck(
                    name="architecture",
                    state=HostPreflightCheckState.FAILED,
                    message="Unsupported host.",
                    field="architecture",
                ),
            ),
            issues=(issue,),
        ),
    )

    result = run_release_candidate_orchestration(
        _request(tmp_path),
        dependencies=dependencies,
    )

    assert result.state is ReleaseCandidateOrchestrationState.FAILED
    assert result.step_results[-1].step is InstallerStepId.PREFLIGHT
    assert result.issues == (issue,)
    assert calls == []


def test_repair_waits_for_replacement_approval_after_preflight(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    dependencies = _dependencies(tmp_path, calls)

    result = run_release_candidate_orchestration(
        _request(
            tmp_path,
            mode=ReleaseCandidateInstallMode.REPAIR,
            replacement_approved=False,
        ),
        dependencies=dependencies,
    )

    assert result.state is (ReleaseCandidateOrchestrationState.WAITING_FOR_INTERACTION)
    assert result.pending_interaction is not None
    assert (
        result.pending_interaction.kind is InstallerInteractionKind.REPLACEMENT_APPROVAL
    )
    assert calls == ["preflight"]


def test_telegram_disabled_run_omits_telegram_steps(tmp_path: Path) -> None:
    calls: list[str] = []

    result = run_release_candidate_orchestration(
        _request(tmp_path),
        dependencies=_dependencies(tmp_path, calls),
    )

    assert result.state is ReleaseCandidateOrchestrationState.SUCCEEDED
    assert calls == [
        "preflight",
        "provisioning",
        "base",
        "taskwarrior",
        "health",
        "acceptance",
    ]
    assert not {
        InstallerStepId.TELEGRAM_ONBOARDING,
        InstallerStepId.TELEGRAM_CONFIGURATION,
        InstallerStepId.SYSTEMD_SERVICE,
    } & {step.step for step in result.step_results}


def test_telegram_run_waits_for_missing_secret(tmp_path: Path) -> None:
    calls: list[str] = []

    result = run_release_candidate_orchestration(
        _request(
            tmp_path,
            enable_telegram=True,
        ),
        dependencies=_dependencies(tmp_path, calls),
    )

    assert result.state is (ReleaseCandidateOrchestrationState.WAITING_FOR_INTERACTION)
    assert result.pending_interaction is not None
    assert result.pending_interaction.kind is InstallerInteractionKind.TELEGRAM_TOKEN
    assert result.pending_interaction.secret is True
    assert calls == [
        "preflight",
        "provisioning",
        "base",
        "taskwarrior",
    ]


def test_non_interactive_missing_secret_fails(tmp_path: Path) -> None:
    calls: list[str] = []

    result = run_release_candidate_orchestration(
        _request(
            tmp_path,
            enable_telegram=True,
            non_interactive=True,
        ),
        dependencies=_dependencies(tmp_path, calls),
    )

    assert result.state is ReleaseCandidateOrchestrationState.FAILED
    assert result.step_results[-1].step is InstallerStepId.TELEGRAM_ONBOARDING
    assert result.issues[0].code is InstallerIssueCode.INCOMPLETE


def test_rejected_telegram_confirmation_cancels(tmp_path: Path) -> None:
    calls: list[str] = []

    result = run_release_candidate_orchestration(
        _request(
            tmp_path,
            enable_telegram=True,
        ),
        telegram_token="123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG",
        telegram_confirmation=_confirmation(confirmed=False),
        dependencies=_dependencies(tmp_path, calls),
    )

    assert result.state is ReleaseCandidateOrchestrationState.CANCELLED
    assert "onboarding" not in calls


def test_full_telegram_sequence_succeeds(tmp_path: Path) -> None:
    calls: list[str] = []

    result = run_release_candidate_orchestration(
        _request(
            tmp_path,
            enable_telegram=True,
        ),
        telegram_token="123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG",
        telegram_confirmation=_confirmation(),
        dependencies=_dependencies(tmp_path, calls),
    )

    assert result.state is ReleaseCandidateOrchestrationState.SUCCEEDED
    assert calls == [
        "preflight",
        "provisioning",
        "base",
        "taskwarrior",
        "onboarding",
        "telegram-configuration",
        "systemd",
        "health",
        "acceptance",
    ]


def test_health_failure_stops_before_acceptance(tmp_path: Path) -> None:
    calls: list[str] = []
    dependencies = _dependencies(tmp_path, calls)
    issue = InstallerIssue(
        code=InstallerIssueCode.STEP_FAILED,
        message="Health failed.",
        step=InstallerStepId.HEALTH,
    )
    dependencies = replace(
        dependencies,
        health=lambda _request: PostInstallHealthResult(
            healthy=False,
            checks=(),
            issues=(issue,),
        ),
    )

    result = run_release_candidate_orchestration(
        _request(tmp_path),
        dependencies=dependencies,
    )

    assert result.state is ReleaseCandidateOrchestrationState.FAILED
    assert result.step_results[-1].step is InstallerStepId.HEALTH
    assert result.issues == (issue,)
    assert "acceptance" not in calls


def test_boundary_exception_is_redacted_and_stops(tmp_path: Path) -> None:
    calls: list[str] = []
    dependencies = _dependencies(tmp_path, calls)

    def fail(
        _request: ReleaseCandidateInstallRequest,
        _version: str,
    ) -> BaseConfigurationResult:
        raise RuntimeError("sensitive boundary detail")

    dependencies = replace(
        dependencies,
        base_configuration=fail,
    )

    result = run_release_candidate_orchestration(
        _request(tmp_path),
        dependencies=dependencies,
    )

    assert result.state is ReleaseCandidateOrchestrationState.FAILED
    assert result.step_results[-1].step is InstallerStepId.BASE_CONFIGURATION
    assert "sensitive" not in result.step_results[-1].message
    assert all("sensitive" not in issue.message for issue in result.issues)


def test_cancellation_remains_separate_from_failure(tmp_path: Path) -> None:
    calls: list[str] = []
    decisions = iter((False, True))

    result = run_release_candidate_orchestration(
        _request(tmp_path),
        dependencies=_dependencies(tmp_path, calls),
        cancelled=lambda: next(decisions),
    )

    assert result.state is ReleaseCandidateOrchestrationState.CANCELLED
    assert result.issues == ()
    assert [step.step for step in result.step_results] == [
        InstallerStepId.PREFLIGHT,
    ]
    assert calls == ["preflight"]


def test_failed_step_preserves_structured_issues(tmp_path: Path) -> None:
    calls: list[str] = []
    dependencies = _dependencies(tmp_path, calls)
    issue = InstallerIssue(
        code=InstallerIssueCode.STEP_FAILED,
        message="Taskwarrior component issue.",
        step=InstallerStepId.TASKWARRIOR,
        path=Path("/opt/lea-tools/taskwarrior/3.4.2/bin/task"),
    )
    dependencies = replace(
        dependencies,
        taskwarrior=lambda _request, _inputs, _progress: (
            ReleaseCandidateTaskwarriorResult(
                success=False,
                already_installed=False,
                executable=None,
                record=None,
                issues=(issue,),
            )
        ),
    )

    result = run_release_candidate_orchestration(
        _request(tmp_path),
        dependencies=dependencies,
    )

    assert result.state is ReleaseCandidateOrchestrationState.FAILED
    assert result.issues == (issue,)
    assert result.step_results[-1].state is InstallerStepState.FAILED


class RecordingProgressReporter:
    """Record orchestration progress events for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []

    def step_started(
        self,
        step: InstallerStepId,
        message: str,
    ) -> None:
        self.events.append(("started", step.value, message))

    def step_completed(
        self,
        step: InstallerStepId,
        message: str,
    ) -> None:
        self.events.append(("completed", step.value, message))

    def heartbeat(
        self,
        message: str,
        *,
        elapsed_seconds: float,
    ) -> None:
        self.events.append(("heartbeat", str(elapsed_seconds), message))

    def detail(
        self,
        message: str,
    ) -> None:
        self.events.append(("detail", "", message))

    def output(
        self,
        text: str,
    ) -> None:
        self.events.append(("output", "", text))


def test_successful_orchestration_reports_step_progress(
    tmp_path: Path,
) -> None:
    """Successful orchestration should report starts and completions."""
    calls: list[str] = []
    progress = RecordingProgressReporter()

    result = run_release_candidate_orchestration(
        _request(tmp_path),
        dependencies=_dependencies(tmp_path, calls),
        progress=progress,
    )

    assert result.state is ReleaseCandidateOrchestrationState.SUCCEEDED

    started = [step for event, step, _message in progress.events if event == "started"]
    completed = [
        step for event, step, _message in progress.events if event == "completed"
    ]

    assert started == [
        "preflight",
        "filesystem",
        "base-configuration",
        "taskwarrior",
        "health",
        "acceptance",
    ]
    assert completed == [
        "preflight",
        "system-account",
        "filesystem",
        "base-configuration",
        "taskwarrior",
        "health",
        "acceptance",
    ]


def _calendar_inputs(tmp_path: Path) -> ReleaseCandidateCalendarInputs:
    """Return pinned calendar inputs for orchestration tests."""
    lock = tmp_path / "calendar-requirements.txt"
    lock.write_text(
        "khal==0.11.4\nvdirsyncer==0.19.3\n",
        encoding="utf-8",
    )
    uv = tmp_path / "bin" / "uv"
    uv.parent.mkdir(exist_ok=True)
    uv.write_text("#!/bin/sh\n", encoding="utf-8")
    python = tmp_path / "bin" / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    return ReleaseCandidateCalendarInputs(
        toolchain_version="1.0.0",
        platform="linux-aarch64",
        requirements_lock=lock,
        expected_lock_sha256="a" * 64,
        uv_executable=uv,
        python_executable=python,
        package_index_url="https://pypi.org/simple",
    )


def test_calendar_plan_is_inserted_after_taskwarrior(
    tmp_path: Path,
) -> None:
    """The approved plan should show calendar before optional Telegram."""
    installation = _installation(
        tmp_path,
        enable_telegram=True,
    )
    plan = create_release_candidate_install_plan(
        installation,
        _inputs(tmp_path),
        _calendar_inputs(tmp_path),
    )
    steps = tuple(item.step for item in plan.steps)

    assert steps.index(InstallerStepId.TASKWARRIOR) < steps.index(
        InstallerStepId.CALENDAR_TOOLCHAIN
    )
    assert steps.index(InstallerStepId.CALENDAR_TOOLCHAIN) < steps.index(
        InstallerStepId.TELEGRAM_ONBOARDING
    )
    calendar_step = next(
        item for item in plan.steps if item.step is InstallerStepId.CALENDAR_TOOLCHAIN
    )
    assert calendar_step.mutations
    assert any(
        mutation.target == Path("/opt/lea-tools/calendar/1.0.0/.venv/bin/khal")
        for mutation in calendar_step.mutations
    )


def test_selected_calendar_runs_between_taskwarrior_and_telegram(
    tmp_path: Path,
) -> None:
    """Selected calendar provisioning should precede Telegram onboarding."""
    calls: list[str] = []
    dependencies = _dependencies(tmp_path, calls)

    def calendar(
        request: ReleaseCandidateInstallRequest,
        inputs: ReleaseCandidateCalendarInputs,
    ) -> ReleaseCandidateCalendarResult:
        calls.append("calendar")
        plan = create_calendar_toolchain_installation_plan(request, inputs)
        return ReleaseCandidateCalendarResult(
            success=True,
            already_installed=False,
            khal_executable=plan.expected_khal_executable,
            vdirsyncer_executable=plan.expected_vdirsyncer_executable,
            record=CalendarToolchainInstallationRecord(
                schema_version=2,
                component="calendar-toolchain",
                toolchain_version=inputs.toolchain_version,
                installation_mode=(CalendarToolchainInstallMode.VERIFIED_NETWORK),
                platform=inputs.platform,
                python_version="3.13.5",
                khal_version=inputs.khal_version,
                vdirsyncer_version=inputs.vdirsyncer_version,
                khal_executable=plan.expected_khal_executable,
                vdirsyncer_executable=(plan.expected_vdirsyncer_executable),
                lock_or_manifest_sha256=inputs.expected_lock_sha256,
                khal_executable_sha256=None,
                vdirsyncer_executable_sha256=None,
                smoke_test="passed",
                installed_at=datetime(
                    2026,
                    8,
                    1,
                    12,
                    0,
                    tzinfo=UTC,
                ),
            ),
            issues=(),
        )

    request = replace(
        _request(
            tmp_path,
            enable_telegram=True,
        ),
        calendar=_calendar_inputs(tmp_path),
    )
    result = run_release_candidate_orchestration(
        request,
        telegram_token="123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG",
        telegram_confirmation=_confirmation(),
        dependencies=replace(dependencies, calendar=calendar),
    )

    assert result.state is ReleaseCandidateOrchestrationState.SUCCEEDED
    assert calls.index("taskwarrior") < calls.index("calendar")
    assert calls.index("calendar") < calls.index("onboarding")
    assert InstallerStepId.CALENDAR_TOOLCHAIN in {
        step.step for step in result.step_results
    }


def test_calendar_failure_stops_before_telegram(
    tmp_path: Path,
) -> None:
    """A structured calendar failure should stop before onboarding."""
    calls: list[str] = []
    dependencies = _dependencies(tmp_path, calls)
    issue = InstallerIssue(
        code=InstallerIssueCode.STEP_FAILED,
        message="Calendar installation failed.",
        step=InstallerStepId.CALENDAR_TOOLCHAIN,
        field="requirements_lock",
    )

    def calendar(
        request: ReleaseCandidateInstallRequest,
        inputs: ReleaseCandidateCalendarInputs,
    ) -> ReleaseCandidateCalendarResult:
        del request, inputs
        calls.append("calendar")
        return ReleaseCandidateCalendarResult(
            success=False,
            already_installed=False,
            khal_executable=None,
            vdirsyncer_executable=None,
            record=None,
            issues=(issue,),
        )

    request = replace(
        _request(
            tmp_path,
            enable_telegram=True,
        ),
        calendar=_calendar_inputs(tmp_path),
    )
    result = run_release_candidate_orchestration(
        request,
        telegram_token="123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFG",
        telegram_confirmation=_confirmation(),
        dependencies=replace(dependencies, calendar=calendar),
    )

    assert result.state is ReleaseCandidateOrchestrationState.FAILED
    assert result.step_results[-1].step is (InstallerStepId.CALENDAR_TOOLCHAIN)
    assert result.issues == (issue,)
    assert "onboarding" not in calls


def test_selected_calendar_requires_runner(
    tmp_path: Path,
) -> None:
    """A selected calendar phase should fail closed without its runner."""
    calls: list[str] = []
    request = replace(
        _request(tmp_path),
        calendar=_calendar_inputs(tmp_path),
    )

    result = run_release_candidate_orchestration(
        request,
        dependencies=_dependencies(tmp_path, calls),
    )

    assert result.state is ReleaseCandidateOrchestrationState.FAILED
    assert result.step_results[-1].step is (InstallerStepId.CALENDAR_TOOLCHAIN)
    assert result.issues[0].field == "calendar"
