# Installation

## Status

LEA is in early development and is not yet production-ready.

The current installation process establishes the development environment and verifies the repository. It does not yet configure LEA as a system service or install runtime models.

## Supported environment

The initial target environment is:

- Raspberry Pi 4B;
- 64-bit DietPi;
- Python 3.13 or later;
- Git;
- `uv`.

Other compatible Linux environments may work, but DietPi remains the primary target during early development.

## Repository location

The initial canonical repository location is:

```text
/opt/lea
```

The repository is separate from future runtime locations for logs, models, caches, indexes and application state.

## Clone the repository

Clone LEA from GitHub:

```bash
sudo git clone https://github.com/BroMarioMethod/lea.git /opt/lea
```

Transfer ownership to the development user:

```bash
sudo chown -R "$USER":"$USER" /opt/lea
```

Enter the repository:

```bash
cd /opt/lea
```

## Verify required tools

Check the installed versions:

```bash
python3 --version
uv --version
git --version
```

The current project requires Python 3.13 or later.

## Synchronise the environment

Create or update the project environment from the committed lockfile:

```bash
uv sync --locked
```

This creates the local virtual environment under:

```text
.venv/
```

The virtual environment is generated locally and is not committed to Git.

## Verify the package

Run the current command-line entry point:

```bash
uv run lea
```

During the current development phase, the command confirms that the package is installed correctly.

## Run quality checks

Run the complete project quality gate:

```bash
scripts/check.sh
```

This performs:

- Ruff formatting verification;
- Ruff linting;
- strict mypy type checking;
- pytest automated tests.

All checks should pass before development begins.

## Repository bootstrap

The repository structure can be created or repaired with:

```bash
scripts/bootstrap_repository.sh /opt/lea
```

The bootstrap process reads:

```text
config/repository_layout.toml
```

It creates missing required paths while preserving existing valid content.

Running it repeatedly should produce no destructive changes.

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
uv sync --locked
```

Run the quality gate:

```bash
scripts/check.sh
```

## Configuration

Machine-specific configuration will use:

```text
.env
```

The `.env` file SHALL NOT be committed to Git.

Supported environment variables will be documented in:

```text
.env.example
```

The current project does not yet require production credentials or external-service tokens.

## Runtime installation

The following are not yet implemented:

- system service installation;
- dedicated Linux service accounts;
- runtime state directories;
- log rotation;
- model installation;
- database initialisation;
- backup restoration;
- production upgrades.

These will be defined in future deployment and installation standards.

## Uninstallation

During early development, LEA can be removed by deleting the repository and its local virtual environment:

```bash
rm -rf /opt/lea
```

This command is destructive and should only be run after confirming that no user data or uncommitted work remains.

Future versions will separate source code from runtime and user data, so production uninstallation will require a more deliberate process.
