"""Tests for the supervisor-neutral Telegram polling worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from lea.adapters.telegram.contracts import (
    TelegramAnswerCallbackResult,
    TelegramEditMessageResult,
    TelegramFetchUpdatesResult,
    TelegramSendMessageResult,
    TelegramSentMessage,
    TelegramTransportIssue,
    TelegramUpdate,
)
from lea.adapters.telegram.fakes import FakeTelegramTransport
from lea.adapters.telegram.offsets import FileTelegramOffsetStore
from lea.adapters.telegram.worker import (
    TelegramWorkerConfig,
    TelegramWorkerDependencies,
    TelegramWorkerIssue,
    run_telegram_worker,
)
from lea.channels.application import (
    ChannelApplication,
    ChannelApplicationResult,
    ChannelCommandDefinition,
    DispatchingChannelApplication,
)
from lea.channels.authorisation import (
    AuthorisedChannelUser,
    ChannelRole,
)
from lea.channels.contracts import (
    ChannelName,
    ChannelRequest,
    ChannelResponse,
    ChannelResponseOutcome,
)

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
REQUEST_ID = "11111111-1111-4111-8111-111111111111"
PROPOSAL_ID = "22222222-2222-4222-8222-222222222222"


@dataclass
class StopAfter:
    """Stop after a deterministic number of signal checks."""

    checks: int
    calls: int = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls > self.checks


def _user() -> AuthorisedChannelUser:
    return AuthorisedChannelUser(
        name="Owner",
        channel=ChannelName.TELEGRAM,
        user_id="123456789",
        conversation_id="123456789",
        role=ChannelRole.OWNER,
        enabled=True,
    )


def _message(update_id: int, text: str = "/status") -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        payload={
            "message": {
                "message_id": update_id,
                "from": {"id": 123456789, "first_name": "Owner"},
                "chat": {"id": 123456789, "type": "private"},
                "text": text,
            }
        },
    )


def _callback(update_id: int) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        payload={
            "callback_query": {
                "id": f"callback-{update_id}",
                "from": {"id": 123456789, "first_name": "Owner"},
                "message": {
                    "message_id": 77,
                    "chat": {"id": 123456789, "type": "private"},
                },
                "data": f"proposal.approve:{PROPOSAL_ID}",
            }
        },
    )


def _application() -> DispatchingChannelApplication:
    def handler(request: ChannelRequest) -> ChannelResponse:
        return ChannelResponse(
            request_id=request.request_id,
            outcome=ChannelResponseOutcome.SUCCEEDED,
            message="Handled.",
            responded_at=NOW,
            correlation_id=request.correlation_id,
            data={"command": request.command},
        )

    return DispatchingChannelApplication(
        (
            ChannelCommandDefinition("runtime.status", handler),
            ChannelCommandDefinition("proposals.approve", handler),
        ),
        clock=lambda: NOW,
    )


def _dependencies(
    tmp_path: Path,
    transport: FakeTelegramTransport,
    *,
    stop_signal: StopAfter,
    warnings: list[TelegramWorkerIssue] | None = None,
) -> TelegramWorkerDependencies:
    identifiers = iter(
        [
            REQUEST_ID,
            "33333333-3333-4333-8333-333333333333",
        ]
    )
    return TelegramWorkerDependencies(
        transport=transport,
        offset_store=FileTelegramOffsetStore(
            (tmp_path / "offset.json").resolve(),
            create_parent=True,
            fsync=False,
        ),
        application=_application(),
        authorised_users=(_user(),),
        request_id_source=lambda: next(identifiers),
        clock=lambda: NOW,
        stop_signal=stop_signal,
        sleeper=lambda _seconds: None,
        warning_sink=warnings.append if warnings is not None else None,
    )


def _config() -> TelegramWorkerConfig:
    return TelegramWorkerConfig(
        bot_username="lea_test_bot",
        poll_timeout_seconds=30,
        fetch_limit=100,
        retry_delay_seconds=0,
        max_consecutive_fetch_failures=2,
    )


def test_processes_message_sends_response_and_advances_offset(
    tmp_path: Path,
) -> None:
    transport = FakeTelegramTransport()
    transport.fetch_results.append(
        TelegramFetchUpdatesResult(True, (_message(42),), ())
    )
    transport.send_results.append(
        TelegramSendMessageResult(
            True,
            TelegramSentMessage("123456789", 100),
            (),
        )
    )

    result = run_telegram_worker(
        _config(),
        _dependencies(tmp_path, transport, stop_signal=StopAfter(2)),
    )

    assert result.success is True
    assert result.processed_updates == 1
    assert transport.send_calls[0].chat_id == "123456789"
    assert transport.fetch_calls[0].offset is None
    assert (tmp_path / "offset.json").read_text(
        encoding="utf-8"
    ) == '{"next_update_id":43,"schema_version":1}\n'


def test_processes_callback_answers_edits_and_advances(
    tmp_path: Path,
) -> None:
    transport = FakeTelegramTransport()
    transport.fetch_results.append(
        TelegramFetchUpdatesResult(True, (_callback(50),), ())
    )
    transport.edit_results.append(
        TelegramEditMessageResult(
            True,
            TelegramSentMessage("123456789", 77),
            (),
        )
    )
    transport.answer_results.append(TelegramAnswerCallbackResult(True, ()))

    result = run_telegram_worker(
        _config(),
        _dependencies(tmp_path, transport, stop_signal=StopAfter(2)),
    )

    assert result.success is True
    assert result.processed_updates == 1
    assert transport.edit_calls[0].message_id == 77
    assert transport.answer_calls[0].callback_query_id == "callback-50"


def test_callback_edit_failure_is_checkpointed_and_non_fatal(
    tmp_path: Path,
) -> None:
    warnings: list[TelegramWorkerIssue] = []
    transport = FakeTelegramTransport()
    transport.fetch_results.append(
        TelegramFetchUpdatesResult(True, (_callback(51),), ())
    )
    transport.answer_results.append(TelegramAnswerCallbackResult(True, ()))
    transport.edit_results.append(
        TelegramEditMessageResult(
            False,
            None,
            (
                TelegramTransportIssue(
                    code="unavailable",
                    message="Unavailable.",
                    operation="edit_message",
                ),
            ),
        )
    )

    result = run_telegram_worker(
        _config(),
        _dependencies(
            tmp_path,
            transport,
            stop_signal=StopAfter(2),
            warnings=warnings,
        ),
    )

    assert result.success is True
    assert result.processed_updates == 1
    assert transport.answer_calls[0].callback_query_id == "callback-51"
    assert transport.edit_calls[0].message_id == 77
    assert [warning.code for warning in warnings] == ["telegram_edit_failed"]
    assert (tmp_path / "offset.json").read_text(
        encoding="utf-8"
    ) == '{"next_update_id":52,"schema_version":1}\n'


def test_delivery_failure_does_not_block_later_updates(
    tmp_path: Path,
) -> None:
    warnings: list[TelegramWorkerIssue] = []
    transport = FakeTelegramTransport()
    transport.fetch_results.append(
        TelegramFetchUpdatesResult(
            True,
            (
                _callback(53),
                _message(54),
            ),
            (),
        )
    )
    transport.answer_results.append(TelegramAnswerCallbackResult(True, ()))
    transport.edit_results.append(
        TelegramEditMessageResult(
            False,
            None,
            (
                TelegramTransportIssue(
                    code="unavailable",
                    message="Unavailable.",
                    operation="edit_message",
                ),
            ),
        )
    )
    transport.send_results.append(
        TelegramSendMessageResult(
            True,
            TelegramSentMessage("123456789", 100),
            (),
        )
    )

    result = run_telegram_worker(
        _config(),
        _dependencies(
            tmp_path,
            transport,
            stop_signal=StopAfter(3),
            warnings=warnings,
        ),
    )

    assert result.success is True
    assert result.processed_updates == 2
    assert len(transport.send_calls) == 1
    assert [warning.code for warning in warnings] == ["telegram_edit_failed"]
    assert (tmp_path / "offset.json").read_text(
        encoding="utf-8"
    ) == '{"next_update_id":55,"schema_version":1}\n'


def test_callback_answer_failure_still_edits_and_checkpoints(
    tmp_path: Path,
) -> None:
    warnings: list[TelegramWorkerIssue] = []
    transport = FakeTelegramTransport()
    transport.fetch_results.append(
        TelegramFetchUpdatesResult(True, (_callback(52),), ())
    )
    transport.answer_results.append(
        TelegramAnswerCallbackResult(
            False,
            (
                TelegramTransportIssue(
                    code="expired",
                    message="Expired.",
                    operation="answer_callback_query",
                ),
            ),
        )
    )
    transport.edit_results.append(
        TelegramEditMessageResult(
            True,
            TelegramSentMessage("123456789", 77),
            (),
        )
    )

    result = run_telegram_worker(
        _config(),
        _dependencies(
            tmp_path,
            transport,
            stop_signal=StopAfter(2),
            warnings=warnings,
        ),
    )

    assert result.success is True
    assert result.processed_updates == 1
    assert transport.answer_calls[0].callback_query_id == "callback-52"
    assert transport.edit_calls[0].message_id == 77
    assert [warning.code for warning in warnings] == ["telegram_callback_answer_failed"]
    assert (tmp_path / "offset.json").read_text(
        encoding="utf-8"
    ) == '{"next_update_id":53,"schema_version":1}\n'


def test_parse_failure_is_checkpointed_without_response(tmp_path: Path) -> None:
    transport = FakeTelegramTransport()
    transport.fetch_results.append(
        TelegramFetchUpdatesResult(
            True,
            (
                TelegramUpdate(
                    update_id=60,
                    payload={"edited_message": {}},
                ),
            ),
            (),
        )
    )

    result = run_telegram_worker(
        _config(),
        _dependencies(tmp_path, transport, stop_signal=StopAfter(2)),
    )

    assert result.success is True
    assert result.processed_updates == 1
    assert transport.send_calls == []


def test_unauthorised_update_is_checkpointed_without_response(
    tmp_path: Path,
) -> None:
    transport = FakeTelegramTransport()
    update = TelegramUpdate(
        update_id=61,
        payload={
            "message": {
                "message_id": 61,
                "from": {"id": 987654321, "first_name": "Unknown"},
                "chat": {"id": 987654321, "type": "private"},
                "text": "/status",
            }
        },
    )
    transport.fetch_results.append(TelegramFetchUpdatesResult(True, (update,), ()))

    result = run_telegram_worker(
        _config(),
        _dependencies(tmp_path, transport, stop_signal=StopAfter(2)),
    )

    assert result.success is True
    assert result.processed_updates == 1
    assert transport.send_calls == []


def test_send_failure_is_checkpointed_and_non_fatal(
    tmp_path: Path,
) -> None:
    warnings: list[TelegramWorkerIssue] = []
    transport = FakeTelegramTransport()
    transport.fetch_results.append(
        TelegramFetchUpdatesResult(True, (_message(70),), ())
    )
    transport.send_results.append(
        TelegramSendMessageResult(
            False,
            None,
            (
                TelegramTransportIssue(
                    code="unavailable",
                    message="Unavailable.",
                    operation="send_message",
                ),
            ),
        )
    )

    result = run_telegram_worker(
        _config(),
        _dependencies(
            tmp_path,
            transport,
            stop_signal=StopAfter(2),
            warnings=warnings,
        ),
    )

    assert result.success is True
    assert result.processed_updates == 1
    assert [warning.code for warning in warnings] == ["telegram_send_failed"]
    assert (tmp_path / "offset.json").read_text(
        encoding="utf-8"
    ) == '{"next_update_id":71,"schema_version":1}\n'


def test_stale_update_is_skipped(tmp_path: Path) -> None:
    offset_path = (tmp_path / "offset.json").resolve()
    store = FileTelegramOffsetStore(offset_path, create_parent=True, fsync=False)
    assert store.advance(80).success

    transport = FakeTelegramTransport()
    transport.fetch_results.append(
        TelegramFetchUpdatesResult(True, (_message(79),), ())
    )
    dependencies = _dependencies(
        tmp_path,
        transport,
        stop_signal=StopAfter(2),
    )
    dependencies = TelegramWorkerDependencies(
        transport=dependencies.transport,
        offset_store=store,
        application=dependencies.application,
        authorised_users=dependencies.authorised_users,
        request_id_source=dependencies.request_id_source,
        clock=dependencies.clock,
        stop_signal=dependencies.stop_signal,
        sleeper=dependencies.sleeper,
    )

    result = run_telegram_worker(_config(), dependencies)

    assert result.success is True
    assert result.skipped_updates == 1
    assert result.processed_updates == 0


def test_fetch_failures_are_bounded_and_redacted(tmp_path: Path) -> None:
    transport = FakeTelegramTransport()

    failed = TelegramFetchUpdatesResult(
        False,
        (),
        (
            TelegramTransportIssue(
                code="network_error",
                message="/etc/lea/secrets/token",
                operation="fetch_updates",
            ),
        ),
    )
    transport.fetch_results.extend((failed, failed))

    result = run_telegram_worker(
        _config(),
        _dependencies(tmp_path, transport, stop_signal=StopAfter(10)),
    )

    assert result.success is False
    assert result.issues[0].code == "telegram_fetch_retry_exhausted"
    assert "/etc/lea" not in result.issues[0].message
    assert len(transport.fetch_calls) == 2


def test_keyboard_interrupt_stops_cleanly(tmp_path: Path) -> None:
    class InterruptingTransport(FakeTelegramTransport):
        def fetch_updates(
            self,
            *,
            offset: int | None,
            limit: int,
            timeout_seconds: int,
        ) -> TelegramFetchUpdatesResult:
            raise KeyboardInterrupt

    result = run_telegram_worker(
        _config(),
        _dependencies(
            tmp_path,
            InterruptingTransport(),
            stop_signal=StopAfter(10),
        ),
    )

    assert result.success is True
    assert result.stopped is True


def test_application_structural_failure_does_not_checkpoint(
    tmp_path: Path,
) -> None:
    class FailedApplication:
        def handle(self, _request: ChannelRequest) -> ChannelApplicationResult:
            from lea.channels.application import ChannelApplicationIssue

            return ChannelApplicationResult(
                success=False,
                response=None,
                issues=(
                    ChannelApplicationIssue(
                        code="failed",
                        message="Failed.",
                    ),
                ),
            )

    transport = FakeTelegramTransport()
    transport.fetch_results.append(
        TelegramFetchUpdatesResult(True, (_message(90),), ())
    )
    dependencies = _dependencies(
        tmp_path,
        transport,
        stop_signal=StopAfter(10),
    )
    dependencies = TelegramWorkerDependencies(
        transport=dependencies.transport,
        offset_store=dependencies.offset_store,
        application=cast(ChannelApplication, FailedApplication()),
        authorised_users=dependencies.authorised_users,
        request_id_source=dependencies.request_id_source,
        clock=dependencies.clock,
        stop_signal=dependencies.stop_signal,
        sleeper=dependencies.sleeper,
    )

    result = run_telegram_worker(_config(), dependencies)

    assert result.success is False
    assert result.issues[0].code == "telegram_application_failed"
    assert not (tmp_path / "offset.json").exists()
