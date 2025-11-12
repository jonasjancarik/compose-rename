#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
compose_rename.py — Rename a Docker Compose project by migrating volumes
to a new project prefix.

What it does:
  1) Detect OLD project name (compose `name:`, .env COMPOSE_PROJECT_NAME, or directory name).
  2) `docker compose down` the OLD stack (keeps volumes).
  3) Discover all Compose-managed volumes for the OLD project (by label, or by name prefix).
  4) Create new volumes (same driver/options) named NEWPROJECT_<volume_key>.
  5) Copy data from old -> new via an ephemeral Alpine container and `tar`.
  6) Project naming flow (interactive by default):
     - Default: rename the project directory to NEWPROJECT and DO NOT modify the compose file.
       Docker Compose will then use the directory name as the project name (unless overridden).
     - Alternative: update the compose file to set `name: NEWPROJECT` and do NOT rename the directory.
       Useful if you want a fixed project name independent of the directory or when using `-p/--project-name`.
  7) Optionally bring up the NEW stack.

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
    # Python 3.8+: prefer importlib.metadata for installed package version
    from importlib.metadata import version as pkg_version  # type: ignore
except Exception:  # pragma: no cover
    pkg_version = None  # type: ignore

try:
    import yaml  # PyYAML
except ImportError:
    print(
        "ERROR: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr
    )
    sys.exit(2)


def get_package_version() -> str:
    """
    Return the installed distribution version if available, otherwise 'unknown'.
    This avoids hardcoding the version in the source.
    """
    try:
        if pkg_version is not None:
            return str(pkg_version("compose-rename"))
    except Exception:
        pass
    return "unknown"


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
    # Allow read-only docker queries even during dry-run
    rc, out, _ = run(cmd, check=True, capture=True, dry_run=False)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out.strip()


def docker_text_lines(cmd: List[str], dry_run: bool = False) -> List[str]:
    # Allow read-only docker queries even during dry-run
    rc, out, _ = run(cmd, check=True, capture=True, dry_run=False)
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

def modify_compose_with_modes(
    compose: Dict,
    project_name_mode: str,
    volume_name_mode: str,
    old_project: str,
    new_project: str,
) -> Dict:
    """
    Apply modifications to the compose object based on selected modes:
      - project_name_mode: 'set' | 'remove' | 'keep'
      - volume_name_mode: 'update' | 'remove' | 'keep'
    Only non-external volumes are considered for volume name updates/removals.
    """
    data = dict(compose) if compose else {}

    # Project name handling
    if project_name_mode == "set":
        data["name"] = new_project
    elif project_name_mode == "remove":
        if "name" in data:
            data.pop("name", None)
    # 'keep' does nothing

    # Volume 'name:' handling for declared, non-external volumes
    vols = data.get("volumes")
    if isinstance(vols, dict) and volume_name_mode in ("update", "remove"):
        for vkey, vdef in vols.items():
            if not isinstance(vdef, dict):
                continue
            is_external = bool(vdef.get("external") is True)
            if is_external:
                # Do not alter external volumes
                continue
            explicit_name = vdef.get("name")
            if explicit_name is None:
                continue
            if volume_name_mode == "remove":
                # Drop explicit name to let Compose auto-name with project prefix
                vdef.pop("name", None)
            elif volume_name_mode == "update":
                # If explicit name starts with the old prefix, replace it
                old_prefix = f"{old_project}_"
                if isinstance(explicit_name, str) and explicit_name.startswith(old_prefix):
                    vdef["name"] = f"{new_project}_{explicit_name[len(old_prefix):]}"
                # else: leave as-is (not clearly tied to old prefix)
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

