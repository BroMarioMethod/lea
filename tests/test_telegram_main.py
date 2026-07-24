"""Tests for the executable Telegram worker process boundary."""

from __future__ import annotations

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
from lea.channels.authorisation import AuthorisedChannelUser, ChannelRole
from lea.channels.contracts import ChannelName
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
    TelegramStopFlag,
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
