"""Release-candidate acceptance harness orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from lea.installers.release_candidate.acceptance_record import (
    AcceptanceRecordWriteResult,
    ReleaseCandidateAcceptanceRecord,
    create_release_candidate_acceptance_record,
    write_release_candidate_acceptance_record,
)
from lea.installers.release_candidate.contracts import (
    InstallerIssue,
    InstallerIssueCode,
    InstallerStepId,
)
from lea.installers.release_candidate.post_install import (
    PostInstallHealthPlan,
    PostInstallHealthResult,
    ReleaseCandidateAcceptanceResult,
    run_post_install_health,
    run_release_candidate_acceptance,
)

AcceptanceClock = Callable[[], datetime]


class AcceptanceHealthRunner(Protocol):
    """Callable boundary for installed-system health checks."""

    def __call__(
        self,
        __plan: PostInstallHealthPlan,
    ) -> PostInstallHealthResult:
        """Run read-only post-install health checks."""
        ...


class FunctionalAcceptanceRunner(Protocol):
    """Callable boundary for functional acceptance checks."""

    def __call__(
        self,
        __plan: PostInstallHealthPlan,
        __health: PostInstallHealthResult,
    ) -> ReleaseCandidateAcceptanceResult:
        """Run release-candidate functional acceptance."""
        ...


class AcceptanceRecordFactory(Protocol):
    """Callable boundary for acceptance-record construction."""

    def __call__(
        self,
        plan: PostInstallHealthPlan,
        health: PostInstallHealthResult,
        acceptance: ReleaseCandidateAcceptanceResult,
        *,
        clock: AcceptanceClock,
    ) -> ReleaseCandidateAcceptanceRecord:
        """Create one release-candidate acceptance record."""
        ...


class AcceptanceRecordWriter(Protocol):
    """Callable boundary for acceptance-record persistence."""

    def __call__(
        self,
        __record: ReleaseCandidateAcceptanceRecord,
        __destination: Path,
        *,
        mode: int,
    ) -> AcceptanceRecordWriteResult:
        """Persist one acceptance record."""
        ...


@dataclass(frozen=True, slots=True)
class ReleaseCandidateAcceptanceHarnessPlan:
    """Immutable plan for one acceptance-harness execution."""

    health: PostInstallHealthPlan
    record_file: Path
    record_mode: int = 0o640

    def __post_init__(self) -> None:
        """Validate one acceptance-harness plan."""
        if not isinstance(self.health, PostInstallHealthPlan):
            raise TypeError("health must be a PostInstallHealthPlan value.")

        _validate_absolute_path(
            self.record_file,
            field_name="record_file",
        )

        if (
            isinstance(self.record_mode, bool)
            or not isinstance(self.record_mode, int)
            or self.record_mode < 0
            or self.record_mode > 0o7777
        ):
            raise ValueError("record_mode must be a valid Unix permission mode.")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateAcceptanceHarnessDependencies:
    """Injected acceptance-harness execution boundaries."""

    run_health: AcceptanceHealthRunner = run_post_install_health
    run_acceptance: FunctionalAcceptanceRunner = run_release_candidate_acceptance
    create_record: AcceptanceRecordFactory = create_release_candidate_acceptance_record
    write_record: AcceptanceRecordWriter = write_release_candidate_acceptance_record


@dataclass(frozen=True, slots=True)
class ReleaseCandidateAcceptanceHarnessResult:
    """Result of one acceptance-harness execution."""

    success: bool
    accepted: bool
    health: PostInstallHealthResult | None
    acceptance: ReleaseCandidateAcceptanceResult | None
    record: ReleaseCandidateAcceptanceRecord | None
    record_write: AcceptanceRecordWriteResult | None
    issues: tuple[InstallerIssue, ...]

    def __post_init__(self) -> None:
        """Validate harness-result consistency."""
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")
        if not isinstance(self.accepted, bool):
            raise TypeError("accepted must be a boolean.")

        if self.success:
            if self.issues:
                raise ValueError("A successful harness result must not contain issues.")

            if (
                self.health is None
                or self.acceptance is None
                or self.record is None
                or self.record_write is None
            ):
                raise ValueError(
                    "A successful harness result requires all result values."
                )

            if not self.record_write.success:
                raise ValueError(
                    "A successful harness result requires a persisted record."
                )

            if self.accepted != self.record.accepted:
                raise ValueError(
                    "The harness and acceptance-record outcomes must match."
                )

        elif not self.issues:
            raise ValueError("A failed harness result must contain at least one issue.")

        if self.accepted:
            if self.health is None or not self.health.healthy:
                raise ValueError(
                    "An accepted harness result requires healthy installation."
                )
            if self.acceptance is None or not self.acceptance.accepted:
                raise ValueError("An accepted harness result requires accepted checks.")


def create_release_candidate_acceptance_harness_plan(
    health: PostInstallHealthPlan,
    *,
    record_file: Path | None = None,
    record_mode: int = 0o640,
) -> ReleaseCandidateAcceptanceHarnessPlan:
    """Create the canonical acceptance-harness plan."""
    if not isinstance(health, PostInstallHealthPlan):
        raise TypeError("health must be a PostInstallHealthPlan value.")

    destination = (
        record_file
        if record_file is not None
        else health.acceptance_work_directory.parent / "release-candidate.json"
    )

    return ReleaseCandidateAcceptanceHarnessPlan(
        health=health,
        record_file=destination,
        record_mode=record_mode,
    )


def run_release_candidate_acceptance_harness(
    plan: ReleaseCandidateAcceptanceHarnessPlan,
    *,
    dependencies: ReleaseCandidateAcceptanceHarnessDependencies | None = None,
    clock: AcceptanceClock = lambda: datetime.now(UTC),
) -> ReleaseCandidateAcceptanceHarnessResult:
    """Run health, acceptance and persistent reporting as one workflow."""
    if not isinstance(plan, ReleaseCandidateAcceptanceHarnessPlan):
        raise TypeError("plan must be a ReleaseCandidateAcceptanceHarnessPlan value.")

    resolved = dependencies or ReleaseCandidateAcceptanceHarnessDependencies()

    try:
        health = resolved.run_health(plan.health)
    except Exception:
        return _harness_failure(
            message="Release-candidate health execution failed.",
        )

    try:
        acceptance = resolved.run_acceptance(
            plan.health,
            health,
        )
    except Exception:
        return _harness_failure(
            message="Release-candidate functional acceptance failed.",
            health=health,
        )

    try:
        record = resolved.create_record(
            plan.health,
            health,
            acceptance,
            clock=clock,
        )
    except Exception:
        return _harness_failure(
            message="Release-candidate acceptance record creation failed.",
            health=health,
            acceptance=acceptance,
        )

    try:
        write_result = resolved.write_record(
            record,
            plan.record_file,
            mode=plan.record_mode,
        )
    except Exception:
        return _harness_failure(
            message="Release-candidate acceptance record persistence failed.",
            health=health,
            acceptance=acceptance,
            record=record,
            path=plan.record_file,
        )

    if not write_result.success:
        return ReleaseCandidateAcceptanceHarnessResult(
            success=False,
            accepted=record.accepted,
            health=health,
            acceptance=acceptance,
            record=record,
            record_write=write_result,
            issues=(
                write_result.issues
                if write_result.issues
                else (
                    InstallerIssue(
                        code=InstallerIssueCode.STEP_FAILED,
                        message=(
                            "Release-candidate acceptance record persistence failed."
                        ),
                        step=InstallerStepId.ACCEPTANCE,
                        path=plan.record_file,
                    ),
                )
            ),
        )

    return ReleaseCandidateAcceptanceHarnessResult(
        success=True,
        accepted=record.accepted,
        health=health,
        acceptance=acceptance,
        record=record,
        record_write=write_result,
        issues=(),
    )


def _harness_failure(
    *,
    message: str,
    health: PostInstallHealthResult | None = None,
    acceptance: ReleaseCandidateAcceptanceResult | None = None,
    record: ReleaseCandidateAcceptanceRecord | None = None,
    path: Path | None = None,
) -> ReleaseCandidateAcceptanceHarnessResult:
    """Create one sanitised harness failure."""
    return ReleaseCandidateAcceptanceHarnessResult(
        success=False,
        accepted=bool(record is not None and record.accepted),
        health=health,
        acceptance=acceptance,
        record=record,
        record_write=None,
        issues=(
            InstallerIssue(
                code=InstallerIssueCode.STEP_FAILED,
                message=message,
                step=InstallerStepId.ACCEPTANCE,
                path=path,
            ),
        ),
    )


def _validate_absolute_path(
    path: Path,
    *,
    field_name: str,
) -> None:
    """Validate one absolute filesystem path."""
    if not isinstance(path, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path value.")
    if not path.is_absolute():
        raise ValueError(f"{field_name} must be absolute.")
    if "\x00" in str(path):
        raise ValueError(f"{field_name} must not contain a null byte.")
