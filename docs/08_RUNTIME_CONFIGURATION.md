# Runtime Configuration and Operations

## Purpose

This guide explains how to create, inspect, bootstrap and verify a LEA runtime.

Milestone 2.0 separates the Git repository from deployed configuration, persistent state, logs, ephemeral runtime data and secret-file references.

Runtime administration is available through:

```bash
uv run lea runtime --help
```

The equivalent package route is:

```bash
uv run python -m lea runtime --help
```

## Safety model

Runtime operations are deliberately explicit:

- configuration paths must be absolute;
- development and test roots must be absolute;
- configuration loading never creates directories;
- health checks never repair or create anything;
- initialisation never overwrites an existing configuration;
- bootstrap creates directories but not data files;
- dry-run mode reports planned changes without mutation;
- secret values are never written to TOML.

## Canonical layouts

### System

```text
/etc/lea/lea.toml
/var/lib/lea/
/var/log/lea/
/run/lea/
```

Persistent state:

```text
/var/lib/lea/audit/
/var/lib/lea/proposals/
/var/lib/lea/knowledge/
/var/lib/lea/indexes/
/var/lib/lea/adapters/
/var/lib/lea/backups/
```

### Development

For `/opt/lea`:

```text
/opt/lea/.lea/config/lea.toml
/opt/lea/.lea/state/
/opt/lea/.lea/log/
/opt/lea/.lea/run/
```

Keep `.lea/` excluded from Git.

### Test

For `/tmp/lea-test`:

```text
/tmp/lea-test/config/lea.toml
/tmp/lea-test/state/
/tmp/lea-test/log/
/tmp/lea-test/run/
```

## Configuration schema

```toml
schema_version = 1
profile = "system"
display_timezone = "Africa/Gaborone"

[paths]
state_dir = "/var/lib/lea"
log_dir = "/var/log/lea"
run_dir = "/run/lea"
audit_dir = "/var/lib/lea/audit"
proposal_dir = "/var/lib/lea/proposals"
knowledge_dir = "/var/lib/lea/knowledge"
index_dir = "/var/lib/lea/indexes"
adapter_dir = "/var/lib/lea/adapters"
backup_dir = "/var/lib/lea/backups"

[files]
audit_file = "/var/lib/lea/audit/actions-integrity.jsonl"
log_file = "/var/log/lea/lea.log"

[secrets]
telegram_token_file = "/etc/lea/secrets/telegram-bot-token"
```

The loader rejects malformed TOML, unsupported schema versions, unknown or missing fields, relative paths, invalid relationships and unrecognised timezones.

## Inspect a configuration

```bash
uv run lea runtime inspect \
    --config /absolute/path/to/lea.toml
```

Include health:

```bash
uv run lea runtime inspect \
    --config /absolute/path/to/lea.toml \
    --health
```

Inspection is read-only.

## Run a health check

```bash
uv run lea runtime health \
    --config /absolute/path/to/lea.toml
```

Health checks verify configuration readability, runtime directories, required access, output parents, optional secret-file presence, timezone availability and path separation.

A missing optional secret is a warning, not a runtime failure.

## Initialise configuration

The configuration parent must already exist.

### Development

```bash
mkdir -p /opt/lea/.lea/config

uv run lea runtime initialise \
    --profile development \
    --root /opt/lea \
    --display-timezone Africa/Gaborone \
    --dry-run
```

Then:

```bash
uv run lea runtime initialise \
    --profile development \
    --root /opt/lea \
    --display-timezone Africa/Gaborone
```

### Test

```bash
mkdir -p /tmp/lea-test/config

uv run lea runtime initialise \
    --profile test \
    --root /tmp/lea-test \
    --display-timezone Africa/Gaborone
```

### System

```bash
sudo install -d /etc/lea
```

Review:

```bash
uv run lea runtime initialise \
    --profile system \
    --display-timezone Africa/Gaborone \
    --dry-run
```

Live system initialisation requires suitable filesystem permissions. The command refuses to overwrite `/etc/lea/lea.toml`.

## Bootstrap runtime directories

```bash
uv run lea runtime bootstrap \
    --config /absolute/path/to/lea.toml \
    --dry-run
```

Then:

```bash
uv run lea runtime bootstrap \
    --config /absolute/path/to/lea.toml
```

Bootstrap does not create the TOML file, audit file, log file, secret files or backup archives.

## Coordinated setup

```bash
uv run lea runtime setup \
    --profile test \
    --root /tmp/lea-test \
    --display-timezone Africa/Gaborone \
    --dry-run
```

Live:

```bash
uv run lea runtime setup \
    --profile test \
    --root /tmp/lea-test \
    --display-timezone Africa/Gaborone
```

Setup stops before bootstrap when initialisation fails.

Because setup refuses an existing configuration, use `bootstrap` when the configuration already exists.

## Setup and verify

```bash
uv run lea runtime verify \
    --profile test \
    --root /tmp/lea-test \
    --display-timezone Africa/Gaborone \
    --dry-run
```

Dry-run output correctly reports `NOT VERIFIED`.

Live:

```bash
uv run lea runtime verify \
    --profile test \
    --root /tmp/lea-test \
    --display-timezone Africa/Gaborone
```

Successful live output reports `VERIFIED`.

## Secret-file references

Configuration stores paths, never values:

```bash
uv run lea runtime initialise \
    --profile system \
    --display-timezone Africa/Gaborone \
    --telegram-token-file /etc/lea/secrets/telegram-bot-token
```

Recommended intent:

```bash
sudo install -d -m 0700 /etc/lea/secrets
sudo install -m 0600 /dev/null /etc/lea/secrets/telegram-bot-token
```

Do not commit, log or paste secret content into TOML.

## Permissions

Apply least privilege:

```text
/etc/lea/             administrator-writable; LEA-readable
/etc/lea/secrets/     restricted
/var/lib/lea/         LEA-readable and writable
/var/log/lea/         LEA-writable
/run/lea/             LEA-writable while running
```

Exact user and group commands are deployment-specific and remain outside Milestone 2.0.

## Timezone behaviour

Persistent timestamps stay timezone-aware UTC.

For Botswana:

```toml
display_timezone = "Africa/Gaborone"
```

The configured timezone affects presentation only.

## Backup boundary

Bootstrap creates the configured backups directory, but Milestone 2.0 does not select content, create archives, schedule jobs, encrypt backups, copy them off-device or restore data.

## Exit statuses

```text
0   Success or successful dry-run plan
1   Runtime failure or unhealthy runtime
2   Configuration, template input or command-usage failure
```

## Troubleshooting

### Configuration parent is missing

Create only the required parent:

```bash
mkdir -p /absolute/runtime/root/config
```

### Existing configuration blocks setup

Use the existing configuration:

```bash
uv run lea runtime bootstrap \
    --config /absolute/path/to/lea.toml
```

Then inspect it:

```bash
uv run lea runtime inspect \
    --config /absolute/path/to/lea.toml \
    --health
```

### Runtime path conflicts with a file

Move or remove the conflicting file only after confirming it is safe. Bootstrap never replaces it.

### Health reports missing directories

Review and apply bootstrap:

```bash
uv run lea runtime bootstrap \
    --config /absolute/path/to/lea.toml \
    --dry-run
```

## Known limitations

Milestone 2.0 does not provide secret generation, encryption or rotation; backup execution or scheduling; service management; operating-system user creation; permission repair; multi-user isolation; migration; remote configuration; hot reload; container layouts; or Windows/macOS deployment standards.

