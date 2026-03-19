"""
Pytest fixtures for dlab tests.
"""

import shutil
from pathlib import Path
from typing import Any, Generator

import pytest
import yaml


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for tests."""
    return tmp_path


@pytest.fixture
def dpack_config_dir(tmp_path: Path) -> Path:
    """
    Create a valid decision-pack config directory structure.

    Returns the path to the decision-pack config directory.
    """
    dpack: Path = tmp_path / "test-dpack"
    dpack.mkdir()

    (dpack / "docker").mkdir()
    (dpack / "docker" / "Dockerfile").write_text(
        "FROM python:3.11-slim\nWORKDIR /workspace\nCMD [\"/bin/bash\"]\n"
    )
    (dpack / "opencode").mkdir()

    config: dict[str, Any] = {
        "name": "test-dpack",
        "description": "Test decision-pack for unit tests",
        "docker_image_name": "test-dpack-img",
        "default_model": "anthropic/claude-sonnet-4",
    }
    with open(dpack / "config.yaml", "w") as f:
        yaml.dump(config, f)

    return dpack


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """
    Create a sample data directory with test files.

    Returns the path to the data directory.
    """
    data_path: Path = tmp_path / "test-data"
    data_path.mkdir()

    (data_path / "sample.csv").write_text("a,b,c\n1,2,3\n")
    (data_path / "subdir").mkdir()
    (data_path / "subdir" / "nested.txt").write_text("nested content")

    return data_path


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """Provide a path for a new work directory (does not exist yet)."""
    return tmp_path / "work"
