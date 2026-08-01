"""Strict deterministic discovery of local khal vdir collections."""

from pathlib import Path

from lea.adapters.khal.contracts import KhalConfig
from lea.calendars import (
    CalendarCollection,
    CalendarListCalendarsResult,
    CalendarProviderIssue,
)

KHAL_MAX_DISPLAY_NAME_BYTES = 4_096
_PROVIDER = "khal"


def discover_khal_calendar_collections(
    config: KhalConfig,
    *,
    maximum_display_name_bytes: int = KHAL_MAX_DISPLAY_NAME_BYTES,
) -> CalendarListCalendarsResult:
    """Discover immediate non-hidden calendar vdirs without subprocess use."""
    if not isinstance(config, KhalConfig):
        raise TypeError("config must be a KhalConfig value.")

    _validate_maximum_bytes(maximum_display_name_bytes)

    root_issue = _inspect_vdirs_root(config.vdirs_directory)

    if root_issue is not None:
        return _failure(root_issue)

    try:
        candidates = tuple(
            sorted(
                (
                    entry
                    for entry in config.vdirs_directory.iterdir()
                    if not entry.name.startswith(".")
                ),
                key=lambda entry: entry.name,
            )
        )
    except OSError:
        return _failure(
            _issue(
                code="khal_vdirs_directory_unreadable",
                message=(
                    "The configured khal vdirs directory could not be enumerated."
                ),
                field="vdirs_directory",
            )
        )

    calendars: list[CalendarCollection] = []
    seen_ids: set[str] = set()

    for candidate in candidates:
        calendar_id = candidate.name
        candidate_issue = _inspect_collection_directory(
            candidate,
            calendar_id=calendar_id,
        )

        if candidate_issue is not None:
            return _failure(candidate_issue)

        if calendar_id in seen_ids:
            return _failure(
                _issue(
                    code="khal_calendar_id_duplicate",
                    message=(
                        "The local vdir structure contained a duplicate "
                        "calendar identifier."
                    ),
                    calendar_id=calendar_id,
                    field="calendar_id",
                )
            )

        display_name_result = _read_display_name(
            candidate / "displayname",
            calendar_id=calendar_id,
            fallback=calendar_id,
            maximum_bytes=maximum_display_name_bytes,
        )

        if isinstance(display_name_result, CalendarProviderIssue):
            return _failure(display_name_result)

        try:
            collection = CalendarCollection(
                calendar_id=calendar_id,
                display_name=display_name_result,
                read_only=False,
            )
        except (TypeError, ValueError):
            return _failure(
                _issue(
                    code="khal_calendar_collection_invalid",
                    message=(
                        "The local vdir collection failed canonical "
                        "calendar validation."
                    ),
                    calendar_id=_safe_issue_identifier(calendar_id),
                    field="calendar_id",
                )
            )

        seen_ids.add(calendar_id)
        calendars.append(collection)

    return CalendarListCalendarsResult(
        success=True,
        calendars=tuple(calendars),
        issues=(),
    )


def _inspect_vdirs_root(
    path: Path,
) -> CalendarProviderIssue | None:
    """Require one exact regular non-symbolic vdirs root."""
    try:
        if path.is_symlink():
            return _issue(
                code="khal_vdirs_directory_unsafe",
                message=(
                    "The configured khal vdirs directory must not be a symbolic link."
                ),
                field="vdirs_directory",
            )

        if not path.exists():
            return _issue(
                code="khal_vdirs_directory_missing",
                message=("The configured khal vdirs directory does not exist."),
                field="vdirs_directory",
            )

        if not path.is_dir():
            return _issue(
                code="khal_vdirs_directory_unsafe",
                message=("The configured khal vdirs path is not a directory."),
                field="vdirs_directory",
            )
    except OSError:
        return _issue(
            code="khal_vdirs_directory_unreadable",
            message=("The configured khal vdirs directory could not be inspected."),
            field="vdirs_directory",
        )

    return None


