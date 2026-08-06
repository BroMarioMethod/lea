# Milestone 4.0 test-card acceptance

## Status

| Field | Value |
| --- | --- |
| Date | 2026-08-06 |
| Branch | `milestone-4.0/calendar-provider` |
| Accepted source commit | `50b8bde8ee55c2c3cd5d2cf03d2073caa2f1bc47` |
| Live result | Passed final exact-commit rerun; merge review remains required |

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
- The final clean fresh-install run completed on the accepted source commit,
  followed by provider provisioning, bootstrap, two-way Android synchronization,
  reboot persistence, and post-reboot synchronization.
- The supported upgrade path completed idempotently without disturbing the
  activated CalDAV configuration.
- Supported Radicale removal and managed LEA purge completed; all managed
  services, state, credentials, service identity and units were absent while
  the source checkout and release assets remained.

## Final gate

The remediation plan from knowledge document
`4a2c1e2b-6d37-4a50-9f42-2f6fb94da801` was implemented on this branch. The
complete repository gate passed with 2525 tests passed and 7 environment-
appropriate skips. The branch is not marked merge-ready by this report:
maintainers must review the exact commit and repeat any organization-required
CI or PR checks.

Replacement rollback behavior is covered by automated tests; a distinct live
version replacement was not fabricated because no second supported calendar
version was available on the test card.

## Evidence custody

The live acceptance record, protected backup and runtime installation records
remain on the test card. They are not source artifacts and must not be copied
into Git. This report and the knowledge document are the only repository-safe
projections of that evidence.