def copy_directory(src_dir: Path, dst_dir: Path, dry_run: bool):
    if src_dir.resolve() == dst_dir.resolve():
        print(f"Directory path unchanged: {src_dir}")
        return
    if dst_dir.exists():
        raise RuntimeError(f"Target directory already exists: {dst_dir}")
    print(f"Copying directory: {src_dir} -> {dst_dir}")
    if not dry_run:
        shutil.copytree(src_dir, dst_dir)


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
        choices=["labels", "prefix", "auto"],
        default="auto",
        help="How to discover volumes to migrate. 'auto' (default) tries labels then safely falls back to prefix for declared non-external volumes; "
        "'labels' uses compose labels; 'prefix' matches name OLD_*.",
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
    # Behavioral choice: default flow is to rename directory and NOT modify compose.
    # Users can opt-in to editing compose instead, or force rename without prompt.
    ap.add_argument(
        "--rename-dir",
        action="store_true",
        help="Prefer: rename the project directory to NEW_NAME and DO NOT modify compose (default if you don't choose).",
    )
    ap.add_argument(
        "--clone-dir",
        action="store_true",
        help="Clone the project directory to NEW_NAME (copy instead of rename). Original directory remains untouched.",
    )
    ap.add_argument(
        "--edit-compose",
        action="store_true",
        help="DEPRECATED: use --project-name-mode set/remove/keep instead.",
    )
    ap.add_argument(
        "--project-name-mode",
        choices=["auto", "set", "remove", "keep"],
        default="auto",
        help="How to handle compose 'name:' when an explicit name is detected. "
        "'auto' (default) asks if explicit name exists; otherwise leaves untouched. "
        "'set' writes name: NEW_NAME; 'remove' deletes name:; 'keep' leaves as-is.",
    )
    ap.add_argument(
        "--volume-name-mode",
        choices=["auto", "update", "remove", "keep"],
        default="auto",
        help="How to handle explicit volume 'name:' fields for non-external volumes. "
        "'auto' (default) asks if explicit names exist; otherwise leaves untouched. "
        "'update' replaces OLD_ prefix with NEW_; 'remove' deletes explicit names; 'keep' leaves as-is.",
    )
    ap.add_argument(
        "--force-overwrite",
        action="store_true",
        help="If a destination volume already exists, copy into it anyway (overwrites files with same names).",
    )
    ap.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {get_package_version()}",
        help="Print version and exit.",
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

    # Decide behavior: rename/clone directory vs edit compose
    if args.clone_dir and args.rename_dir:
        print("ERROR: --clone-dir and --rename-dir are mutually exclusive.", file=sys.stderr)
        sys.exit(2)
    if args.rename_dir and args.edit_compose:
        print(
            "WARNING: --edit-compose is deprecated. Use --project-name-mode instead.",
            file=sys.stderr,
        )
    has_explicit_project = bool(
        (isinstance(compose_obj, dict) and compose_obj.get("name"))
        or dotenv.get("COMPOSE_PROJECT_NAME")
    )
    do_rename_dir = False
    do_edit_compose = False
    if args.rename_dir:
        do_rename_dir = True
    elif args.edit_compose:
        # Deprecated path: interpret as project-name-mode 'set'
        do_edit_compose = True
    else:
        # Interactive choice, unless dry-run (then default to rename-dir)
        if args.dry_run:
            print(
                "DRY-RUN: defaulting to directory rename and leaving compose file untouched."
            )
            do_rename_dir = True
        else:
            print("\nProject naming choice:")
            print("  [Enter] Rename the project directory to the NEW name (default).")
            print("           Docker Compose will then use the directory name as the project name,")
            print("           unless you override it with `name:` in compose, COMPOSE_PROJECT_NAME in .env, or `-p` at runtime.")
            print("  [k]     Keep the directory name (no rename).")
            print("           You'll be prompted (or can use flags) to set/remove/keep compose `name:` and volume names.")
            if has_explicit_project:
                print(
                    "\nNOTE: Your project currently sets an explicit project name (compose `name:` or .env `COMPOSE_PROJECT_NAME`)."
                )
                print(
                    "      Renaming only the directory will NOT change the project name Compose uses unless you remove/ignore those."
                )
            choice = (
                input("\nProceed with default directory rename? [Enter/k]: ")
                .strip()
                .lower()
            )
            if choice == "k":
                do_edit_compose = False
                do_rename_dir = False
            else:
                do_rename_dir = True

    if not args.skip_down:
        print("Stopping old stack (down)...")
        ensure_compose_down(
            project_dir, compose_path, old_project, dry_run=args.dry_run
        )
    else:
        print("Skipping 'docker compose down' per --skip-down")

    # If cloning is requested, clone the directory now and switch context to the clone
    if args.clone_dir:
        old_dir = project_dir
        new_dir = project_dir.with_name(new_project)
        try:
            copy_directory(old_dir, new_dir, dry_run=args.dry_run)
            project_dir = new_dir
            if compose_path.parent == old_dir:
                compose_path = project_dir / compose_path.name
            print(f"Project directory cloned. Using: {project_dir}")
            # In clone mode, keep the original directory intact and do not rename.
            # User can still choose whether to edit compose in the clone.
            do_rename_dir = False
        except Exception as e:
            print(f"ERROR: Failed to clone directory: {e}", file=sys.stderr)
            sys.exit(1)

    # After potential clone, re-load compose for inspections and interactive choices
    try:
        compose_obj = load_compose(compose_path)
    except Exception:
        pass
    compose_has_explicit_name = isinstance(compose_obj, dict) and ("name" in compose_obj)
    compose_vols = compose_obj.get("volumes") if isinstance(compose_obj, dict) else {}
    non_external_explicit_volume_names = []
    if isinstance(compose_vols, dict):
        for k, v in compose_vols.items():
            if isinstance(v, dict) and v.get("external") is not True and "name" in v:
                non_external_explicit_volume_names.append(k)

    # Determine project_name_mode and volume_name_mode (interactive if 'auto' and conditions met)
    project_name_mode = args.project_name_mode
    volume_name_mode = args.volume_name_mode
    if project_name_mode == "auto" and compose_has_explicit_name and not args.dry_run:
        print("\nAn explicit project name ('name:') is set in your compose file.")
        print("Choose how to handle it in the NEW project:")
        print("  [s] Set to NEW_NAME (recommended if you want a fixed project name)")
        print("  [r] Remove it (recommended if you want directory-driven project name)")
        print("  [k] Keep existing value (not recommended; may keep OLD name)")
        choice = input("Project name handling [s/r/k] (default: s): ").strip().lower()
        if choice == "r":
            project_name_mode = "remove"
        elif choice == "k":
            project_name_mode = "keep"
        else:
            project_name_mode = "set"
    elif project_name_mode == "auto":
        # Nothing explicit to handle; leave untouched
        project_name_mode = "keep"

    if volume_name_mode == "auto" and non_external_explicit_volume_names and not args.dry_run:
        print("\nExplicit volume 'name:' fields were found for non-external volumes:")
        print("  " + ", ".join(non_external_explicit_volume_names))
        print("Choose how to handle them in the NEW project:")
        print("  [u] Update names (replace OLD_ prefix with NEW_)")
        print("  [r] Remove explicit names (let Compose auto-prefix with project name)")
        print("  [k] Keep as-is (not recommended if they reference OLD prefix)")
        vchoice = input("Volume names handling [u/r/k] (default: u): ").strip().lower()
        if vchoice == "r":
            volume_name_mode = "remove"
        elif vchoice == "k":
            volume_name_mode = "keep"
        else:
            volume_name_mode = "update"
    elif volume_name_mode == "auto":
        # Nothing explicit to handle; leave untouched
        volume_name_mode = "keep"

    # Warn if .env enforces COMPOSE_PROJECT_NAME and user chose to 'remove' project name
    if project_name_mode == "remove" and dotenv.get("COMPOSE_PROJECT_NAME"):
        print(
            "NOTE: .env contains COMPOSE_PROJECT_NAME, which will still force the project name.\n"
            "      Remove/adjust it if you want directory-driven project naming.",
            file=sys.stderr,
        )

    # Discover volumes
    discovery_mode = args.mode
    if args.mode == "labels":
        old_vols = list_project_volumes_by_labels(old_project, dry_run=args.dry_run)
    elif args.mode == "prefix":
        old_vols = list_project_volumes_by_prefix(old_project, dry_run=args.dry_run)
    else:  # auto
        old_vols = list_project_volumes_by_labels(old_project, dry_run=args.dry_run)
        if not old_vols:
            print(
                "No volumes found via labels; falling back to prefix (safe, declared volumes only)."
            )
            old_vols = list_project_volumes_by_prefix(old_project, dry_run=args.dry_run)
            discovery_mode = "auto-prefix"

    if not old_vols:
        print(
            "No project volumes found for migration. If you expected some, try --mode prefix.",
            file=sys.stderr,
        )

    # Compute allowed volume keys from compose for safe auto fallback
    compose_vols = compose_obj.get("volumes") or {}
    allowed_declared_keys = {
        str(k)
        for k, v in (compose_vols.items() if isinstance(compose_vols, dict) else [])
        if not (isinstance(v, dict) and v.get("external") is True)
    }

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
        # In auto fallback, restrict to declared non-external volume keys to avoid migrating unrelated/external volumes.
        if (
            discovery_mode == "auto-prefix"
            and allowed_declared_keys
            and vol_key not in allowed_declared_keys
        ):
            print(
                f"Skipping {ov} (key '{vol_key}') not declared as a non-external volume in compose."
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

    # Apply compose modifications if requested via flags or edit choice
    # Re-load compose from current compose_path to ensure we edit the active file
    try:
        compose_obj = load_compose(compose_path)
    except Exception:
        pass
    if do_edit_compose or project_name_mode in ("set", "remove") or volume_name_mode in ("update", "remove"):
        updated_compose = modify_compose_with_modes(
            compose_obj, project_name_mode, volume_name_mode, old_project, new_project
        )
        save_compose(compose_path, updated_compose, backup=True, dry_run=args.dry_run)
    else:
        print("Leaving compose file unchanged (no modifications requested).")

    # Optionally rename directory (default path)
    if do_rename_dir:
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
