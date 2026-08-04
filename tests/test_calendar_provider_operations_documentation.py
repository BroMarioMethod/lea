"""Acceptance checks for the calendar operations runbook."""

from pathlib import Path

DOCUMENT = (
    Path(__file__).parents[1]
    / "docs"
    / "development"
    / "CALENDAR_PROVIDER_OPERATIONS.md"
)


def test_runbook_covers_required_lifecycle_and_android_operations() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")

    for heading in (
        "## Install or repair the calendar client",
        "## Provision Radicale and CalDAV",
        "## Pair DAVx⁵ on Android",
        "## Two-way live acceptance",
        "## Backup and restore",
        "## Upgrade and rollback",
        "## Removal and credential revocation",
    ):
        assert heading in text

    for required in (
        "lea calendar discover",
        "lea calendar sync",
        "lea accept-calendar-android",
        "--server-to-android-verified",
        "--android-to-server-verified",
        "--user-isolation-verified",
        "--backup-verified",
        "lea uninstall-release-candidate --purge --yes",
        "/opt/lea-tools/calendar",
        "/var/lib/lea/secrets/calendar/caldav-password",
        "conflict_resolution = null",
        "https://manual.davx5.com/accounts_collections.html",
    ):
        assert required in text


def test_runbook_forbids_secret_and_device_evidence() -> None:
    text = DOCUMENT.read_text(encoding="utf-8").lower()

    assert "never put a plaintext password" in text
    assert "do not record their values or event ids" in text
    assert "davx⁵ synchronisation is not a backup" in text
    assert "<reviewed-lowercase-sha256>" in text
