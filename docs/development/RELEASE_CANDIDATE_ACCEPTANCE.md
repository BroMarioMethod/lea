# LEA release-candidate acceptance

## Purpose

The release-candidate acceptance command verifies an installed LEA system after
installation has completed.

It is not an installer and must not be run against the development checkout as
a substitute for a clean-room installation test.

The command:

- runs read-only installed-system health checks;
- performs the disposable Taskwarrior functional lifecycle;
- optionally validates the installed Telegram bot identity;
- writes a deterministic, secret-free acceptance record;
- returns a stable process exit code.

## Command

For an installation without Telegram:

```bash
uv run lea accept-release-candidate \
    --no-telegram
```

For an installation configured with Telegram:

```bash
uv run lea accept-release-candidate \
    --telegram
```

The Telegram choice is mandatory. This prevents an operator from accidentally
omitting Telegram checks from an installation that is expected to use Telegram.

## When to run acceptance

Run the real acceptance command only after:

1. LEA has been installed on the clean target system.
2. The installation command has completed.
3. The required runtime configuration and installation records exist.
4. Taskwarrior has been installed through the managed installer.
5. Telegram configuration is complete when Telegram is enabled.
6. The installed system is ready for release-candidate verification.

The first real acceptance run belongs to the clean-room installation stage. It
must not be performed merely against the repository checkout on the development
device.

## Standard paths

The default installed-system paths are:

| Purpose | Path |
|---|---|
| Runtime configuration | `/etc/lea/lea.toml` |
| Telegram configuration | `/etc/lea/telegram/telegram.toml` |
| LEA installation record | `/var/lib/lea/install/release-candidate.json` |
| Taskwarrior installation record | `/var/lib/lea/install/taskwarrior.json` |
| Taskwarrior acceptance workspace | `/var/lib/lea/acceptance/taskwarrior` |
| Acceptance record | `/var/lib/lea/acceptance/release-candidate.json` |
| systemctl executable | `/usr/bin/systemctl` |

Path overrides exist for isolated testing and controlled recovery. They are not
the normal production invocation.

## Outcomes and exit codes

| Outcome | Exit code | Meaning |
|---|---:|---|
| `PASSED` | `0` | The harness completed, all required checks passed and the acceptance record was written. |
| `FAILED` | `1` | The harness completed and recorded a genuine acceptance rejection. |
| Usage error | `2` | Command arguments or supplied paths were invalid. |
| `ERROR` | `70` | The harness could not complete or could not persist its record. |

A `FAILED` result is different from an `ERROR`.

`FAILED` means the acceptance process completed correctly and found that the
installed release candidate did not satisfy one or more required checks.

`ERROR` means the acceptance mechanism itself could not complete reliably.

## Telegram selection

Use `--telegram` only when the installed release candidate was configured with
Telegram.

This mode performs:

- Telegram configuration validation;
- authorised-user file validation;
- Telegram token-file permission validation;
- systemd service enabled and active checks;
- a live Telegram `getMe` identity validation.

Use `--no-telegram` only when the release candidate was intentionally installed
without Telegram.

Do not use `--no-telegram` to bypass a Telegram failure.

## Acceptance record

The normal record is written to:

```text
/var/lib/lea/acceptance/release-candidate.json
```

The record contains:

- the acceptance schema and component;
- the UTC recording timestamp;
- the overall outcome;
- runtime and Taskwarrior record paths;
- whether Telegram acceptance was selected;
- structured health checks;
- structured functional acceptance checks.

The record must not contain:

- Telegram bot tokens;
- Telegram API response bodies;
- authorised Telegram user or conversation identifiers;
- Taskwarrior task contents;
- environment-variable contents;
- raw exception details;
- passwords, credentials or API keys.

The record is written atomically with Unix mode `0640`.

## Safe preliminary verification

Before running real acceptance, verify the committed acceptance assets:

```bash
uv run python scripts/validate_release_candidate_acceptance.py
```

This validation is non-mutating. It inspects committed files and command help
only. It does not:

- run installed-system health checks;
- invoke Taskwarrior;
- call systemd;
- contact Telegram;
- read the Telegram token;
- write an acceptance record.

## Help verification

The command help may be checked safely through either public entry path:

```bash
uv run lea accept-release-candidate --help

uv run python -m lea accept-release-candidate --help
```

Both commands must return exit status `0`.

## Isolated path overrides

The following options support controlled testing:

```text
--configuration-root PATH
--state-root PATH
--systemctl PATH
--record-file PATH
```

Every supplied path must be absolute.

Example isolated invocation:

```bash
uv run lea accept-release-candidate \
    --no-telegram \
    --configuration-root /tmp/lea-test/etc/lea \
    --state-root /tmp/lea-test/var/lib/lea \
    --systemctl /tmp/lea-test/usr/bin/systemctl \
    --record-file /tmp/lea-test/acceptance.json
```

Supplying valid paths causes the real acceptance harness to run. Use injected
automated tests for routine development verification instead of manually
executing this example.

## Failure handling

When acceptance returns `1`:

1. Read the human-readable failed checks.
2. Inspect the generated acceptance record.
3. Correct the installed-system problem.
4. Re-run the same acceptance command.
5. Retain the final passing record with the release-candidate evidence.

When acceptance returns `70`:

1. Treat the acceptance evidence as incomplete.
2. Correct the harness or persistence failure.
3. Confirm the record destination is safe and writable.
4. Re-run acceptance from the beginning.
5. Do not treat the release candidate as accepted until exit status `0`.

## Release evidence

A release candidate is not accepted merely because the automated test suite
passes on the development machine.

Release evidence should include:

- a successful clean-room installation;
- the exact release-candidate commit or tag;
- the installation command and selected options;
- the acceptance command and exit status;
- the persisted acceptance record;
- any failure and repair notes;
- confirmation that no secret values were captured in evidence.
