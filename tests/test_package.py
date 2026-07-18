"""Tests for the top-level LEA package."""


def test_package_is_importable() -> None:
    """LEA should be importable as an installed package."""
    import lea

    assert lea.__name__ == "lea"
