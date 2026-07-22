"""Argument parsing for the LEA Local CLI."""

import argparse


def create_local_cli_parser() -> argparse.ArgumentParser:
    """Create the root Local CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="lea",
        description="Use LEA through its deterministic local interface.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Write one deterministic JSON result."
    )
    parser.add_argument(
        "--no-colour",
        action="store_true",
        help="Disable colour in human-readable output.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Inspect LEA runtime and provider status.")
    task_parser = subparsers.add_parser(
        "task", help="Manage tasks through the configured task provider."
    )
    _add_task_subcommands(task_parser)
    proposal_parser = subparsers.add_parser(
        "proposal", help="Review and decide persistent action proposals."
    )
    _add_proposal_subcommands(proposal_parser)
    return parser


def _add_task_subcommands(parser: argparse.ArgumentParser) -> None:
    """Add the initial task command grammar."""
    subparsers = parser.add_subparsers(dest="task_command", required=True)
    subparsers.add_parser("list", help="List tasks.")
    create_parser = subparsers.add_parser("create", help="Create one task.")
    create_parser.add_argument("--description", required=True, help="Task description.")
    for command, help_text in (
        ("modify", "Modify one exact task."),
        ("complete", "Complete one exact task."),
        ("delete", "Delete one exact task without purging provider storage."),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("uuid", help="Canonical task UUID.")


def _add_proposal_subcommands(parser: argparse.ArgumentParser) -> None:
    """Add the initial proposal command grammar."""
    subparsers = parser.add_subparsers(dest="proposal_command", required=True)
    subparsers.add_parser("list", help="List persistent proposals.")
    for command, help_text in (
        ("show", "Show one persistent proposal."),
        ("approve", "Approve one persistent proposal."),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("proposal_id", help="Stable proposal identifier.")
    reject_parser = subparsers.add_parser(
        "reject", help="Reject one persistent proposal."
    )
    reject_parser.add_argument("proposal_id", help="Stable proposal identifier.")
    reject_parser.add_argument(
        "--reason", help="Optional human-readable rejection reason."
    )
