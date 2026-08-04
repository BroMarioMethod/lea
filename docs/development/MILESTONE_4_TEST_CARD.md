# Milestone 4.0 Test-card Procedure

## Purpose

This is the ordered test procedure to follow after booting the LEA
release-candidate test card and pulling the Milestone 4.0 candidate. It verifies
the real root installer, managed khal/vdirsyncer toolchain, CLI and orchestration
chain, Radicale boundary, DAVx⁵ synchronisation, persistence, recovery and
removal behavior.

Use this procedure together with:

- `docs/development/RELEASE_CHECKLIST_MILESTONE_4.0.md` for the release decision;
- `docs/development/MILESTONE_4_RC_MAINTENANCE.md` for defects and retest notes;
- `docs/development/CALENDAR_PROVIDER_OPERATIONS.md` for detailed server,
  credential, backup, upgrade and removal rules.

Do not skip to live Android testing when an earlier gate fails. Stop, preserve
non-secret diagnostics, correct the candidate on its development branch, add a
regression test, and restart at the gate named by the correction.

## Evidence and secret-handling rules

Record only:

- candidate commit and branch;
- date, platform and installation mode;
- command exit status and named check result;
- expected and actual numeric mode and owner/group names;
- systemd active/enabled state;
- pass/fail for event direction, timezone, isolation and restore;
- defect, root cause, fix commit and retest result.

Never record Telegram tokens, CalDAV passwords, bcrypt verifiers, phone
identifiers, private URLs, live event summaries, calendar IDs or event UIDs in
Git, screenshots, shell history or diagnostics. Use unique temporary events and
delete them after acceptance.

## Gate 0 — Select and identify the candidate

From the test card:

```bash
cd /opt/lea
git status --short --branch
git fetch --prune origin
git switch milestone-4.0/calendar-provider
git pull --ff-only origin milestone-4.0/calendar-provider
git status --short --branch
git rev-parse HEAD
git log -1 --oneline --decorate
```

Expected:

- the source tree is clean;
- local and remote branch tips match;
- the commit is the exact candidate named in the test record.

Stop if the tree is dirty, the pull is not a fast-forward, or the commit differs
from the intended candidate. Do not test an unrecorded mixture of changes.

## Gate 1 — Host and release-asset preflight

Verify the supported host and system services:

```bash
uname -m
cat /etc/os-release
python3 --version
uv --version
test -S /run/dbus/system_bus_socket
systemctl is-active dbus.service
systemctl is-system-running
```

Verify that the pinned assets exist and retain their independently reviewed
digests:

```bash
sha256sum /opt/lea-release-assets/task-3.4.2.tar.gz
sha256sum /opt/lea-release-assets/calendar-requirements.lock
```

Do not copy a digest from the command output into the expected-value source.
Compare it with the independently reviewed release evidence. Stop on any host,
service, path or digest mismatch.

## Gate 2 — Candidate self-check

Before consuming another installation cycle, run:

```bash
cd /opt/lea
UV_CACHE_DIR=/tmp/lea-uv-cache scripts/check.sh
```

Expected: wrapper validation, Ruff, mypy, deployment validators and pytest all
pass. Host-dependent tests may skip only for the documented missing external
runtime reason. Stop on any failure.

This gate is also the automated proof that calendar inputs are connected
through the public wrapper and CLI, immutable request, engine/orchestrator,
installer dispatch, installation record and post-install acceptance path.

## Gate 3 — Choose the lifecycle path

For final release evidence, perform a fresh installation on a clean supported
card. Use `repair` only to verify a previously installed candidate after a
specific correction. Use `upgrade` only after the backup/restore gate passes.

Record one of:

```text
fresh-install
repair
upgrade
```

Repair success does not substitute for final fresh-install evidence.

## Gate 4 — Install through the supported entry point

The preferred test-user entry point is:

```bash
cd /opt/lea
sudo ./install.sh \
  --mode <fresh-install-or-repair> \
  --display-timezone Africa/Gaborone \
  --no-telegram
```

Use `--telegram` when the test profile includes the already documented live
Telegram acceptance. The wrapper supplies reviewed release defaults; inspect
its rendered plan before approval. If explicit overrides are required, use the
advanced command documented in `docs/03_INSTALLATION.md` and record only
non-secret paths, versions and digests.

Expected stages:

1. host preflight;
2. service account and managed filesystem provisioning;
3. base configuration;
4. Taskwarrior installation and activation;
5. calendar toolchain installation and activation;
6. read-only post-install health;
7. disposable functional acceptance.

