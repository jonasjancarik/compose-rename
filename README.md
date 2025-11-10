# compose-rename

Rename a Docker Compose project by migrating volumes to a new project prefix.

## Run with uvx (no install)

- From PyPI:

```bash
uvx compose-rename --help
```

- From a Git repository (for latest version, possibly ahead of PyPI):

```bash
uvx --from git+https://github.com/jonasjancarik/compose-rename@main compose-rename --help
```

## Usage

```bash
compose-rename \
  --project-dir /path/to/project \
  --new-name newproj \
  [--old-name oldproj] \
  [--mode labels|prefix|auto] \
  [--dry-run] [--skip-down] [--up-after] [--rename-dir] [--force-overwrite]
```

Test first with `--dry-run`. Requires Docker CLI and PyYAML.

### Options

- **--project-dir PATH**: Absolute/relative path to the existing Compose project directory. The tool auto-detects the compose file inside this directory unless you set `--compose-file`.
- **--compose-file PATH**: Optional explicit path to the compose file. If unset, it searches for `compose.yaml`, `compose.yml`, `docker-compose.yaml`, then `docker-compose.yml` in `--project-dir`.
- **--new-name NAME**: Required. The new Compose project name. This is written to the compose file as `name:` and serves as the prefix for resources (e.g., volumes become `newname_<volume_key>`).
- **--old-name NAME**: Optional. Override auto-detected OLD project name. Detection order (if not provided): `name:` in compose → `.env` `COMPOSE_PROJECT_NAME` → directory name.
- **--mode labels|prefix|auto**: How to discover volumes to migrate.
  - `auto` (default): Tries `labels` first; if none found, safely falls back to `prefix` but only for volume keys declared in the compose file under `volumes:` that are not marked `external: true`. This avoids migrating unrelated/external volumes.
  - `labels`: Uses `com.docker.compose.project=<old>` labels. Migrates volumes that Compose created.
  - `prefix`: Matches volumes named `<old>_...`. Useful when labels are missing (e.g., Swarm) or for external volumes following the prefix convention. Be cautious: this can include non-Compose/external volumes.
- **--dry-run**: Prints the full plan and performs read-only Docker queries (volume list/inspect), but makes no changes: no `down`, no creates, no copy, no file writes, no directory rename, no `up`.
- **--skip-down**: Skip `docker compose down` on the OLD project. Without `--dry-run`, migration still occurs (creates/copies/compose file write). Use with caution if the old stack is running.
- **--up-after**: After migrating and updating the compose file, bring up the NEW project with `docker compose up -d`.
- **--rename-dir**: Rename the project directory to `--new-name` at the end.
- **--force-overwrite**: If a destination volume already exists, copy into it anyway (files with the same names are overwritten). Without this, existing destination volumes are skipped.
- **-V, --version**: Print the installed package version and exit.

## Behavior and tips

- **Dry run**: Performs read-only Docker queries (e.g., `docker volume ls`, `docker volume inspect`) to show a full plan. It does not stop stacks, create volumes, copy data, write files, or rename directories.
- **Skip down**: Only prevents `docker compose down` on the OLD project. Without `--dry-run`, the tool will still create destination volumes, copy data, and update the compose file. Use with caution if the old stack is running (data may change during copy).
- **Mode**:
  - `labels` (default): Finds Compose-managed volumes by label `com.docker.compose.project=<old>`.
  - `prefix`: Finds volumes by name prefix `<old>_...`. Useful when labels are missing (e.g., Swarm or externally created volumes).

## Common commands

- Plan only (no changes), discover volumes and show migration plan:

```bash
compose-rename --project-dir /path/to/project --new-name newproj --dry-run
# or with explicit mode
compose-rename --project-dir /path/to/project --new-name newproj --dry-run --mode prefix
```

- Migrate safely (stop old stack first):

```bash
compose-rename --project-dir /path/to/project --new-name newproj
```

- Migrate without stopping old stack first (not a check; performs migration):

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


