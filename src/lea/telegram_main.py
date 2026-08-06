"""Executable foreground entry point for the LEA Telegram worker."""

from __future__ import annotations

import os
import signal
import sys
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import TextIO, cast
from uuid import uuid4

from lea.actions import ActionHandlerRegistry
from lea.adapters.khal import (
    KhalCalendarProviderFactoryConfig,
    build_khal_calendar_provider,
)
from lea.adapters.telegram.bot_api import telegram_bot_api_transport
from lea.adapters.telegram.worker import (
    TelegramWorkerConfig,
    TelegramWorkerDependencies,
    TelegramWorkerResult,
    run_telegram_worker,
)
from lea.audit import IntegrityJsonlAuditStore, generate_event_id
from lea.calendars import CalendarProvider, CalendarProviderIssue
from lea.channels.handlers import (
    ChannelHandlerDependencies,
    build_default_channel_application,
)
from lea.orchestration import ActionOrchestrator
from lea.proposals import ProposalSubmissionService
from lea.runtime.contracts import RuntimeConfig, RuntimeProfile
from lea.runtime.health import check_runtime_health
from lea.runtime.loader import load_runtime_config
from lea.runtime.proposal_repository import runtime_proposal_repository
from lea.runtime.telegram import (
    TelegramRuntimeConfig,
    TelegramRuntimeResult,
    build_telegram_runtime,
)

EXIT_SUCCESS = 0
EXIT_APPLICATION_ERROR = 1
EXIT_CONFIGURATION_ERROR = 2
EXIT_INTERNAL_ERROR = 70

_RUNTIME_CONFIG_ENV = "LEA_RUNTIME_CONFIG"
_TELEGRAM_CONFIG_ENV = "LEA_TELEGRAM_CONFIG"
_SYSTEM_CALENDAR_INSTALLATION_RECORD = Path(
    "/var/lib/lea/install/calendar-toolchain.json"
)
_SYSTEM_CALENDAR_TOOLS_ROOT = Path("/opt/lea-tools/calendar")
_SYSTEM_CALENDAR_CONFIGURATION_DIRECTORY = Path("/etc/lea/calendar")
_SYSTEM_CALENDAR_STATE_ROOT = Path("/var/lib/lea/calendar")
_TELEGRAM_FIELDS = frozenset(
    {
        "enabled",
        "bot_username",
        "authorised_users_file",
        "offset_file",
        "poll_timeout_seconds",
        "fetch_limit",
    }
)


TelegramWorkerRunner = Callable[
    [TelegramWorkerConfig, TelegramWorkerDependencies],
    TelegramWorkerResult,
]
"""Callable boundary for foreground worker execution."""

TelegramRuntimeBuilder = Callable[
    [RuntimeConfig, TelegramRuntimeConfig],
    TelegramRuntimeResult,
]
"""Callable boundary for Telegram runtime construction."""


@dataclass(frozen=True, slots=True)
class TelegramCalendarProviderBuildResult:
    """Result of constructing the optional Telegram calendar provider."""

    success: bool
    provider: CalendarProvider | None
    issues: tuple[CalendarProviderIssue, ...]

    def __post_init__(self) -> None:
        """Validate runtime-provider result consistency."""
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if self.success:
            if self.provider is None:
                raise ValueError(
                    "A successful calendar provider build must contain a provider."
                )

            if self.issues:
                raise ValueError(
                    "A successful calendar provider build must not contain issues."
                )

            return

        if self.provider is not None:
            raise ValueError(
                "A failed calendar provider build must not contain a provider."
            )

        if not self.issues:
            raise ValueError("A failed calendar provider build must contain an issue.")


CalendarProviderBuilder = Callable[
    [RuntimeConfig],
    TelegramCalendarProviderBuildResult,
]
"""Callable boundary for production calendar-provider construction."""


@dataclass(slots=True)
class TelegramStopFlag:
    """Mutable cooperative signal flag owned by the process boundary."""

    requested: bool = False

    def __call__(self) -> bool:
        """Return whether process shutdown was requested."""
        return self.requested

    def request(
        self,
        _signum: int,
        _frame: FrameType | None,
    ) -> None:
        """Request cooperative shutdown."""
        self.requested = True


