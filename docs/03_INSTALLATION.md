# Installation

## Status

LEA remains under active development and is not yet recommended for production
use.

The current Milestone 4.0 release-candidate installer can provision a supported
DietPi host, create LEA's managed runtime layout, install the pinned
Taskwarrior and calendar-client runtimes, run post-install health checks and
execute disposable functional acceptance. Radicale remains a separately
managed CalDAV service, and DAVx⁵ remains an Android-side component.

The non-Telegram installation profile has passed clean-room verification on a
fresh Raspberry Pi 4B DietPi installation. Live Telegram onboarding and service
acceptance remain outstanding. Milestone 4.0 additionally requires recorded
Radicale user-isolation, Android two-way synchronisation and backup/restore
acceptance before release tagging.

## Supported environment

The primary tested environment is:

- Raspberry Pi 4B;
- AArch64 / ARM64;
- 64-bit DietPi based on Debian GNU/Linux 13;
- Python 3.13 or later;
- Git;
- `uv`;
- systemd;
- a working system D-Bus.

Other compatible Linux environments may work, but DietPi remains the primary
release-candidate target.

## Repository location

The canonical source repository location is:

```text
/opt/lea
```

Managed runtime state is stored separately beneath:

```text
/etc/lea
/var/lib/lea
/var/log/lea
/run/lea
/opt/lea-tools
```

The source repository must not be used as LEA's runtime data store.

### Root installation and managed-file ownership

The installer normally runs as root, but root's creation ownership and umask
are not the desired final state for LEA runtime files. Every integration that
creates or replaces a managed file must explicitly apply and then verify its
contracted mode, owner and group. It must not assume that `open`, `write_text`,
an atomic rename or mode `0640` alone produces a file readable by the intended
service process.

Tests and release-candidate acceptance must cover both expected ownership
patterns where applicable: operator-owned configuration shared with group
`lea`, and service-owned state such as `lea:lea`. They must exercise the real
root installation path and verify numeric mode, owner, group and service
readability after atomic creation, replacement, upgrade and restore.

## DietPi system D-Bus requirement

LEA's installer and future managed services require a working system D-Bus.

A fresh DietPi image may ship with D-Bus or related systemd facilities disabled
or masked according to its first-boot configuration. Before installation,
verify:

```bash
test -S /run/dbus/system_bus_socket \
    && echo 'D-Bus socket present' \
    || echo 'D-Bus socket missing'

systemctl is-active dbus.service
systemctl is-system-running
```

A healthy host should have:

- `/run/dbus/system_bus_socket`;
- an active `dbus.service`;
- `systemctl is-system-running` reporting `running` or another understood
  non-fatal state.

The implementation may use `dbus-daemon` or `dbus-broker`; LEA must not require
one specific implementation.

When D-Bus is unavailable on DietPi, install the required packages and reboot:

```bash
sudo apt update
sudo apt install dbus dbus-system-bus
sudo reboot
```

After reconnecting, repeat the checks above.

The release-candidate installer currently detects host compatibility but does
not yet automatically repair every DietPi D-Bus configuration. Any required
manual D-Bus preparation must be reported explicitly and treated as an
installer prerequisite.

## Clone the repository

Clone LEA:

```bash
sudo git clone https://github.com/BroMarioMethod/lea.git /opt/lea
sudo chown -R "$USER":"$USER" /opt/lea
cd /opt/lea
```

For release-candidate testing, check out the exact commit or tag declared by the
test plan.

## Synchronise the locked environment

Run:

```bash
uv sync --frozen
```

This creates the local virtual environment under:

```text
.venv/
```

The environment is generated locally and must not be committed.

## Required native build dependencies

The current release candidate builds Taskwarrior 3.4.2 from pinned source.

The host requires:

```text
cmake
make
g++
cargo
rustc
pkg-config
libuuid development headers
```

On Debian or DietPi, install the required packages using the documented package
names for the current distribution release.

Verify the toolchain:

```bash
cmake --version
make --version
g++ --version
cargo --version
rustc --version
pkg-config --modversion uuid
```

