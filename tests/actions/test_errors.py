"""Tests for action-contract exceptions."""

from lea.actions import ActionContractError
from lea.errors import LeaError


def test_action_contract_error_is_a_lea_error() -> None:
    """Contract failures should be handled as expected LEA failures."""
    assert issubclass(ActionContractError, LeaError)
