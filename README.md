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
  [--dry-run] [--skip-down] [--up-after] \
  [--rename-dir | --copy] \
  [--project-name-mode auto|set|remove|keep] \
  [--volume-name-mode auto|update|remove|keep] \
  [--force-overwrite]
```

Test first with `--dry-run`. Requires Docker CLI and PyYAML.

### Options

- **--project-dir PATH**: Absolute/relative path to the existing Compose project directory. The tool auto-detects the compose file inside this directory unless you set `--compose-file`.
- **--compose-file PATH**: Optional explicit path to the compose file. If unset, it searches for `compose.yaml`, `compose.yml`, `docker-compose.yaml`, then `docker-compose.yml` in `--project-dir`.
- **--new-name NAME**: Required. The new Compose project name (prefix for resources, e.g., volumes become `newname_<volume_key>`). How this name is applied to the project is chosen interactively by default.
- **--old-name NAME**: Optional. Override auto-detected OLD project name. Detection order (if not provided): `name:` in compose → `.env` `COMPOSE_PROJECT_NAME` → directory name.
- **--mode labels|prefix|auto**: How to discover volumes to migrate.
  - `auto` (default): Tries `labels` first; if none found, safely falls back to `prefix` but only for volume keys declared in the compose file under `volumes:` that are not marked `external: true`. This avoids migrating unrelated/external volumes.
  - `labels`: Uses `com.docker.compose.project=<old>` labels. Migrates volumes that Compose created.
  - `prefix`: Matches volumes named `<old>_...`. Useful when labels are missing (e.g., Swarm) or for external volumes following the prefix convention. Be cautious: this can include non-Compose/external volumes.
- **--dry-run**: Prints the full plan and performs read-only Docker queries (volume list/inspect), but makes no changes: no `down`, no creates, no copy, no file writes, no directory rename, no `up`.
- **--skip-down**: Skip `docker compose down` on the OLD project. Without `--dry-run`, migration still occurs (creates/copies/compose file write). Use with caution if the old stack is running.
- **--up-after**: After migration, bring up the NEW project with `docker compose up -d`.
- **--rename-dir**: Prefer renaming the project directory to `--new-name` and DO NOT modify the compose file. This is the default choice if you don't specify a preference.
- **--copy**: Copy the project directory to `--new-name` and keep the original directory untouched. Volumes are still migrated by copying data from old to new. 
- **--project-name-mode auto|set|remove|keep**: How to handle an explicit compose `name:` if present.
  - `auto` (default): Ask if explicit name exists; otherwise keep.
  - `set`: Write `name: --new-name`.
  - `remove`: Delete `name:` and also remove `.env` `COMPOSE_PROJECT_NAME` if present (backing up `.env` to `.env.bak`) so Compose uses directory-driven naming.
  - `keep`: Leave as-is.
- **--volume-name-mode auto|update|remove|keep**: How to handle explicit volume `name:` for non-external volumes.
  - `auto` (default): Ask if explicit names exist; otherwise keep.
  - `update`: Replace `OLD_` prefix with `NEW_` for names starting with the old prefix.
  - `remove`: Delete explicit names so Compose auto-prefixes with the project name.
  - `keep`: Leave as-is.
- **--force-overwrite**: If a destination volume already exists, copy into it anyway (files with the same names are overwritten). Without this, existing destination volumes are skipped.
- **-V, --version**: Print the installed package version and exit.

## Behavior and tips

- **Dry run**: Performs read-only Docker queries (e.g., `docker volume ls`, `docker volume inspect`) to show a full plan. It does not stop stacks, create volumes, copy data, write files, or rename directories.
- **Skip down**: Only prevents `docker compose down` on the OLD project. Without `--dry-run`, the tool will still create destination volumes, copy data, and update the compose file. Use with caution if the old stack is running (data may change during copy).
- **Mode**:
  - `labels` (default): Finds Compose-managed volumes by label `com.docker.compose.project=<old>`.
  - `prefix`: Finds volumes by name prefix `<old>_...`. Useful when labels are missing (e.g., Swarm or externally created volumes).
- **Default naming flow**: By default, after migrating volumes, the tool prefers to rename the project directory to the NEW name and leave the compose file untouched. Docker Compose will then use the directory name as the project name when you run commands from that directory.
  - Choose the alternative `--edit-compose` (or press `e` when prompted) if you want a fixed project name independent of the directory name, or if you routinely use `docker compose -p/--project-name`.
  - If your compose file already sets `name:` or your `.env` contains `COMPOSE_PROJECT_NAME`, renaming only the directory will not change the project name Compose uses. Either remove those overrides or choose the compose-edit option. If you select `--project-name-mode remove`, the tool removes both the compose `name:` and `.env` `COMPOSE_PROJECT_NAME` (with a `.env` backup) for you.

## Common commands

- Plan only (no changes), discover volumes and show migration plan:

```bash
compose-rename --project-dir /path/to/project --new-name newproj --dry-run
# or with explicit mode
compose-rename --project-dir /path/to/project --new-name newproj --dry-run --mode prefix
```

- Migrate safely (stop old stack first) and choose naming flow interactively (default is directory rename):

```bash
compose-rename --project-dir /path/to/project --new-name newproj
```

- Copy the project directory (keep the original intact) and edit the copied compose:

```bash
compose-rename --project-dir /path/to/project --new-name newproj --copy --edit-compose
```

- When explicit `name:` or explicit volume names are present, choose behavior non-interactively:

```bash
# Set new project name and update explicit volume names
compose-rename --project-dir /path/to/project --new-name newproj \
  --project-name-mode set --volume-name-mode update

# Remove explicit project name and remove explicit volume names
compose-rename --project-dir /path/to/project --new-name newproj \
  --project-name-mode remove --volume-name-mode remove
```

- Migrate without stopping old stack first (not a check; performs migration):

```bash
compose-rename --project-dir /path/to/project --new-name newproj --skip-down
```

- Force the alternative flow (edit compose instead of renaming the directory):

```bash
compose-rename --project-dir /path/to/project --new-name newproj --edit-compose
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


