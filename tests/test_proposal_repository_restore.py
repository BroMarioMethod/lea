"""Backup, restore, and reconstruction tests for proposal persistence."""

from datetime import UTC, datetime
from pathlib import Path
from shutil import copytree

from lea.actions import ActionProposal
from lea.runtime import (
    bootstrap_runtime,
    isolated_test_runtime_paths,
    runtime_proposal_repository,
)

FIRST_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"


def create_proposal(
    *,
    proposal_id: str,
    minute: int,
    description: str,
) -> ActionProposal:
    """Return one deterministic proposal."""
    return ActionProposal(
        proposal_id=proposal_id,
        action="task.create",
        parameters={"description": description},
        source="user",
        created_at=datetime(
            2026,
            7,
            21,
            12,
            minute,
            tzinfo=UTC,
        ),
        reason=f"Create {description}.",
    )


def populate_repository(
    root: Path,
) -> tuple[ActionProposal, ActionProposal]:
    """Bootstrap and populate one isolated runtime repository."""
    paths = isolated_test_runtime_paths(root)
    assert bootstrap_runtime(paths).success is True

    repository = runtime_proposal_repository(paths)

    first = create_proposal(
        proposal_id=FIRST_ID,
        minute=0,
        description="first restored task",
    )
    second = create_proposal(
        proposal_id=SECOND_ID,
        minute=1,
        description="second restored task",
    )

    assert repository.create(first).success is True
    assert repository.create(second).success is True

    return first, second


def restore_proposal_directory(
    *,
    source_root: Path,
    destination_root: Path,
) -> None:
    """Copy canonical proposal files into a fresh bootstrapped runtime."""
    source_paths = isolated_test_runtime_paths(source_root)
    destination_paths = isolated_test_runtime_paths(destination_root)

    assert bootstrap_runtime(destination_paths).success is True

    destination_paths.proposal_dir.rmdir()
    copytree(
        source_paths.proposal_dir,
        destination_paths.proposal_dir,
    )


def test_restored_repository_reads_without_hidden_state(
    tmp_path: Path,
) -> None:
    """Canonical Markdown alone should reconstruct exact proposals."""
    source_root = tmp_path / "source"
    restored_root = tmp_path / "restored"
    first, second = populate_repository(source_root)

    restore_proposal_directory(
        source_root=source_root,
        destination_root=restored_root,
    )

    restored_paths = isolated_test_runtime_paths(restored_root)
    restored = runtime_proposal_repository(restored_paths)

    first_result = restored.read(FIRST_ID)
    second_result = restored.read(SECOND_ID)

    assert first_result.success is True
    assert first_result.proposal == first
    assert second_result.success is True
    assert second_result.proposal == second


def test_restored_repository_lists_in_canonical_order(
    tmp_path: Path,
) -> None:
    """Restoration must not depend on original filesystem insertion order."""
    source_root = tmp_path / "source"
    restored_root = tmp_path / "restored"
    first, second = populate_repository(source_root)

    restore_proposal_directory(
        source_root=source_root,
        destination_root=restored_root,
    )

    restored = runtime_proposal_repository(isolated_test_runtime_paths(restored_root))
    result = restored.list_all()

    assert result.success is True
    assert result.proposals == (first, second)


def test_restored_repository_verifies_cleanly(
    tmp_path: Path,
) -> None:
    """An unmodified restored repository should pass verification."""
    source_root = tmp_path / "source"
    restored_root = tmp_path / "restored"
    populate_repository(source_root)

    restore_proposal_directory(
        source_root=source_root,
        destination_root=restored_root,
    )

    restored = runtime_proposal_repository(isolated_test_runtime_paths(restored_root))
    result = restored.verify()

    assert result.valid is True
    assert result.checked_documents == 2
    assert result.issues == ()


def test_restore_requires_no_database_or_index_files(
    tmp_path: Path,
) -> None:
    """Proposal reconstruction should use only canonical Markdown files."""
    source_root = tmp_path / "source"
    restored_root = tmp_path / "restored"
    populate_repository(source_root)

    source_paths = isolated_test_runtime_paths(source_root)

    assert tuple(source_paths.proposal_dir.glob("*.md"))
    assert tuple(source_paths.proposal_dir.glob("*.db")) == ()
    assert tuple(source_paths.proposal_dir.glob("*.sqlite")) == ()
    assert tuple(source_paths.proposal_dir.glob("*.json")) == ()

    restore_proposal_directory(
        source_root=source_root,
        destination_root=restored_root,
    )

    restored = runtime_proposal_repository(isolated_test_runtime_paths(restored_root))

    assert restored.verify().valid is True
    assert len(restored.list_all().proposals) == 2


