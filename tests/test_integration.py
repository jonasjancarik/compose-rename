"""
Integration tests - end-to-end scenarios combining multiple features.
"""
import subprocess
from pathlib import Path
from typing import Tuple

import pytest
import yaml

from tests.conftest import (
    docker_volume_exists,
    read_volume_file,
    run_docker_compose,
    unique_project_name,
    verify_volume_data,
)


def run_compose_rename(
    project_dir: Path,
    new_name: str,
    old_name: str = None,
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
    for key, value in kwargs.items():
        key_arg = key.replace("_", "-")
        if isinstance(value, bool) and value:
            cmd.append(f"--{key_arg}")
        elif not isinstance(value, bool):
            cmd.extend([f"--{key_arg}", str(value)])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def test_full_migration_with_data_preservation(compose_with_data_in_volumes):
    """
    Integration test: Full migration with data preservation.
    Tests: labels mode + rename directory + data preservation
    """
    project = compose_with_data_in_volumes
    new_name = unique_project_name("fullmigration")

    # Verify original data
    old_vol = project["volumes"][0]
    assert verify_volume_data(old_vol, ["file1.txt", "file2.txt"])

    # Run full migration
    rc, stdout, stderr = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        mode="labels",
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Verify directory was renamed
    new_dir = project["dir"].parent / new_name
    assert new_dir.exists() or project["dir"].name == new_name

    # Verify volumes were migrated
    new_vol = old_vol.replace(project["project_name"], new_name)
    assert docker_volume_exists(new_vol)

    # Verify data was preserved
    assert verify_volume_data(new_vol, ["file1.txt", "file2.txt"])
    assert read_volume_file(new_vol, "file1.txt") == "Important data"
    assert read_volume_file(new_vol, "file2.txt") == "More data"

    # Cleanup
    if docker_volume_exists(new_vol):
        subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_migration_with_explicit_names_and_update_mode(compose_with_explicit_volume_names):
    """
    Integration test: Migration with explicit volume names using update mode.
    Tests: explicit names + update mode + rename directory
    """
    project = compose_with_explicit_volume_names
    new_name = unique_project_name("explicitupdate")

    compose_path = project["dir"] / project["compose_file"]
    original_compose = yaml.safe_load(compose_path.read_text())
    original_vol_name = original_compose["volumes"]["named_vol"]["name"]

    rc, stdout, stderr = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        volume_name_mode="update",
        mode="labels",
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Find compose file (might be renamed)
    new_dir = project["dir"].parent / new_name
    if new_dir.exists():
        compose_path = new_dir / project["compose_file"]
    else:
        compose_path = project["dir"] / project["compose_file"]

    updated_compose = yaml.safe_load(compose_path.read_text())
    updated_vol_name = updated_compose["volumes"]["named_vol"]["name"]
    assert updated_vol_name == original_vol_name.replace(
        project["project_name"], new_name
    )

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_copy_mode_with_multiple_volumes(compose_multiple_volumes):
    """
    Integration test: Copy mode with multiple volumes.
    Tests: copy directory + multiple volumes + labels mode
    """
    project = compose_multiple_volumes
    new_name = unique_project_name("copymultivol")
    original_dir = project["dir"]

    rc, stdout, stderr = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        copy=True,
        mode="labels",
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Original directory should still exist
    assert original_dir.exists()

    # New directory should exist
    new_dir = original_dir.parent / new_name
    assert new_dir.exists()

    # All volumes should be migrated
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        assert docker_volume_exists(new_vol), f"Volume {new_vol} should exist"

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_dry_run_then_actual_migration(basic_compose_project):
    """
    Integration test: Dry-run followed by actual migration.
    Tests: dry-run shows plan, then actual migration works
    """
    project = basic_compose_project
    new_name = unique_project_name("drythenreal")

    # First, dry-run
    rc1, stdout1, stderr1 = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        dry_run=True,
    )

    assert rc1 == 0, f"Dry-run failed: {stderr1}\n{stdout1}"
    assert "Planned volume migrations" in stdout1 or "migration" in stdout1.lower()

    # Verify nothing changed
    assert project["dir"].exists()
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        assert not docker_volume_exists(new_vol)

    # Now actual migration
    rc2, stdout2, stderr2 = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        dry_run=False,
    )

    assert rc2 == 0, f"Migration failed: {stderr2}\n{stdout2}"

    # Verify volumes were migrated
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        assert docker_volume_exists(new_vol)

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_migration_with_up_after_flag(basic_compose_project):
    """
    Integration test: Migration with --up-after flag.
    Tests: migration + bringing up new stack
    """
    project = basic_compose_project
    new_name = unique_project_name("upafterproject")

    rc, stdout, stderr = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        up_after=True,
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Find new directory
    new_dir = project["dir"].parent / new_name
    if not new_dir.exists():
        new_dir = project["dir"]

    # Verify new stack is running
    rc_ps, stdout_ps, stderr_ps = run_docker_compose(
        new_dir,
        project["compose_file"],
        new_name,
        ["ps"],
    )

    # Should have containers (or at least no error)
    assert rc_ps == 0 or new_name in stdout_ps.lower()

    # Cleanup - bring down new stack
    try:
        run_docker_compose(new_dir, project["compose_file"], new_name, ["down", "-v"])
    except Exception:
        pass

