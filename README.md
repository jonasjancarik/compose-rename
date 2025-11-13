# compose-rename

Rename a Docker Compose project by migrating volumes to a new project prefix.

## Run without installing

Run `compose-rename` without installing it:

With uvx (from PyPI):

```bash
uvx compose-rename --help
```

With uvx (from Git repository, for latest version, possibly ahead of PyPI):

```bash
uvx --from git+https://github.com/jonasjancarik/compose-rename@main compose-rename --help
```

Or with pipx:

```bash
pipx run compose-rename --help
```

or

```bash
pipx run --spec git+https://github.com/jonasjancarik/compose-rename@main compose-rename --help
```

## Usage

```bash
compose-rename \
  --project-dir /path/to/project \
  --new-name newproj \
  [--old-name oldproj] \
  [--mode labels|prefix|auto] \
  [--dry-run] [--skip-down] [--up-after] \
  [--rename-dir | --copy] \
  [--volume-name-mode auto|update|remove|keep] \
  [--force-overwrite]
```

**Requirements**: Docker CLI and PyYAML.

### Default behavior

By default, the tool:
1. Renames the project directory to the new name (`--new-name`)
2. Removes any explicit project name (`name:`) from the compose file
3. Removes `COMPOSE_PROJECT_NAME` from the `.env` file if present

This enables **directory-driven naming** where Docker Compose derives the project name from the directory name. Use `--copy` to keep the original directory intact, or set explicit volume names with `--volume-name-mode`.

**Always test first with `--dry-run`** to preview the migration plan before making changes.

### Options

#### Required

| Option | Description |
|--------|-------------|
| `--project-dir PATH` | Absolute/relative path to the existing Compose project directory. The tool auto-detects the compose file inside this directory unless you set `--compose-file`. |
| `--new-name NAME` | The new Compose project name (prefix for resources, e.g., volumes become `newname_<volume_key>`). By default, the tool removes any explicit project name from the compose file and `.env` file, allowing Docker Compose to use directory-driven naming. |

#### Optional

| Option | Default | Description |
|--------|---------|-------------|
| `--compose-file PATH` | Auto-detect | Explicit path to the compose file. If unset, it searches for `compose.yaml`, `compose.yml`, `docker-compose.yaml`, then `docker-compose.yml` in `--project-dir`. |
| `--old-name NAME` | Auto-detect | Override auto-detected OLD project name. If not provided, detection order is: `name:` in compose → `.env` `COMPOSE_PROJECT_NAME` → directory name. |
| `--mode MODE` | `auto` | How to discover volumes to migrate. Values: `auto` (tries `labels` first, falls back to `prefix` for declared volumes), `labels` (uses `com.docker.compose.project=<old>` labels), `prefix` (matches volumes named `<old>_...` - use with caution as it can include non-Compose volumes). |
| `--volume-name-mode MODE` | `auto` | How to handle explicit volume `name:` for non-external volumes. Values: `auto` (ask if explicit names exist, otherwise keep), `update` (replace `OLD_` prefix with `NEW_`), `remove` (delete explicit names for auto-prefixing), `keep` (leave as-is). |

#### Flags

| Option | Default | Description |
|--------|---------|-------------|
| `--dry-run` | Disabled | Prints the full plan and performs read-only Docker queries (volume list/inspect), but makes no changes: no `down`, no creates, no copy, no file writes, no directory rename, no `up`. |
| `--skip-down` | Disabled | Skip `docker compose down` on the OLD project. Without `--dry-run`, migration still occurs (creates/copies/compose file write). Use with caution if the old stack is running. |
| `--up-after` | Disabled | After migration, bring up the NEW project with `docker compose up -d`. |
| `--rename-dir` | Enabled* | Rename the project directory to `--new-name`. The tool will also remove any explicit project name (`name:`) from the compose file and `COMPOSE_PROJECT_NAME` from `.env` if present, allowing Docker Compose to use directory-driven naming. *Default unless `--copy` is used. |
| `--copy` | Disabled | Copy the project directory to `--new-name` and keep the original directory untouched. Volumes are still migrated by copying data from old to new. The tool will also remove any explicit project name from the copied compose file and `.env` if present. |
| `--force-overwrite` | Disabled | If a destination volume already exists, copy into it anyway (files with the same names are overwritten). Without this, existing destination volumes are skipped. |
| `-V, --version` | — | Print the installed package version and exit. |