def test_restored_corruption_is_detected(
    tmp_path: Path,
) -> None:
    """Verification should detect content corruption after restoration."""
    source_root = tmp_path / "source"
    restored_root = tmp_path / "restored"
    populate_repository(source_root)

    restore_proposal_directory(
        source_root=source_root,
        destination_root=restored_root,
    )

    restored_paths = isolated_test_runtime_paths(restored_root)
    corrupted = restored_paths.proposal_dir / f"{FIRST_ID}.md"
    corrupted.write_text(
        "# Corrupted proposal\n",
        encoding="utf-8",
    )

    result = runtime_proposal_repository(restored_paths).verify()

    assert result.valid is False
    assert result.checked_documents == 2
    assert result.issues[0].code == "proposal_malformed_document"
    assert result.issues[0].path == corrupted


def test_restored_unexpected_file_is_detected(
    tmp_path: Path,
) -> None:
    """Verification should expose unexpected restored artefacts."""
    source_root = tmp_path / "source"
    restored_root = tmp_path / "restored"
    populate_repository(source_root)

    restore_proposal_directory(
        source_root=source_root,
        destination_root=restored_root,
    )

    restored_paths = isolated_test_runtime_paths(restored_root)
    unexpected = restored_paths.proposal_dir / "backup-notes.txt"
    unexpected.write_text(
        "Unexpected restored artefact.",
        encoding="utf-8",
    )

    result = runtime_proposal_repository(restored_paths).verify()

    assert result.valid is False
    assert result.checked_documents == 2
    assert result.issues[0].code == "proposal_unexpected_file"
    assert result.issues[0].path == unexpected


def test_restored_temporary_file_is_detected(
    tmp_path: Path,
) -> None:
    """Interrupted-write artefacts should remain visible after restore."""
    source_root = tmp_path / "source"
    restored_root = tmp_path / "restored"
    populate_repository(source_root)

    restore_proposal_directory(
        source_root=source_root,
        destination_root=restored_root,
    )

    restored_paths = isolated_test_runtime_paths(restored_root)
    temporary = restored_paths.proposal_dir / f".{FIRST_ID}.restore.tmp"
    temporary.write_text(
        "Partial restored content.",
        encoding="utf-8",
    )

    result = runtime_proposal_repository(restored_paths).verify()

    assert result.valid is False
    assert result.checked_documents == 2
    assert result.issues[0].code == "proposal_temporary_file"
    assert result.issues[0].path == temporary


def test_restored_identity_mismatch_is_detected(
    tmp_path: Path,
) -> None:
    """Verification should catch proposal identity changes after restore."""
    source_root = tmp_path / "source"
    restored_root = tmp_path / "restored"
    populate_repository(source_root)

    restore_proposal_directory(
        source_root=source_root,
        destination_root=restored_root,
    )

    restored_paths = isolated_test_runtime_paths(restored_root)
    first_path = restored_paths.proposal_dir / f"{FIRST_ID}.md"
    second_path = restored_paths.proposal_dir / f"{SECOND_ID}.md"

    first_path.write_bytes(second_path.read_bytes())

    result = runtime_proposal_repository(restored_paths).verify()

    assert result.valid is False
    assert result.checked_documents == 2
    assert result.issues[0].code == "proposal_identity_mismatch"
    assert result.issues[0].path == first_path


def test_source_and_restored_repositories_are_independent(
    tmp_path: Path,
) -> None:
    """Changes after restoration must not affect the source backup."""
    source_root = tmp_path / "source"
    restored_root = tmp_path / "restored"
    populate_repository(source_root)

    restore_proposal_directory(
        source_root=source_root,
        destination_root=restored_root,
    )

    source_paths = isolated_test_runtime_paths(source_root)
    restored_paths = isolated_test_runtime_paths(restored_root)

    restored_file = restored_paths.proposal_dir / f"{FIRST_ID}.md"
    source_file = source_paths.proposal_dir / f"{FIRST_ID}.md"
    original_source = source_file.read_bytes()

    restored_file.write_text(
        "# Changed after restoration\n",
        encoding="utf-8",
    )

    assert source_file.read_bytes() == original_source
    assert runtime_proposal_repository(source_paths).verify().valid is True
    assert runtime_proposal_repository(restored_paths).verify().valid is False
