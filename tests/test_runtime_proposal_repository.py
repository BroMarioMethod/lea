"""Integration tests for runtime-backed proposal persistence."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lea.actions import ActionProposal
from lea.runtime import (
    bootstrap_runtime,
    isolated_test_runtime_config,
    isolated_test_runtime_paths,
    runtime_proposal_repository,
)

PROPOSAL_ID = "4b10f26d-0c54-4f3d-a14c-bce8a743116f"


def create_proposal() -> ActionProposal:
    """Return one deterministic proposal."""
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        action="task.create",
        parameters={
            "description": "Runtime integration task",
        },
        source="user",
        created_at=datetime(
            2026,
            7,
            21,
            12,
            0,
            tzinfo=UTC,
        ),
        reason=("Persist this proposal through the configured runtime repository."),
    )


def test_repository_uses_runtime_paths(
    tmp_path: Path,
) -> None:
    """Runtime paths should select the canonical proposal directory."""
    paths = isolated_test_runtime_paths(tmp_path)

    repository = runtime_proposal_repository(paths)

    assert repository.root == paths.proposal_dir


def test_repository_uses_runtime_configuration(
    tmp_path: Path,
) -> None:
    """Runtime configuration should select its proposal directory."""
    config = isolated_test_runtime_config(tmp_path)

    repository = runtime_proposal_repository(config)

    assert repository.root == config.paths.proposal_dir


def test_repository_does_not_bootstrap_runtime_implicitly(
    tmp_path: Path,
) -> None:
    """Repository construction must not create runtime directories."""
    paths = isolated_test_runtime_paths(tmp_path)
    repository = runtime_proposal_repository(paths)

    result = repository.create(create_proposal())

    assert result.success is False
    assert result.issues[0].code == "proposal_directory_missing"
    assert paths.proposal_dir.exists() is False


def test_bootstrapped_runtime_supports_proposal_creation(
    tmp_path: Path,
) -> None:
    """Runtime bootstrap should prepare the persistent repository."""
    paths = isolated_test_runtime_paths(tmp_path)

    bootstrap = bootstrap_runtime(paths)
    repository = runtime_proposal_repository(paths)
    result = repository.create(create_proposal())

    assert bootstrap.success is True
    assert result.success is True
    assert result.path == paths.proposal_dir / f"{PROPOSAL_ID}.md"
    assert result.path.is_file()


def test_runtime_repository_supports_exact_read(
    tmp_path: Path,
) -> None:
    """A bootstrapped runtime should read persisted proposals."""
    paths = isolated_test_runtime_paths(tmp_path)
    assert bootstrap_runtime(paths).success is True

    repository = runtime_proposal_repository(paths)
    proposal = create_proposal()

    assert repository.create(proposal).success is True

    result = repository.read(PROPOSAL_ID)

    assert result.success is True
    assert result.proposal == proposal


def test_runtime_repository_supports_listing(
    tmp_path: Path,
) -> None:
    """A bootstrapped runtime should list persisted proposals."""
    config = isolated_test_runtime_config(tmp_path)
    assert bootstrap_runtime(config.paths).success is True

    repository = runtime_proposal_repository(config)
    proposal = create_proposal()

    assert repository.create(proposal).success is True

    result = repository.list_all()

    assert result.success is True
    assert result.proposals == (proposal,)


def test_runtime_repository_supports_verification(
    tmp_path: Path,
) -> None:
    """A bootstrapped runtime repository should verify cleanly."""
    config = isolated_test_runtime_config(tmp_path)
    assert bootstrap_runtime(config.paths).success is True

    repository = runtime_proposal_repository(config)

    assert repository.create(create_proposal()).success is True

    result = repository.verify()

    assert result.valid is True
    assert result.checked_documents == 1
    assert result.issues == ()


def test_runtime_repository_persists_across_instances(
    tmp_path: Path,
) -> None:
    """Repository instances should share canonical runtime storage."""
    paths = isolated_test_runtime_paths(tmp_path)
    assert bootstrap_runtime(paths).success is True

    writer = runtime_proposal_repository(paths)
    proposal = create_proposal()

    assert writer.create(proposal).success is True

    reader = runtime_proposal_repository(paths)
    result = reader.read(PROPOSAL_ID)

    assert result.success is True
    assert result.proposal == proposal


def test_runtime_repository_fsync_option_is_forwarded(
    tmp_path: Path,
) -> None:
    """Explicit synchronisation should work through integration."""
    paths = isolated_test_runtime_paths(tmp_path)
    assert bootstrap_runtime(paths).success is True

    repository = runtime_proposal_repository(
        paths,
        fsync=True,
    )

    result = repository.create(create_proposal())

    assert result.success is True
    assert result.path is not None
    assert result.path.is_file()


def test_runtime_repository_rejects_unrelated_values() -> None:
    """Integration must reject values outside runtime contracts."""
    with pytest.raises(
        TypeError,
        match="RuntimeConfig or RuntimePaths",
    ):
        runtime_proposal_repository(
            object(),  # type: ignore[arg-type]
        )
