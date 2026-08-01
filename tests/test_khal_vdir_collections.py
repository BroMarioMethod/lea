"""Tests for deterministic local khal vdir collection discovery."""

from pathlib import Path

import pytest

from lea.adapters.khal import (
    KHAL_MAX_DISPLAY_NAME_BYTES,
    KhalConfig,
    discover_khal_calendar_collections,
)


def make_config(
    tmp_path: Path,
) -> KhalConfig:
    """Return one isolated khal configuration with an empty vdirs root."""
    executable = tmp_path / "bin" / "khal"
    configuration = tmp_path / "config" / "khal.conf"
    vdirs_directory = tmp_path / "state" / "vdirs"
    state_directory = tmp_path / "state" / "khal"
    working_directory = tmp_path / "working"

    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    configuration.parent.mkdir(parents=True)
    configuration.write_text("[calendars]\n", encoding="utf-8")
    vdirs_directory.mkdir(parents=True)
    state_directory.mkdir(parents=True)
    working_directory.mkdir()

    return KhalConfig(
        executable=executable,
        configuration=configuration,
        vdirs_directory=vdirs_directory,
        state_directory=state_directory,
        working_directory=working_directory,
        expected_version="0.11.4",
    )


def test_empty_vdirs_root_returns_empty_success(
    tmp_path: Path,
) -> None:
    """An empty managed root should be a valid calendar collection set."""
    result = discover_khal_calendar_collections(make_config(tmp_path))

    assert result.success is True
    assert result.calendars == ()
    assert result.issues == ()


def test_discovers_fallback_names_in_deterministic_order(
    tmp_path: Path,
) -> None:
    """Directory names should provide stable IDs and fallback labels."""
    config = make_config(tmp_path)
    (config.vdirs_directory / "work").mkdir()
    (config.vdirs_directory / "personal").mkdir()

    result = discover_khal_calendar_collections(config)

    assert result.success is True
    assert tuple(
        (calendar.calendar_id, calendar.display_name, calendar.read_only)
        for calendar in result.calendars
    ) == (
        ("personal", "personal", False),
        ("work", "work", False),
    )


def test_reads_optional_bounded_display_name(
    tmp_path: Path,
) -> None:
    """One final line ending should be accepted and removed."""
    config = make_config(tmp_path)
    collection = config.vdirs_directory / "personal"
    collection.mkdir()
    (collection / "displayname").write_text(
        "Personal calendar\n",
        encoding="utf-8",
    )

    result = discover_khal_calendar_collections(config)

    assert result.success is True
    assert result.calendars[0].display_name == "Personal calendar"


def test_hidden_root_entries_are_not_discovered(
    tmp_path: Path,
) -> None:
    """Discovery should match the managed `vdirs/*` khal glob."""
    config = make_config(tmp_path)
    (config.vdirs_directory / ".metadata").mkdir()
    (config.vdirs_directory / ".ignored-file").write_text(
        "ignored\n",
        encoding="utf-8",
    )
    (config.vdirs_directory / "visible").mkdir()

    result = discover_khal_calendar_collections(config)

    assert result.success is True
    assert tuple(calendar.calendar_id for calendar in result.calendars) == ("visible",)


def test_missing_non_directory_and_symbolic_roots_fail(
    tmp_path: Path,
) -> None:
    """The trusted root must be one exact regular directory."""
    config = make_config(tmp_path)
    config.vdirs_directory.rmdir()

    missing = discover_khal_calendar_collections(config)
    assert missing.success is False
    assert missing.issues[0].code == "khal_vdirs_directory_missing"

    config.vdirs_directory.write_text("not a directory\n", encoding="utf-8")
    non_directory = discover_khal_calendar_collections(config)
    assert non_directory.success is False
    assert non_directory.issues[0].code == "khal_vdirs_directory_unsafe"

    config.vdirs_directory.unlink()
    target = tmp_path / "real-vdirs"
    target.mkdir()
    config.vdirs_directory.symlink_to(target, target_is_directory=True)
    symbolic = discover_khal_calendar_collections(config)
    assert symbolic.success is False
    assert symbolic.issues[0].code == "khal_vdirs_directory_unsafe"


