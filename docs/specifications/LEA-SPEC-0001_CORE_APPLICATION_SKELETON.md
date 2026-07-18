---
title: Core Application Skeleton Specification
document_id: LEA-SPEC-0001
version: 0.1.0
status: Accepted
authors:
  - Marius du Preez
  - OpenAI ChatGPT
license: GPL-3.0-only
created: 2026-07-18
last_updated: 2026-07-18
review_required: false
---

# Core Application Skeleton Specification

## Document Status

| Item | Value |
|---|---|
| Status | Accepted |
| Requires Review | No |
| Implementation | Not Started |
| Test Status | Not Tested |

---

## 1. Purpose

This specification defines the first executable application structure for LEA.

The implementation SHALL provide a small, deterministic application skeleton that establishes:

- a command-line entry point;
- application lifecycle boundaries;
- configuration loading;
- structured logging;
- controlled error handling;
- predictable process exit statuses.

This milestone SHALL establish foundations for later workflow, plugin and AI subsystems without implementing those subsystems prematurely.

---

## 2. Why?

LEA currently has an installable Python package and a placeholder command, but it does not yet have an application architecture.

A defined application skeleton provides one controlled path through which future capabilities can be initialised, executed and shut down.

Without this boundary, configuration, logging, error handling and integrations could become scattered across unrelated modules.

---

## 3. Scope

This specification defines:

- the package module structure for the initial application;
- the public command-line entry point;
- application startup and shutdown;
- immutable application configuration;
- environment-variable configuration;
- structured console logging;
- application-specific exceptions;
- exit-status mapping;
- initial unit tests.

This specification does not define:

- AI model integration;
- workflow execution;
- plugin discovery or loading;
- Telegram or other communication adapters;
- runtime filesystem layout;
- persistent databases;
- domain-specific configuration;
- background services or daemons;
- command-line subcommands;
- network access.

---

## 4. Engineering Principles

### EP-001 — Deterministic Startup

Application startup SHALL be deterministic for the same configuration and environment.

### EP-002 — Explicit Dependencies

Application components SHALL receive their dependencies explicitly rather than retrieving hidden global state.

### EP-003 — Controlled Failure

Expected application failures SHALL be converted into clear log messages and documented non-zero exit statuses.

### EP-004 — No AI Authority

The core application skeleton SHALL contain no model-generated decisions or direct AI execution.

### EP-005 — Local-First Operation

The initial application SHALL start and complete without network access.

### EP-006 — Minimal Foundation

The implementation SHALL include only infrastructure required by the current milestone.

Future abstractions SHALL NOT be introduced unless they are necessary to satisfy an accepted requirement.

---

## 5. Package Structure

The initial package structure SHALL be:

```text
src/lea/
├── __init__.py
├── __main__.py
├── application.py
├── config.py
├── errors.py
├── logging.py
└── main.py
```

Tests SHALL reside under:

```text
tests/
├── test_application.py
├── test_config.py
└── test_main.py
```

Modules MAY be divided further in later milestones when their responsibilities justify additional structure.

---

## 6. Requirements

### CA-001 — Public Command

The installed command:

```text
lea
```

SHALL invoke:

```text
lea.main:main
```

The package SHALL also support:

```bash
python -m lea
```

Both invocation methods SHALL use the same application entry point.

### CA-002 — Entry-Point Signature

The public entry-point function SHALL have the signature:

```python
def main() -> int:
    ...
```

It SHALL return an integer process exit status.

The wrapper used by installed scripts SHALL convert that returned value into the process exit status.

### CA-003 — Application Function

The deterministic application function SHALL be separated from the command-line wrapper.

Its initial interface SHALL resemble:

```python
def run(config: AppConfig) -> None:
    ...
```

The application function SHALL NOT terminate the Python interpreter directly.

### CA-004 — Configuration Object

Application configuration SHALL be represented by an immutable typed object named:

```text
AppConfig
```

The initial configuration SHALL include:

- application environment;
- log level.

### CA-005 — Configuration Source

The initial configuration SHALL be loaded from environment variables.

Supported variables SHALL be:

```text
LEA_ENV
LEA_LOG_LEVEL
```

Default values SHALL be:

```text
LEA_ENV=development
LEA_LOG_LEVEL=INFO
```

### CA-006 — Supported Environments

The initial supported application environments SHALL be:

```text
development
test
production
```

Environment values SHALL be normalised to lower case before validation.

Unsupported values SHALL produce a configuration error.

### CA-007 — Supported Log Levels

The initial supported log levels SHALL be:

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

Log-level values SHALL be normalised to upper case before validation.

Unsupported values SHALL produce a configuration error.

### CA-008 — Environment Loading

The core configuration loader SHALL read from a supplied mapping where practical.

It SHALL NOT require tests to mutate the process-wide environment.

The process environment MAY be supplied by the public entry point.

### CA-009 — Logging Initialisation

Logging SHALL be initialised after configuration has been validated and before application execution begins.

The initial implementation SHALL log to standard error.

### CA-010 — Log Format

The initial console log format SHALL include:

- timestamp;
- severity;
- logger name;
- message.

