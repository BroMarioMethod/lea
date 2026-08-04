# Calendar provider operations

This runbook covers the Milestone 4.0 calendar client, Radicale and Android
boundaries. Operate Radicale on a private LAN address or through a private VPN;
do not bind it to a wildcard or expose it directly to the public internet.
Use TLS at the network boundary whenever credentials cross a network.

## Security and managed paths

The components have separate lifecycle boundaries:

- the versioned khal/vdirsyncer toolchain is under
  `/opt/lea-tools/calendar/`;
- non-secret client configuration is under `/etc/lea/calendar/`;
- local vdirs and synchronisation state are under `/var/lib/lea/calendar/`;
- the CalDAV password is `/var/lib/lea/secrets/calendar/caldav-password`;
- Radicale configuration, bcrypt user verifiers and collection storage must be
  separate paths outside the source checkout;
- installation and Android acceptance records are under
  `/var/lib/lea/install/` and `/var/lib/lea/acceptance/`.

Never put a plaintext password, bcrypt verifier, phone identifier or live event
identifier in Git, shell history, screenshots, diagnostics or this runbook.
Use a distinct, revocable password for each DAVx⁵ account.

## Install or repair the calendar client

Use the release asset's reviewed hash-pinned requirements lock and independently
verify its expected SHA-256. Supply exact trusted `uv` and Python paths; never
allow `PATH` to select them implicitly.

```text
lea install-release-candidate \
  --mode fresh-install \
  --calendar-requirements-lock /opt/lea-release-assets/calendar-requirements.lock \
  --calendar-requirements-sha256 <reviewed-lowercase-sha256> \
  --calendar-uv-executable <absolute-trusted-uv-path> \
  --calendar-python-executable <absolute-trusted-python-path> \
  --calendar-toolchain-version <pinned-layout-version> \
  --calendar-khal-version 0.11.4 \
  --calendar-vdirsyncer-version 0.19.3 \
  <the-required-pinned-taskwarrior-arguments> \
  --approve --non-interactive
```

The verified-network installer rejects unhashed, unpinned and source-only
packages. Bundled-wheelhouse and external-executable installations use the
calendar installer boundary directly and retain the same exact-version, hash,
smoke-test and installation-record requirements. Do not substitute an
unreviewed package index or executable.

After installation, inspect `/var/lib/lea/install/calendar-toolchain.json` and
run `lea calendar list`. The recorded khal and vdirsyncer paths must be absolute
managed paths and the disposable calendar lifecycle must pass.

## Provision Radicale and CalDAV

Radicale is deliberately not part of the khal provider or Android installer.
Deployment automation must call `lea.installers.radicale.install_radicale` with:

- one exact non-symbolic Radicale executable, pinned version and SHA-256;
- a private or loopback bind address and explicit port;
- bcrypt htpasswd verifiers with cost 12 or higher, supplied from a protected
  secret input;
- distinct configuration, mode-0700 secret and private storage directories;
- the hardened `lea-radicale.service` definition; and
- explicit activation, unauthenticated DAV health inspection and two-account
  reciprocal collection-isolation acceptance.

The installer verifies the executable both before and immediately before
registration. It fails closed on configuration, credential, unit or record
drift and does not silently replace any of them. Treat a mismatch as an
investigation, not a repair instruction.

Provision the vdirsyncer secret through
`provision_calendar_caldav_password`, then explicitly activate the CalDAV
configuration through `activate_calendar_caldav_configuration` with replacement
approval. The generated pair discovers collections in both directions and sets
`conflict_resolution = null`; conflicts therefore stop for operator review.
The password is fetched from the separate mode-0600 file and is never embedded
in `vdirsyncer.conf`.

Discover collections before the first synchronization:

```text
lea calendar discover
lea proposal list
lea proposal approve <proposal-id>
lea proposal execute <proposal-id>
lea calendar sync
lea proposal approve <sync-proposal-id>
lea proposal execute <sync-proposal-id>
```

Telegram uses the equivalent explicit `/calendar_discover` and
`/calendar_sync` proposal flows. Approval alone never executes or synchronizes.

## Pair DAVx⁵ on Android