def load_telegram_runtime_config(
    source_path: Path,
) -> TelegramRuntimeConfig:
    """Load strict Telegram worker TOML from one absolute file."""
    if not source_path.is_absolute():
        raise ValueError("Telegram configuration path must be absolute.")

    try:
        contents = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("Telegram configuration could not be read.") from error

    try:
        raw = tomllib.loads(contents)
    except tomllib.TOMLDecodeError as error:
        raise ValueError("Telegram configuration is not valid TOML.") from error

    if set(raw) != {"telegram"}:
        raise ValueError(
            "Telegram configuration must contain only the [telegram] table."
        )

    section = raw["telegram"]

    if not isinstance(section, dict):
        raise ValueError("Telegram configuration [telegram] must be a table.")

    data = cast(dict[str, object], section)

    if set(data) != _TELEGRAM_FIELDS:
        raise ValueError("Telegram configuration contains missing or unknown fields.")

    try:
        return TelegramRuntimeConfig(
            enabled=_boolean(data["enabled"], field="enabled"),
            bot_username=_text(data["bot_username"], field="bot_username"),
            authorised_users_file=_absolute_path(
                data["authorised_users_file"],
                field="authorised_users_file",
            ),
            offset_file=_absolute_path(
                data["offset_file"],
                field="offset_file",
            ),
            poll_timeout_seconds=_integer(
                data["poll_timeout_seconds"],
                field="poll_timeout_seconds",
            ),
            fetch_limit=_integer(
                data["fetch_limit"],
                field="fetch_limit",
            ),
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"Telegram configuration is invalid: {error}") from error


