"""
Basic functionality tests for compose-rename.
"""
import sys
from pathlib import Path

import pytest

# Add parent directory to path to import compose_rename
sys.path.insert(0, str(Path(__file__).parent.parent))

from compose_rename import (
    detect_old_project_name,
    load_compose,
    normalize_project_name,
    read_dotenv,
    save_compose,
)


def test_normalize_project_name():
    """Test project name normalization."""
    assert normalize_project_name("Test Project") == "testproject"
    assert normalize_project_name("test-project") == "test-project"
    assert normalize_project_name("TEST_PROJECT") == "test_project"
    assert normalize_project_name("test.project") == "test.project"
    assert normalize_project_name("test@project") == "testproject"  # Special chars removed


def test_load_compose(basic_compose_project):
    """Test loading compose file."""
    compose_path = basic_compose_project["dir"] / basic_compose_project["compose_file"]
    compose = load_compose(compose_path)
    assert isinstance(compose, dict)
    assert "services" in compose
    assert "volumes" in compose


def test_read_dotenv(temp_dir):
    """Test reading .env file."""
    env_file = temp_dir / ".env"
    env_file.write_text("COMPOSE_PROJECT_NAME=testproject\nOTHER_VAR=value\n")
    env = read_dotenv(env_file)
    assert env["COMPOSE_PROJECT_NAME"] == "testproject"
    assert env["OTHER_VAR"] == "value"


def test_read_dotenv_nonexistent(temp_dir):
    """Test reading non-existent .env file."""
    env_file = temp_dir / ".env"
    env = read_dotenv(env_file)
    assert env == {}


def test_detect_old_project_name_explicit(basic_compose_project):
    """Test detecting project name from explicit name in compose."""
    compose_path = basic_compose_project["dir"] / basic_compose_project["compose_file"]
    compose = load_compose(compose_path)
    # Add explicit name
    compose["name"] = "explicitname"
    save_compose(compose_path, compose, backup=False, dry_run=False)
    dotenv = read_dotenv(basic_compose_project["dir"] / ".env")
    detected = detect_old_project_name(compose, basic_compose_project["dir"], dotenv, None)
    assert detected == "explicitname"


def test_detect_old_project_name_env(compose_with_env_file):
    """Test detecting project name from .env file."""
    compose_path = compose_with_env_file["dir"] / compose_with_env_file["compose_file"]
    compose = load_compose(compose_path)
    dotenv = read_dotenv(compose_with_env_file["dir"] / ".env")
    detected = detect_old_project_name(
        compose, compose_with_env_file["dir"], dotenv, None
    )
    assert detected == compose_with_env_file["project_name"]


def test_detect_old_project_name_directory(basic_compose_project):
    """Test detecting project name from directory name."""
    compose_path = basic_compose_project["dir"] / basic_compose_project["compose_file"]
    compose = load_compose(compose_path)
    dotenv = read_dotenv(basic_compose_project["dir"] / ".env")
    detected = detect_old_project_name(
        compose, basic_compose_project["dir"], dotenv, None
    )
    # Should fall back to directory name
    assert detected == normalize_project_name(basic_compose_project["dir"].name)


def test_detect_old_project_name_explicit_override(basic_compose_project):
    """Test explicit --old-name override."""
    compose_path = basic_compose_project["dir"] / basic_compose_project["compose_file"]
    compose = load_compose(compose_path)
    dotenv = read_dotenv(basic_compose_project["dir"] / ".env")
    detected = detect_old_project_name(
        compose, basic_compose_project["dir"], dotenv, "override-name"
    )
    assert detected == "override-name"

