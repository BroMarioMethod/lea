"""Tests for deterministic Telegram proposal controls."""

from dataclasses import FrozenInstanceError

import pytest

from lea.adapters.telegram import (
    TelegramCallbackAction,
    TelegramCallbackDataResult,
    TelegramControlIssue,
    TelegramControlResult,
    TelegramParsedCallbackData,
    build_telegram_controls,
    parse_telegram_callback_data,
)
from lea.channels import (
    ChannelControl,
    ChannelControlType,
)

PROPOSAL_ID = "11111111-1111-4111-8111-111111111111"
CONTROL_IDS = {
    "proposal.approve": "21111111-1111-4111-8111-111111111111",
    "proposal.reject": "31111111-1111-4111-8111-111111111111",
    "proposal.cancel": "41111111-1111-4111-8111-111111111111",
    "proposal.revise": "51111111-1111-4111-8111-111111111111",
}


def _control(
    action: str,
    *,
    label: str | None = None,
    proposal_id: object = PROPOSAL_ID,
    required_capability: str = "Proposals.Confirm",
    parameters: dict[str, object] | None = None,
) -> ChannelControl:
    return ChannelControl(
        control_id=CONTROL_IDS.get(
            action,
            "61111111-1111-4111-8111-111111111111",
        ),
        label=label or action.rsplit(".", maxsplit=1)[-1].title(),
        control_type=ChannelControlType.ACTION,
        action=action,
        parameters=(
            parameters if parameters is not None else {"proposal_id": proposal_id}
        ),
        required_capability=required_capability,
    )


def test_controls_are_rendered_in_deterministic_action_order() -> None:
    result = build_telegram_controls(
        (
            _control("proposal.revise"),
            _control("proposal.cancel"),
            _control("proposal.approve"),
            _control("proposal.reject"),
        )
    )

    assert result.success is True
    assert result.keyboard is not None
    assert tuple(button.callback_data for button in result.keyboard.rows[0]) == (
        f"proposal.approve:{PROPOSAL_ID}",
        f"proposal.reject:{PROPOSAL_ID}",
        f"proposal.cancel:{PROPOSAL_ID}",
        f"proposal.revise:{PROPOSAL_ID}",
    )


def test_control_labels_are_preserved() -> None:
    result = build_telegram_controls(
        (_control("proposal.approve", label="Approve proposal"),)
    )

    assert result.keyboard is not None
    assert result.keyboard.rows[0][0].text == "Approve proposal"


@pytest.mark.parametrize(
    "action",
    [
        TelegramCallbackAction.APPROVE,
        TelegramCallbackAction.REJECT,
        TelegramCallbackAction.CANCEL,
        TelegramCallbackAction.REVISE,
    ],
)
def test_callback_data_round_trip(
    action: TelegramCallbackAction,
) -> None:
    callback_data = f"{action.value}:{PROPOSAL_ID}"

    result = parse_telegram_callback_data(callback_data)

    assert result.success is True
    assert result.callback == TelegramParsedCallbackData(
        action=action,
        proposal_id=PROPOSAL_ID,
    )


def test_approve_control_does_not_imply_execution() -> None:
    result = build_telegram_controls((_control("proposal.approve"),))

    assert result.keyboard is not None
    callback_data = result.keyboard.rows[0][0].callback_data
    assert callback_data.startswith("proposal.approve:")
    assert "execute" not in callback_data


def test_revision_uses_replacement_request_action() -> None:
    result = parse_telegram_callback_data(f"proposal.revise:{PROPOSAL_ID}")

    assert result.callback is not None
    assert result.callback.action is TelegramCallbackAction.REVISE


def test_duplicate_actions_are_rejected() -> None:
    first = _control("proposal.approve", label="Approve")
    duplicate = ChannelControl(
        control_id="71111111-1111-4111-8111-111111111111",
        label="Approve again",
        control_type=ChannelControlType.ACTION,
        action="proposal.approve",
        parameters={"proposal_id": PROPOSAL_ID},
        required_capability="Proposals.Confirm",
    )

    result = build_telegram_controls((first, duplicate))

    assert result.success is False
    assert result.issues[0].code == "telegram_control_action_duplicate"


def test_unsupported_action_is_rejected() -> None:
    result = build_telegram_controls((_control("proposal.execute"),))

    assert result.success is False
    assert result.issues[0].code == "telegram_control_action_unsupported"


def test_wrong_capability_is_rejected() -> None:
    result = build_telegram_controls(
        (
            _control(
                "proposal.approve",
                required_capability="Proposals.Execute.LowRisk",
            ),
        )
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_control_capability_invalid"


@pytest.mark.parametrize(
    "proposal_id",
    ["not-a-uuid", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"],
)
def test_invalid_control_proposal_id_is_rejected(
    proposal_id: str,
) -> None:
    result = build_telegram_controls(
        (_control("proposal.approve", proposal_id=proposal_id),)
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_control_proposal_id_invalid"


def test_missing_control_proposal_id_is_rejected() -> None:
    result = build_telegram_controls(
        (
            _control(
                "proposal.approve",
                parameters={},
            ),
        )
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_control_proposal_id_missing"


def test_extra_control_parameters_are_rejected() -> None:
    result = build_telegram_controls(
        (
            _control(
                "proposal.approve",
                parameters={
                    "proposal_id": PROPOSAL_ID,
                    "execute": True,
                },
            ),
        )
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_control_parameters_unsupported"


@pytest.mark.parametrize(
    ("callback_data", "code"),
    [
        ("proposal.approve", "telegram_callback_data_invalid"),
        (
            f"proposal.execute:{PROPOSAL_ID}",
            "telegram_callback_action_unsupported",
        ),
        (
            "proposal.approve:not-a-uuid",
            "telegram_callback_proposal_id_invalid",
        ),
        (
            f"proposal.approve:{PROPOSAL_ID}:extra",
            "telegram_callback_data_invalid",
        ),
    ],
)
def test_invalid_callback_data_is_rejected(
    callback_data: str,
    code: str,
) -> None:
    result = parse_telegram_callback_data(callback_data)

    assert result.success is False
    assert result.issues[0].code == code


def test_empty_control_collection_is_rejected() -> None:
    result = build_telegram_controls(())

    assert result.success is False
    assert result.issues[0].code == "telegram_controls_missing"


def test_result_contracts_enforce_consistency() -> None:
    issue = TelegramControlIssue(
        code="invalid",
        message="Invalid control.",
    )

    with pytest.raises(ValueError, match="must contain a keyboard"):
        TelegramControlResult(
            success=True,
            keyboard=None,
            issues=(),
        )

    with pytest.raises(ValueError, match="must contain parsed callback data"):
        TelegramCallbackDataResult(
            success=True,
            callback=None,
            issues=(),
        )

    with pytest.raises(ValueError, match="must contain at least one issue"):
        TelegramControlResult(
            success=False,
            keyboard=None,
            issues=(),
        )

    assert issue.code == "invalid"


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (
            lambda: TelegramParsedCallbackData(
                action=TelegramCallbackAction.APPROVE,
                proposal_id=PROPOSAL_ID,
            ),
            "proposal_id",
        ),
        (
            lambda: TelegramControlIssue(
                code="invalid",
                message="Invalid control.",
            ),
            "code",
        ),
    ],
)
def test_control_contracts_are_immutable(
    factory: object,
    field_name: str,
) -> None:
    value = factory()  # type: ignore[operator]

    with pytest.raises(FrozenInstanceError):
        setattr(value, field_name, "changed")
