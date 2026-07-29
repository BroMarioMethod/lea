"""Deterministic Telegram controls for proposal interactions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from lea.adapters.telegram.contracts import (
    TELEGRAM_MAX_CALLBACK_DATA_BYTES,
    TelegramInlineButton,
    TelegramInlineKeyboard,
)
from lea.channels import ChannelControl, ChannelControlType


class TelegramCallbackAction(StrEnum):
    """Supported Telegram proposal callback actions."""

    APPROVE = "proposal.approve"
    EXECUTE = "proposal.execute"
    REJECT = "proposal.reject"
    CANCEL = "proposal.cancel"
    REVISE = "proposal.revise"


@dataclass(frozen=True, slots=True)
class TelegramControlIssue:
    """One deterministic Telegram control-construction problem."""

    code: str
    message: str
    field: str | None = None
    control_id: str | None = None

    def __post_init__(self) -> None:
        """Validate safe control issue fields."""
        if not self.code.strip():
            raise ValueError("Telegram control issue code must be non-empty.")

        if not self.message.strip():
            raise ValueError("Telegram control issue message must be non-empty.")

        if self.field is not None and not self.field.strip():
            raise ValueError(
                "Telegram control issue field must be non-empty when provided."
            )

        if self.control_id is not None:
            _validate_uuid(self.control_id, field_name="control_id")


@dataclass(frozen=True, slots=True)
class TelegramParsedCallbackData:
    """One validated proposal callback-data value."""

    action: TelegramCallbackAction
    proposal_id: str

    def __post_init__(self) -> None:
        """Validate the canonical proposal identifier."""
        _validate_uuid(self.proposal_id, field_name="proposal_id")


@dataclass(frozen=True, slots=True)
class TelegramCallbackDataResult:
    """Immutable result of parsing Telegram callback data."""

    success: bool
    callback: TelegramParsedCallbackData | None
    issues: tuple[TelegramControlIssue, ...]

    def __post_init__(self) -> None:
        """Enforce callback-data result consistency."""
        if self.success:
            if self.callback is None:
                raise ValueError(
                    "A successful Telegram callback-data result must "
                    "contain parsed callback data."
                )

            if self.issues:
                raise ValueError(
                    "A successful Telegram callback-data result must not "
                    "contain issues."
                )
            return

        if self.callback is not None:
            raise ValueError(
                "A failed Telegram callback-data result must not contain "
                "parsed callback data."
            )

        if not self.issues:
            raise ValueError(
                "A failed Telegram callback-data result must contain "
                "at least one issue."
            )


@dataclass(frozen=True, slots=True)
class TelegramControlResult:
    """Immutable result of converting channel controls to Telegram controls."""

    success: bool
    keyboard: TelegramInlineKeyboard | None
    issues: tuple[TelegramControlIssue, ...]

    def __post_init__(self) -> None:
        """Enforce control-result consistency."""
        if self.success:
            if self.keyboard is None:
                raise ValueError(
                    "A successful Telegram control result must contain a keyboard."
                )

            if self.issues:
                raise ValueError(
                    "A successful Telegram control result must not contain issues."
                )
            return

        if self.keyboard is not None:
            raise ValueError(
                "A failed Telegram control result must not contain a keyboard."
            )

        if not self.issues:
            raise ValueError(
                "A failed Telegram control result must contain at least one issue."
            )


_ACTION_ORDER = {
    TelegramCallbackAction.APPROVE: 0,
    TelegramCallbackAction.EXECUTE: 1,
    TelegramCallbackAction.REJECT: 2,
    TelegramCallbackAction.CANCEL: 3,
    TelegramCallbackAction.REVISE: 4,
}

_EXECUTION_CAPABILITIES = frozenset(
    {
        "Proposals.Execute.LowRisk",
        "Proposals.Execute.MediumRisk",
        "Proposals.Execute.HighRisk",
    }
)


def build_telegram_controls(
    controls: tuple[ChannelControl, ...],
) -> TelegramControlResult:
    """Convert channel-neutral proposal controls into one inline keyboard."""
    if not controls:
        return _failure(
            code="telegram_controls_missing",
            message="At least one channel control is required.",
        )

    parsed_controls: list[tuple[TelegramCallbackAction, ChannelControl, str]] = []
    issues: list[TelegramControlIssue] = []

    for index, control in enumerate(controls):
        result = _parse_control(control, index=index)

        if isinstance(result, TelegramControlIssue):
            issues.append(result)
            continue

        action, callback_data = result
        parsed_controls.append((action, control, callback_data))

    if issues:
        return TelegramControlResult(
            success=False,
            keyboard=None,
            issues=tuple(issues),
        )

    actions = tuple(action for action, _, _ in parsed_controls)

    if len(set(actions)) != len(actions):
        return _failure(
            code="telegram_control_action_duplicate",
            message="Telegram controls must not contain duplicate actions.",
            field="controls",
        )

    ordered = tuple(
        sorted(
            parsed_controls,
            key=lambda item: (
                _ACTION_ORDER[item[0]],
                item[1].label.casefold(),
                item[1].control_id,
            ),
        )
    )
    buttons = tuple(
        TelegramInlineButton(
            text=control.label,
            callback_data=callback_data,
        )
        for _, control, callback_data in ordered
    )

    return TelegramControlResult(
        success=True,
        keyboard=TelegramInlineKeyboard(
            rows=(buttons,),
        ),
        issues=(),
    )


def parse_telegram_callback_data(
    callback_data: str,
) -> TelegramCallbackDataResult:
    """Parse one compact proposal callback-data value."""
    if not isinstance(callback_data, str):
        raise TypeError("callback_data must be a string.")

    action_text, separator, proposal_id = callback_data.partition(":")

    if not separator or not action_text or not proposal_id:
        return _callback_failure(
            code="telegram_callback_data_invalid",
            message=("Telegram callback data must contain an action and proposal ID."),
            field="callback_data",
        )

    if ":" in proposal_id:
        return _callback_failure(
            code="telegram_callback_data_invalid",
            message="Telegram callback data contains too many separators.",
            field="callback_data",
        )

    try:
        action = TelegramCallbackAction(action_text)
    except ValueError:
        return _callback_failure(
            code="telegram_callback_action_unsupported",
            message="Telegram callback action is not supported.",
            field="callback_data",
        )

    try:
        parsed = TelegramParsedCallbackData(
            action=action,
            proposal_id=proposal_id,
        )
    except ValueError as error:
        return _callback_failure(
            code="telegram_callback_proposal_id_invalid",
            message=str(error),
            field="callback_data",
        )

    if len(callback_data.encode("utf-8")) > TELEGRAM_MAX_CALLBACK_DATA_BYTES:
        return _callback_failure(
            code="telegram_callback_data_oversized",
            message=("Telegram callback data exceeds the supported UTF-8 byte limit."),
            field="callback_data",
        )

    return TelegramCallbackDataResult(
        success=True,
        callback=parsed,
        issues=(),
    )


def _parse_control(
    control: ChannelControl,
    *,
    index: int,
) -> tuple[TelegramCallbackAction, str] | TelegramControlIssue:
    if control.control_type is not ChannelControlType.ACTION:
        return TelegramControlIssue(
            code="telegram_control_type_unsupported",
            message="Only action controls can be rendered for Telegram.",
            field=f"controls[{index}].control_type",
            control_id=control.control_id,
        )

    try:
        action = TelegramCallbackAction(control.action)
    except ValueError:
        return TelegramControlIssue(
            code="telegram_control_action_unsupported",
            message="The channel control action is not supported by Telegram.",
            field=f"controls[{index}].action",
            control_id=control.control_id,
        )

    if action is TelegramCallbackAction.EXECUTE:
        capability_valid = control.required_capability in _EXECUTION_CAPABILITIES
        capability_message = (
            "Execute controls must preserve one risk-specific proposal "
            "execution capability."
        )
    else:
        capability_valid = control.required_capability == "Proposals.Confirm"
        capability_message = (
            "Proposal decision controls must preserve the Proposals.Confirm capability."
        )

    if not capability_valid:
        return TelegramControlIssue(
            code="telegram_control_capability_invalid",
            message=capability_message,
            field=f"controls[{index}].required_capability",
            control_id=control.control_id,
        )

    proposal_id = control.parameters.get("proposal_id")

    if not isinstance(proposal_id, str):
        return TelegramControlIssue(
            code="telegram_control_proposal_id_missing",
            message="The channel control must contain a proposal_id string.",
            field=f"controls[{index}].parameters.proposal_id",
            control_id=control.control_id,
        )

    try:
        _validate_uuid(proposal_id, field_name="proposal_id")
    except ValueError as error:
        return TelegramControlIssue(
            code="telegram_control_proposal_id_invalid",
            message=str(error),
            field=f"controls[{index}].parameters.proposal_id",
            control_id=control.control_id,
        )

    extra_parameters = set(control.parameters) - {"proposal_id"}

    if extra_parameters:
        return TelegramControlIssue(
            code="telegram_control_parameters_unsupported",
            message=("Proposal controls must not contain unsupported parameters."),
            field=f"controls[{index}].parameters",
            control_id=control.control_id,
        )

    callback_data = f"{action.value}:{proposal_id}"

    if len(callback_data.encode("utf-8")) > TELEGRAM_MAX_CALLBACK_DATA_BYTES:
        return TelegramControlIssue(
            code="telegram_control_callback_data_oversized",
            message=(
                "The generated Telegram callback data exceeds the UTF-8 byte limit."
            ),
            field=f"controls[{index}].parameters.proposal_id",
            control_id=control.control_id,
        )

    return action, callback_data


def _validate_uuid(value: str, *, field_name: str) -> None:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID.") from error

    if str(parsed) != value:
        raise ValueError(f"{field_name} must use canonical lower-case UUID format.")


def _callback_failure(
    *,
    code: str,
    message: str,
    field: str | None = None,
) -> TelegramCallbackDataResult:
    return TelegramCallbackDataResult(
        success=False,
        callback=None,
        issues=(
            TelegramControlIssue(
                code=code,
                message=message,
                field=field,
            ),
        ),
    )


def _failure(
    *,
    code: str,
    message: str,
    field: str | None = None,
) -> TelegramControlResult:
    return TelegramControlResult(
        success=False,
        keyboard=None,
        issues=(
            TelegramControlIssue(
                code=code,
                message=message,
                field=field,
            ),
        ),
    )
