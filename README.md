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
  [--mode labels|prefix] \
  [--dry-run] [--skip-down] [--up-after] [--rename-dir] [--force-overwrite]
```

Test first with `--dry-run`. Requires Docker CLI and PyYAML.

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


