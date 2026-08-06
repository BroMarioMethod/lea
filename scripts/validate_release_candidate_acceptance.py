#!/usr/bin/env python3
"""Validate committed release-candidate acceptance assets safely."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

CLI_PATH = REPOSITORY_ROOT / "src/lea/release_candidate_acceptance_cli.py"
HARNESS_PATH = (
    REPOSITORY_ROOT / "src/lea/installers/release_candidate/acceptance_harness.py"
)
RECORD_PATH = (
    REPOSITORY_ROOT / "src/lea/installers/release_candidate/acceptance_record.py"
)
MAIN_PATH = REPOSITORY_ROOT / "src/lea/main.py"
DOCUMENTATION_PATH = (
    REPOSITORY_ROOT / "docs/development/RELEASE_CANDIDATE_ACCEPTANCE.md"
)
CALENDAR_REQUIREMENTS_INPUT_PATH = (
    REPOSITORY_ROOT / "third_party/calendar/requirements.in"
)
CALENDAR_REQUIREMENTS_LOCK_PATH = (
    REPOSITORY_ROOT / "third_party/calendar/requirements-linux-aarch64-py313.txt"
)
CALENDAR_SHA256SUMS_PATH = REPOSITORY_ROOT / "third_party/calendar/SHA256SUMS"


@dataclass(frozen=True, slots=True)
class AcceptanceValidationIssue:
    """One deterministic acceptance-asset validation issue."""

    code: str
    message: str
    path: Path

    def __post_init__(self) -> None:
        """Validate one issue."""
        if not self.code.strip():
            raise ValueError("Validation issue code must be non-empty.")
        if not self.message.strip():
            raise ValueError("Validation issue message must be non-empty.")
        if not self.path.is_absolute():
            raise ValueError("Validation issue path must be absolute.")


def validate_release_candidate_acceptance(
    *,
    cli_path: Path = CLI_PATH,
    harness_path: Path = HARNESS_PATH,
    record_path: Path = RECORD_PATH,
    main_path: Path = MAIN_PATH,
    documentation_path: Path = DOCUMENTATION_PATH,
    calendar_requirements_input_path: Path = (CALENDAR_REQUIREMENTS_INPUT_PATH),
    calendar_requirements_lock_path: Path = (CALENDAR_REQUIREMENTS_LOCK_PATH),
    calendar_sha256sums_path: Path = CALENDAR_SHA256SUMS_PATH,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[AcceptanceValidationIssue, ...]:
    """Validate acceptance assets without running the acceptance harness."""
    issues: list[AcceptanceValidationIssue] = []

    cli = _read(cli_path, issues)
    harness = _read(harness_path, issues)
    record = _read(record_path, issues)
    main = _read(main_path, issues)
    documentation = _read(documentation_path, issues)
    calendar_requirements_input = _read(
        calendar_requirements_input_path,
        issues,
    )
    calendar_requirements_lock = _read(
        calendar_requirements_lock_path,
        issues,
    )
    calendar_sha256sums = _read(
        calendar_sha256sums_path,
        issues,
    )

    if cli is not None:
        _require_parts(
            cli,
            path=cli_path,
            code="acceptance_cli_contract_missing",
            required=(
                'prog="lea accept-release-candidate"',
                '"--telegram"',
                '"--no-telegram"',
                "EXIT_ACCEPTANCE_FAILED = 1",
                "EXIT_USAGE_ERROR = 2",
                "EXIT_INTERNAL_ERROR = 70",
                "run_release_candidate_acceptance_harness",
            ),
            issues=issues,
        )

    if harness is not None:
        _require_parts(
            harness,
            path=harness_path,
            code="acceptance_harness_contract_missing",
            required=(
                "run_release_candidate_acceptance_harness",
                "create_release_candidate_acceptance_record",
                "write_release_candidate_acceptance_record",
                "ReleaseCandidateAcceptanceHarnessResult",
            ),
            issues=issues,
        )

    if record is not None:
        _require_parts(
            record,
            path=record_path,
            code="acceptance_record_contract_missing",
            required=(
                '"lea-release-candidate-acceptance"',
                "schema_version=1",
                "sort_keys=True",
                "os.replace",
                "mode: int = 0o640",
            ),
            issues=issues,
        )

        for forbidden in (
            "telegram_token",
            "authorised_user_id",
            "conversation_id",
            "environment_variables",
            "raw_exception",
        ):
            if forbidden in record:
                issues.append(
                    AcceptanceValidationIssue(
                        code="acceptance_record_sensitive_field_detected",
                        message=(
                            "The acceptance-record implementation contains a "
                            f"forbidden sensitive-field name: {forbidden}"
                        ),
                        path=record_path,
                    )
                )

    if main is not None:
        _require_parts(
            main,
            path=main_path,
            code="acceptance_dispatch_missing",
            required=(
                '"accept-release-candidate"',
                "execute_release_candidate_acceptance_cli",
                "release_candidate_acceptance_cli_runner",
            ),
            issues=issues,
        )

    if documentation is not None:
        _require_parts(
            documentation,
            path=documentation_path,
            code="acceptance_documentation_incomplete",
            required=(
                "uv run lea accept-release-candidate",
                "--telegram",
                "--no-telegram",
                "/var/lib/lea/acceptance/release-candidate.json",
                "Exit code",
                "Telegram bot tokens",
                "clean-room installation",
                "uv run python scripts/validate_release_candidate_acceptance.py",
            ),
            issues=issues,
        )

    _validate_calendar_release_assets(
        requirements_input=calendar_requirements_input,
        requirements_input_path=calendar_requirements_input_path,
        requirements_lock=calendar_requirements_lock,
        requirements_lock_path=calendar_requirements_lock_path,
        sha256sums=calendar_sha256sums,
        sha256sums_path=calendar_sha256sums_path,
        issues=issues,
    )

    _validate_help(
        repository_root,
        issues=issues,
    )

    return tuple(issues)


def _validate_calendar_release_assets(
    *,
    requirements_input: str | None,
    requirements_input_path: Path,
    requirements_lock: str | None,
    requirements_lock_path: Path,
    sha256sums: str | None,
    sha256sums_path: Path,
    issues: list[AcceptanceValidationIssue],
) -> None:
    """Validate the pinned calendar supply-chain assets."""
    expected_requirements = (
        "khal==0.11.4",
        "vdirsyncer==0.19.3",
    )

    if requirements_input is not None:
        active_requirements = tuple(
            line.strip()
            for line in requirements_input.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )

        if active_requirements != expected_requirements:
            issues.append(
                AcceptanceValidationIssue(
                    code="calendar_requirements_input_invalid",
                    message=(
                        "The calendar requirements input must contain only "
                        "the reviewed khal and vdirsyncer pins."
                    ),
                    path=requirements_input_path,
                )
            )

    if requirements_lock is not None:
        _require_parts(
            requirements_lock,
            path=requirements_lock_path,
            code="calendar_lock_contract_missing",
            required=(
                "--only-binary :all:",
                "khal==0.11.4 \\",
                "vdirsyncer==0.19.3 \\",
                "--hash=sha256:",
            ),
            issues=issues,
        )

        unpinned_lines: list[int] = []

        for line_number, line in enumerate(
            requirements_lock.splitlines(),
            start=1,
        ):
            stripped = line.strip()

            if (
                not stripped
                or stripped.startswith("#")
                or stripped.startswith("--")
                or line[0].isspace()
            ):
                continue

            if "==" not in stripped:
                unpinned_lines.append(line_number)

        if unpinned_lines:
            issues.append(
                AcceptanceValidationIssue(
                    code="calendar_lock_unpinned_requirement",
                    message=(
                        "The calendar lock contains an unpinned top-level requirement."
                    ),
                    path=requirements_lock_path,
                )
            )

    if sha256sums is None or requirements_lock is None:
        return

    manifest_lines = tuple(
        line.strip()
        for line in sha256sums.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )

    if len(manifest_lines) != 1:
        issues.append(
            AcceptanceValidationIssue(
                code="calendar_checksum_manifest_invalid",
                message=(
                    "The calendar checksum manifest must contain exactly "
                    "one active entry."
                ),
                path=sha256sums_path,
            )
        )
        return

    parts = manifest_lines[0].split()

    if len(parts) != 2:
        issues.append(
            AcceptanceValidationIssue(
                code="calendar_checksum_manifest_invalid",
                message="The calendar checksum manifest entry is malformed.",
                path=sha256sums_path,
            )
        )
        return

    expected_sha256, recorded_filename = parts

    if (
        len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
        or recorded_filename != requirements_lock_path.name
    ):
        issues.append(
            AcceptanceValidationIssue(
                code="calendar_checksum_manifest_invalid",
                message=(
                    "The calendar checksum manifest does not identify the "
                    "canonical lock correctly."
                ),
                path=sha256sums_path,
            )
        )
        return

    try:
        actual_sha256 = hashlib.sha256(requirements_lock_path.read_bytes()).hexdigest()
    except OSError:
        issues.append(
            AcceptanceValidationIssue(
                code="calendar_lock_unreadable",
                message=("The calendar requirements lock could not be hashed."),
                path=requirements_lock_path,
            )
        )
        return

    if actual_sha256 != expected_sha256:
        issues.append(
            AcceptanceValidationIssue(
                code="calendar_lock_checksum_mismatch",
                message=(
                    "The calendar requirements lock does not match the "
                    "committed checksum manifest."
                ),
                path=requirements_lock_path,
            )
        )


def main() -> int:
    """Validate committed release-candidate acceptance assets."""
    issues = validate_release_candidate_acceptance()

    if issues:
        print(
            "Release-candidate acceptance validation: FAILED",
            file=sys.stderr,
        )
        for issue in issues:
            try:
                displayed_path = issue.path.relative_to(REPOSITORY_ROOT)
            except ValueError:
                displayed_path = issue.path

            print(
                f"{issue.code}: {issue.message} | path={displayed_path}",
                file=sys.stderr,
            )
        return 1

    print("Release-candidate acceptance validation: PASSED")
    return 0


def _validate_help(
    repository_root: Path,
    *,
    issues: list[AcceptanceValidationIssue],
) -> None:
    """Validate public help without executing installed-system acceptance."""
    command = (
        "uv",
        "run",
        "lea",
        "accept-release-candidate",
        "--help",
    )

    try:
        result = subprocess.run(
            command,
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        issues.append(
            AcceptanceValidationIssue(
                code="acceptance_help_execution_failed",
                message="The acceptance command help could not be executed.",
                path=repository_root,
            )
        )
        return

    if result.returncode != 0:
        issues.append(
            AcceptanceValidationIssue(
                code="acceptance_help_failed",
                message="The acceptance command help returned a failure.",
                path=repository_root,
            )
        )
        return

    for required in (
        "usage: lea accept-release-candidate",
        "--telegram",
        "--no-telegram",
        "--configuration-root",
        "--state-root",
        "--record-file",
    ):
        if required not in result.stdout:
            issues.append(
                AcceptanceValidationIssue(
                    code="acceptance_help_content_missing",
                    message=(
                        "The acceptance command help is missing required "
                        f"content: {required}"
                    ),
                    path=repository_root,
                )
            )


def _require_parts(
    contents: str,
    *,
    path: Path,
    code: str,
    required: tuple[str, ...],
    issues: list[AcceptanceValidationIssue],
) -> None:
    """Require exact stable contract fragments."""
    for part in required:
        if part not in contents:
            issues.append(
                AcceptanceValidationIssue(
                    code=code,
                    message=f"Required acceptance content is missing: {part}",
                    path=path,
                )
            )


def _read(
    path: Path,
    issues: list[AcceptanceValidationIssue],
) -> str | None:
    """Read one required UTF-8 acceptance asset."""
    if not path.is_absolute():
        raise ValueError("Acceptance validation paths must be absolute.")

    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        issues.append(
            AcceptanceValidationIssue(
                code="acceptance_asset_missing",
                message="A required acceptance asset is missing.",
                path=path,
            )
        )
    except (OSError, UnicodeError):
        issues.append(
            AcceptanceValidationIssue(
                code="acceptance_asset_unreadable",
                message="A required acceptance asset could not be read.",
                path=path,
            )
        )

    return None


if __name__ == "__main__":
    raise SystemExit(main())
