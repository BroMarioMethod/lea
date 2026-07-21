"""Safe runtime configuration initialisation for LEA."""

from pathlib import Path

from lea.runtime.contracts import (
    RuntimeConfig,
    RuntimeInitialisationResult,
    RuntimeInitialisationStatus,
)
from lea.runtime.serialisation import write_runtime_config


def initialise_runtime_config(
    config: RuntimeConfig,
    *,
    dry_run: bool = False,
) -> RuntimeInitialisationResult:
    """Initialise one runtime configuration without overwriting."""
    destination = config.paths.config_file

    existing_result = _inspect_existing_destination(
        destination,
        dry_run=dry_run,
    )

    if existing_result is not None:
        return existing_result

    parent_result = _inspect_parent_directory(
        destination,
        dry_run=dry_run,
    )

    if parent_result is not None:
        return parent_result

    if dry_run:
        return RuntimeInitialisationResult(
            success=True,
            dry_run=True,
            status=RuntimeInitialisationStatus.WOULD_CREATE,
            destination=destination,
            message="The runtime configuration would be created.",
        )

    try:
        write_runtime_config(
            config,
            destination=destination,
            overwrite=False,
        )
    except FileExistsError:
        return RuntimeInitialisationResult(
            success=False,
            dry_run=False,
            status=RuntimeInitialisationStatus.ALREADY_EXISTS,
            destination=destination,
            message=(
                "The runtime configuration already exists and was not overwritten."
            ),
        )
    except IsADirectoryError:
        return RuntimeInitialisationResult(
            success=False,
            dry_run=False,
            status=RuntimeInitialisationStatus.CONFLICT,
            destination=destination,
            message=(
                "The runtime configuration destination is occupied by a directory."
            ),
        )
    except OSError:
        return RuntimeInitialisationResult(
            success=False,
            dry_run=False,
            status=RuntimeInitialisationStatus.FAILED,
            destination=destination,
            message=("The runtime configuration could not be created."),
        )

    return RuntimeInitialisationResult(
        success=True,
        dry_run=False,
        status=RuntimeInitialisationStatus.CREATED,
        destination=destination,
        message="The runtime configuration was created.",
    )


def _inspect_existing_destination(
    destination: Path,
    *,
    dry_run: bool,
) -> RuntimeInitialisationResult | None:
    """Inspect an existing initialisation destination."""
    if not destination.exists():
        return None

    if destination.is_file():
        return RuntimeInitialisationResult(
            success=False,
            dry_run=dry_run,
            status=RuntimeInitialisationStatus.ALREADY_EXISTS,
            destination=destination,
            message=(
                "The runtime configuration already exists and would not be overwritten."
            ),
        )

    return RuntimeInitialisationResult(
        success=False,
        dry_run=dry_run,
        status=RuntimeInitialisationStatus.CONFLICT,
        destination=destination,
        message=(
            "The runtime configuration destination exists but is not a regular file."
        ),
    )


def _inspect_parent_directory(
    destination: Path,
    *,
    dry_run: bool,
) -> RuntimeInitialisationResult | None:
    """Confirm that the destination parent is available."""
    parent = destination.parent

    if not parent.exists():
        return RuntimeInitialisationResult(
            success=False,
            dry_run=dry_run,
            status=RuntimeInitialisationStatus.FAILED,
            destination=destination,
            message=("The configuration destination parent directory does not exist."),
        )

    if not parent.is_dir():
        return RuntimeInitialisationResult(
            success=False,
            dry_run=dry_run,
            status=RuntimeInitialisationStatus.CONFLICT,
            destination=destination,
            message=("The configuration destination parent is not a directory."),
        )

    return None
