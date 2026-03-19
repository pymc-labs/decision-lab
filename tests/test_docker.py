"""
Tests for dlab.docker module.

These tests require Docker to be running.
"""

from pathlib import Path
from typing import Any

import pytest

from dlab.docker import (
    build_image,
    build_runner_script,
    compute_docker_dir_hash,
    container_exists,
    exec_command,
    image_exists,
    start_container,
    stop_container,
)


TEST_IMAGE_NAME: str = "dlab-test-image"
TEST_CONTAINER_NAME: str = "dlab-test-container"


@pytest.fixture
def docker_dir(tmp_path: Path) -> Path:
    """Create a minimal docker directory with a Dockerfile."""
    docker_path: Path = tmp_path / "docker"
    docker_path.mkdir()

    dockerfile: Path = docker_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\nCMD [\"echo\", \"hello\"]\n")

    return tmp_path


@pytest.fixture
def built_image(docker_dir: Path) -> str:
    """Build a test image and return its name. Cleans up after test."""
    build_image(str(docker_dir), TEST_IMAGE_NAME)
    yield TEST_IMAGE_NAME
    # Cleanup: remove the image after test
    import subprocess
    subprocess.run(["docker", "rmi", "-f", TEST_IMAGE_NAME], capture_output=True)


@pytest.fixture
def running_container(built_image: str, tmp_path: Path) -> str:
    """Start a test container and return its name. Cleans up after test."""
    work_dir: Path = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "_opencode_logs").mkdir()

    start_container(built_image, str(work_dir), TEST_CONTAINER_NAME)
    yield TEST_CONTAINER_NAME
    # Cleanup: stop and remove container after test
    stop_container(TEST_CONTAINER_NAME)


class TestImageExists:
    """Tests for image_exists function."""

    def test_nonexistent_image(self) -> None:
        """Should return False for image that doesn't exist."""
        result: bool = image_exists("this-image-definitely-does-not-exist-abc123")
        assert result is False

    def test_existing_image(self, built_image: str) -> None:
        """Should return True for image that exists."""
        result: bool = image_exists(built_image)
        assert result is True


class TestBuildImage:
    """Tests for build_image function."""

    def test_build_success(self, docker_dir: Path) -> None:
        """Should build image successfully."""
        image_name: str = "dlab-build-test"

        build_image(str(docker_dir), image_name)

        assert image_exists(image_name)

        # Cleanup
        import subprocess
        subprocess.run(["docker", "rmi", "-f", image_name], capture_output=True)

    def test_missing_docker_dir(self, tmp_path: Path) -> None:
        """Should raise ValueError if docker/ directory missing."""
        with pytest.raises(ValueError, match="docker/ directory not found"):
            build_image(str(tmp_path), "test-image")

    def test_invalid_dockerfile(self, tmp_path: Path) -> None:
        """Should raise ValueError on build failure."""
        docker_path: Path = tmp_path / "docker"
        docker_path.mkdir()
        (docker_path / "Dockerfile").write_text("INVALID DOCKERFILE CONTENT\n")

        with pytest.raises(ValueError, match="Docker build failed"):
            build_image(str(tmp_path), "test-image")


class TestContainerExists:
    """Tests for container_exists function."""

    def test_nonexistent_container(self) -> None:
        """Should return False for container that doesn't exist."""
        result: bool = container_exists("this-container-definitely-does-not-exist")
        assert result is False

    def test_existing_container(self, running_container: str) -> None:
        """Should return True for container that exists."""
        result: bool = container_exists(running_container)
        assert result is True


class TestStartContainer:
    """Tests for start_container function."""

    def test_start_success(self, built_image: str, tmp_path: Path) -> None:
        """Should start container with correct mounts."""
        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "_opencode_logs").mkdir()
        container_name: str = "dlab-start-test"

        try:
            start_container(built_image, str(work_dir), container_name)
            assert container_exists(container_name)
        finally:
            stop_container(container_name)

    def test_container_already_exists(self, running_container: str, built_image: str, tmp_path: Path) -> None:
        """Should raise ValueError if container already exists."""
        work_dir: Path = tmp_path / "work2"
        work_dir.mkdir()
        (work_dir / "_opencode_logs").mkdir()

        with pytest.raises(ValueError, match="Container already exists"):
            start_container(built_image, str(work_dir), running_container)


class TestExecCommand:
    """Tests for exec_command function."""

    def test_exec_success(self, running_container: str) -> None:
        """Should execute command and return result."""
        exit_code, stdout, stderr = exec_command(
            running_container, ["echo", "hello", "world"]
        )

        assert exit_code == 0
        assert "hello world" in stdout

    def test_exec_failure(self, running_container: str) -> None:
        """Should return non-zero exit code on failure."""
        exit_code, stdout, stderr = exec_command(
            running_container, ["false"]  # 'false' command always exits with 1
        )

        assert exit_code == 1


class TestStopContainer:
    """Tests for stop_container function."""

    def test_stop_running_container(self, built_image: str, tmp_path: Path) -> None:
        """Should stop and remove a running container."""
        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "_opencode_logs").mkdir()
        container_name: str = "dlab-stop-test"

        start_container(built_image, str(work_dir), container_name)
        assert container_exists(container_name)

        stop_container(container_name)
        assert not container_exists(container_name)

    def test_stop_nonexistent_container(self) -> None:
        """Should not raise error if container doesn't exist (idempotent)."""
        # Should not raise
        stop_container("this-container-does-not-exist")


