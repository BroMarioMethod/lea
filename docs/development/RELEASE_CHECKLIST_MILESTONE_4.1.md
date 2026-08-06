# Milestone 4.1 Release Checklist

| Field | Value |
|---|---|
| Milestone | `4.1` — Calendar Collaboration and Recurring Events |
| Base tag | `milestone-4.0` |
| Branch | `milestone-4.1/calendar-collaboration` |
| Proposed tag | `milestone-4.1` |
| MVP provider | Radicale via the Milestone 4 provider boundary |

## Automated gate

- [x] recurrence contracts, parser and timezone tests pass;
- [x] recurring-series and explicit-instance mutation tests pass;
- [x] attendee and response-state tests pass;
- [x] CLI and Telegram policy/proposal parity tests pass;
- [x] synchronization and conflict diagnostics tests pass;
- [x] backup/restore compatibility tests pass;
- [x] Ruff, mypy, validators and complete pytest pass;
- [x] Google OAuth and additional providers are excluded from the MVP artifact
  or separately labeled and approved as beta;
- [ ] the merge-result quality gate passes on the final merge result.

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

The final card operator must persist the required live evidence with
`lea accept-calendar-collaboration` using all seven verification flags listed
in `MILESTONE_4_1_TEST_CARD.md`. The resulting record remains on the card and
is not committed.

## Release decision

Do not merge or tag 4.1 until every MVP gate passes. OAuth and additional
providers require a separate beta decision and must not be used to declare the
MVP complete. The current candidate `11dccd6` has a green automated gate
(2,547 passed, 7 expected skips); the physical test-card gate and merge-result
quality gate remain open until their evidence is recorded.
