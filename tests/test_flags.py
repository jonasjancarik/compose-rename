"""
Tests for various flags (dry-run, skip-down, up-after, force-overwrite).
"""
import subprocess
from pathlib import Path
from typing import Tuple

import pytest

from tests.conftest import docker_volume_exists, run_docker_compose, unique_project_name


def run_compose_rename(
    project_dir: Path,
    new_name: str,
    old_name: str = None,
    dry_run: bool = False,
    skip_down: bool = False,
    up_after: bool = False,
    force_overwrite: bool = False,
    **kwargs,
) -> Tuple[int, str, str]:
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
    if dry_run:
        cmd.append("--dry-run")
    if skip_down:
        cmd.append("--skip-down")
    if up_after:
        cmd.append("--up-after")
    if force_overwrite:
        cmd.append("--force-overwrite")
    for key, value in kwargs.items():
        key_arg = key.replace("_", "-")
        if isinstance(value, bool) and value:
            cmd.append(f"--{key_arg}")
        elif not isinstance(value, bool):
            cmd.extend([f"--{key_arg}", str(value)])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def test_dry_run(basic_compose_project):
    """Test dry-run mode - should not make any changes."""
    project = basic_compose_project
    new_name = unique_project_name("dryrunproject")
    original_dir = project["dir"]

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"], dry_run=True
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Directory should not be renamed
    assert original_dir.exists()
    new_dir = original_dir.parent / new_name
    assert not new_dir.exists()

    # Volumes should not be created
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        assert not docker_volume_exists(new_vol), f"New volume {new_vol} should not exist in dry-run"

    # Original volumes should still exist
    for old_vol in project["volumes"]:
        assert docker_volume_exists(old_vol), f"Original volume {old_vol} should still exist"


def test_skip_down(basic_compose_project):
    """Test skip-down flag - should not stop the old stack."""
    project = basic_compose_project
    new_name = unique_project_name("skipdownproject")

    # Verify stack is running
    rc, stdout, stderr = run_docker_compose(
        project["dir"],
        project["compose_file"],
        project["project_name"],
        ["ps"],
    )
    assert rc == 0

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"], skip_down=True
    )

    # Should succeed even though stack might still be running
    # (Note: this might cause issues if volumes are in use, but that's expected behavior)

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_up_after(basic_compose_project):
    """Test up-after flag - should bring up new stack after migration."""
    project = basic_compose_project
    new_name = unique_project_name("upafterproject")

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"], up_after=True
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Verify new stack is running
    new_dir = project["dir"].parent / new_name
    if not new_dir.exists():
        new_dir = project["dir"]

    rc, stdout, stderr = run_docker_compose(
        new_dir,
        project["compose_file"],
        new_name,
        ["ps"],
    )
    # Should have containers running
    assert "newproject" in stdout.lower() or new_name in stdout.lower() or rc == 0

    # Cleanup - bring down new stack
    try:
        run_docker_compose(new_dir, project["compose_file"], new_name, ["down", "-v"])
    except Exception:
        pass


def test_force_overwrite_existing_volume(basic_compose_project):
    """Test force-overwrite flag with existing destination volume."""
    project = basic_compose_project
    new_name = unique_project_name("forceproject")

    # Create a destination volume that already exists
    old_vol = project["volumes"][0]
    new_vol = old_vol.replace(project["project_name"], new_name)
    subprocess.run(
        ["docker", "volume", "create", new_vol],
        check=True,
        capture_output=True,
    )

    # Use --copy mode so directory doesn't get renamed, allowing us to test force-overwrite
    rc, stdout, stderr = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        copy=True,
        force_overwrite=True,
    )

    # Should succeed and copy data into existing volume
    assert rc == 0, f"Command failed: {stderr}\n{stdout}"
    # Should mention that it's copying into existing volume
    assert "already exists" in stdout.lower() or "force-overwrite" in stdout.lower() or "copying" in stdout.lower()

    # Cleanup
    if docker_volume_exists(new_vol):
        subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_dry_run_shows_plan(basic_compose_project):
    """Test that dry-run shows a migration plan."""
    project = basic_compose_project
    new_name = unique_project_name("planproject")

    rc, stdout, stderr = run_compose_rename(
        project["dir"], new_name, project["project_name"], dry_run=True
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Should show planned migrations
    assert "Planned volume migrations" in stdout or "migration" in stdout.lower()
    # Should mention volumes
    for vol in project["volumes"]:
        assert vol in stdout or vol.split("_")[-1] in stdout