class TestStartContainerWithEnvFile:
    """Tests for start_container with env_file parameter."""

    def test_start_with_env_file(self, built_image: str, tmp_path: Path) -> None:
        """Should start container with env file and have env vars available."""
        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "_opencode_logs").mkdir()
        container_name: str = "dlab-env-test"

        env_file: Path = tmp_path / "test.env"
        env_file.write_text("TEST_VAR=hello_from_env\n")

        try:
            start_container(built_image, str(work_dir), container_name, env_file=str(env_file))
            assert container_exists(container_name)

            # Verify env var is available in container
            exit_code, stdout, stderr = exec_command(
                container_name, ["sh", "-c", "echo $TEST_VAR"]
            )
            assert exit_code == 0
            assert "hello_from_env" in stdout
        finally:
            stop_container(container_name)

    def test_start_with_nonexistent_env_file(self, built_image: str, tmp_path: Path) -> None:
        """Should raise ValueError if env file doesn't exist."""
        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "_opencode_logs").mkdir()
        container_name: str = "dlab-env-missing-test"

        with pytest.raises(ValueError, match="Environment file not found"):
            start_container(
                built_image, str(work_dir), container_name,
                env_file="/path/to/nonexistent/env/file"
            )

    def test_start_without_env_file(self, built_image: str, tmp_path: Path) -> None:
        """Should start container without env file (default behavior)."""
        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "_opencode_logs").mkdir()
        container_name: str = "dlab-no-env-test"

        try:
            start_container(built_image, str(work_dir), container_name, env_file=None)
            assert container_exists(container_name)
        finally:
            stop_container(container_name)


class TestBuildRunnerScript:
    """Tests for build_runner_script function (no Docker required)."""

    def test_basic_script(self) -> None:
        """Script should have opencode command and tee."""
        script: str = build_runner_script("/.prompt.txt", "anthropic/claude-sonnet-4", "main")

        assert "#!/bin/bash" in script
        assert "set -o pipefail" in script
        assert 'opencode run --format json --log-level DEBUG --model "anthropic/claude-sonnet-4"' in script
        assert "tee /_opencode_logs/main.log" in script

    def test_script_model_and_prefix(self) -> None:
        """Model and log prefix should appear correctly in script."""
        script: str = build_runner_script(
            "/.prompt.txt", "anthropic/claude-opus-4", "instance-3",
        )

        assert '--model "anthropic/claude-opus-4"' in script
        assert "tee /_opencode_logs/instance-3.log" in script


class TestComputeDockerDirHash:
    """Tests for compute_docker_dir_hash function (no Docker required)."""

    def test_deterministic(self, tmp_path: Path) -> None:
        """Same directory should produce same hash on repeated calls."""
        docker_dir: Path = tmp_path / "docker"
        docker_dir.mkdir()
        (docker_dir / "Dockerfile").write_text("FROM python:3.11-slim\n")

        hash1: str = compute_docker_dir_hash(docker_dir)
        hash2: str = compute_docker_dir_hash(docker_dir)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex digest

    def test_detects_file_change(self, tmp_path: Path) -> None:
        """Modifying a file should change the hash."""
        docker_dir: Path = tmp_path / "docker"
        docker_dir.mkdir()
        dockerfile: Path = docker_dir / "Dockerfile"
        dockerfile.write_text("FROM python:3.11-slim\n")

        hash1: str = compute_docker_dir_hash(docker_dir)

        dockerfile.write_text("FROM python:3.12-slim\n")
        hash2: str = compute_docker_dir_hash(docker_dir)

        assert hash1 != hash2

    def test_detects_new_file(self, tmp_path: Path) -> None:
        """Adding a file should change the hash."""
        docker_dir: Path = tmp_path / "docker"
        docker_dir.mkdir()
        (docker_dir / "Dockerfile").write_text("FROM python:3.11-slim\n")

        hash1: str = compute_docker_dir_hash(docker_dir)

        (docker_dir / "requirements.txt").write_text("pandas\n")
        hash2: str = compute_docker_dir_hash(docker_dir)

        assert hash1 != hash2

    def test_ignores_pycache(self, tmp_path: Path) -> None:
        """__pycache__ and .pyc files should be ignored."""
        docker_dir: Path = tmp_path / "docker"
        docker_dir.mkdir()
        (docker_dir / "Dockerfile").write_text("FROM python:3.11-slim\n")

        hash1: str = compute_docker_dir_hash(docker_dir)

        # Add __pycache__ directory with .pyc file
        pycache: Path = docker_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "module.cpython-311.pyc").write_bytes(b"\x00\x01\x02")

        # Add a standalone .pyc file
        (docker_dir / "other.pyc").write_bytes(b"\x00\x01\x02")

        hash2: str = compute_docker_dir_hash(docker_dir)

        assert hash1 == hash2

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory should return a valid hash without crashing."""
        docker_dir: Path = tmp_path / "docker"
        docker_dir.mkdir()

        result: str = compute_docker_dir_hash(docker_dir)

        assert isinstance(result, str)
        assert len(result) == 64

    def test_opencode_version_changes_hash(self, tmp_path: Path) -> None:
        """Different opencode_version should produce a different hash."""
        docker_dir: Path = tmp_path / "docker"
        docker_dir.mkdir()
        (docker_dir / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        hash_latest: str = compute_docker_dir_hash(docker_dir)
        hash_pinned: str = compute_docker_dir_hash(docker_dir, "0.1.50")

        assert hash_latest != hash_pinned