def _inspect_collection_directory(
    path: Path,
    *,
    calendar_id: str,
) -> CalendarProviderIssue | None:
    """Require one immediate regular non-symbolic collection directory."""
    issue_calendar_id = _safe_issue_identifier(calendar_id)

    try:
        if path.is_symlink():
            return _issue(
                code="khal_calendar_collection_unsafe",
                message=("A local calendar collection must not be a symbolic link."),
                calendar_id=issue_calendar_id,
                field="vdirs_directory",
            )

        if not path.is_dir():
            return _issue(
                code="khal_calendar_collection_unsafe",
                message=(
                    "A non-hidden entry in the khal vdirs root was not a "
                    "calendar directory."
                ),
                calendar_id=issue_calendar_id,
                field="vdirs_directory",
            )
    except OSError:
        return _issue(
            code="khal_calendar_collection_unreadable",
            message=("A local calendar collection could not be inspected."),
            calendar_id=issue_calendar_id,
            field="vdirs_directory",
        )

    return None


def _read_display_name(
    path: Path,
    *,
    calendar_id: str,
    fallback: str,
    maximum_bytes: int,
) -> str | CalendarProviderIssue:
    """Read one optional bounded UTF-8 displayname metadata file."""
    try:
        if path.is_symlink():
            return _issue(
                code="khal_calendar_display_name_unsafe",
                message=("Calendar display-name metadata must not be a symbolic link."),
                calendar_id=_safe_issue_identifier(calendar_id),
                field="display_name",
            )

        if not path.exists():
            return fallback

        if not path.is_file():
            return _issue(
                code="khal_calendar_display_name_unsafe",
                message=("Calendar display-name metadata is not a regular file."),
                calendar_id=_safe_issue_identifier(calendar_id),
                field="display_name",
            )

        if path.stat().st_size > maximum_bytes:
            return _issue(
                code="khal_calendar_display_name_too_large",
                message=(
                    "Calendar display-name metadata exceeded the configured size limit."
                ),
                calendar_id=_safe_issue_identifier(calendar_id),
                field="display_name",
            )

        document = path.read_bytes()
    except OSError:
        return _issue(
            code="khal_calendar_display_name_unreadable",
            message=("Calendar display-name metadata could not be read."),
            calendar_id=_safe_issue_identifier(calendar_id),
            field="display_name",
        )

    if len(document) > maximum_bytes:
        return _issue(
            code="khal_calendar_display_name_too_large",
            message=(
                "Calendar display-name metadata exceeded the configured size limit."
            ),
            calendar_id=_safe_issue_identifier(calendar_id),
            field="display_name",
        )

    try:
        text = document.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _issue(
            code="khal_calendar_display_name_invalid_utf8",
            message=("Calendar display-name metadata was not valid UTF-8."),
            calendar_id=_safe_issue_identifier(calendar_id),
            field="display_name",
        )

    display_name = _remove_one_line_ending(text)

    if (
        not display_name
        or display_name != display_name.strip()
        or "\n" in display_name
        or "\r" in display_name
        or any(
            ord(character) < 32 or ord(character) == 127 for character in display_name
        )
    ):
        return _issue(
            code="khal_calendar_display_name_invalid",
            message=(
                "Calendar display-name metadata must contain one "
                "non-empty line without surrounding whitespace or "
                "control characters."
            ),
            calendar_id=_safe_issue_identifier(calendar_id),
            field="display_name",
        )

    return display_name


def _remove_one_line_ending(value: str) -> str:
    """Remove one optional conventional final line ending."""
    if value.endswith("\r\n"):
        return value[:-2]

    if value.endswith("\n"):
        return value[:-1]

    return value


def _safe_issue_identifier(value: str) -> str | None:
    """Return an identifier only when issue construction can preserve it."""
    if not isinstance(value, str) or not value.strip():
        return None

    if value != value.strip():
        return None

    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None

    return value


def _validate_maximum_bytes(value: int) -> None:
    """Validate one positive non-boolean byte limit."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("maximum_display_name_bytes must be an integer.")

    if value <= 0:
        raise ValueError("maximum_display_name_bytes must be greater than zero.")


def _failure(
    issue: CalendarProviderIssue,
) -> CalendarListCalendarsResult:
    """Construct one fail-closed collection-discovery result."""
    return CalendarListCalendarsResult(
        success=False,
        calendars=(),
        issues=(issue,),
    )


def _issue(
    *,
    code: str,
    message: str,
    field: str,
    calendar_id: str | None = None,
) -> CalendarProviderIssue:
    """Construct one structured khal collection-discovery issue."""
    return CalendarProviderIssue(
        code=code,
        message=message,
        provider=_PROVIDER,
        operation="list_calendars",
        calendar_id=calendar_id,
        field=field,
    )
