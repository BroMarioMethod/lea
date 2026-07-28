license: AGPL-3.0-only
---
id: LEA-SPEC-0009
title: Runtime Layout and Configuration Specification
version: 0.2.0
status: Accepted
review_required: false
---

# Runtime Layout and Configuration Specification

## Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Complete |
| Test Status | 663 repository tests passing |

## 1. Purpose

This specification defines LEA's runtime filesystem layout, deterministic configuration loading, safe setup, health checking, inspection, reporting and administration commands.

The runtime layout separates source-controlled project files from deployed state, personal data, secrets, logs and generated indexes.

## 2. Scope

Milestone 2.0 provides:

- immutable runtime path and configuration contracts;
- strict UTF-8 TOML loading from an explicit absolute path;
- system, development and test profiles;
- deterministic TOML templates and serialisation;
- safe configuration initialisation without accidental overwrite;
- runtime-directory bootstrap with dry-run support;
- read-only runtime health checks;
- coordinated setup and post-setup verification;
- read-only configuration inspection;
- deterministic human-readable reports;
- `lea runtime` command handling and top-level dispatch;
- timezone-aware UTC storage with IANA local-time presentation;
- secret-file path references without secret values;
- no automatic network access or external tool execution.

## 3. Non-goals

Milestone 2.0 does not provide persistent proposal storage, Taskwarrior integration, messaging adapters, AI model loading, plugin discovery, service installation, operating-system user creation, package installation, secret generation or encryption, backup execution, personal-data migration, multi-user isolation or container deployment.

## 4. Design principles

The runtime system is deterministic, explicit, immutable after loading, independent of the current working directory, strict about unknown and missing fields, testable without root privileges and free from embedded secrets.

## 5. Canonical profiles

### 5.1 System

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

Configured data files:

```text
/var/lib/lea/audit/actions-integrity.jsonl
/var/log/lea/lea.log
```

### 5.2 Development

For an explicitly supplied workspace root:

```text
<workspace>/.lea/config/lea.toml
<workspace>/.lea/state/
<workspace>/.lea/log/
<workspace>/.lea/run/
```

The `.lea/` directory must remain excluded from Git.

### 5.3 Test

For an explicitly supplied isolated root:

```text
<test-root>/config/lea.toml
<test-root>/state/
<test-root>/log/
<test-root>/run/
```

## 6. TOML configuration

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

Unknown and missing fields fail closed.

## 7. Path and relationship rules

Runtime paths:

- are absolute;
- reject empty values and embedded null bytes;
- do not depend on the current working directory;
- preserve symbolic links during parsing;
- need not exist during pure loading.

The implementation requires the audit file to be inside `audit_dir`, the log file to be inside `log_dir`, and persistent directories not to be nested under `run_dir`.

## 8. Loading and validation

The loader reads one explicit UTF-8 TOML file, validates schema version, required and unknown fields, profile values, paths, path relationships and IANA timezone identifiers, then returns an immutable `ConfigurationResult`.

It does not search fallback locations, read environment variables implicitly, create directories, read secret contents or mutate global state.

## 9. Templates, serialisation and initialisation

Canonical templates are available for all profiles.

Serialisation is deterministic, uses UTF-8 and LF line endings, ends with one newline, emits secret paths only and omits an unused secrets table.

Configuration initialisation requires an existing parent directory and refuses to overwrite an existing destination.

## 10. Time handling

Persistent timestamps remain timezone-aware UTC. `display_timezone` affects presentation only.

The presentation utility preserves the represented instant and rejects naive or non-UTC input.

## 11. Bootstrap

Bootstrap explicitly creates missing runtime directories, preserves existing directories, rejects non-directory conflicts, supports dry-run mode and reports every inspected path.

It does not create configuration, audit, log or secret files and performs no network access.

## 12. Health checks

Read-only health checks report configuration readability, directory existence and type, required access, output-file parent availability, optional secret-file presence, timezone availability and path-separation violations.

Health checking never repairs, creates or deletes anything.

## 13. Setup, verification and inspection

`setup_runtime` initialises configuration first and runs bootstrap only after successful initialisation.

`setup_and_verify_runtime` runs a health check only after successful live setup. Dry-run setup never claims verification.

`inspect_runtime` loads one explicit configuration and optionally includes a read-only health check.

## 14. Runtime command line

Existing application startup remains:

```bash
lea
```

Runtime administration is available through:

```bash
lea runtime inspect
lea runtime health
lea runtime initialise
lea runtime bootstrap
lea runtime setup
lea runtime verify
```

The equivalent package route is:

```bash
python -m lea runtime --help
```

Mutation-capable commands support `--dry-run`.

Exit statuses:

```text
0   Success
1   Runtime or application failure
2   Configuration or command-usage failure
70  Unexpected failure in the existing application path
```

## 15. Secret handling

Configuration and reports contain secret-file paths only. Secret contents are not read by Milestone 2.0 and must not be committed, logged or embedded in TOML.

## 16. Security considerations

The implementation avoids shell command construction, implicit environment expansion, silent repair, permissive fallback and accidental configuration overwrite. Filesystem ownership and least-privilege permissions remain operator responsibilities.

## 17. Testing

Coverage includes contracts, layouts, strict loading, serialisation round trips, timezone conversion, initialisation, bootstrap, health checks, setup, verification, inspection, reporting, CLI parsing, dispatch, exit codes and no unintended filesystem mutation.

At completion, all 663 repository tests pass.

## 18. Documentation

Operator guidance is provided in:

```text
docs/08_RUNTIME_CONFIGURATION.md
```

## 19. Known limitations

Milestone 2.0 does not provide encrypted secret storage, secret rotation, backup execution or scheduling, service management, multi-user isolation, automatic migration, remote configuration, hot reload, container layouts, Windows or macOS deployment standards, configuration-parent creation or permission repair.
