"""
Pytest fixtures for compose-rename tests.

Creates temporary Docker Compose projects for testing.
"""
import json
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest
import yaml


def unique_project_name(base: str) -> str:
    """Generate a unique project name by appending a short UUID."""
    return f"{base}{uuid.uuid4().hex[:8]}"


def run_docker_compose(
    project_dir: Path,
    compose_file: str,
    project_name: str,
    command: List[str],
    check: bool = True,
) -> Tuple[int, str, str]:
    """Run docker compose command and return (rc, stdout, stderr)."""
    cmd = [
        "docker",
        "compose",
        "--project-directory",
        str(project_dir),
        "-f",
        str(project_dir / compose_file),
        "-p",
        project_name,
    ] + command
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, proc.stdout, proc.stderr
        )
    return proc.returncode, proc.stdout, proc.stderr


def docker_volume_exists(volume_name: str) -> bool:
    """Check if a Docker volume exists."""
    proc = subprocess.run(
        ["docker", "volume", "inspect", volume_name],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def docker_volume_list() -> List[str]:
    """List all Docker volume names."""
    proc = subprocess.run(
        ["docker", "volume", "ls", "-q"], capture_output=True, text=True, check=True
    )
    return [v.strip() for v in proc.stdout.splitlines() if v.strip()]


def docker_volume_inspect(volume_name: str) -> Dict:
    """Inspect a Docker volume and return its info."""
    proc = subprocess.run(
        ["docker", "volume", "inspect", volume_name],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return data[0] if isinstance(data, list) else data


def docker_volume_rm(volume_name: str, force: bool = False) -> None:
    """Remove a Docker volume."""
    cmd = ["docker", "volume", "rm"]
    if force:
        cmd.append("--force")
    cmd.append(volume_name)
    subprocess.run(cmd, check=True, capture_output=True)


def write_file(path: Path, content: str) -> None:
    """Write content to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def temp_dir():
    """Create a temporary directory that gets cleaned up."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def basic_compose_project(temp_dir):
    """
    Create a basic Docker Compose project with:
    - compose.yaml file
    - One service with a volume
    - No explicit project name
    - No .env file
    """
    project_name = "testproject"
    compose_content = """
version: '3.8'
services:
  app:
    image: alpine:3.20
    command: sh -c "echo 'Hello from test' > /data/message.txt && sleep 3600"
    volumes:
      - app_data:/data
volumes:
  app_data:
"""
    compose_file = temp_dir / "compose.yaml"
    write_file(compose_file, compose_content)

    # Start the stack
    run_docker_compose(temp_dir, "compose.yaml", project_name, ["up", "-d"])

    yield {
        "dir": temp_dir,
        "compose_file": "compose.yaml",
        "project_name": project_name,
        "volumes": [f"{project_name}_app_data"],
    }

    # Cleanup
    try:
        run_docker_compose(temp_dir, "compose.yaml", project_name, ["down", "-v"])
    except Exception:
        pass


@pytest.fixture
def compose_with_explicit_name(temp_dir):
    """
    Create a Docker Compose project with explicit 'name:' field.
    """
    project_name = "explicitproject"
    compose_content = f"""
name: {project_name}
version: '3.8'
services:
  app:
    image: alpine:3.20
    command: sh -c "echo 'Hello' > /data/message.txt && sleep 3600"
    volumes:
      - app_data:/data
volumes:
  app_data:
"""
    compose_file = temp_dir / "compose.yaml"
    write_file(compose_file, compose_content)

    run_docker_compose(temp_dir, "compose.yaml", project_name, ["up", "-d"])

    yield {
        "dir": temp_dir,
        "compose_file": "compose.yaml",
        "project_name": project_name,
        "volumes": [f"{project_name}_app_data"],
    }

    try:
        run_docker_compose(temp_dir, "compose.yaml", project_name, ["down", "-v"])
    except Exception:
        pass


@pytest.fixture
def compose_with_env_file(temp_dir):
    """
    Create a Docker Compose project with COMPOSE_PROJECT_NAME in .env.
    """
    project_name = "envproject"
    compose_content = """
version: '3.8'
services:
  app:
    image: alpine:3.20
    command: sh -c "echo 'Hello' > /data/message.txt && sleep 3600"
    volumes:
      - app_data:/data
volumes:
  app_data:
"""
    env_content = f"COMPOSE_PROJECT_NAME={project_name}\n"
    compose_file = temp_dir / "compose.yaml"
    env_file = temp_dir / ".env"
    write_file(compose_file, compose_content)
    write_file(env_file, env_content)

    run_docker_compose(temp_dir, "compose.yaml", project_name, ["up", "-d"])

    yield {
        "dir": temp_dir,
        "compose_file": "compose.yaml",
        "project_name": project_name,
        "volumes": [f"{project_name}_app_data"],
        "has_env": True,
    }

    try:
        run_docker_compose(temp_dir, "compose.yaml", project_name, ["down", "-v"])
    except Exception:
        pass


@pytest.fixture
def compose_with_explicit_volume_names(temp_dir):
    """
    Create a Docker Compose project with explicit volume 'name:' fields.
    """
    project_name = "volnameproject"
    compose_content = f"""
version: '3.8'
services:
  app:
    image: alpine:3.20
    command: sh -c "echo 'Hello' > /data/message.txt && sleep 3600"
    volumes:
      - app_data:/data
      - named_vol:/named
volumes:
  app_data:
  named_vol:
    name: {project_name}_custom_name
"""
    compose_file = temp_dir / "compose.yaml"
    write_file(compose_file, compose_content)

    run_docker_compose(temp_dir, "compose.yaml", project_name, ["up", "-d"])

    yield {
        "dir": temp_dir,
        "compose_file": "compose.yaml",
        "project_name": project_name,
        "volumes": [
            f"{project_name}_app_data",
            f"{project_name}_custom_name",
        ],
        "explicit_volume_names": ["named_vol"],
    }

    try:
        run_docker_compose(temp_dir, "compose.yaml", project_name, ["down", "-v"])
    except Exception:
        pass


@pytest.fixture
def compose_with_external_volume(temp_dir):
    """
    Create a Docker Compose project with an external volume.
    """
    project_name = "externalproject"
    external_vol_name = "external_shared_volume"

    # Create external volume
    subprocess.run(
        ["docker", "volume", "create", external_vol_name],
        check=True,
        capture_output=True,
    )

    compose_content = f"""
version: '3.8'
services:
  app:
    image: alpine:3.20
    command: sh -c "echo 'Hello' > /data/message.txt && sleep 3600"
    volumes:
      - app_data:/data
      - external_vol:/external
volumes:
  app_data:
  external_vol:
    external: true
    name: {external_vol_name}
"""
    compose_file = temp_dir / "compose.yaml"
    write_file(compose_file, compose_content)

    run_docker_compose(temp_dir, "compose.yaml", project_name, ["up", "-d"])

    yield {
        "dir": temp_dir,
        "compose_file": "compose.yaml",
        "project_name": project_name,
        "volumes": [f"{project_name}_app_data"],
        "external_volumes": [external_vol_name],
    }

    try:
        run_docker_compose(temp_dir, "compose.yaml", project_name, ["down", "-v"])
    except Exception:
        pass
    try:
        docker_volume_rm(external_vol_name, force=True)
    except Exception:
        pass


@pytest.fixture
def compose_multiple_volumes(temp_dir):
    """
    Create a Docker Compose project with multiple volumes.
    """
    project_name = "multivolproject"
    compose_content = """
version: '3.8'
services:
  app:
    image: alpine:3.20
    command: sh -c "echo 'Hello' > /data/message.txt && sleep 3600"
    volumes:
      - app_data:/data
      - cache_data:/cache
  db:
    image: alpine:3.20
    command: sh -c "echo 'DB data' > /db/data.txt && sleep 3600"
    volumes:
      - db_data:/db
volumes:
  app_data:
  cache_data:
  db_data:
"""
    compose_file = temp_dir / "compose.yaml"
    write_file(compose_file, compose_content)

    run_docker_compose(temp_dir, "compose.yaml", project_name, ["up", "-d"])

    yield {
        "dir": temp_dir,
        "compose_file": "compose.yaml",
        "project_name": project_name,
        "volumes": [
            f"{project_name}_app_data",
            f"{project_name}_cache_data",
            f"{project_name}_db_data",
        ],
    }

    try:
        run_docker_compose(temp_dir, "compose.yaml", project_name, ["down", "-v"])
    except Exception:
        pass


@pytest.fixture
def compose_with_data_in_volumes(temp_dir):
    """
    Create a Docker Compose project with volumes containing data.
    """
    project_name = "dataproject"
    compose_content = """
version: '3.8'
services:
  app:
    image: alpine:3.20
    command: sh -c "echo 'Important data' > /data/file1.txt && echo 'More data' > /data/file2.txt && sleep 3600"
    volumes:
      - app_data:/data
volumes:
  app_data:
"""
    compose_file = temp_dir / "compose.yaml"
    write_file(compose_file, compose_content)

    run_docker_compose(temp_dir, "compose.yaml", project_name, ["up", "-d"])

    # Wait a bit for data to be written
    import time

    time.sleep(2)

    yield {
        "dir": temp_dir,
        "compose_file": "compose.yaml",
        "project_name": project_name,
        "volumes": [f"{project_name}_app_data"],
    }

    try:
        run_docker_compose(temp_dir, "compose.yaml", project_name, ["down", "-v"])
    except Exception:
        pass


def verify_volume_data(volume_name: str, expected_files: List[str]) -> bool:
    """Verify that a volume contains expected files."""
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{volume_name}:/vol:ro",
        "alpine:3.20",
        "sh",
        "-c",
        f"ls -1 /vol",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    files = [f.strip() for f in proc.stdout.splitlines() if f.strip()]
    return all(f in files for f in expected_files)


def read_volume_file(volume_name: str, file_path: str) -> str:
    """Read a file from a volume."""
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{volume_name}:/vol:ro",
        "alpine:3.20",
        "cat",
        f"/vol/{file_path}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def load_compose(path: Path) -> Dict:
    """Load a compose file (helper for tests)."""
    import yaml

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

