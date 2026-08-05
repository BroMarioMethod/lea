"""Action contract exceptions."""

from lea.errors import LeaError


class ActionContractError(LeaError):
    """Raised when action-contract data is invalid."""


class ActionHandlerFailure(RuntimeError):
    """Redaction-safe expected failure reported by an action handler."""

    def __init__(self, *, code: str, message: str) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be non-empty.")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be non-empty.")
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
