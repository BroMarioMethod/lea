# Milestone 4.1 Release Checklist

| Field | Value |
|---|---|
| Milestone | `4.1` — Calendar Collaboration and Recurring Events |
| Base tag | `milestone-4.0` |
| Branch | `milestone-4.1/calendar-collaboration` |
| Proposed tag | `milestone-4.1` |
| MVP provider | Radicale via the Milestone 4 provider boundary |

## Automated gate

- [ ] recurrence contracts, parser and timezone tests pass;
- [ ] recurring-series and explicit-instance mutation tests pass;
- [ ] attendee and response-state tests pass;
- [ ] CLI and Telegram policy/proposal parity tests pass;
- [ ] synchronization and conflict diagnostics tests pass;
- [ ] backup/restore compatibility tests pass;
- [ ] Ruff, mypy, validators and complete pytest pass;
- [ ] Google OAuth and additional providers are excluded from the MVP artifact
  or separately labeled and approved as beta;
- [ ] the merge-result quality gate passes.

## Physical test-card gate

- [ ] fresh install from the final 4.1 candidate;
- [ ] root ownership and service readability remain correct;
- [ ] create and inspect a recurring timed event;
- [ ] create and inspect a recurring all-day event;
- [ ] modify a series and an explicit instance with no unintended siblings;
- [ ] cancel a series and an explicit instance safely;
- [ ] send an attendee invitation and record each supported response state;
- [ ] verify server-to-Android recurring and attendee synchronization;
- [ ] verify Android-to-server recurring and attendee synchronization;
- [ ] verify timezone and recurrence behavior after reboot;
- [ ] verify backup/isolated restore preserves series, instances and attendees;
- [ ] verify upgrade, rollback, non-purge removal and confirmed purge;
- [ ] retain credential-free evidence outside Git.

## Release decision

Do not merge or tag 4.1 until every MVP gate passes. OAuth and additional
providers require a separate beta decision and must not be used to declare the
MVP complete.
