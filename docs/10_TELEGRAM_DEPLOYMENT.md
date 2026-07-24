# Telegram Worker Deployment and Recovery

## Purpose

The LEA Telegram adapter runs as a supervisor-neutral foreground process. The
same `lea-telegram` executable can be managed by `systemd`, runit, OpenRC, s6,
launchd or another supervisor without changes to application code.

The committed files under `config/examples/` and `deploy/systemd/` are examples
and deployment assets. They must never contain real bot tokens, Telegram user
identifiers or private chat identifiers.

## Committed assets

- `deploy/systemd/lea-telegram.service`
- `config/examples/lea-telegram-worker.env`
- `config/examples/lea.telegram.example.toml`
- `config/examples/telegram-authorised-users.example.toml`

Validate them from the repository root:

```sh
uv run python scripts/validate_telegram_deployment.py
```

The validator reads only committed examples. It does not read the bot token or
other real files under `/etc/lea`.

## DietPi and systemd layout

The intended live paths are:

```text
/etc/lea/lea.toml
/etc/lea/secrets/telegram-bot-token
/etc/lea/telegram/telegram.toml
/etc/lea/telegram/authorised-users.toml
/etc/lea/telegram/worker.env
/var/lib/lea/telegram/offset.json
```

The service runs as the dedicated `lea` account and starts:

```text
/opt/lea/.venv/bin/lea-telegram
```

The process remains in the foreground. It must not fork, daemonise itself or
write a PID file.

Do not install or enable the service until the final live smoke-test procedure
has created and verified the real external configuration.

## Preflight checks

Before service installation, validate the committed asset:

```sh
cd /opt/lea
uv run python scripts/validate_telegram_deployment.py
```

Validate the main runtime without exposing secret contents:

```sh
uv run lea runtime inspect     --config /etc/lea/lea.toml     --health
```

The Telegram process boundary also performs runtime health checking and strict
configuration loading before it starts polling.

## Installing the DietPi service

These commands belong to the final live deployment stage:

```sh
sudo install -o root -g root -m 0644     /opt/lea/deploy/systemd/lea-telegram.service     /etc/systemd/system/lea-telegram.service

sudo systemctl daemon-reload
sudo systemctl enable --now lea-telegram.service
```

Check status and recent logs:

```sh
systemctl status lea-telegram.service --no-pager
journalctl -u lea-telegram.service -n 100 --no-pager
```

Follow logs during a controlled smoke test:

```sh
journalctl -u lea-telegram.service -f
```

## Controlled stop and restart

```sh
sudo systemctl stop lea-telegram.service
sudo systemctl start lea-telegram.service
sudo systemctl restart lea-telegram.service
```

`SIGTERM` requests cooperative shutdown. The worker finishes its current
bounded operation and exits without losing a successfully completed update.

## Recovery

First inspect status:

```sh
systemctl status lea-telegram.service --no-pager
journalctl -u lea-telegram.service -n 200 --no-pager
```

Then verify:

- `/etc/lea/telegram/worker.env` references absolute paths;
- the Telegram configuration is enabled;
- the authorised-user file contains at least one enabled user;
- the token file exists with mode `0600`;
- `/var/lib/lea/telegram` is writable by the `lea` account;
- the main runtime health check passes;
- the Pi can reach `api.telegram.org` over HTTPS.

Do not delete the offset file as a routine recovery step. Removing it can cause
Telegram to redeliver older updates.

## Alternative supervisors

All alternative supervisors must run the same foreground command with the same
two environment variables:

```text
LEA_RUNTIME_CONFIG=/etc/lea/lea.toml
LEA_TELEGRAM_CONFIG=/etc/lea/telegram/telegram.toml
```

Command:

```text
/opt/lea/.venv/bin/lea-telegram
```

The supervisor should:

- run the process as the dedicated `lea` account;
- send `SIGTERM` for shutdown;
- restart only after failure;
- provide at least 45 seconds for graceful shutdown;
- preserve the `/etc/lea`, `/var/lib/lea`, `/var/log/lea` and `/run/lea`
  filesystem boundaries;
- keep secrets outside command-line arguments and logs.

Supervisor-specific assets may be added later without changing the worker.