def execute(
    environment: Mapping[str, str],
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    worker_runner: TelegramWorkerRunner = run_telegram_worker,
    runtime_builder: TelegramRuntimeBuilder | None = None,
    calendar_provider_builder: CalendarProviderBuilder | None = None,
    register_signal: Callable[..., object] = signal.signal,
) -> int:
    """Execute the Telegram worker from explicit process inputs."""
    runtime_path = _environment_path(environment, _RUNTIME_CONFIG_ENV)
    telegram_path = _environment_path(environment, _TELEGRAM_CONFIG_ENV)

    if runtime_path is None or telegram_path is None:
        stderr.write(
            "Telegram worker configuration error: "
            f"{_RUNTIME_CONFIG_ENV} and {_TELEGRAM_CONFIG_ENV} "
            "must contain absolute paths.\n"
        )
        return EXIT_CONFIGURATION_ERROR

    loaded_runtime = load_runtime_config(runtime_path)

    if not loaded_runtime.success or loaded_runtime.config is None:
        configuration_issue = loaded_runtime.issues[0]
        stderr.write(
            "Telegram worker configuration error: "
            f"{configuration_issue.code}: "
            f"{configuration_issue.message}\n"
        )
        return EXIT_CONFIGURATION_ERROR

    runtime = loaded_runtime.config

    try:
        telegram = load_telegram_runtime_config(telegram_path)
    except ValueError as error:
        stderr.write(f"Telegram worker configuration error: {error}\n")
        return EXIT_CONFIGURATION_ERROR

    if not check_runtime_health(runtime).healthy:
        stderr.write("Telegram worker runtime health check failed.\n")
        return EXIT_CONFIGURATION_ERROR

    builder = runtime_builder or _default_runtime_builder
    built = builder(runtime, telegram)

    if not built.success or built.dependencies is None:
        runtime_issue = built.issues[0]
        stderr.write(
            "Telegram worker construction failed: "
            f"{runtime_issue.code}: "
            f"{runtime_issue.message}\n"
        )
        return EXIT_CONFIGURATION_ERROR

    calendar_provider: CalendarProvider | None = None
    provider_builder = calendar_provider_builder

    if provider_builder is None and runtime.profile is RuntimeProfile.SYSTEM:
        provider_builder = _default_calendar_provider_builder

    if provider_builder is not None:
        try:
            calendar_built = provider_builder(runtime)
        except (TypeError, ValueError):
            stderr.write("Telegram calendar provider configuration is invalid.\n")
            return EXIT_CONFIGURATION_ERROR
        except Exception:
            stderr.write(
                "Telegram calendar provider construction failed unexpectedly.\n"
            )
            return EXIT_INTERNAL_ERROR

        if not isinstance(calendar_built, TelegramCalendarProviderBuildResult):
            stderr.write(
                "Telegram calendar provider builder returned an invalid result.\n"
            )
            return EXIT_INTERNAL_ERROR

        if calendar_built.success:
            calendar_provider = calendar_built.provider
        else:
            provider_issue = calendar_built.issues[0]
            stderr.write(
                "Telegram calendar provider unavailable: "
                f"{provider_issue.code}: "
                f"{provider_issue.message}\n"
            )

    stop = TelegramStopFlag()

    try:
        register_signal(signal.SIGINT, stop.request)
        register_signal(signal.SIGTERM, stop.request)

        audit_store = IntegrityJsonlAuditStore(
            runtime.paths.audit_file,
            create_parents=False,
        )
        proposal_submission = ProposalSubmissionService(
            ActionOrchestrator(
                ActionHandlerRegistry(),
                audit_store,
                _utc_now,
                generate_event_id,
            ),
            runtime_proposal_repository(runtime),
        )
        application = build_default_channel_application(
            ChannelHandlerDependencies(
                config_path=runtime_path,
                expected_profile=runtime.profile,
                clock=_utc_now,
                proposal_submitter=proposal_submission.submit,
                proposal_id_source=lambda: str(uuid4()),
                control_id_source=lambda: str(uuid4()),
                calendar_provider=calendar_provider,
            )
        )
        result = worker_runner(
            TelegramWorkerConfig(
                bot_username=telegram.bot_username,
                poll_timeout_seconds=telegram.poll_timeout_seconds,
                fetch_limit=telegram.fetch_limit,
            ),
            TelegramWorkerDependencies(
                transport=built.dependencies.transport,
                offset_store=built.dependencies.offset_store,
                application=application,
                authorised_users=built.dependencies.authorised_users,
                request_id_source=lambda: str(uuid4()),
                clock=_utc_now,
                stop_signal=stop,
                sleeper=time.sleep,
            ),
        )
    except Exception:
        stderr.write("Telegram worker failed unexpectedly.\n")
        return EXIT_INTERNAL_ERROR

    if not result.success:
        worker_issue = result.issues[0]
        stderr.write(
            "Telegram worker stopped with an error: "
            f"{worker_issue.code}: "
            f"{worker_issue.message}\n"
        )
        return EXIT_APPLICATION_ERROR

    stdout.write(
        "Telegram worker stopped cleanly. "
        f"Processed={result.processed_updates}; "
        f"skipped={result.skipped_updates}.\n"
    )
    return EXIT_SUCCESS


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the Telegram foreground worker."""
    supplied = tuple(sys.argv[1:] if arguments is None else arguments)

    if supplied:
        sys.stderr.write("The Telegram worker does not accept arguments.\n")
        return EXIT_CONFIGURATION_ERROR

    return execute(os.environ)


def _system_calendar_provider_factory_config(
    runtime: RuntimeConfig,
) -> KhalCalendarProviderFactoryConfig:
    """Return the exact managed system calendar-provider configuration."""
    if runtime.profile is not RuntimeProfile.SYSTEM:
        raise ValueError(
            "System calendar provider construction requires the system profile."
        )

    return KhalCalendarProviderFactoryConfig(
        installation_record=_SYSTEM_CALENDAR_INSTALLATION_RECORD,
        tools_root=_SYSTEM_CALENDAR_TOOLS_ROOT,
        configuration_directory=(_SYSTEM_CALENDAR_CONFIGURATION_DIRECTORY),
        state_root=_SYSTEM_CALENDAR_STATE_ROOT,
        working_directory=_SYSTEM_CALENDAR_STATE_ROOT,
        display_timezone=runtime.display_timezone,
    )


def _default_calendar_provider_builder(
    runtime: RuntimeConfig,
) -> TelegramCalendarProviderBuildResult:
    """Build the verified managed khal provider without repair."""
    result = build_khal_calendar_provider(
        _system_calendar_provider_factory_config(runtime)
    )
    return TelegramCalendarProviderBuildResult(
        success=result.success,
        provider=result.provider,
        issues=result.issues,
    )


def _default_runtime_builder(
    runtime: RuntimeConfig,
    telegram: TelegramRuntimeConfig,
) -> TelegramRuntimeResult:
    return build_telegram_runtime(
        runtime,
        telegram,
        transport_factory=telegram_bot_api_transport,
    )


def _environment_path(
    environment: Mapping[str, str],
    name: str,
) -> Path | None:
    value = environment.get(name)

    if value is None or not value.strip():
        return None

    path = Path(value)
    return path if path.is_absolute() else None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a boolean.")
    return value


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string.")
    return value


def _integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer.")
    return value


def _absolute_path(value: object, *, field: str) -> Path:
    path = Path(_text(value, field=field))
    if not path.is_absolute():
        raise ValueError(f"{field} must be an absolute path.")
    return path
