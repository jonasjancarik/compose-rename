"""
Tests for volume-name-mode options (update, remove, keep).
"""
import subprocess
from pathlib import Path
from typing import Tuple

import pytest
import yaml

from tests.conftest import docker_volume_exists, unique_project_name


def run_compose_rename(
    project_dir: Path,
    new_name: str,
    old_name: str = None,
    volume_name_mode: str = "auto",
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
    if volume_name_mode:
        cmd.extend(["--volume-name-mode", volume_name_mode])
    for key, value in kwargs.items():
        key_arg = key.replace("_", "-")
        if isinstance(value, bool) and value:
            cmd.append(f"--{key_arg}")
        elif not isinstance(value, bool):
            cmd.extend([f"--{key_arg}", str(value)])

    proc = subprocess.run(cmd, capture_output=True, text=True, input="u\n" if volume_name_mode == "auto" else "")
    return proc.returncode, proc.stdout, proc.stderr


def test_volume_name_mode_update(compose_with_explicit_volume_names):
    """Test updating explicit volume names."""
    project = compose_with_explicit_volume_names
    new_name = unique_project_name("updatedproject")

    # Check original compose has explicit name
    compose_path = project["dir"] / project["compose_file"]
    original_compose = yaml.safe_load(compose_path.read_text())
    assert "volumes" in original_compose
    assert "named_vol" in original_compose["volumes"]
    assert "name" in original_compose["volumes"]["named_vol"]
    original_vol_name = original_compose["volumes"]["named_vol"]["name"]

    rc, stdout, stderr = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        volume_name_mode="update",
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Find compose file (might be in renamed directory)
    compose_path = project["dir"] / project["compose_file"]
    new_dir = project["dir"].parent / new_name
    if new_dir.exists() and (new_dir / project["compose_file"]).exists():
        compose_path = (new_dir / project["compose_file"]).resolve()
    elif not compose_path.exists():
        # Try to find it
        for d in project["dir"].parent.iterdir():
            if d.is_dir() and d.name.startswith("updated"):
                potential_path = d / project["compose_file"]
                if potential_path.exists():
                    compose_path = potential_path.resolve()
                    break

    # Check compose file was updated
    updated_compose = yaml.safe_load(compose_path.read_text())
    assert "volumes" in updated_compose
    assert "named_vol" in updated_compose["volumes"]
    updated_vol_name = updated_compose["volumes"]["named_vol"]["name"]
    assert updated_vol_name == original_vol_name.replace(
        project["project_name"], new_name
    )

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_volume_name_mode_remove(compose_with_explicit_volume_names):
    """Test removing explicit volume names."""
    project = compose_with_explicit_volume_names
    new_name = unique_project_name("removedproject")

    compose_path = project["dir"] / project["compose_file"]
    original_compose = yaml.safe_load(compose_path.read_text())
    assert "name" in original_compose["volumes"]["named_vol"]

    rc, stdout, stderr = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        volume_name_mode="remove",
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Find compose file (might be in renamed directory)
    compose_path = project["dir"] / project["compose_file"]
    new_dir = project["dir"].parent / new_name
    if new_dir.exists() and (new_dir / project["compose_file"]).exists():
        compose_path = (new_dir / project["compose_file"]).resolve()
    elif not compose_path.exists():
        # Try to find it
        for d in project["dir"].parent.iterdir():
            if d.is_dir() and d.name.startswith("removed"):
                potential_path = d / project["compose_file"]
                if potential_path.exists():
                    compose_path = potential_path.resolve()
                    break

    # Check compose file - explicit name should be removed
    updated_compose = yaml.safe_load(compose_path.read_text())
    assert "volumes" in updated_compose
    assert "named_vol" in updated_compose["volumes"]
    # Name should be removed (let Compose auto-prefix)
    assert "name" not in updated_compose["volumes"]["named_vol"]

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_volume_name_mode_keep(compose_with_explicit_volume_names):
    """Test keeping explicit volume names unchanged."""
    project = compose_with_explicit_volume_names
    new_name = unique_project_name("keptproject")

    compose_path = project["dir"] / project["compose_file"]
    original_compose = yaml.safe_load(compose_path.read_text())
    original_vol_name = original_compose["volumes"]["named_vol"]["name"]

    rc, stdout, stderr = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        volume_name_mode="keep",
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Find compose file (might be in renamed directory)
    compose_path = project["dir"] / project["compose_file"]
    new_dir = project["dir"].parent / new_name
    if new_dir.exists() and (new_dir / project["compose_file"]).exists():
        compose_path = (new_dir / project["compose_file"]).resolve()
    elif not compose_path.exists():
        # Try to find it
        for d in project["dir"].parent.iterdir():
            if d.is_dir() and d.name.startswith("kept"):
                potential_path = d / project["compose_file"]
                if potential_path.exists():
                    compose_path = potential_path.resolve()
                    break

    # Check compose file - name should be unchanged
    updated_compose = yaml.safe_load(compose_path.read_text())
    assert "volumes" in updated_compose
    assert "named_vol" in updated_compose["volumes"]
    assert updated_compose["volumes"]["named_vol"]["name"] == original_vol_name

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_volume_name_mode_auto_no_explicit_names(basic_compose_project):
    """Test auto mode when no explicit volume names exist."""
    project = basic_compose_project
    new_name = unique_project_name("autonameproject")

    rc, stdout, stderr = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        volume_name_mode="auto",
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Should succeed without prompting (no explicit names to handle)

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)


def test_external_volumes_not_modified(compose_with_external_volume):
    """Test that external volumes are not modified."""
    project = compose_with_external_volume
    new_name = unique_project_name("externalnewproject")

    compose_path = project["dir"] / project["compose_file"]
    original_compose = yaml.safe_load(compose_path.read_text())
    external_vol_name = original_compose["volumes"]["external_vol"]["name"]

    rc, stdout, stderr = run_compose_rename(
        project["dir"],
        new_name,
        project["project_name"],
        volume_name_mode="update",  # Even with update, external should be untouched
    )

    assert rc == 0, f"Command failed: {stderr}\n{stdout}"

    # Find compose file (might be in renamed directory)
    compose_path = project["dir"] / project["compose_file"]
    new_dir = project["dir"].parent / new_name
    if new_dir.exists() and (new_dir / project["compose_file"]).exists():
        compose_path = (new_dir / project["compose_file"]).resolve()
    elif not compose_path.exists():
        # Try to find it
        for d in project["dir"].parent.iterdir():
            if d.is_dir() and d.name.startswith("externalnew"):
                potential_path = d / project["compose_file"]
                if potential_path.exists():
                    compose_path = potential_path.resolve()
                    break

    # Check external volume name unchanged
    updated_compose = yaml.safe_load(compose_path.read_text())
    assert updated_compose["volumes"]["external_vol"]["name"] == external_vol_name
    assert updated_compose["volumes"]["external_vol"]["external"] is True

    # Cleanup
    for old_vol in project["volumes"]:
        new_vol = old_vol.replace(project["project_name"], new_name)
        if docker_volume_exists(new_vol):
            subprocess.run(["docker", "volume", "rm", new_vol], capture_output=True)