DAVx⁵ is installed and managed on the phone, not by LEA. The official DAVx⁵
manual describes [account and collection management](https://manual.davx5.com/accounts_collections.html),
[synchronisation settings](https://manual.davx5.com/settings.html), and
[Radicale compatibility](https://www.davx5.com/tested-with/radicale).

1. On the private LAN or VPN, add an account in DAVx⁵ using the Radicale base
   URL ending in `/`, the authorised username and that phone's revocable
   password. Do not store the password in notes or Git.
2. Open the DAVx⁵ account, refresh the collection list and enable only the
   calendars permitted for this user.
3. Enable calendar synchronisation for the account and perform an explicit
   refresh. Confirm the Android calendar application exposes only those
   selected collections.
4. If access is no longer needed, revoke or rotate the Radicale credential
   first, remove the DAVx⁵ account through DAVx⁵, and verify that the old
   credential can no longer authenticate.

DAVx⁵ synchronisation is not a backup. Keep independent server-side backups.

## Two-way live acceptance

Use unique temporary summaries but do not record their values or event IDs in
Git. Perform all four checks before recording acceptance:

1. Create a timed event through LEA, approve it, explicitly execute it, run
   collection discovery/synchronisation, refresh DAVx⁵, and verify the same
   time and timezone in the Android calendar application.
2. Create a different event in the Android application, refresh DAVx⁵, run
   explicit LEA synchronisation, and verify it through `lea calendar list` and
   `lea calendar show <calendar-id> <event-uid>`.
3. Authenticate as a second test user and verify reciprocal access fails: each
   user must be unable to read or write the other user's collection.
4. Complete the backup and restore drill below and verify both test events from
   restored state.

Only after direct observation of every check, write non-secret evidence:

```text
lea accept-calendar-android \
  --server-to-android-verified \
  --android-to-server-verified \
  --user-isolation-verified \
  --backup-verified
```

The command refuses partial confirmation, creates a mode-0640 record atomically
and refuses to overwrite different evidence.

## Backup and restore

Back up these exact surfaces with ownership and modes preserved:

- Radicale configuration, bcrypt users file and collection storage;
- `/etc/lea/calendar/`;
- `/var/lib/lea/calendar/` and the separate CalDAV password file;
- `/var/lib/lea/install/` and `/var/lib/lea/acceptance/`.

Stop `lea-radicale.service` while taking a file-level Radicale storage backup,
or use a storage snapshot with equivalent consistency guarantees. Restore into
an isolated host or staging root, reapply the original ownership and modes,
start the service, run health and two-account isolation checks, then synchronize
and verify known events. A copied archive without a successful restore drill is
not a verified backup.

## Upgrade and rollback

1. Complete and verify the backup/restore drill first.
2. Pin the new lock digest, tool versions, platform, trusted `uv` and Python.
3. Run `lea install-release-candidate --mode upgrade` with the full pinned
   calendar arguments and explicit `--approve-replacement`.
4. The installer preserves the prior installation record as
   `calendar-toolchain.json.pre-upgrade.backup`, stages and verifies the new
   version, and restores the prior record if installation fails. Stop if any old record,
   executable, configuration or hash differs from expected state; never delete
   a mismatch merely to make the upgrade continue.
5. Re-run exact version checks, disposable lifecycle acceptance, discovery and
   explicit synchronization. Then repeat Android two-way verification.
6. Keep the pre-upgrade backup until the new version and a post-upgrade restore
   drill pass. Roll back by stopping services and restoring the complete matched
   configuration, state, secret and installation-record set together.

Archive the pre-upgrade record backup with the verified system backup before a
later upgrade. A second upgrade refuses to overwrite this evidence.

Radicale upgrades follow the same rule but remain a separate change: verify the
new external executable before service changes, take a consistent storage
backup, replace only through an explicitly approved deployment transaction,
then repeat health and reciprocal isolation checks.

## Removal and credential revocation

Removal is intentionally destructive and requires both flags:

```text
lea uninstall-release-candidate --purge --yes
```

The tested plan stops and disables LEA first, then removes runtime resources,
`/opt/lea-tools/taskwarrior`, `/opt/lea-tools/calendar`, managed configuration,
state, logs and finally the service account. It preserves the source checkout
and `/opt/lea-release-assets`.

Before purge, revoke Android and other CalDAV credentials and make a verified
backup. Radicale has a separate service lifecycle: stop and disable
`lea-radicale.service`, remove its unit and non-secret configuration, and retain
its users file and collection storage until the backup restore has passed.
Purge those secrets and collections only as a second, explicitly authorised
operation with exact paths. Finally verify the revoked credentials fail and no
managed service remains active.
