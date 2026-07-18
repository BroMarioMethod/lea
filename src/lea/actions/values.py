"""JSON-compatible value handling for action contracts."""

import math
from collections.abc import Mapping
from types import MappingProxyType

from lea.actions.errors import ActionContractError

type FrozenJsonValue = (
    str
    | int
    | float
    | bool
    | None
    | tuple["FrozenJsonValue", ...]
    | Mapping[str, "FrozenJsonValue"]
)


def freeze_json_value(
    value: object,
    *,
    path: str = "parameters",
) -> FrozenJsonValue:
    """Validate and convert a value into an immutable JSON-compatible form."""
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ActionContractError(f"{path} must not contain non-finite numbers.")

        return value

    if isinstance(value, list):
        return tuple(
            freeze_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )

    if isinstance(value, Mapping):
        frozen: dict[str, FrozenJsonValue] = {}

        for key, item in value.items():
            if not isinstance(key, str):
                raise ActionContractError(
                    f"{path} must contain only string mapping keys."
                )

            child_path = f"{path}.{key}"
            frozen[key] = freeze_json_value(item, path=child_path)

        return MappingProxyType(frozen)

    raise ActionContractError(
        f"{path} contains an unsupported value of type {type(value).__name__}."
    )


def freeze_parameters(
    parameters: Mapping[str, object],
) -> Mapping[str, FrozenJsonValue]:
    """Validate and deeply freeze action parameters."""
    frozen = freeze_json_value(parameters)

    if not isinstance(frozen, Mapping):
        raise ActionContractError("Action parameters must be a mapping.")

    return frozen
