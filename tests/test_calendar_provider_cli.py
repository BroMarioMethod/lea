"""Tests for protected calendar-provider administrative inputs."""

from lea import calendar_provider_cli


def test_credentials_file_loads_canonical_accounts_without_exposing_hashes() -> None:
    credentials = calendar_provider_cli._parse_credentials_document(
        "alpha:$2b$12$.....................................................\n"
        "beta:$2b$12$/////////////////////////////////////////////////////\n"
    )
    assert tuple(value.username for value in credentials) == ("alpha", "beta")
