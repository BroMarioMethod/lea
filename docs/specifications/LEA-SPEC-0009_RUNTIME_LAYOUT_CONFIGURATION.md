---
id: LEA-SPEC-0009
title: Runtime Layout and Configuration Specification
version: 0.1.1
status: Accepted
review_required: false
---

# Runtime Layout and Configuration Specification

## Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Not Started |
| Test Status | Not Tested |

## 1. Purpose

This specification defines LEA's runtime filesystem layout and deterministic configuration loading.

The runtime layout separates source-controlled project files from deployed state, personal data, secrets, logs and generated indexes.

Milestone 2.0 provides the foundation required before persistent proposal storage, Taskwarrior integration, messaging adapters and test-user deployment.

## 2. Scope

Milestone 2.0 shall provide:

- canonical runtime path contracts;
- a deterministic TOML configuration schema;
- explicit development and system deployment profiles;
- configuration loading from an explicitly supplied path;
- deterministic validation of configuration values;
- runtime directory bootstrap;
- runtime health checks;
- UTC storage with local-time presentation support;
- explicit secret-path references without secret values in configuration;
- no hidden fallback to repository-relative runtime state;
- no automatic network access;
- no external tool execution.

## 3. Non-goals

Milestone 2.0 shall not provide:

- persistent proposal storage;
- Taskwarrior integration;
- Telegram or LAN messaging;
- AI model loading;
- plugin discovery;
- automatic service installation;
- operating-system user creation;
- package installation;
- secret generation or encryption;
- backup execution;
- migration of existing personal data;
- multi-user runtime isolation;
- container deployment.

## 4. Design principles

The runtime configuration system shall be:

- deterministic;
- explicit;
- immutable after successful loading;
- independent of the current working directory;
- safe against accidental repository data pollution;
- testable without root privileges;
- suitable for DietPi and other Debian-family Linux systems;
- readable by humans;
- strict about unknown and missing fields;
- free from embedded secrets.

## 5. Deployment profiles

### 5.1 System profile

Recommended system deployment paths:

```text
/etc/lea/                 Configuration
/var/lib/lea/             Persistent application state
/var/log/lea/             Application logs
/run/lea/                 Ephemeral runtime state
```

Suggested subdirectories:

```text
/etc/lea/
    lea.toml
    secrets/

/var/lib/lea/
    audit/
    proposals/
    knowledge/
    indexes/
    adapters/
    backups/

/var/log/lea/
    lea.log

/run/lea/
    lea.pid
    sockets/
```

### 5.2 Development profile

Development and tests shall support explicitly supplied non-root paths such as:

```text
<workspace>/.runtime/etc/
<workspace>/.runtime/state/
<workspace>/.runtime/log/
<workspace>/.runtime/run/
```

Development runtime paths shall remain excluded from Git. Production code shall not assume that the repository root is the runtime root.

## 6. Configuration file

The initial configuration format shall be TOML. The canonical configuration file shall be explicitly supplied to the loader.

Example:

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

Unknown fields shall fail closed.

## 7. Public contracts

### 7.1 RuntimeProfile

A stable `StrEnum` shall identify `system`, `development` and `test` profiles.

### 7.2 RuntimePaths

An immutable `RuntimePaths` contract shall contain canonical absolute paths for:

- configuration file;
- state directory;
- log directory;
- run directory;
- audit directory;
- proposal directory;
- knowledge directory;
- index directory;
- adapter directory;
- backup directory;
- audit file;
- log file.

### 7.3 SecretPaths

An immutable `SecretPaths` contract shall contain paths to secret files and shall not contain secret values.

### 7.4 RuntimeConfig

An immutable `RuntimeConfig` contract shall contain schema version, runtime profile, display timezone, `RuntimePaths` and `SecretPaths`.

### 7.5 Configuration result

Configuration loading shall return either a valid immutable configuration or a structured failure with stable code, message, field or path where available, and source configuration path where available.

## 8. Path rules

Configured runtime paths shall:

- be absolute;
- be normalised without relying on the current working directory;
- reject embedded null bytes;
- reject empty values;
- preserve symbolic links rather than resolving them silently during parsing;
- not require the target path to exist during pure configuration parsing;
- be checked for existence and permissions by a separate health-check step.

## 9. Directory relationships

At minimum:

- the audit file shall be inside the configured audit directory;
- the log file shall be inside the configured log directory;
- persistent directories shall not be nested under the run directory;
- system-profile runtime state shall not be stored inside the source repository;
- development-profile paths may be placed inside an explicitly designated ignored runtime directory.

Validation shall compare normalised path components and avoid unsafe string-prefix comparisons.

