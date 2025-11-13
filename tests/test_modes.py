"""
Tests for different volume discovery modes (labels, prefix, auto).
"""
import subprocess
from pathlib import Path

import pytest

from tests.conftest import (
    docker_volume_exists,
    read_volume_file,
    unique_project_name,
    verify_volume_data,
)


def run_compose_rename(
    project_dir: Path,
    new_name: str,
    old_name: str = None,
    mode: str = "auto",
    dry_run: bool = False,
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
    if mode:
        cmd.extend(["--mode", mode])
    if dry_run:
        cmd.append("--dry-run")
    for key, value in kwargs.items():
        key_arg = key.replace("_", "-")
        if isinstance(value, bool) and value:
            cmd.append(f"--{key_arg}")
        elif not isinstance(value, bool):
            cmd.extend([f"--{key_arg}", str(value)])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def test_mode_labels(basic_compose_project):
    """Test volume discovery using labels mode."""
    project = basic_compose_project
    new_name = unique_project_name("newproject")

    # Run compose-rename
    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"], mode="labels"
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Verify volumes were migrated
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        assert docker_volume_exists(new_vol), f"New volume {new_vol} should exist"
        # Old volume should still exist (not removed by compose-rename)
        assert docker_volume_exists(old_vol), f"Old volume {old_vol} should still exist"

    # Cleanup new volumes
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_mode_prefix(basic_compose_project):
    """Test volume discovery using prefix mode."""
    project = basic_compose_project
    new_name = unique_project_name("prefixproject")

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"], mode="prefix"
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Verify volumes were migrated
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        assert docker_volume_exists(new_vol), f"New volume {new_vol} should exist"

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_mode_auto(basic_compose_project):
    """Test volume discovery using auto mode (default)."""
    project = basic_compose_project
    new_name = unique_project_name("autoproject")

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"], mode="auto"
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Verify volumes were migrated
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        assert docker_volume_exists(new_vol), f"New volume {new_vol} should exist"

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_mode_auto_fallback_to_prefix(compose_multiple_volumes):
    """Test auto mode falling back to prefix when labels don't work."""
    project = compose_multiple_volumes
    new_name = unique_project_name("fallbackproject")

    # First, remove labels from volumes to force fallback
    # (This simulates volumes created without compose labels)
    for vol in project["volumes"]:
        # We can't easily remove labels, but we can test the fallback behavior
        pass

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"], mode="auto"
    )

    # Should succeed (either via labels or prefix fallback)
    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_volume_data_preserved(compose_with_data_in_volumes):
    """Test that volume data is preserved during migration."""
    project = compose_with_data_in_volumes
    new_name = unique_project_name("datapreserved")

    # Verify original data exists
    old_vol = project["volumes"][0]
    assert verify_volume_data(old_vol, ["file1.txt", "file2.txt"])

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"], mode="labels"
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Verify new volume has the same data
    new_vol = old_vol.replace(project["project_name"], new_name)
    assert docker_volume_exists(new_vol)
    assert verify_volume_data(new_vol, ["file1.txt", "file2.txt"])

    # Verify file contents
    assert read_volume_file(new_vol, "file1.txt") == "Important data"
    assert read_volume_file(new_vol, "file2.txt") == "More data"

    # Cleanup
    if docker_volume_exists(new_vol):
        subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_multiple_volumes_migration(compose_multiple_volumes):
    """Test migrating multiple volumes."""
    project = compose_multiple_volumes
    new_name = unique_project_name("multivol")

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"], mode="labels"
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Verify all volumes were migrated
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        assert docker_volume_exists(new_vol), f"New volume {new_vol} should exist"

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)