## Common commands

- Plan only (no changes), discover volumes and show migration plan:

```bash
compose-rename --project-dir /path/to/project --new-name newproj --dry-run
# or with explicit mode
compose-rename --project-dir /path/to/project --new-name newproj --dry-run --mode prefix
```

- Basic migration (stops old stack, migrates volumes, renames directory):

```bash
compose-rename --project-dir /path/to/project --new-name newproj
```

- Copy the project directory (keep the original intact):

```bash
compose-rename --project-dir /path/to/project --new-name newproj --copy
```

- When explicit volume names are present, choose behavior non-interactively:

```bash
# Update explicit volume names (replace OLD_ prefix with NEW_)
compose-rename --project-dir /path/to/project --new-name newproj \
  --volume-name-mode update

# Remove explicit volume names (let Compose auto-prefix)
compose-rename --project-dir /path/to/project --new-name newproj \
  --volume-name-mode remove
```

- Migrate without stopping old stack first (use with caution):

```bash
compose-rename --project-dir /path/to/project --new-name newproj --skip-down
```


## Verify volumes manually

```bash
# For prefix mode
docker volume ls | grep '^OLDPROJECT_'

# For labels mode
docker volume ls --filter label=com.docker.compose.project=OLDPROJECT
```

# Development

## Testing

The project includes a comprehensive test suite using pytest. Tests create real Docker Compose projects and volumes to verify functionality.

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov=compose_rename --cov-report=html

# Run specific test file
uv run pytest tests/test_basic.py

# Run with verbose output
uv run pytest -v
```

### Test Coverage

The test suite covers:
- Volume discovery modes (labels, prefix, auto)
- Volume name handling modes (update, remove, keep)
- Directory operations (rename vs copy)
- Command-line flags (dry-run, skip-down, up-after, force-overwrite)
- Project name detection scenarios
- Edge cases and error handling
- Integration scenarios

See `tests/README.md` for more details.

**Note**: Tests require Docker to be installed and running.

## Automated publishing (GitHub Actions)

This repository includes a workflow that publishes to PyPI whenever you push a tag like `vX.Y.Z`.

- Workflow file: `.github/workflows/publish.yml`
- It verifies the tag matches `project.version` in `pyproject.toml`, builds with `uv build`, and publishes with `uv publish`.
- The workflow uses the environment variable `UV_PYPI_TOKEN` and expects a repository secret named `PYPI_API_TOKEN`.

Setup (one-time):
- In GitHub → Repository → Settings → Secrets and variables → Actions:
  - Add a new repository secret `PYPI_API_TOKEN` with your PyPI API token.

Release steps:
1. Bump version in `pyproject.toml`
2. Commit and push to `main`
3. Tag and push the tag:
   - `git tag vX.Y.Z && git push origin vX.Y.Z`
4. GitHub Actions will build and publish to PyPI automatically.

Install a tagged version from Git directly (useful for testing or pinning):

```bash
uvx --from git+https://github.com/jonasjancarik/compose-rename@vX.Y.Z compose-rename --version
```

```bash
pipx run --spec git+https://github.com/jonasjancarik/compose-rename@vX.Y.Z compose-rename --version
```

## Local builds on tag push (optional)

If you want fresh `dist/` artifacts locally whenever you push a version tag, enable the provided git hook:

```bash
git config core.hooksPath .githooks
```

Now, when you push a tag like `v0.1.3`, the `pre-push` hook will run `uv build` and leave `dist/` ready for a manual:

```bash
uv publish
```

Manual build helper:

```bash
./scripts/build-dist.sh
```