Stop on an undocumented manual correction. Add the correction and its root
cause to the maintenance log before retrying.

## Gate 5 — Root ownership, mode and readability

The root installer must leave explicit final metadata; mode alone is
insufficient. Inspect the real paths selected by the installation records:

```bash
sudo stat -c '%a %U:%G %n' \
  /etc/lea/lea.toml \
  /etc/lea/taskwarrior/taskrc \
  /var/lib/lea/install/release-candidate.json \
  /var/lib/lea/install/taskwarrior.json \
  /var/lib/lea/install/calendar-toolchain.json \
  /var/lib/lea/audit/actions-integrity.jsonl

sudo find /etc/lea /var/lib/lea /opt/lea-tools \
  -xdev -type l -print
```

Compare every result with its installation contract. Configuration shared with
the service may be operator-owned with group `lea`; service state may be
`lea:lea`. Do not treat `$USER:lea`, `root:lea` and `lea:lea` as interchangeable.
There must be no unexpected symbolic links.

Prove effective access as the service identity:

```bash
sudo -u lea test -r /etc/lea/lea.toml
sudo -u lea test -r /etc/lea/taskwarrior/taskrc
sudo -u lea test -r /var/lib/lea/install/calendar-toolchain.json
sudo -u lea test -x /opt/lea-tools/taskwarrior/3.4.2/bin/task
```

Also verify the recorded khal and vdirsyncer paths rather than assuming a
layout version. Stop if root ownership, umask, atomic replacement or setgid
inheritance leaves a file unreadable or writable by the wrong identity.

## Gate 6 — Installed-system acceptance

Run the installed acceptance harness:

```bash
cd /opt/lea
sudo "$(command -v uv)" run lea accept-release-candidate \
  --no-telegram \
  --record-file /var/lib/lea/acceptance/release-candidate.json
```

Use `--telegram` for a Telegram-enabled profile. Expected: exit status `0` and
a mode-`0640` acceptance record with the contracted owner/group. A test-suite
pass does not replace this installed-system check.

## Gate 7 — Local calendar and orchestration chain

List collections through the public CLI:

```bash
cd /opt/lea
sudo -u lea "$(command -v uv)" run lea calendar list
```

Select a dedicated temporary test calendar without recording its identifier in
Git. Create a timed event proposal using local non-secret test values:

```bash
sudo -u lea "$(command -v uv)" run lea calendar create \
  <calendar-id> \
  --summary <temporary-summary> \
  --start <ISO-datetime> \
  --end <ISO-datetime> \
  --timezone Africa/Gaborone

sudo -u lea "$(command -v uv)" run lea proposal list
sudo -u lea "$(command -v uv)" run lea proposal approve \
  <proposal-id> --actor test-card-operator
sudo -u lea "$(command -v uv)" run lea proposal execute <proposal-id>
```

Expected:

- creation produces a persistent proposal but no event before execution;
- approval does not itself create the event;
- explicit execution creates exactly one event;
- list/show returns the event through the managed provider.

Repeat the proposal lifecycle for modify and cancel. Verify reject/cancel and a
duplicate or stale execution fail safely without unintended mutation.

## Gate 8 — Radicale health and reciprocal isolation

Provision and inspect Radicale exactly as described in
`docs/development/CALENDAR_PROVIDER_OPERATIONS.md`. It is a separate managed
service and must use a private LAN/VPN address, protected bcrypt credentials,
private storage and the hardened unit.

Verify:

```bash
systemctl is-enabled lea-radicale.service
systemctl is-active lea-radicale.service
systemctl status lea-radicale.service --no-pager
```

With two disposable accounts and separate collections, prove both directions:

- account A cannot read or write account B's collection;
- account B cannot read or write account A's collection.

Stop on any cross-account visibility, unexpected wildcard/public binding,
plaintext credential exposure, configuration drift or service hardening error.

## Gate 9 — Discovery and explicit synchronisation

Run discovery as a proposal-backed action:

```bash
sudo -u lea "$(command -v uv)" run lea calendar discover
sudo -u lea "$(command -v uv)" run lea proposal list
sudo -u lea "$(command -v uv)" run lea proposal approve \
  <proposal-id> --actor test-card-operator
sudo -u lea "$(command -v uv)" run lea proposal execute <proposal-id>
```

Then create and execute synchronization through the same boundary:

```bash
sudo -u lea "$(command -v uv)" run lea calendar sync
sudo -u lea "$(command -v uv)" run lea proposal list
sudo -u lea "$(command -v uv)" run lea proposal approve \
  <proposal-id> --actor test-card-operator
sudo -u lea "$(command -v uv)" run lea proposal execute <proposal-id>
```

