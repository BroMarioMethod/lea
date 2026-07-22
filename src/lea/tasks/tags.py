"""Provider-neutral task-tag normalisation."""

import re

_TASK_TAG_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def normalise_task_tag(value: str) -> str:
    """Return one canonical task tag or raise a validation error."""
    normalised = value.strip().replace("-", "_")

    if not normalised:
        raise ValueError("task tags must not be blank.")

    if _TASK_TAG_PATTERN.fullmatch(normalised) is None:
        raise ValueError(
            "task tags must start with a letter or underscore and contain "
            "only letters, digits and underscores."
        )

    return normalised


def validate_canonical_task_tag(value: str) -> None:
    """Require one tag to already use canonical task-tag form."""
    if normalise_task_tag(value) != value:
        raise ValueError("provider task tags must already use canonical form.")