## Taskwarrior source archive

The release-candidate installer requires an absolute path to the pinned
Taskwarrior source archive.

Recommended location:

```text
/opt/lea-release-assets/task-3.4.2.tar.gz
```

Expected SHA-256:

```text
d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716
```

Verify the archive before installation:

```bash
sha256sum /opt/lea-release-assets/task-3.4.2.tar.gz
```

The result must match the expected checksum exactly.

## Calendar release assets

Milestone 4.0 installs khal and vdirsyncer as one managed, versioned toolchain.
Use the reviewed lock supplied with the release assets:

```text
/opt/lea-release-assets/calendar-requirements.lock
```

Create the canonical release-assets directory with the supported preparation
command documented in `MILESTONE_4_TEST_CARD.md`; do not manually copy or
regenerate the tracked lock during installation.

Verify its independently reviewed SHA-256 before installation. The installer
requires the absolute lock path, lowercase digest, exact trusted `uv` and
Python paths, toolchain layout version, and pinned khal and vdirsyncer
versions. It rejects unpinned, unhashed and source-only packages.

The complete commands and security boundaries for calendar installation,
Radicale provisioning, DAVx⁵ pairing, acceptance, backup, upgrade and removal
are in `docs/development/CALENDAR_PROVIDER_OPERATIONS.md`. Radicale is not
implicitly installed by the release-candidate command and must not be exposed
directly to the public internet.

## Current supported installer entry point

The current advanced release-candidate interface is:

```bash
sudo "$(command -v uv)" run lea install-release-candidate \
    --mode fresh-install \
    --display-timezone Africa/Gaborone \
    --no-telegram \
    --taskwarrior-source-archive \
        /opt/lea-release-assets/task-3.4.2.tar.gz \
    --taskwarrior-sha256 \
        d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716 \
    --taskwarrior-version 3.4.2 \
    --taskwarrior-platform linux-aarch64 \
    --taskwarrior-build-directory /var/tmp/lea-taskwarrior-build \
    --taskwarrior-build-concurrency 1 \
    --calendar-requirements-lock \
        /opt/lea-release-assets/calendar-requirements.lock \
    --calendar-requirements-sha256 \
        <reviewed-lowercase-sha256> \
    --calendar-uv-executable "$(command -v uv)" \
    --calendar-python-executable /usr/bin/python3.13 \
    --calendar-toolchain-version <pinned-layout-version> \
    --calendar-khal-version 0.11.4 \
    --calendar-vdirsyncer-version 0.19.3 \
    --approve
```

This command:

1. inspects host compatibility;
2. creates or verifies the `lea` system account;
3. provisions managed directories and files;
4. installs base runtime configuration;
5. builds and activates Taskwarrior 3.4.2;
6. installs and verifies the managed khal/vdirsyncer toolchain;
7. runs read-only health checks;
8. runs disposable functional acceptance.

Before repeating a physical release-candidate test-card run for any new tool
integration, prove in automated tests that every public CLI option reaches the
release-candidate request, orchestration engine, installer dispatch and
post-install acceptance path. A standalone installer implementation is not a
complete integration.

The supported guided user entry point is:

```bash
sudo ./install.sh
```

The wrapper resolves the repository location, locates `uv`, supplies the pinned
Taskwarrior source-build defaults and delegates all installation behaviour to
the existing deterministic Python CLI.

Installer options may be passed through, for example:

```bash
sudo ./install.sh \
    --mode fresh-install \
    --display-timezone Africa/Gaborone \
    --no-telegram
```

The advanced `lea install-release-candidate` command remains available for
development, diagnostics and explicit path overrides.

## Installer output modes

The installer supports:

```text
--quiet
--normal
--verbose
```

`--normal` is the default.

- `--quiet` renders only prompts, errors and the final result;
- `--normal` renders step progress and long-running heartbeats;
- `--verbose` additionally streams detailed build output.

## Installation modes

The installer supports:

```text
fresh-install
upgrade
repair
```

Use `fresh-install` on a clean supported host.

Use `repair` only for an existing managed installation that requires validated
reconciliation.