## 10. Configuration loading

The loader shall:

1. receive an explicit configuration path;
2. read UTF-8 TOML;
3. reject malformed TOML;
4. require the supported schema version;
5. reject missing required fields;
6. reject unknown fields;
7. validate enum values;
8. validate timezone identifiers;
9. construct immutable path contracts;
10. return a structured result.

The loader shall not search multiple default locations, read environment variables implicitly, create directories, read secret contents, connect to external services or mutate global state.

## 11. Time handling

Persistent timestamps shall remain timezone-aware UTC values. The configuration shall include an IANA display timezone such as `Africa/Gaborone`.

A presentation utility shall convert UTC timestamps to the configured display timezone while preserving the represented instant and rejecting naive input.

## 12. Runtime bootstrap

A deterministic bootstrap operation shall create configured directories only when explicitly requested.

It shall:

- create missing directories only;
- preserve existing directories and files;
- refuse paths that conflict with existing non-directory entries;
- report every created and pre-existing path;
- support dry-run mode;
- avoid creating secret files;
- avoid overwriting configuration;
- perform no network access.

Bootstrap shall not run implicitly during configuration loading.

## 13. Health checks

A read-only runtime health check shall report:

- configuration-file readability;
- directory existence and type;
- read and write permission where required;
- audit-file and log-file parent availability;
- secret-file presence without exposing content;
- display-timezone validity;
- runtime-path separation violations.

Health checks shall not repair, create or delete anything.

## 14. Secret handling

Secret values shall not appear in Git-tracked configuration, logs, diagnostic bundles, exception messages, Markdown knowledge or audit payloads unless a later accepted specification explicitly requires it.

Configuration may reference secret-file paths. Reading secret values is outside Milestone 2.0.

## 15. Failure behaviour

Stable issue codes shall distinguish at least:

- configuration_not_found;
- configuration_not_readable;
- malformed_toml;
- unsupported_schema_version;
- missing_field;
- unknown_field;
- invalid_profile;
- invalid_path;
- invalid_path_relationship;
- invalid_timezone;
- runtime_path_missing;
- runtime_path_not_directory;
- runtime_path_not_readable;
- runtime_path_not_writable;
- secret_file_missing.

## 16. Immutability

Public configuration and result contracts shall use frozen dataclasses with slots. Exposed mappings and sequences shall be deeply immutable or represented by immutable tuples and dedicated contracts.

## 17. Security considerations

The implementation shall:

- reject relative production runtime paths;
- avoid shell command construction;
- avoid implicit environment-variable expansion;
- avoid logging secret contents;
- separate parsing, bootstrap and health-check operations;
- avoid silent repair;
- avoid permissive fallbacks after configuration errors.

Directory permission guidance shall follow least privilege.

## 18. Testing requirements

Automated tests shall cover at least:

- valid system, development and test configuration;
- malformed TOML;
- missing configuration file;
- unsupported schema version;
- unknown top-level and nested fields;
- missing required fields;
- invalid profile;
- relative and empty paths;
- invalid audit-file and log-file relationships;
- repository/runtime separation;
- valid and invalid IANA timezones;
- UTC-to-local conversion;
- naive timestamp rejection;
- immutable contracts;
- bootstrap creation, idempotence and dry run;
- conflicting non-directory paths;
- complete and incomplete health checks;
- missing secret file;
- no secret-content reads;
- no filesystem mutation during health checks;
- no current-working-directory dependency;
- no implicit environment-variable loading.

The full repository quality gate shall pass before completion.

## 19. Documentation requirements

Completion documentation shall include:

- system and development layouts;
- example TOML configuration;
- runtime bootstrap and health-check instructions;
- file and directory permission guidance;
- secret-file guidance;
- timezone behaviour;
- backup boundaries;
- known limitations.

## 20. Known limitations

Milestone 2.0 shall not provide encrypted secret storage, secret rotation, backup scheduling, service management, multi-user isolation, automatic migration, remote configuration, hot reload, container layouts, or Windows/macOS deployment standards.

## 21. Acceptance criteria

Milestone 2.0 is complete when:

- this specification is accepted;
- immutable runtime configuration contracts are implemented;
- explicit TOML loading is implemented;
- unknown and missing fields fail closed;
- runtime paths are validated independently of the current working directory;
- system and development profiles are supported;
- UTC-to-local presentation is implemented;
- deterministic bootstrap is implemented;
- read-only health checking is implemented;
- secret paths are referenced without reading or storing secret values;
- example configuration and operational documentation are complete;
- all automated tests and repository quality checks pass.