def test_non_directory_collection_entry_fails_closed(
    tmp_path: Path,
) -> None:
    """Visible non-directory entries must not be treated as calendars."""
    config = make_config(tmp_path)
    (config.vdirs_directory / "personal").mkdir()
    (config.vdirs_directory / "unexpected.txt").write_text(
        "unexpected\n",
        encoding="utf-8",
    )

    result = discover_khal_calendar_collections(config)

    assert result.success is False
    assert result.calendars == ()
    assert result.issues[0].code == "khal_calendar_collection_unsafe"


def test_symbolic_collection_fails_closed(
    tmp_path: Path,
) -> None:
    """Calendar identity must not cross the configured vdirs boundary."""
    config = make_config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (config.vdirs_directory / "linked").symlink_to(
        outside,
        target_is_directory=True,
    )

    result = discover_khal_calendar_collections(config)

    assert result.success is False
    assert result.issues[0].code == "khal_calendar_collection_unsafe"


def test_invalid_calendar_identifier_fails_closed(
    tmp_path: Path,
) -> None:
    """Unsafe directory names must not become provider identifiers."""
    config = make_config(tmp_path)
    (config.vdirs_directory / " personal").mkdir()

    result = discover_khal_calendar_collections(config)

    assert result.success is False
    assert result.calendars == ()
    assert result.issues[0].code == "khal_calendar_collection_invalid"
    assert result.issues[0].calendar_id is None


def test_symbolic_and_non_regular_display_names_fail(
    tmp_path: Path,
) -> None:
    """Display-name metadata must remain inside the collection."""
    config = make_config(tmp_path)
    collection = config.vdirs_directory / "personal"
    collection.mkdir()
    outside = tmp_path / "outside-displayname"
    outside.write_text("Outside\n", encoding="utf-8")
    (collection / "displayname").symlink_to(outside)

    symbolic = discover_khal_calendar_collections(config)
    assert symbolic.success is False
    assert symbolic.issues[0].code == "khal_calendar_display_name_unsafe"

    (collection / "displayname").unlink()
    (collection / "displayname").mkdir()
    non_regular = discover_khal_calendar_collections(config)
    assert non_regular.success is False
    assert non_regular.issues[0].code == "khal_calendar_display_name_unsafe"


def test_oversized_display_name_fails(
    tmp_path: Path,
) -> None:
    """Display-name metadata should have a finite byte limit."""
    config = make_config(tmp_path)
    collection = config.vdirs_directory / "personal"
    collection.mkdir()
    (collection / "displayname").write_bytes(b"x" * (KHAL_MAX_DISPLAY_NAME_BYTES + 1))

    result = discover_khal_calendar_collections(config)

    assert result.success is False
    assert result.issues[0].code == "khal_calendar_display_name_too_large"


def test_invalid_utf8_display_name_fails(
    tmp_path: Path,
) -> None:
    """Display-name metadata must decode strictly as UTF-8."""
    config = make_config(tmp_path)
    collection = config.vdirs_directory / "personal"
    collection.mkdir()
    (collection / "displayname").write_bytes(b"\xff")

    result = discover_khal_calendar_collections(config)

    assert result.success is False
    assert result.issues[0].code == ("khal_calendar_display_name_invalid_utf8")


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "\n",
        " Personal",
        "Personal ",
        "Personal\nCalendar",
        "Personal\rCalendar",
        "Personal\x00Calendar",
    ],
)
def test_invalid_display_name_shapes_fail(
    tmp_path: Path,
    contents: str,
) -> None:
    """Display names should be one exact non-empty printable line."""
    config = make_config(tmp_path)
    collection = config.vdirs_directory / "personal"
    collection.mkdir()
    (collection / "displayname").write_text(contents, encoding="utf-8")

    result = discover_khal_calendar_collections(config)

    assert result.success is False
    assert result.issues[0].code == "khal_calendar_display_name_invalid"


def test_programming_inputs_are_validated(
    tmp_path: Path,
) -> None:
    """Caller errors should be rejected before filesystem discovery."""
    config = make_config(tmp_path)

    with pytest.raises(TypeError, match="KhalConfig"):
        discover_khal_calendar_collections(
            object(),  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError, match="must be an integer"):
        discover_khal_calendar_collections(
            config,
            maximum_display_name_bytes=True,
        )

    with pytest.raises(ValueError, match="greater than zero"):
        discover_khal_calendar_collections(
            config,
            maximum_display_name_bytes=0,
        )