`upgrade` is reserved for a supported managed upgrade path and must not be used
as a substitute for repair.

## Telegram selection

Use:

```text
--no-telegram
```

for the currently verified local profile.

Use:

```text
--telegram
```

only during the controlled live Telegram onboarding and smoke-test stage.

The real Telegram bot token, authorised Telegram user ID and private chat ID
must:

- remain outside Git;
- not be placed in shell history where avoidable;
- not appear in logs, arguments, diagnostics or support bundles;
- be configured only when live runtime testing begins.

## Post-install health and acceptance

After installation, run the dedicated acceptance command:

```bash
sudo "$(command -v uv)" run lea accept-release-candidate \
    --config /etc/lea/lea.toml \
    --record /var/lib/lea/acceptance/release-candidate.json
```

Consult:

```text
docs/development/RELEASE_CANDIDATE_ACCEPTANCE.md
```

for the complete acceptance procedure and evidence requirements.

## Reboot verification

After a successful installation:

```bash
sudo reboot
```

After reconnecting, verify:

```bash
sudo stat -c '%A %a %U:%G %n' \
    /etc/tmpfiles.d/lea.conf \
    /run/lea \
    /etc/lea/lea.toml \
    /etc/lea/taskwarrior/taskrc \
    /var/lib/lea/install/release-candidate.json \
    /var/lib/lea/install/taskwarrior.json \
    /opt/lea-tools/taskwarrior/3.4.2/bin/task

sudo /opt/lea-tools/taskwarrior/3.4.2/bin/task --version

systemctl is-system-running
test -S /run/dbus/system_bus_socket
```

The runtime directory `/run/lea` must be recreated automatically from:

```text
/etc/tmpfiles.d/lea.conf
```

Then rerun health and functional acceptance.

## Development installation

Developers should run:

```bash
cd /opt/lea
uv sync --frozen
./scripts/check.sh
```

The full gate performs:

- Ruff formatting verification;
- Ruff linting;
- strict mypy type checking;
- pytest;
- release-candidate acceptance-asset validation.

## Updating an existing clone

Enter the repository:

```bash
cd /opt/lea
```

Confirm that the working tree is clean:

```bash
git status
```

Retrieve remote updates:

```bash
git pull --ff-only
```

Synchronise the locked environment:

```bash
uv sync --frozen
```

Run the complete gate:

```bash
./scripts/check.sh
```

Do not perform a managed runtime upgrade merely by pulling repository changes.
Use an explicitly supported installer upgrade or repair path.

## Runtime configuration

The canonical runtime configuration is:

```text
/etc/lea/lea.toml
```

Taskwarrior configuration is:

```text
/etc/lea/taskwarrior/taskrc
```

Managed installation records are stored beneath:

```text
/var/lib/lea/install
```

Secrets must remain outside the repository.

## Uninstallation

The current managed purge interface is:

```bash
sudo "$(command -v uv)" run lea uninstall-release-candidate --purge
```

The command renders the complete destructive plan and asks for confirmation.

For explicitly approved non-interactive removal:

```bash
sudo "$(command -v uv)" run lea uninstall-release-candidate \
    --purge \
    --yes
```

Managed purge removes LEA-managed configuration, runtime state, logs,
Taskwarrior installation, service files, service account and service group.

It preserves:

```text
/opt/lea
/opt/lea-release-assets
```

The supported user-facing wrapper is:

```bash
sudo ./uninstall.sh
```

It always selects the managed purge contract and retains the Python CLI's
destructive confirmation prompt.

For explicitly approved non-interactive removal:

```bash
sudo ./uninstall.sh --yes
```

The advanced `lea uninstall-release-candidate --purge` command remains
available for development and diagnostics.

Do not remove `/opt/lea` as part of managed uninstallation unless the source
repository has been reviewed separately for uncommitted work.

## Verification evidence

The clean-room verification record is:

```text
docs/development/RELEASE_CANDIDATE_CLEAN_ROOM_VERIFICATION.md
```

It documents the verified non-Telegram profile and the remaining live Telegram
acceptance work.