The timestamp SHALL include timezone information.

### CA-011 — Logging Ownership

Application modules SHALL obtain named loggers using:

```python
logging.getLogger(__name__)
```

Application modules SHALL NOT repeatedly configure global logging.

### CA-012 — Startup Message

A successful application run SHALL emit a startup log containing:

- the application name;
- the application version;
- the selected environment.

### CA-013 — Completion Message

A successful application run SHALL emit a completion log.

### CA-014 — Application Version

The application version SHALL be obtained from installed package metadata.

The version SHALL NOT be duplicated as an independent constant when package metadata is available.

### CA-015 — Base Exception

Expected LEA application failures SHALL inherit from:

```text
LeaError
```

### CA-016 — Configuration Exception

Invalid configuration SHALL raise:

```text
ConfigurationError
```

`ConfigurationError` SHALL inherit from `LeaError`.

### CA-017 — Exit Statuses

The command-line process SHALL use:

| Status | Meaning |
|---:|---|
| `0` | Successful execution |
| `1` | Expected LEA application failure |
| `2` | Invalid configuration |
| `70` | Unexpected internal failure |

Exit status `70` follows the commonly recognised software-error value from `sysexits.h`.

### CA-018 — Expected Error Handling

A `ConfigurationError` SHALL:

- produce a concise error log;
- return exit status `2`;
- not display a traceback during normal execution.

Other `LeaError` instances SHALL:

- produce a concise error log;
- return exit status `1`;
- not display a traceback during normal execution.

### CA-019 — Unexpected Error Handling

An unexpected exception SHALL:

- be logged with exception information;
- return exit status `70`.

The implementation SHALL NOT silently suppress unexpected failures.

### CA-020 — Import Safety

Importing LEA modules SHALL NOT:

- configure logging;
- read configuration;
- access the network;
- create files;
- start application execution.

These actions SHALL occur only through explicit function calls.

### CA-021 — Network Independence

Starting the application SHALL require no network access.

### CA-022 — Filesystem Independence

The initial application SHALL not require runtime directories, writable project files or persistent storage.

### CA-023 — Language Convention

Logs, exceptions, documentation and comments SHALL use UK English.

### CA-024 — Type Safety

All application functions SHALL use type annotations and pass strict mypy checks.

### CA-025 — Tests

Automated tests SHALL cover at least:

1. default configuration;
2. normalised configuration values;
3. invalid application environment;
4. invalid log level;
5. successful application execution;
6. successful public entry-point status;
7. configuration-error exit status;
8. expected application-error exit status;
9. unexpected-error exit status;
10. package execution through the shared entry point.

Tests SHALL remain deterministic and network-independent.

---

## 7. Initial Execution Sequence

The public entry point SHALL perform the following sequence:

1. Load and validate configuration.
2. Initialise logging.
3. Execute the application function.
4. Map expected failures to documented exit statuses.
5. Log unexpected exceptions.
6. Return the final exit status.

Conceptually:

```text
process environment
        ↓
load_config()
        ↓
configure_logging()
        ↓
run(config)
        ↓
exit status
```

---

## 8. Configuration Example

The following environment variables SHALL be supported:

```bash
export LEA_ENV=development
export LEA_LOG_LEVEL=INFO
uv run lea
```

An invalid example:

```bash
export LEA_LOG_LEVEL=VERBOSE
uv run lea
```

SHALL terminate with exit status `2`.

---

## 9. Security Considerations

The initial configuration SHALL contain no secrets.

Log messages SHALL NOT include complete environment mappings.

Future secret-bearing configuration SHALL require explicit redaction rules before being logged.

Unexpected exception logs MAY contain diagnostic details and SHALL be treated as potentially sensitive.

---

## 10. Out of Scope

This specification does not define:

- `.env` file parsing;
- TOML application configuration;
- command-line arguments;
- interactive input;
- model selection;
- plugin registration;
- workflow actions;
- service supervision;
- rotating file logs;
- telemetry;
- remote logging;
- localisation.

---

## 11. Success Criteria

This specification is satisfied when:

- `uv run lea` completes successfully;
- `uv run python -m lea` uses the same application path;
- default configuration loads correctly;
- invalid configuration returns exit status `2`;
- expected and unexpected failures use their documented statuses;
- logging is configured once through an explicit function;
- no network or persistent storage is required;
- all tests pass;
- Ruff, mypy and pytest pass through `scripts/check.sh`;
- implementation behaviour matches this specification.

---

## 12. Future Considerations

Future specifications MAY introduce:

- command-line subcommands;
- layered TOML and environment configuration;
- runtime workspace discovery;
- structured JSON logs;
- log-file rotation;
- dependency injection containers;
- application lifecycle hooks;
- workflow-engine startup;
- plugin-manager startup;
- health and diagnostics commands;
- service-manager integration.

---

## 13. References

- LEA-STD-0001 — Repository Layout Standard
- LEA-SPEC-0001 depends on the Python project configuration in `pyproject.toml`
- RFC 2119 — Key words for use in RFCs to Indicate Requirement Levels
- RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words
- `sysexits.h` — conventional process exit statuses
