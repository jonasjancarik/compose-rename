# compose-rename

Rename a Docker Compose project by migrating volumes to a new project prefix.

## Run with uvx (no install)

- From PyPI (after publishing):

```bash
uvx compose-rename --help
```

- From a Git repository (without publishing yet):

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


