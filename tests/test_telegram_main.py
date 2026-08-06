"""Tests for the executable Telegram worker process boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import cast

from lea.adapters.telegram.contracts import TelegramTransport
from lea.adapters.telegram.fakes import FakeTelegramTransport
from lea.adapters.telegram.offsets import FileTelegramOffsetStore
from lea.adapters.telegram.worker import (
    TelegramWorkerConfig,
    TelegramWorkerDependencies,
    TelegramWorkerIssue,
    TelegramWorkerResult,
)
from lea.calendars import (
    CalendarCancelRequest,
    CalendarCollection,
    CalendarCreateRequest,
    CalendarEventQuery,
    CalendarListCalendarsResult,
    CalendarListEventsResult,
    CalendarModifyRequest,
    CalendarMutationResult,
    CalendarProviderInspectionResult,
    CalendarProviderIssue,
    CalendarShowEventResult,
)
from lea.channels.authorisation import AuthorisedChannelUser, ChannelRole
from lea.channels.contracts import (
    ChannelIdentity,
    ChannelName,
    ChannelRequest,
    ChannelRequestType,
    ChannelResponseOutcome,
)
from lea.runtime import system_runtime_config
from lea.runtime.contracts import RuntimeConfig
from lea.runtime.telegram import (
    TelegramRuntimeConfig,
    TelegramRuntimeDependencies,
    TelegramRuntimeResult,
)
from lea.telegram_main import (
    EXIT_APPLICATION_ERROR,
    EXIT_CONFIGURATION_ERROR,
    EXIT_SUCCESS,
    TelegramCalendarProviderBuildResult,
    TelegramStopFlag,
    _system_calendar_provider_factory_config,
    execute,
    load_telegram_runtime_config,
)


def _write_runtime_config(tmp_path: Path) -> Path:
    names = (
        "state",
        "logs",
        "run",
        "audit",
        "proposals",
        "knowledge",
        "indexes",
        "adapters",
        "backups",
    )
    directories = {name: (tmp_path / name).resolve() for name in names}
    for directory in directories.values():
        directory.mkdir()

    config_path = (tmp_path / "lea.toml").resolve()
    taskwarrior = (tmp_path / "taskwarrior.json").resolve()
    taskwarrior.write_text("{}\n", encoding="utf-8")

    content = (
        "schema_version = 1\n"
        'profile = "test"\n'
        'display_timezone = "UTC"\n\n'
        "[paths]\n"
        f'state_dir = "{directories["state"]}"\n'
        f'log_dir = "{directories["logs"]}"\n'
        f'run_dir = "{directories["run"]}"\n'
        f'audit_dir = "{directories["audit"]}"\n'
        f'proposal_dir = "{directories["proposals"]}"\n'
        f'knowledge_dir = "{directories["knowledge"]}"\n'
        f'index_dir = "{directories["indexes"]}"\n'
        f'adapter_dir = "{directories["adapters"]}"\n'
        f'backup_dir = "{directories["backups"]}"\n\n'
        "[files]\n"
        f'audit_file = "{directories["audit"] / "audit.jsonl"}"\n'
        f'log_file = "{directories["logs"] / "lea.log"}"\n\n'
        "[component_records]\n"
        f'taskwarrior = "{taskwarrior}"\n'
    )
    config_path.write_text(content, encoding="utf-8")
    return config_path


def _write_telegram_config(tmp_path: Path) -> Path:
    path = (tmp_path / "telegram.toml").resolve()
    content = (
        "[telegram]\n"
        "enabled = true\n"
        'bot_username = "lea_test_bot"\n'
        f'authorised_users_file = "{(tmp_path / "users.toml").resolve()}"\n'
        f'offset_file = "{(tmp_path / "offset.json").resolve()}"\n'
        "poll_timeout_seconds = 30\n"
        "fetch_limit = 100\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def _runtime_result(
    runtime: RuntimeConfig,
    telegram: TelegramRuntimeConfig,
    tmp_path: Path,
) -> TelegramRuntimeResult:
    del runtime
    user = AuthorisedChannelUser(
        name="Owner",
        channel=ChannelName.TELEGRAM,
        user_id="123456789",
        conversation_id="123456789",
        role=ChannelRole.OWNER,
        enabled=True,
    )
    return TelegramRuntimeResult(
        success=True,
        dependencies=TelegramRuntimeDependencies(
            config=telegram,
            authorised_users=(user,),
            offset_store=FileTelegramOffsetStore(
                (tmp_path / "offset.json").resolve(),
                create_parent=True,
                fsync=False,
            ),
            transport=cast(TelegramTransport, FakeTelegramTransport()),
        ),
        issues=(),
    )


def test_loads_strict_telegram_configuration(tmp_path: Path) -> None:
    result = load_telegram_runtime_config(_write_telegram_config(tmp_path))

    assert result.enabled is True
    assert result.bot_username == "lea_test_bot"


def test_stop_flag_is_set_by_signal_handler() -> None:
    stop = TelegramStopFlag()
    stop.request(15, None)
    assert stop() is True


def test_missing_environment_paths_return_configuration_error() -> None:
    stderr = StringIO()
    code = execute({}, stderr=stderr)

    assert code == EXIT_CONFIGURATION_ERROR
    assert "LEA_RUNTIME_CONFIG" in stderr.getvalue()


def test_successful_worker_returns_zero(tmp_path: Path) -> None:
    runtime_path = _write_runtime_config(tmp_path)
    telegram_path = _write_telegram_config(tmp_path)
    stdout = StringIO()
    registered: list[int] = []

    def builder(
        runtime: RuntimeConfig,
        telegram: TelegramRuntimeConfig,
    ) -> TelegramRuntimeResult:
        return _runtime_result(runtime, telegram, tmp_path)

    def worker(
        config: TelegramWorkerConfig,
        dependencies: TelegramWorkerDependencies,
    ) -> TelegramWorkerResult:
        assert config.bot_username == "lea_test_bot"
        assert dependencies.authorised_users

        request_id = dependencies.request_id_source()
        assert isinstance(request_id, str)

        return TelegramWorkerResult(True, True, 2, 1, ())

    code = execute(
        {
            "LEA_RUNTIME_CONFIG": str(runtime_path),
            "LEA_TELEGRAM_CONFIG": str(telegram_path),
        },
        stdout=stdout,
        runtime_builder=builder,
        worker_runner=worker,
        register_signal=lambda signum, _handler: registered.append(int(signum)),
    )

    assert code == EXIT_SUCCESS
    assert "Processed=2; skipped=1" in stdout.getvalue()
    assert len(registered) == 2


def test_worker_failure_returns_application_error(tmp_path: Path) -> None:
    runtime_path = _write_runtime_config(tmp_path)
    telegram_path = _write_telegram_config(tmp_path)
    stderr = StringIO()

    def builder(
        runtime: RuntimeConfig,
        telegram: TelegramRuntimeConfig,
    ) -> TelegramRuntimeResult:
        return _runtime_result(runtime, telegram, tmp_path)

    def worker(
        _config: TelegramWorkerConfig,
        _dependencies: TelegramWorkerDependencies,
    ) -> TelegramWorkerResult:
        return TelegramWorkerResult(
            False,
            False,
            0,
            0,
            (
                TelegramWorkerIssue(
                    code="failed",
                    message="Failed.",
                    operation="worker",
                ),
            ),
        )

    code = execute(
        {
            "LEA_RUNTIME_CONFIG": str(runtime_path),
            "LEA_TELEGRAM_CONFIG": str(telegram_path),
        },
        stderr=stderr,
        runtime_builder=builder,
        worker_runner=worker,
        register_signal=lambda _signum, _handler: None,
    )

    assert code == EXIT_APPLICATION_ERROR
    assert "failed" in stderr.getvalue()


class RecordingCalendarProvider:
    """Provide deterministic calendar reads at the Telegram process boundary."""

    def inspect(self) -> CalendarProviderInspectionResult:
        return CalendarProviderInspectionResult(
            available=True,
            provider="test",
            version="1.0",
            issues=(),
        )

    def list_calendars(self) -> CalendarListCalendarsResult:
        return CalendarListCalendarsResult(
            success=True,
            calendars=(
                CalendarCollection(
                    calendar_id="personal",
                    display_name="Personal",
                ),
            ),
            issues=(),
        )

    def list_events(
        self,
        query: CalendarEventQuery,
    ) -> CalendarListEventsResult:
        del query
        return CalendarListEventsResult(
            success=True,
            events=(),
            issues=(),
        )

    def show_event(
        self,
        calendar_id: str,
        event_uid: str,
    ) -> CalendarShowEventResult:
        del calendar_id, event_uid
        return CalendarShowEventResult(
            success=False,
            event=None,
            issues=(
                CalendarProviderIssue(
                    code="calendar_event_not_found",
                    message="The calendar event was not found.",
                    provider="test",
                    operation="show_event",
                ),
            ),
        )

    def create_event(
        self,
        request: CalendarCreateRequest,
    ) -> CalendarMutationResult:
        del request
        raise AssertionError("Telegram read wiring must not create events.")

    def modify_event(
        self,
        request: CalendarModifyRequest,
    ) -> CalendarMutationResult:
        del request
        raise AssertionError("Telegram read wiring must not modify events.")

    def cancel_event(
        self,
        request: CalendarCancelRequest,
    ) -> CalendarMutationResult:
        del request
        raise AssertionError("Telegram read wiring must not cancel events.")


def _calendar_request(command: str) -> ChannelRequest:
    """Return one authorised Telegram calendar request."""
    return ChannelRequest(
        request_id="11111111-1111-4111-8111-111111111111",
        source_update_id="telegram:calendar-test",
        identity=ChannelIdentity(
            channel=ChannelName.TELEGRAM,
            user_id="123456789",
            conversation_id="123456789",
            role="owner",
            capabilities=("Calendar.Read",),
        ),
        request_type=ChannelRequestType.COMMAND,
        command=command,
        parameters={"arguments": []},
        received_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )


def test_system_calendar_factory_config_uses_managed_layout() -> None:
    """Production construction should use the specified managed paths."""
    runtime = system_runtime_config(
        display_timezone="Africa/Gaborone",
    )

    config = _system_calendar_provider_factory_config(runtime)

    assert config.installation_record == Path(
        "/var/lib/lea/install/calendar-toolchain.json"
    )
    assert config.tools_root == Path("/opt/lea-tools/calendar")
    assert config.configuration_directory == Path("/etc/lea/calendar")
    assert config.state_root == Path("/var/lib/lea/calendar")
    assert config.working_directory == Path("/var/lib/lea/calendar")
    assert config.display_timezone == "Africa/Gaborone"


def test_calendar_provider_is_injected_into_telegram_application(
    tmp_path: Path,
) -> None:
    """A verified provider should serve calendar reads through Telegram."""
    runtime_path = _write_runtime_config(tmp_path)
    telegram_path = _write_telegram_config(tmp_path)
    built_for: list[RuntimeConfig] = []

    def runtime_builder(
        runtime: RuntimeConfig,
        telegram: TelegramRuntimeConfig,
    ) -> TelegramRuntimeResult:
        return _runtime_result(runtime, telegram, tmp_path)

    def calendar_builder(
        runtime: RuntimeConfig,
    ) -> TelegramCalendarProviderBuildResult:
        built_for.append(runtime)
        return TelegramCalendarProviderBuildResult(
            success=True,
            provider=RecordingCalendarProvider(),
            issues=(),
        )

    def worker(
        _config: TelegramWorkerConfig,
        dependencies: TelegramWorkerDependencies,
    ) -> TelegramWorkerResult:
        handled = dependencies.application.handle(
            _calendar_request("calendar.list_calendars")
        )

        assert handled.response is not None
        assert handled.response.outcome is ChannelResponseOutcome.SUCCEEDED
        assert handled.response.data is not None
        assert handled.response.data["calendars"] == (
            {
                "calendar_id": "personal",
                "display_name": "Personal",
                "read_only": False,
            },
        )
        return TelegramWorkerResult(True, True, 1, 0, ())

    code = execute(
        {
            "LEA_RUNTIME_CONFIG": str(runtime_path),
            "LEA_TELEGRAM_CONFIG": str(telegram_path),
        },
        runtime_builder=runtime_builder,
        calendar_provider_builder=calendar_builder,
        worker_runner=worker,
        register_signal=lambda _signum, _handler: None,
    )

    assert code == EXIT_SUCCESS
    assert len(built_for) == 1
    assert built_for[0].display_timezone == "UTC"


def test_calendar_provider_failure_degrades_only_calendar_commands(
    tmp_path: Path,
) -> None:
    """A structured provider failure should not stop unrelated Telegram work."""
    runtime_path = _write_runtime_config(tmp_path)
    telegram_path = _write_telegram_config(tmp_path)
    stderr = StringIO()

    def runtime_builder(
        runtime: RuntimeConfig,
        telegram: TelegramRuntimeConfig,
    ) -> TelegramRuntimeResult:
        return _runtime_result(runtime, telegram, tmp_path)

    def calendar_builder(
        runtime: RuntimeConfig,
    ) -> TelegramCalendarProviderBuildResult:
        del runtime
        return TelegramCalendarProviderBuildResult(
            success=False,
            provider=None,
            issues=(
                CalendarProviderIssue(
                    code="khal_installation_record_invalid",
                    message="The calendar installation record is unavailable.",
                    provider="khal",
                    operation="build_provider",
                    field="installation_record",
                ),
            ),
        )

    def worker(
        _config: TelegramWorkerConfig,
        dependencies: TelegramWorkerDependencies,
    ) -> TelegramWorkerResult:
        handled = dependencies.application.handle(
            _calendar_request("calendar.list_calendars")
        )

        assert handled.response is not None
        assert (
            handled.response.outcome is ChannelResponseOutcome.TEMPORARILY_UNAVAILABLE
        )
        assert handled.response.issue is not None
        assert handled.response.issue.code == "calendar_provider_unavailable"
        return TelegramWorkerResult(True, True, 1, 0, ())

    code = execute(
        {
            "LEA_RUNTIME_CONFIG": str(runtime_path),
            "LEA_TELEGRAM_CONFIG": str(telegram_path),
        },
        stderr=stderr,
        runtime_builder=runtime_builder,
        calendar_provider_builder=calendar_builder,
        worker_runner=worker,
        register_signal=lambda _signum, _handler: None,
    )

    assert code == EXIT_SUCCESS
    assert "khal_installation_record_invalid" in stderr.getvalue()
