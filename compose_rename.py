#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
compose_rename.py — Rename a Docker Compose project by *migrating volumes*
(Option B: create new volumes with the new project prefix and copy data over)

What it does:
  1) Detect OLD project name (compose `name:`, .env COMPOSE_PROJECT_NAME, or directory name).
  2) `docker compose down` the OLD stack (keeps volumes).
  3) Discover all Compose-managed volumes for the OLD project (by label, or by name prefix).
  4) Create new volumes (same driver/options) named NEWPROJECT_<volume_key>.
  5) Copy data from old -> new via an ephemeral Alpine container and `tar`.
  6) Update the compose file to set `name: NEWPROJECT`.
  7) Optionally rename the project directory to NEWPROJECT.
  8) Optionally bring up the NEW stack.

Notes:
  - By default, only Compose-managed volumes are migrated (those created by Compose).
    External volumes are not touched unless you switch to `--mode prefix` and they match the OLD prefix.
  - Networks are recreated automatically by Compose; there is no data to copy for networks.
  - Test with `--dry-run` first. Ensure you have backups.
  - Requires: Python 3.8+, PyYAML (`pip install pyyaml`), Docker CLI in PATH.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import yaml  # PyYAML
except ImportError:
    print(
        "ERROR: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr
    )
    sys.exit(2)


def run(
    cmd: List[str],
    check: bool = True,
    capture: bool = True,
    dry_run: bool = False,
    env: Optional[Dict[str, str]] = None,
):
    """Run a shell command with pretty printing. Returns (rc, stdout, stderr)."""
    printable = " ".join(cmd)
    print(f"+ {printable}")
    if dry_run:
        return 0, "", ""

    proc = subprocess.run(cmd, capture_output=capture, text=True, env=env)
    if check and proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, proc.stdout, proc.stderr
        )
    return (
        proc.returncode,
        proc.stdout if capture else "",
        proc.stderr if capture else "",
    )


def docker_json(cmd: List[str], dry_run: bool = False):
    rc, out, _ = run(cmd, check=True, capture=True, dry_run=dry_run)
    if dry_run:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out.strip()


def docker_text_lines(cmd: List[str], dry_run: bool = False) -> List[str]:
    rc, out, _ = run(cmd, check=True, capture=True, dry_run=dry_run)
    if dry_run:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def load_compose(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_compose(path: Path, data: Dict, backup: bool = True, dry_run: bool = False):
    if backup and not dry_run:
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
        print(f"Backed up compose file to: {bak}")
    print(f"Writing updated compose to: {path}")
    if not dry_run:
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False)


def read_dotenv(env_path: Path) -> Dict[str, str]:
    env = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def default_compose_path(project_dir: Path) -> Path:
    candidates = [
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
    ]
    for c in candidates:
        p = project_dir / c
        if p.exists():
            return p
    raise FileNotFoundError(
        f"No compose file found in {project_dir} (checked {', '.join(candidates)})"
    )


def normalize_project_name(name: str) -> str:
    """
    Compose accepts lowercase + separators; mimic a safe normalization:
    - strip spaces
    - lowercase
    - keep alphanumerics, '-', '_' and '.'
    """
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9._-]+", "", name)
    return name


def detect_old_project_name(
    compose: Dict,
    project_dir: Path,
    dotenv: Dict[str, str],
    explicit_old: Optional[str],
) -> str:
    if explicit_old:
        return normalize_project_name(explicit_old)
    if isinstance(compose, dict) and compose.get("name"):
        return normalize_project_name(str(compose["name"]))
    if dotenv.get("COMPOSE_PROJECT_NAME"):
        return normalize_project_name(dotenv["COMPOSE_PROJECT_NAME"])
    return normalize_project_name(project_dir.name)


def ensure_compose_down(
    project_dir: Path, compose_path: Path, project_name: str, dry_run: bool
):
    run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(project_dir),
            "-f",
            str(compose_path),
            "-p",
            project_name,
            "down",
            "--remove-orphans",
        ],
        check=True,
        capture=True,
        dry_run=dry_run,
    )


def list_project_volumes_by_labels(old_project: str, dry_run: bool) -> List[str]:
    # Compose sets labels on volumes: com.docker.compose.project=<name>
    return docker_text_lines(
        [
            "docker",
            "volume",
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={old_project}",
        ],
        dry_run=dry_run,
    )


def list_project_volumes_by_prefix(old_project: str, dry_run: bool) -> List[str]:
    vols = docker_text_lines(["docker", "volume", "ls", "-q"], dry_run=dry_run)
    return [v for v in vols if v.startswith(f"{old_project}_")]


