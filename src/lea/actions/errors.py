"""Action contract exceptions."""

from lea.errors import LeaError


class ActionContractError(LeaError):
    """Raised when action-contract data is invalid."""
