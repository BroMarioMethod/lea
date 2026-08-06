"""Tests for strict authorised-user TOML loading."""

from pathlib import Path

import pytest

from lea.channels import (
    AuthorisedUserConfigIssue,
    AuthorisedUserConfigResult,
    ChannelCapability,
    ChannelName,
    ChannelRole,
    load_authorised_channel_users,
    parse_authorised_channel_users,
)

VALID = """
schema_version = 1

[[users]]
name = "Owner"
channel = "telegram"
user_id = 123456789
conversation_id = 123456789
role = "owner"
enabled = true
add_capabilities = ["Knowledge.Read.Medium"]
remove_capabilities = ["Tasks.Delete"]
calendar_ids = ["work", "personal", "work"]
"""


def test_parse_valid_configuration() -> None:
    result = parse_authorised_channel_users(VALID)

    assert result.success is True
    assert result.issues == ()
    assert len(result.users) == 1
    assert result.users[0].name == "Owner"
    assert result.users[0].channel is ChannelName.TELEGRAM
    assert result.users[0].user_id == "123456789"
    assert result.users[0].role is ChannelRole.OWNER
    assert result.users[0].add_capabilities == (
        ChannelCapability.KNOWLEDGE_READ_MEDIUM,
    )
    assert result.users[0].remove_capabilities == (ChannelCapability.TASKS_DELETE,)
    assert result.users[0].calendar_ids == ("personal", "work")


def test_string_identifiers_are_accepted() -> None:
    result = parse_authorised_channel_users(
        VALID.replace("user_id = 123456789", 'user_id = "123456789"').replace(
            "conversation_id = 123456789",
            'conversation_id = "123456789"',
        )
    )

    assert result.success is True
    assert result.users[0].user_id == "123456789"


def test_duplicate_names_are_allowed_for_distinct_identities() -> None:
    result = parse_authorised_channel_users(
        VALID
        + """
[[users]]
name = "Owner"
channel = "telegram"
user_id = 987654321
conversation_id = 987654321
role = "tester"
enabled = true
"""
    )

    assert result.success is True
    assert len(result.users) == 2


def test_duplicate_exact_identity_is_rejected() -> None:
    result = parse_authorised_channel_users(
        VALID
        + """
[[users]]
name = "Duplicate"
channel = "telegram"
user_id = 123456789
conversation_id = 123456789
role = "tester"
enabled = true
"""
    )

    assert result.success is False
    assert any(issue.code == "duplicate_authorised_identity" for issue in result.issues)


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ("schema_version = 1", "schema_version = 2", "unsupported_schema_version"),
        ("schema_version = 1", "schema_version = true", "unsupported_schema_version"),
        ('role = "owner"', 'role = "administrator"', "invalid_enum"),
        ('channel = "telegram"', 'channel = "matrix"', "invalid_enum"),
        ("enabled = true", 'enabled = "yes"', "invalid_boolean"),
        ("user_id = 123456789", "user_id = 0", "invalid_identifier"),
        (
            'add_capabilities = ["Knowledge.Read.Medium"]',
            'add_capabilities = ["Unknown.Read"]',
            "unknown_capability",
        ),
    ],
)
def test_invalid_values_fail_closed(
    old: str,
    new: str,
    code: str,
) -> None:
    result = parse_authorised_channel_users(VALID.replace(old, new))

    assert result.success is False
    assert any(issue.code == code for issue in result.issues)


def test_unknown_top_level_field_is_rejected() -> None:
    result = parse_authorised_channel_users(VALID + '\nunknown = "value"\n')

    assert result.success is False
    assert any(issue.code == "unknown_field" for issue in result.issues)


def test_unknown_user_field_is_rejected() -> None:
    result = parse_authorised_channel_users(
        VALID.replace(
            'role = "owner"',
            'role = "owner"\nusername = "owner"',
        )
    )

    assert result.success is False
    assert any(issue.field == "users[0].username" for issue in result.issues)


def test_missing_required_user_field_is_rejected() -> None:
    result = parse_authorised_channel_users(VALID.replace('name = "Owner"\n', ""))

    assert result.success is False
    assert any(issue.field == "users[0].name" for issue in result.issues)


def test_users_must_be_array_of_tables() -> None:
    result = parse_authorised_channel_users('schema_version = 1\nusers = "owner"\n')

    assert result.success is False
    assert any(issue.code == "invalid_users" for issue in result.issues)


def test_invalid_toml_is_rejected() -> None:
    result = parse_authorised_channel_users("schema_version = [")

    assert result.success is False
    assert result.issues[0].code == "authorised_users_invalid_toml"


def test_loader_reads_valid_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "authorised-users.toml"
    path.write_text(VALID, encoding="utf-8")
    path.chmod(0o600)

    result = load_authorised_channel_users(path)

    assert result.success is True
    assert result.users[0].name == "Owner"


def test_loader_rejects_missing_file(tmp_path: Path) -> None:
    result = load_authorised_channel_users(tmp_path / "missing.toml")

    assert result.success is False
    assert result.issues[0].code == "authorised_users_not_found"


def test_loader_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.toml"
    target.write_text(VALID, encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "authorised-users.toml"
    link.symlink_to(target)

    result = load_authorised_channel_users(link)

    assert result.success is False
    assert result.issues[0].code == "authorised_users_symlink_rejected"


def test_loader_rejects_group_or_world_writable_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "authorised-users.toml"
    path.write_text(VALID, encoding="utf-8")
    path.chmod(0o622)

    result = load_authorised_channel_users(path)

    assert result.success is False
    assert result.issues[0].code == "authorised_users_insecure_permissions"


def test_loader_requires_absolute_path() -> None:
    with pytest.raises(ValueError, match="must be absolute"):
        load_authorised_channel_users(Path("relative.toml"))


def test_result_contract_consistency() -> None:
    issue = AuthorisedUserConfigIssue(
        code="invalid",
        message="Invalid configuration.",
    )

    with pytest.raises(ValueError, match="must not contain issues"):
        AuthorisedUserConfigResult(
            success=True,
            users=(),
            issues=(issue,),
        )

    with pytest.raises(ValueError, match="must not contain users"):
        AuthorisedUserConfigResult(
            success=False,
            users=parse_authorised_channel_users(VALID).users,
            issues=(issue,),
        )
