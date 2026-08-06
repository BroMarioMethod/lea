# Milestone 4.1 Test-card Procedure

Follow this procedure on the final candidate card after the automated gate
passes. Start from `milestone-4.0`-derived source and record the exact commit.
Use the Milestone 4 test-card procedure for installation, ownership, Radicale,
backup, reboot and removal prerequisites.

## Ordered checks

1. Pull and verify the clean candidate commit.
2. Run the complete automated quality gate.
3. Install fresh and run installed-system acceptance.
4. Verify managed paths, modes, owners, groups and service readability.
5. Create a recurring timed event through the CLI proposal flow; approve and
   execute it, then list and show its generated instances.
6. Create an all-day recurring event and verify local-date/timezone semantics.
7. Modify the series; verify the intended instances change and unrelated
   events do not.
8. Modify and cancel one explicit instance; verify the rest of the series.
9. Invite a second test account; exercise each supported attendee response.
10. Synchronize in both directions through DAVx⁵ and verify recurrence,
    timezone, attendee and response state.
11. Reboot and repeat one recurring-event synchronization check.
12. Back up, restore into an isolated staging root, and verify the series,
    instance exception and attendee response.
13. Exercise upgrade/rollback and both removal paths.
14. Record only non-secret pass/fail evidence and the final commit.

After all checks pass, persist the collaboration acceptance record on the card
(never in the repository) with:

```text
lea accept-calendar-collaboration \
  --candidate-commit "$(git rev-parse HEAD)" \
  --server-to-android-verified \
  --android-to-server-verified \
  --recurrence-verified \
  --attendee-response-verified \
  --reboot-verified \
  --user-isolation-verified \
  --backup-verified
```

The command must reject any missing check and writes a restrictive,
credential-free `calendar-collaboration.json` record.

## Stop conditions

Stop on recurrence timezone drift, ambiguous instance targeting, mutation before
explicit execution, attendee data leakage across accounts, silent conflict
resolution, insecure ownership/modes, secret output, or any undocumented manual
correction. Do not use experimental OAuth/provider integrations to satisfy an
MVP gate.

## Evidence rules

Never commit passwords, OAuth tokens, phone identifiers, calendar IDs, event
UIDs, attendee addresses or live event summaries. Keep operational acceptance
records and protected backups on the test card.