def ensure_volume_exists(name: str, dry_run: bool) -> bool:
    rc, out, err = run(
        ["docker", "volume", "inspect", name],
        check=False,
        capture=True,
        dry_run=dry_run,
    )
    if dry_run:
        return False
    return rc == 0


def inspect_volume(name: str, dry_run: bool) -> Dict:
    j = docker_json(["docker", "volume", "inspect", name], dry_run=dry_run)
    if isinstance(j, list) and j:
        return j[0]
    return {}


def create_volume_like(
    new_name: str, like_info: Dict, labels_extra: Dict[str, str], dry_run: bool
):
    driver = like_info.get("Driver") or "local"
    opts = like_info.get("Options") or {}
    labels = like_info.get("Labels") or {}
    cmd = ["docker", "volume", "create", "--driver", driver]
    for k, v in opts.items():
        cmd += ["--opt", f"{k}={v}"]
    merged_labels = dict(labels)
    merged_labels.update(labels_extra or {})
    for k, v in merged_labels.items():
        cmd += ["--label", f"{k}={v}"]
    cmd.append(new_name)
    run(cmd, check=True, capture=True, dry_run=dry_run)


def copy_volume_data(src_vol: str, dst_vol: str, dry_run: bool):
    # Alpine + tar. Avoid pipefail for busybox; preserve perms with -p.
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{src_vol}:/from:ro",
        "-v",
        f"{dst_vol}:/to",
        "alpine:3.20",
        "ash",
        "-c",
        "set -e; cd /from; tar -cf - . | (cd /to; tar -xpf -)",
    ]
    run(cmd, check=True, capture=True, dry_run=dry_run)


def update_compose_project_name(compose: Dict, new_project: str) -> Dict:
    data = dict(compose) if compose else {}
    data["name"] = new_project
    return data


def rename_directory(old_dir: Path, new_dir: Path, dry_run: bool):
    if old_dir.resolve() == new_dir.resolve():
        print(f"Directory name unchanged: {old_dir}")
        return
    if new_dir.exists():
        raise RuntimeError(f"Target directory already exists: {new_dir}")
    print(f"Renaming directory: {old_dir} -> {new_dir}")
    if not dry_run:
        old_dir.rename(new_dir)


def bring_up_new_stack(
    project_dir: Path, compose_path: Path, new_project: str, dry_run: bool
):
    run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(project_dir),
            "-f",
            str(compose_path),
            "-p",
            new_project,
            "up",
            "-d",
        ],
        check=True,
        capture=True,
        dry_run=dry_run,
    )


