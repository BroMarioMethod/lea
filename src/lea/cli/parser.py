"""Argument parsing for the LEA Local CLI."""

import argparse
from pathlib import Path

from lea.actions import ActionStatus
from lea.runtime import RuntimeProfile


def create_local_cli_parser() -> argparse.ArgumentParser:
    """Create the root Local CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="lea",
        description="Use LEA through its deterministic local interface.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write one deterministic JSON result.",
    )
    parser.add_argument(
        "--config",
        type=_absolute_path,
        metavar="PATH",
        help=(
            "Absolute path to the LEA TOML configuration. "
            "Defaults to /etc/lea/lea.toml for the system profile."
        ),
    )
    parser.add_argument(
        "--profile",
        choices=tuple(profile.value for profile in RuntimeProfile),
        help="Require the loaded configuration to use this runtime profile.",
    )
    parser.add_argument(
        "--no-colour",
        action="store_true",
        help="Disable colour in human-readable output.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "status",
        help="Inspect LEA runtime and provider status.",
    )

    task_parser = subparsers.add_parser(
        "task",
        help="Manage tasks through the configured task provider.",
    )
    _add_task_subcommands(task_parser)

    proposal_parser = subparsers.add_parser(
        "proposal",
        help="Review and decide persistent action proposals.",
    )
    _add_proposal_subcommands(proposal_parser)

    return parser


def _absolute_path(value: str) -> Path:
    """Parse one explicit absolute filesystem path."""
    path = Path(value)

    if not path.is_absolute():
        raise argparse.ArgumentTypeError("PATH must be absolute.")

    return path


def _add_task_subcommands(parser: argparse.ArgumentParser) -> None:
    """Add the initial task command grammar."""
    subparsers = parser.add_subparsers(
        dest="task_command",
        required=True,
    )

    list_parser = subparsers.add_parser(
        "list",
        help="List tasks.",
    )
    list_parser.add_argument(
        "--uuid",
        help="Canonical task UUID.",
    )
    list_parser.add_argument(
        "--status",
        choices=("pending", "completed", "deleted"),
        default="pending",
        help="Task status filter.",
    )
    list_parser.add_argument(
        "--project",
        help="Exact project filter.",
    )
    list_parser.add_argument(
        "--tag",
        help="Exact tag filter.",
    )

    create_parser = subparsers.add_parser(
        "create",
        help="Create one task.",
    )
    create_parser.add_argument(
        "--description",
        required=True,
        help="Task description.",
    )
    create_parser.add_argument(
        "--project",
        help="Task project.",
    )
    create_parser.add_argument(
        "--priority",
        choices=("H", "M", "L"),
        help="Task priority.",
    )
    create_parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Task tag. May be supplied more than once.",
    )

    modify_parser = subparsers.add_parser(
        "modify",
        help="Modify one exact task.",
    )
    modify_parser.add_argument(
        "uuid",
        help="Canonical task UUID.",
    )
    modify_parser.add_argument(
        "--description",
        help="Replacement task description.",
    )
    modify_parser.add_argument(
        "--project",
        help="Replacement task project.",
    )
    modify_parser.add_argument(
        "--priority",
        choices=("H", "M", "L"),
        help="Replacement task priority.",
    )
    modify_parser.add_argument(
        "--add-tag",
        action="append",
        default=[],
        help="Tag to add. May be supplied more than once.",
    )
    modify_parser.add_argument(
        "--remove-tag",
        action="append",
        default=[],
        help="Tag to remove. May be supplied more than once.",
    )

    for command, help_text in (
        ("complete", "Complete one exact task."),
        ("delete", "Delete one exact task without purging provider storage."),
    ):
        command_parser = subparsers.add_parser(
            command,
            help=help_text,
        )
        command_parser.add_argument(
            "uuid",
            help="Canonical task UUID.",
        )


def _add_proposal_subcommands(parser: argparse.ArgumentParser) -> None:
    """Add the initial proposal command grammar."""
    subparsers = parser.add_subparsers(
        dest="proposal_command",
        required=True,
    )
    list_parser = subparsers.add_parser(
        "list",
        help="List persistent proposals.",
    )
    list_parser.add_argument(
        "--status",
        choices=tuple(status.value for status in ActionStatus),
        help="Filter by exact proposal status.",
    )
    list_parser.add_argument(
        "--action-type",
        help="Filter by exact namespaced action type.",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of proposals to return.",
    )

    for command, help_text in (
        ("show", "Show one persistent proposal."),
        ("execute", "Execute one approved persistent proposal."),
    ):
        command_parser = subparsers.add_parser(
            command,
            help=help_text,
        )
        command_parser.add_argument(
            "proposal_id",
            help="Stable proposal identifier.",
        )

    approve_parser = subparsers.add_parser(
        "approve",
        help="Approve one persistent proposal.",
    )
    approve_parser.add_argument(
        "proposal_id",
        help="Stable proposal identifier.",
    )
    approve_parser.add_argument(
        "--actor",
        required=True,
        help="Human actor recording the approval.",
    )
    approve_parser.add_argument(
        "--reason",
        help="Optional human-readable approval reason.",
    )

    cancel_parser = subparsers.add_parser(
        "cancel",
        help="Cancel one persistent proposal.",
    )
    cancel_parser.add_argument(
        "proposal_id",
        help="Stable proposal identifier.",
    )
    cancel_parser.add_argument(
        "--actor",
        required=True,
        help="Human actor recording the cancellation.",
    )
    cancel_parser.add_argument(
        "--reason",
        help="Optional human-readable cancellation reason.",
    )

    reject_parser = subparsers.add_parser(
        "reject",
        help="Reject one persistent proposal.",
    )
    reject_parser.add_argument(
        "proposal_id",
        help="Stable proposal identifier.",
    )
    reject_parser.add_argument(
        "--actor",
        required=True,
        help="Human actor recording the rejection.",
    )
    reject_parser.add_argument(
        "--reason",
        help="Optional human-readable rejection reason.",
    )
