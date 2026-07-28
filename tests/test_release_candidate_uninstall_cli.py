"""Tests for the guided release-candidate uninstall CLI."""

from io import StringIO

from lea.installers.release_candidate import (
    ReleaseCandidateUninstallPlan,
    ReleaseCandidateUninstallResult,
    ReleaseCandidateUninstallStepId,
    ReleaseCandidateUninstallStepResult,
    ReleaseCandidateUninstallStepState,
)
from lea.release_candidate_uninstall_cli import (
    EXIT_CANCELLED,
    EXIT_SUCCESS,
    EXIT_UNINSTALL_ERROR,
    EXIT_USAGE_ERROR,
    ReleaseCandidateUninstallCliDependencies,
    execute_release_candidate_uninstall_cli,
)


class Inputs:
    """Deterministic guided text input."""

    def __init__(self, values: tuple[str, ...]) -> None:
        self.values = list(values)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        """Return the next supplied response."""
        self.prompts.append(prompt)
        if not self.values:
            raise AssertionError(f"Unexpected prompt: {prompt}")
        return self.values.pop(0)


class RecordingUninstaller:
    """Record one plan and return a configured result."""

    def __init__(self, *, success: bool = True) -> None:
        self.success = success
        self.plans: list[ReleaseCandidateUninstallPlan] = []

    def __call__(
        self,
        plan: ReleaseCandidateUninstallPlan,
    ) -> ReleaseCandidateUninstallResult:
        """Record the plan and return a deterministic result."""
        self.plans.append(plan)

        if self.success:
            return ReleaseCandidateUninstallResult(
                success=True,
                steps=tuple(
                    ReleaseCandidateUninstallStepResult(
                        step=step.step,
                        state=(ReleaseCandidateUninstallStepState.COMPLETED),
                        message="Removed.",
                    )
                    for step in plan.steps
                ),
                issues=(),
            )

        issue = plan.steps[0]
        from lea.installers.release_candidate import (
            ReleaseCandidateUninstallIssue,
            ReleaseCandidateUninstallIssueCode,
        )

        failure = ReleaseCandidateUninstallIssue(
            code=ReleaseCandidateUninstallIssueCode.STEP_FAILED,
            message="Synthetic uninstall failure.",
            step=issue.step,
        )
        return ReleaseCandidateUninstallResult(
            success=False,
            steps=(
                ReleaseCandidateUninstallStepResult(
                    step=ReleaseCandidateUninstallStepId.SYSTEMD_SERVICE,
                    state=ReleaseCandidateUninstallStepState.FAILED,
                    message="Synthetic uninstall failure.",
                    issues=(failure,),
                ),
                *tuple(
                    ReleaseCandidateUninstallStepResult(
                        step=step.step,
                        state=ReleaseCandidateUninstallStepState.SKIPPED,
                        message="Skipped after failure.",
                    )
                    for step in plan.steps[1:]
                ),
            ),
            issues=(failure,),
        )


def test_requires_purge_flag() -> None:
    """The destructive purge flag must be explicit."""
    stderr = StringIO()

    exit_code = execute_release_candidate_uninstall_cli(
        [],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == EXIT_USAGE_ERROR
    assert "--purge" in stderr.getvalue()


def test_declining_confirmation_cancels_before_mutation() -> None:
    """A declined prompt should not call the uninstall executor."""
    uninstaller = RecordingUninstaller()
    inputs = Inputs(("no",))
    stdout = StringIO()

    exit_code = execute_release_candidate_uninstall_cli(
        ["--purge"],
        stdout=stdout,
        stderr=StringIO(),
        dependencies=ReleaseCandidateUninstallCliDependencies(
            text_input=inputs,
            uninstaller=uninstaller,
        ),
    )

    assert exit_code == EXIT_CANCELLED
    assert uninstaller.plans == []
    assert "uninstall plan" in stdout.getvalue()
    assert "Uninstallation cancelled." in stdout.getvalue()


def test_yes_executes_without_prompt() -> None:
    """--yes should approve one purge without terminal input."""
    uninstaller = RecordingUninstaller()
    stdout = StringIO()

    exit_code = execute_release_candidate_uninstall_cli(
        ["--purge", "--yes"],
        stdout=stdout,
        stderr=StringIO(),
        dependencies=ReleaseCandidateUninstallCliDependencies(
            text_input=Inputs(()),
            uninstaller=uninstaller,
        ),
    )

    assert exit_code == EXIT_SUCCESS
    assert len(uninstaller.plans) == 1
    assert uninstaller.plans[0].request.purge is True
    assert uninstaller.plans[0].request.confirmed is True
    assert "State: succeeded" in stdout.getvalue()


def test_interactive_yes_executes_purge() -> None:
    """An explicit interactive yes should approve the purge."""
    uninstaller = RecordingUninstaller()

    exit_code = execute_release_candidate_uninstall_cli(
        ["--purge"],
        stdout=StringIO(),
        stderr=StringIO(),
        dependencies=ReleaseCandidateUninstallCliDependencies(
            text_input=Inputs(("yes",)),
            uninstaller=uninstaller,
        ),
    )

    assert exit_code == EXIT_SUCCESS
    assert len(uninstaller.plans) == 1


def test_failed_uninstall_renders_to_stderr() -> None:
    """Structured uninstall failures should return status one."""
    uninstaller = RecordingUninstaller(success=False)
    stdout = StringIO()
    stderr = StringIO()

    exit_code = execute_release_candidate_uninstall_cli(
        ["--purge", "--yes"],
        stdout=stdout,
        stderr=stderr,
        dependencies=ReleaseCandidateUninstallCliDependencies(
            text_input=Inputs(()),
            uninstaller=uninstaller,
        ),
    )

    assert exit_code == EXIT_UNINSTALL_ERROR
    assert "uninstall plan" in stdout.getvalue()
    assert "State: failed" in stderr.getvalue()
    assert "Synthetic uninstall failure." in stderr.getvalue()