def main():
    ap = argparse.ArgumentParser(
        description="Rename a Docker Compose project by migrating volumes to a new prefix."
    )
    ap.add_argument(
        "--project-dir",
        required=True,
        help="Path to the existing Compose project directory (OLD).",
    )
    ap.add_argument(
        "--compose-file",
        default=None,
        help="Compose file path (default: auto-detect in project dir).",
    )
    ap.add_argument(
        "--new-name",
        required=True,
        help="New Compose project name (prefix for resources).",
    )
    ap.add_argument(
        "--old-name", default=None, help="Override auto-detected OLD project name."
    )
    ap.add_argument(
        "--mode",
        choices=["labels", "prefix"],
        default="labels",
        help="How to discover volumes to migrate. 'labels' (default) uses compose labels; 'prefix' matches name OLD_*.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without changing anything.",
    )
    ap.add_argument(
        "--skip-down",
        action="store_true",
        help="Do not run 'docker compose down' on the OLD project.",
    )
    ap.add_argument(
        "--up-after",
        action="store_true",
        help="Run 'docker compose up -d' for the NEW project after migration.",
    )
    ap.add_argument(
        "--rename-dir",
        action="store_true",
        help="Rename the project directory to NEW_NAME at the end.",
    )
    ap.add_argument(
        "--force-overwrite",
        action="store_true",
        help="If a destination volume already exists, copy into it anyway (overwrites files with same names).",
    )
    args = ap.parse_args()

    project_dir = Path(args.project_dir).resolve()
    if not project_dir.exists():
        print(f"ERROR: Project dir not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    compose_path = (
        Path(args.compose_file)
        if args.compose_file
        else default_compose_path(project_dir)
    )
    compose_path = compose_path.resolve()
    print(f"Compose file: {compose_path}")

    dotenv = read_dotenv(project_dir / ".env")
    compose_obj = load_compose(compose_path)
    old_project = detect_old_project_name(
        compose_obj, project_dir, dotenv, args.old_name
    )
    new_project = normalize_project_name(args.new_name)

    print(f"Old project name: {old_project}")
    print(f"New project name: {new_project}")

    if old_project == new_project:
        print("Old and new project names are the same. Nothing to do.", file=sys.stderr)
        sys.exit(1)

    if not args.skip_down:
        print("Stopping old stack (down)...")
        ensure_compose_down(
            project_dir, compose_path, old_project, dry_run=args.dry_run
        )
    else:
        print("Skipping 'docker compose down' per --skip-down")

    # Discover volumes
    if args.mode == "labels":
        old_vols = list_project_volumes_by_labels(old_project, dry_run=args.dry_run)
    else:
        old_vols = list_project_volumes_by_prefix(old_project, dry_run=args.dry_run)

    if not old_vols:
        print(
            "No project volumes found for migration. If you expected some, try --mode prefix.",
            file=sys.stderr,
        )

    # Build mapping: old volume name -> (new volume name, volume_key)
    mapping: Dict[str, Tuple[str, str]] = {}
    for ov in old_vols:
        info = inspect_volume(ov, dry_run=args.dry_run)
        labels = info.get("Labels") or {}
        vol_key = labels.get("com.docker.compose.volume")
        if not vol_key and ov.startswith(f"{old_project}_"):
            vol_key = ov[len(old_project) + 1 :]
        if not vol_key:
            print(
                f"WARNING: Could not determine volume key for {ov}. Skipping.",
                file=sys.stderr,
            )
            continue
        nv = f"{new_project}_{vol_key}"
        mapping[ov] = (nv, vol_key)

    if not mapping:
        print("No migratable volumes discovered. Exiting.", file=sys.stderr)
        sys.exit(0)

    print("Planned volume migrations:")
    for ov, (nv, vkey) in mapping.items():
        print(f"  {ov}  ->  {nv}   (key: {vkey})")

    # Create & copy
    for ov, (nv, vkey) in mapping.items():
        print(f"\n=== Migrating volume: {ov} -> {nv} ===")
        # Inspect source volume now (driver/options/labels)
        src_info = inspect_volume(ov, dry_run=args.dry_run)
        src_labels = src_info.get("Labels") or {}
        if ensure_volume_exists(nv, dry_run=args.dry_run):
            print(f"Destination volume already exists: {nv}")
            if not args.force_overwrite:
                print(
                    "  Use --force-overwrite to copy into it anyway. Skipping this volume."
                )
                continue
            else:
                print("  --force-overwrite set: will copy into existing destination.")
        else:
            labels_extra = {
                "com.docker.compose.project": new_project,
                # Compose will set this itself on create; we mimic for convenience:
                "com.docker.compose.volume": vkey,
                "migrated_from": ov,
            }
            # also carry over compose version if present
            if "com.docker.compose.version" in src_labels:
                labels_extra["com.docker.compose.version"] = src_labels[
                    "com.docker.compose.version"
                ]
            create_volume_like(nv, src_info, labels_extra, dry_run=args.dry_run)

        print("Copying data ...")
        copy_volume_data(ov, nv, dry_run=args.dry_run)

    # Update compose name
    updated_compose = update_compose_project_name(compose_obj, new_project)
    save_compose(compose_path, updated_compose, backup=True, dry_run=args.dry_run)

    # Optionally rename directory
    if args.rename_dir:
        old_dir = project_dir
        new_dir = project_dir.with_name(new_project)
        try:
            rename_directory(old_dir, new_dir, dry_run=args.dry_run)
            project_dir = new_dir
            # If the compose file lives directly in the project dir, update its path
            if compose_path.parent == old_dir:
                compose_path = project_dir / compose_path.name
        except Exception as e:
            print(f"ERROR: Failed to rename directory: {e}", file=sys.stderr)
            sys.exit(1)

    if args.up_after:
        print("Bringing up the NEW stack...")
        try:
            bring_up_new_stack(
                project_dir, compose_path, new_project, dry_run=args.dry_run
            )
        except subprocess.CalledProcessError:
            print(
                "ERROR: Failed to start the new stack. Start it manually:",
                file=sys.stderr,
            )
            print(
                f"  docker compose --project-directory {project_dir} -f {compose_path} -p {new_project} up -d",
                file=sys.stderr,
            )

    print("\nDone.")
    print(
        "Remember to update any scripts/systemd units that referenced old container names."
    )
    print(f"New container names will look like: {new_project}-<service>-1")


if __name__ == "__main__":
    main()
