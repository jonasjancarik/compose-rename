# Tests for compose-rename

This directory contains comprehensive tests for the `compose-rename` tool.

## Test Structure

- `conftest.py` - Pytest fixtures for creating temporary Docker Compose projects
- `test_basic.py` - Basic functionality tests (name detection, normalization, etc.)
- `test_modes.py` - Tests for different volume discovery modes (labels, prefix, auto)
- `test_volume_name_modes.py` - Tests for volume name handling modes (update, remove, keep)
- `test_directory_operations.py` - Tests for directory operations (copy vs rename)
- `test_flags.py` - Tests for various command-line flags (dry-run, skip-down, up-after, etc.)
- `test_edge_cases.py` - Edge cases and error scenarios

## Running Tests

### Run all tests:
```bash
uv run pytest
```

### Run with coverage:
```bash
uv run pytest --cov=compose_rename --cov-report=html
```

### Run specific test file:
```bash
uv run pytest tests/test_basic.py
```

### Run specific test:
```bash
uv run pytest tests/test_basic.py::test_normalize_project_name
```

### Run with verbose output:
```bash
uv run pytest -v
```

## Test Fixtures

The test suite uses pytest fixtures to create temporary Docker Compose projects:

- `basic_compose_project` - Simple project with one service and one volume
- `compose_with_explicit_name` - Project with explicit `name:` field in compose file
- `compose_with_env_file` - Project with `COMPOSE_PROJECT_NAME` in `.env`
- `compose_with_explicit_volume_names` - Project with explicit volume `name:` fields
- `compose_with_external_volume` - Project with external volumes
- `compose_multiple_volumes` - Project with multiple volumes
- `compose_with_data_in_volumes` - Project with volumes containing actual data

## Requirements

- Docker must be installed and running
- Docker Compose must be available
- Tests require network access to pull Docker images (alpine:3.20)

## Test Coverage

The test suite covers:

1. **Volume Discovery Modes**
   - Labels mode
   - Prefix mode
   - Auto mode (with fallback)

2. **Volume Name Handling**
   - Update explicit names
   - Remove explicit names
   - Keep explicit names
   - Auto mode (interactive)

3. **Directory Operations**
   - Default rename behavior
   - Copy directory option
   - Mutually exclusive options

4. **Command Flags**
   - Dry-run mode
   - Skip-down flag
   - Up-after flag
   - Force-overwrite flag

5. **Project Name Detection**
   - From explicit `name:` in compose
   - From `.env` file
   - From directory name
   - Explicit override

6. **Edge Cases**
   - Same old/new names
   - Non-existent directories
   - No volumes to migrate
   - External volumes
   - Data preservation

## Notes

- Tests create real Docker Compose projects and volumes
- Tests clean up after themselves, but manual cleanup may be needed if tests fail
- Some tests may take time due to Docker operations
- Tests require Docker daemon to be running

