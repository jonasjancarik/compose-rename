"""
Tests for directory operations (rename vs copy).
"""
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.conftest import docker_volume_exists, unique_project_name


def run_compose_rename(
    project_dir: Path,
    new_name: str,
    old_name: str = None,
    copy: bool = False,
    rename_dir: bool = False,
    **kwargs,
) -> tuple[int, str, str]:
    """Run compose-rename command."""
    import sys

    cmd = [
        sys.executable,
        "-m",
        "compose_rename",
        "--project-dir",
        str(project_dir),
        "--new-name",
        new_name,
    ]
    if old_name:
        cmd.extend(["--old-name", old_name])
    if copy:
        cmd.append("--copy")
    if rename_dir:
        cmd.append("--rename-dir")
    for key, value in kwargs.items():
        key_arg = key.replace("_", "-")
        if isinstance(value, bool) and value:
            cmd.append(f"--{key_arg}")
        elif not isinstance(value, bool):
            cmd.extend([f"--{key_arg}", str(value)])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def test_default_rename_directory(basic_compose_project):
    """Test default behavior: rename directory."""
    project = basic_compose_project
    new_name = unique_project_name("renamedproject")
    original_dir = project["dir"]
    original_dir_name = original_dir.name

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"]
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Directory should be renamed
    new_dir = original_dir.parent / new_name
    assert new_dir.exists(), f"New directory {new_dir} should exist"
    assert not original_dir.exists() or original_dir.name != original_dir_name

    # Compose file should exist in new location
    compose_file = new_dir / project["compose_file"]
    assert compose_file.exists()

    # Verify volumes were migrated
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        assert docker_volume_exists(new_vol), f"New volume {new_vol} should exist"

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_copy_directory(basic_compose_project):
    """Test copying directory instead of renaming."""
    project = basic_compose_project
    new_name = unique_project_name("copiedproject")
    original_dir = project["dir"]

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"], copy=True
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Original directory should still exist
    assert original_dir.exists(), "Original directory should still exist"

    # New directory should exist
    new_dir = original_dir.parent / new_name
    assert new_dir.exists(), f"New directory {new_dir} should exist"

    # Compose file should exist in both locations
    original_compose = original_dir / project["compose_file"]
    new_compose = new_dir / project["compose_file"]
    assert original_compose.exists()
    assert new_compose.exists()

    # Verify volumes were migrated
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        assert docker_volume_exists(new_vol), f"New volume {new_vol} should exist"

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_copy_vs_rename_mutually_exclusive(basic_compose_project):
    """Test that --copy and --rename-dir are mutually exclusive."""
    project = basic_compose_project
    new_name = unique_project_name("mutuallyexclusive")

    rc, stdout, stderr = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        copy=True,
        rename_dir=True,
    )

    assert rc != 0, "Should fail when both --copy and --rename-dir are used"
    assert "mutually exclusive" in stderr.lower() or "mutually exclusive" in stdout.lower()


def test_compose_name_removed_on_rename(basic_compose_project):
    """Test that explicit project name is removed from compose file."""
    project = basic_compose_project
    new_name = unique_project_name("nonameproject")

    # Add explicit name to compose
    compose_path = project["dir"] / project["compose_file"]
    compose = yaml.safe_load(compose_path.read_text())
    compose["name"] = project["project_name"]
    compose_path.write_text(yaml.safe_dump(compose), encoding="utf-8")

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"]
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Find the compose file (might be in renamed directory)
    new_dir = project["dir"].parent / new_name
    if new_dir.exists():
        compose_path = new_dir / project["compose_file"]
    else:
        compose_path = project["dir"] / project["compose_file"]

    updated_compose = yaml.safe_load(compose_path.read_text())
    # Name should be removed (default behavior)
    assert "name" not in updated_compose or updated_compose.get("name") != project["project_name"]

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_env_file_updated_on_rename(compose_with_env_file):
    """Test that COMPOSE_PROJECT_NAME is removed from .env file."""
    project = compose_with_env_file
    new_name = unique_project_name("newenvproject")

    env_path = project["dir"] / ".env"
    assert "COMPOSE_PROJECT_NAME" in env_path.read_text()

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"]
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Find .env file (might be in renamed directory)
    new_dir = project["dir"].parent / new_name
    if new_dir.exists():
        env_path = new_dir / ".env"
    else:
        env_path = project["dir"] / ".env"

    if env_path.exists():
        env_content = env_path.read_text()
        # COMPOSE_PROJECT_NAME should be removed
        assert "COMPOSE_PROJECT_NAME" not in env_content or "COMPOSE_PROJECT_NAME=" not in env_content

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)

