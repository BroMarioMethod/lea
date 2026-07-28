# LEA Milestone 2.7 Release Checklist

| Item | Value |
|---|---|
| Document Status | Accepted |
| Release Readiness | Ready to Tag |
| Milestone | 2.7 — Test-user Release Candidate |
| Package Version | `0.2.0` |
| Annotated Tag | `milestone-2.7` |
| Release Date | 28 July 2026 |
| Licence | AGPL-3.0-only |
| Primary Platform | Raspberry Pi 4B, AArch64, DietPi / Debian 13 |

## Release decision

Milestone 2.7 is the first clean-room verified LEA test-user release candidate.

The package version advances from `0.1.0` to `0.2.0` because the
release adds substantial new, backwards-compatible product capability while LEA
remains below version 1.0.

The repository uses milestone tags rather than semantic-version Git tags.
Therefore the release tag is:

```text
milestone-2.7
```

No additional `v0.2.0` tag is required for this milestone.

## Source and metadata

- [x] The release is prepared from the protected `main` history.
- [x] The working tree must be clean before the final release commit.
- [x] `pyproject.toml` declares package version `0.2.0`.
- [x] `tests/test_version.py` expects `0.2.0`.
- [x] `uv.lock` is regenerated from the updated project metadata.
- [x] Python 3.13 or later remains the supported runtime.
- [x] The project licence remains AGPL-3.0-only.
- [x] Taskwarrior remains pinned to version 3.4.2.
- [x] The pinned Taskwarrior source SHA-256 remains:
  `d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716`.

## Automated release gate

The final release commit must pass:

- [x] `bash -n install.sh uninstall.sh`;
- [x] Ruff formatting verification;
- [x] Ruff linting;
- [x] strict mypy type checking;
- [x] Telegram deployment-asset validation;
- [x] release-candidate acceptance-asset validation;
- [x] the complete pytest suite.

The final command is:

```bash
./scripts/check.sh
```

The commit must not be tagged unless this command exits successfully.

## Clean-room installation

The clean-room DietPi tester evidence confirms:

- [x] fresh installation without Telegram;
- [x] pinned Taskwarrior 3.4.2 source build and activation;
- [x] post-install health verification;
- [x] disposable Taskwarrior lifecycle acceptance;
- [x] persistent acceptance-record generation;
- [x] runtime-directory recreation after reboot;
- [x] post-reboot health and acceptance;
- [x] repair-mode installation;
- [x] safe cancellation;
- [x] managed purge;
- [x] preservation of `/opt/lea` and `/opt/lea-release-assets`;
- [x] fresh reinstall through `install.sh`;
- [x] purge through `uninstall.sh`.

## Live Telegram acceptance

The controlled live Telegram evidence confirms:

- [x] hidden bot-token entry;
- [x] live bot validation through Telegram `getMe`;
- [x] intended private owner discovery and confirmation;
- [x] owner-role registration;
- [x] secure token and configuration permissions;
- [x] enabled and active `lea-telegram.service`;
- [x] successful `/status` and `/tasks` interaction;
- [x] successful Telegram-enabled acceptance;
- [x] automatic service startup after reboot;
- [x] successful commands and acceptance after reboot;
- [x] absence of the token from process arguments;
- [x] absence of the token from the process environment;
- [x] absence of the token from recent service journal output;
- [x] induced worker-process failure;
- [x] automatic systemd recovery with a new process and increased restart count;
- [x] successful commands and acceptance after recovery.

Real tokens and Telegram identifiers remain outside Git and release evidence.

## Documentation

- [x] Installation and uninstallation guidance matches the wrapper interfaces.
- [x] Clean-room evidence records the non-Telegram and Telegram profiles.
- [x] LEA-SPEC-0016 is marked implemented and verified.
- [x] The clean-room verification record is marked verified.
- [x] No behavioural verification remains outstanding.
- [x] The release tag name and package version are fixed by this checklist.

## Known host observation

The tester DietPi image masks `systemd-logind.service`. Invoking the underlying
`reboot` command through `sudo` can report an `org.freedesktop.login1`
activation error even when the host reboots successfully.

This is a documented DietPi host behaviour, not an LEA runtime failure.
System D-Bus, runtime-directory recreation, Telegram service startup and
post-reboot acceptance all passed.

## Publication

After the release-preparation branch is merged and the full gate passes on
`main`, create the annotated tag:

```bash
git tag -a milestone-2.7 \
    -m "Milestone 2.7 — Test-user release candidate (LEA 0.2.0)"
```

Push `main` and the tag:

```bash
git push origin main
git push origin milestone-2.7
```

Verify publication:

```bash
git show --no-patch --decorate milestone-2.7
git ls-remote --tags origin milestone-2.7
```

The tag must point to the exact clean, fully tested release commit.