Expected: neither discovery nor synchronization occurs merely from submission
or approval. Conflicts stop for operator review; they are not silently resolved.

## Gate 10 — DAVx⁵ and Android two-way acceptance

Pair DAVx⁵ using the private Radicale URL and the phone's distinct revocable
credential. Enable only the permitted test collection.

Perform both directions separately:

1. LEA → Android: synchronize the LEA-created timed event, refresh DAVx⁵ and
   confirm summary, date, time and `Africa/Gaborone` timezone on Android.
2. Android → LEA: create a different timed event on Android, refresh DAVx⁵,
   execute explicit LEA synchronization, then verify it with `lea calendar
   events` and `lea calendar show <calendar-id> <event-uid>`.

Record only pass/fail. Do not record the live identifiers or summaries.

## Gate 11 — Backup and isolated restore

Follow the exact backup surfaces and consistency rules in
`docs/development/CALENDAR_PROVIDER_OPERATIONS.md`. Stop Radicale for a
file-level storage backup or use an equivalent consistent snapshot. Preserve
ownership and modes.

Restore into an isolated host or staging root, not over the only working copy.
Verify:

- Radicale health;
- reciprocal user isolation;
- managed configuration and record modes/ownership;
- both known test events after explicit synchronization.

A copied archive without a successful isolated restore is not accepted.

## Gate 12 — Write Android acceptance evidence

Only after Gates 8, 10 and 11 pass, run:

```bash
cd /opt/lea
sudo "$(command -v uv)" run lea accept-calendar-android \
  --server-to-android-verified \
  --android-to-server-verified \
  --user-isolation-verified \
  --backup-verified
```

Expected: exit status `0` and a mode-`0640` record beneath
`/var/lib/lea/acceptance/`. The command must reject partial evidence and refuse
to overwrite different evidence.

## Gate 13 — Reboot persistence

Reboot the card, reconnect and verify:

```bash
systemctl is-system-running
systemctl is-active lea-radicale.service
test -d /run/lea
cd /opt/lea
sudo "$(command -v uv)" run lea accept-release-candidate --no-telegram
sudo -u lea "$(command -v uv)" run lea calendar list
```

For Telegram-enabled profiles, use `--telegram` and repeat the documented live
Telegram commands. Repeat one explicit calendar synchronization and confirm the
Android collection remains functional.

## Gate 14 — Repair, upgrade and rollback

After the final fresh-install evidence is retained:

1. rerun the same candidate in `repair` mode and verify idempotency;
2. complete a verified backup/restore before `upgrade` mode;
3. use the full pinned calendar arguments and `--approve-replacement`;
4. verify the pre-upgrade installation-record backup is preserved;
5. repeat ownership, installed acceptance, isolation and Android two-way gates;
6. inject or observe a safe failure in staging and prove the previous record and
   active toolchain remain usable.

Never delete mismatched state merely to make repair or upgrade continue.

## Gate 15 — Removal and credential revocation

First revoke the Android credential and prove it can no longer authenticate.
Verify the backup before any destructive operation.

Test Radicale non-purge removal separately as documented; it must retain
configuration, users and collections. Only after restore evidence exists may
its separately confirmed purge be tested.

Render and review the LEA purge plan before approving:

```bash
cd /opt/lea
sudo ./uninstall.sh
```

For the explicitly authorised destructive test:

```bash
cd /opt/lea
sudo ./uninstall.sh --yes
```

Expected: managed LEA configuration, state, logs, service identity,
Taskwarrior and calendar toolchains are removed. `/opt/lea`,
`/opt/lea-release-assets` and unrelated paths remain. Verify there are no
active managed services or usable revoked credentials.

## Gate 16 — Record results and decide

On the development branch, update
`docs/development/MILESTONE_4_RC_MAINTENANCE.md` with each defect and retest.
Update `docs/development/RELEASE_CHECKLIST_MILESTONE_4.0.md` only for directly
observed evidence.

Before merge:

1. resolve every maintenance entry;
2. transfer durable lessons to specifications, tests or operational docs;
3. remove the temporary maintenance log if the release process requires it;
4. run `scripts/check.sh` on the final candidate commit;
5. merge into current `main`;
6. rerun `scripts/check.sh` on the merge commit;
7. create `milestone-4.0` only when every release criterion is satisfied.

Do not tag a repair-only result, a partial Android check or a candidate whose
live evidence came from a different commit.
