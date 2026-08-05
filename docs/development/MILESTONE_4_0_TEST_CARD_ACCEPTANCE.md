# Milestone 4.0 test-card acceptance

## Status

| Field | Value |
| --- | --- |
| Date | 2026-08-04 |
| Branch | `milestone-4.0/calendar-provider` |
| Accepted source commit | `79d42d5` |
| Live result | Passed with development follow-ups |

This report is intentionally credential-free. It contains no password,
verifier, device identifier, event identifier or live event summary.

## Passed evidence

- Release-candidate repair, health and disposable calendar lifecycle passed.
- The managed khal and vdirsyncer paths and versions matched their installation
  record.
- Radicale required authentication and was bound only to a private address.
- Two accounts could access their own principals and were reciprocally denied
  access to the other principal.
- Explicit discovery and synchronization completed.
- Server-to-Android and Android-to-server propagation were directly observed.
- Android-originated data was verified through list and exact-show provider
  operations.
- A stopped-service backup was restored into an isolated staging root.
- The restored server passed health and reciprocal-isolation checks.
- A fresh staging vdir synchronized from restored storage and contained both
  acceptance directions.
- The credential-free Android acceptance record was written with mode 0640.
- The credential-bearing backup was restricted to root ownership and mode
  0600.

## Follow-up gate

The live run exposed merge-blocking deployment gaps. The canonical remediation
plan is the tracked knowledge document with ID
`4a2c1e2b-6d37-4a50-9f42-2f6fb94da801`. In summary, merge remains blocked on:

- reproducible Radicale release assets;
- a supported Radicale and CalDAV deployment entry point;
- correct privileged-provisioning ownership;
- bounded service readiness;
- explicit non-interactive first-collection bootstrap;
- redaction-safe execution diagnostics;
- secure backup tooling; and
- automated regression coverage followed by a complete live rerun.

## Evidence custody

The live acceptance record, protected backup and runtime installation records
remain on the test card. They are not source artifacts and must not be copied
into Git. This report and the knowledge document are the only repository-safe
projections of that evidence.
