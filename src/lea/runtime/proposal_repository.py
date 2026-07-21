"""Runtime integration for persistent proposal repositories."""

from lea.proposals import MarkdownProposalRepository
from lea.runtime.contracts import RuntimeConfig, RuntimePaths


def runtime_proposal_repository(
    runtime: RuntimeConfig | RuntimePaths,
    *,
    fsync: bool = False,
) -> MarkdownProposalRepository:
    """Return the proposal repository configured for one LEA runtime."""
    if isinstance(runtime, RuntimeConfig):
        paths = runtime.paths
    elif isinstance(runtime, RuntimePaths):
        paths = runtime
    else:
        raise TypeError("runtime must be a RuntimeConfig or RuntimePaths value.")

    return MarkdownProposalRepository(
        paths.proposal_dir,
        create_parents=False,
        fsync=fsync,
    )
