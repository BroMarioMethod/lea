# Milestone 4.1 Release-candidate Maintenance Log

This Git-tracked working log records implementation slices and test-card
lessons. Do not record secrets, live calendar identifiers, attendee addresses,
tokens or device identifiers. Review before merge and remove this file only
after durable findings have been transferred to the specification/checklist.

## Slice record

| Slice | Commit | Result |
|---|---|---|
| Recurrence contracts and RRULE parsing | `8082984` | Focused and full gates passed |
| Deterministic recurrence expansion | `a374449` | Focused and full gates passed |
| Series/instance mutation targets | `063aa93` | Focused and full gates passed |
| Attendee contracts and khal parsing | `082ad37` | Focused and full gates passed |
| CLI collaboration flows | `83b4611` | Focused and full gates passed |
| Conflict diagnostics | `c080fa4` | Focused synchronization and full gate passed |
| Collaboration acceptance evidence | `7893ed2` | Focused/docs/typing gates passed |
| Candidate-bound acceptance evidence | `eff2a31` | Full gate passed; evidence now records exact SHA |
| Isolated restore hardening | `09f2126` | Recovery/rollback suite passed |

## Current external status

- Automated implementation checks are green for the slices above.
- Exact candidate `11dccd6` passed `scripts/check.sh`: 2,547 tests passed and
  7 expected environment skips.
- At `1c3c12d`, the branch is clean, synced with its origin branch, and
  `git merge-tree --write-tree origin/main HEAD` reports no conflicts.
- The physical DAVx⁵/Android test-card run for the final commit is still
  required; it must produce the collaboration acceptance record outside Git.
- Merge remains blocked until the final card evidence and merge-result gate are
  recorded in the release checklist.
