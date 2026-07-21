"""Tests for timezone-safe LEA timestamp presentation."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from lea.runtime import localise_utc_timestamp


def test_utc_timestamp_converts_to_gaborone_time() -> None:
    """UTC timestamps should display in Botswana local time."""
    timestamp = datetime(
        2026,
        7,
        21,
        12,
        0,
        tzinfo=UTC,
    )

    localised = localise_utc_timestamp(
        timestamp,
        display_timezone="Africa/Gaborone",
    )

    assert localised.hour == 14
    assert localised.minute == 0
    assert localised.utcoffset() == timedelta(hours=2)


def test_conversion_preserves_instant() -> None:
    """Timezone conversion must not change the represented instant."""
    timestamp = datetime(
        2026,
        7,
        21,
        12,
        0,
        tzinfo=UTC,
    )

    localised = localise_utc_timestamp(
        timestamp,
        display_timezone="Africa/Gaborone",
    )

    assert localised.astimezone(UTC) == timestamp


def test_original_timestamp_is_not_mutated() -> None:
    """Presentation conversion should leave the input unchanged."""
    timestamp = datetime(
        2026,
        7,
        21,
        12,
        0,
        tzinfo=UTC,
    )

    localise_utc_timestamp(
        timestamp,
        display_timezone="Africa/Gaborone",
    )

    assert timestamp == datetime(
        2026,
        7,
        21,
        12,
        0,
        tzinfo=UTC,
    )
    assert timestamp.tzinfo is UTC


def test_utc_display_timezone_preserves_value() -> None:
    """UTC presentation should preserve the timestamp value."""
    timestamp = datetime(
        2026,
        7,
        21,
        12,
        0,
        tzinfo=UTC,
    )

    localised = localise_utc_timestamp(
        timestamp,
        display_timezone="UTC",
    )

    assert localised == timestamp
    assert localised.utcoffset() == timedelta(0)


def test_daylight_saving_timezone_uses_correct_offset() -> None:
    """IANA rules should determine seasonal local offsets."""
    winter = datetime(
        2026,
        1,
        15,
        12,
        0,
        tzinfo=UTC,
    )
    summer = datetime(
        2026,
        7,
        15,
        12,
        0,
        tzinfo=UTC,
    )

    winter_local = localise_utc_timestamp(
        winter,
        display_timezone="Europe/London",
    )
    summer_local = localise_utc_timestamp(
        summer,
        display_timezone="Europe/London",
    )

    assert winter_local.utcoffset() == timedelta(0)
    assert summer_local.utcoffset() == timedelta(hours=1)


def test_naive_timestamp_is_rejected() -> None:
    """Timezone-naive input must fail closed."""
    timestamp = datetime(2026, 7, 21, 12, 0)

    with pytest.raises(
        ValueError,
        match="must be timezone-aware",
    ):
        localise_utc_timestamp(
            timestamp,
            display_timezone="Africa/Gaborone",
        )


def test_non_utc_timestamp_is_rejected() -> None:
    """Stored timestamps must be canonical UTC values."""
    non_utc_timezone = timezone(timedelta(hours=2))
    timestamp = datetime(
        2026,
        7,
        21,
        14,
        0,
        tzinfo=non_utc_timezone,
    )

    with pytest.raises(
        ValueError,
        match="canonical UTC",
    ):
        localise_utc_timestamp(
            timestamp,
            display_timezone="Africa/Gaborone",
        )


@pytest.mark.parametrize(
    "display_timezone",
    [
        "",
        "   ",
    ],
)
def test_blank_display_timezone_is_rejected(
    display_timezone: str,
) -> None:
    """Blank timezone identifiers must fail explicitly."""
    timestamp = datetime(
        2026,
        7,
        21,
        12,
        0,
        tzinfo=UTC,
    )

    with pytest.raises(
        ValueError,
        match="non-empty IANA timezone",
    ):
        localise_utc_timestamp(
            timestamp,
            display_timezone=display_timezone,
        )


def test_unknown_timezone_is_rejected() -> None:
    """Unknown IANA timezone identifiers must fail."""
    timestamp = datetime(
        2026,
        7,
        21,
        12,
        0,
        tzinfo=UTC,
    )

    with pytest.raises(
        ValueError,
        match="recognised IANA timezone",
    ):
        localise_utc_timestamp(
            timestamp,
            display_timezone="Invalid/Timezone",
        )


def test_fractional_seconds_are_preserved() -> None:
    """Presentation conversion should preserve precision."""
    timestamp = datetime(
        2026,
        7,
        21,
        12,
        0,
        30,
        123456,
        tzinfo=UTC,
    )

    localised = localise_utc_timestamp(
        timestamp,
        display_timezone="Africa/Gaborone",
    )

    assert localised.second == 30
    assert localised.microsecond == 123456
    assert localised.astimezone(UTC) == timestamp
