"""
Integration tests for the dlab Docker pipeline and end-to-end CLI flow.

These tests use the real "poem" decision-pack and require Docker to be running.
The TestEndToEnd class additionally requires ANTHROPIC_API_KEY in .env.

Run with:
    ~/miniconda3/envs/mmm-docker/bin/python -m pytest tests/test_integration.py -v
"""

import argparse
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Generator

import pytest
import yaml

from dlab.cli import cmd_run, create_parser
from dlab.config import load_dpack_config
from dlab.docker import (
    build_image,
    container_exists,
    exec_command,
    image_exists,
    needs_rebuild,
    start_container,
    stop_container,
)
from dlab.session import create_session


REPO_ROOT: Path = Path(__file__).parent.parent.resolve()
POEM_DPACK_DIR: str = str(REPO_ROOT / "decision-packs" / "poem")
ENV_FILE: str = str(REPO_ROOT / ".env")

INTEGRATION_IMAGE_NAME: str = "dlab-integration-test"
E2E_IMAGE_NAME: str = "dlab-e2e-test"


def _has_api_key() -> bool:
    """Check if .env file exists and contains ANTHROPIC_API_KEY."""
    env_path: Path = Path(ENV_FILE)
    if not env_path.exists():
        return False
    content: str = env_path.read_text()
    return "ANTHROPIC_API_KEY=" in content


def _remove_image(name: str) -> None:
    """Remove a Docker image, ignoring errors if it doesn't exist."""
    subprocess.run(["docker", "rmi", "-f", name], capture_output=True)


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def poem_config() -> dict[str, Any]:
    """Load the real poem decision-pack configuration."""
    return load_dpack_config(POEM_DPACK_DIR)


@pytest.fixture(scope="module")
def integration_image(poem_config: dict[str, Any]) -> Generator[str, None, None]:
    """Build the integration test image once; clean up after all tests."""
    opencode_version: str = poem_config["opencode_version"]
    build_image(POEM_DPACK_DIR, INTEGRATION_IMAGE_NAME, opencode_version)
    yield INTEGRATION_IMAGE_NAME
    _remove_image(INTEGRATION_IMAGE_NAME)
    _remove_image(f"{INTEGRATION_IMAGE_NAME}-base")


@pytest.fixture(scope="module")
def e2e_dpack_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Copy poem decision-pack to temp dir with test-specific image name."""
    base: Path = tmp_path_factory.mktemp("e2e_dpack")
    dpack_copy: Path = base / "poem"
    shutil.copytree(POEM_DPACK_DIR, str(dpack_copy))

    config_path: Path = dpack_copy / "config.yaml"
    config_data: dict[str, Any] = yaml.safe_load(config_path.read_text())
    config_data["docker_image_name"] = E2E_IMAGE_NAME
    config_path.write_text(yaml.dump(config_data))

    return dpack_copy


@pytest.fixture(scope="module")
def e2e_image(e2e_dpack_dir: Path) -> Generator[str, None, None]:
    """Build the e2e test image once; clean up after all tests."""
    config: dict[str, Any] = load_dpack_config(str(e2e_dpack_dir))
    build_image(str(e2e_dpack_dir), E2E_IMAGE_NAME, config["opencode_version"])
    yield E2E_IMAGE_NAME
    _remove_image(E2E_IMAGE_NAME)
    _remove_image(f"{E2E_IMAGE_NAME}-base")


# ---------------------------------------------------------------------------
# TestPipelineIntegration
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    """
    Test the Docker pipeline with the real poem decision-pack.

    No API key needed -- these tests never call an LLM.
    """

    @pytest.fixture
    def empty_data_dir(self, tmp_path: Path) -> Path:
        """Create an empty data directory (poem decision-pack needs no data)."""
        data_path: Path = tmp_path / "data"
        data_path.mkdir()
        return data_path

    @pytest.fixture
    def session_work_dir(
        self, tmp_path: Path, poem_config: dict[str, Any], empty_data_dir: Path,
    ) -> Path:
        """Create a session and return the work directory path."""
        work_dir: Path = tmp_path / "work"
        state: dict[str, Any] = create_session(
            poem_config, str(empty_data_dir), work_dir=str(work_dir),
        )
        return Path(state["work_dir"])

    @pytest.fixture
    def container_name(self) -> str:
        """Generate a unique container name for this test."""
        suffix: str = uuid.uuid4().hex[:8]
        return f"dlab-inttest-{suffix}"

    @pytest.fixture
    def running_container(
        self,
        integration_image: str,
        session_work_dir: Path,
        container_name: str,
    ) -> Generator[str, None, None]:
        """Start a container and ensure cleanup on teardown."""
        start_container(integration_image, str(session_work_dir), container_name)
        yield container_name
        stop_container(container_name)

    def test_image_was_built(self, integration_image: str) -> None:
        """Both wrapper and base images should exist after build."""
        assert image_exists(integration_image)
        assert image_exists(f"{integration_image}-base")

    def test_opencode_installed_in_image(
        self,
        integration_image: str,
        session_work_dir: Path,
        container_name: str,
    ) -> None:
        """opencode should be available inside the built image."""
        start_container(integration_image, str(session_work_dir), container_name)
        try:
            exit_code, stdout, stderr = exec_command(
                container_name, ["opencode", "--version"],
            )
            assert exit_code == 0
            assert stdout.strip()
        finally:
            stop_container(container_name)

    def test_node_installed_in_image(
        self,
        integration_image: str,
        session_work_dir: Path,
        container_name: str,
    ) -> None:
        """Node.js should be available inside the built image."""
        start_container(integration_image, str(session_work_dir), container_name)
        try:
            exit_code, stdout, stderr = exec_command(
                container_name, ["node", "--version"],
            )
            assert exit_code == 0
            assert stdout.strip().startswith("v")
        finally:
            stop_container(container_name)

    def test_create_session_with_poem_dpack(
        self, poem_config: dict[str, Any], empty_data_dir: Path, tmp_path: Path,
    ) -> None:
        """Session should set up the full poem directory structure."""
        work_dir: Path = tmp_path / "session-test"
        state: dict[str, Any] = create_session(
            poem_config, str(empty_data_dir), work_dir=str(work_dir),
        )
        work_path: Path = Path(state["work_dir"])

        # Core directories
        assert (work_path / "data").exists()
        assert (work_path / ".opencode").exists()
        assert (work_path / "_opencode_logs").exists()

        # Opencode config
        assert (work_path / ".opencode" / "opencode.json").exists()

        # Agents
        assert (work_path / ".opencode" / "agents" / "literary-agent.md").exists()
        assert (work_path / ".opencode" / "agents" / "poet.md").exists()
        assert (work_path / ".opencode" / "agents" / "popo-poet.md").exists()

        # Parallel agents config + generated tool
        assert (work_path / ".opencode" / "parallel_agents" / "poet.yaml").exists()
        assert (work_path / ".opencode" / "tools" / "parallel-agents.ts").exists()

        # State
        assert (work_path / ".state.json").exists()
        assert state["status"] == "created"
        assert state["dpack_name"] == "poem"

    def test_start_and_stop_container(
        self,
        integration_image: str,
        session_work_dir: Path,
        container_name: str,
    ) -> None:
        """Container should start, be visible, and be cleanly removed."""
        start_container(integration_image, str(session_work_dir), container_name)
        assert container_exists(container_name)

        exit_code, stdout, stderr = exec_command(container_name, ["ls", "/workspace"])
        assert exit_code == 0
        assert "data" in stdout

        stop_container(container_name)
        assert not container_exists(container_name)

    def test_container_has_workspace_mount(self, running_container: str) -> None:
        """Container should have the session work directory mounted at /workspace."""
        exit_code, stdout, stderr = exec_command(
            running_container, ["ls", "/workspace/.opencode/agents/"],
        )
        assert exit_code == 0
        assert "literary-agent.md" in stdout
        assert "poet.md" in stdout
        assert "popo-poet.md" in stdout

    def test_container_has_logs_mount(
        self, running_container: str, session_work_dir: Path,
    ) -> None:
        """Writes to /_opencode_logs inside container should appear on host."""
        exit_code, stdout, stderr = exec_command(
            running_container,
            ["sh", "-c", "echo test-log-content > /_opencode_logs/test.log"],
        )
        assert exit_code == 0

        host_log: Path = session_work_dir / "_opencode_logs" / "test.log"
        assert host_log.exists()
        assert "test-log-content" in host_log.read_text()

    def test_needs_rebuild_false_after_build(
        self, integration_image: str, poem_config: dict[str, Any],
    ) -> None:
        """After building, needs_rebuild should return False."""
        should_rebuild: bool
        reason: str
        should_rebuild, reason = needs_rebuild(
            POEM_DPACK_DIR, integration_image, poem_config["opencode_version"],
        )
        assert should_rebuild is False
        assert reason == "image is up to date"

    def test_stop_container_is_idempotent(self) -> None:
        """Stopping a non-existent container should not raise."""
        stop_container(f"nonexistent-{uuid.uuid4().hex[:8]}")


# ---------------------------------------------------------------------------
# TestEndToEnd
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_api_key(), reason="No ANTHROPIC_API_KEY in .env")
class TestEndToEnd:
    """
    End-to-end test running cmd_run() with the poem decision-pack.

    Requires ANTHROPIC_API_KEY in the .env file at repo root.
    Exercises the full workflow: literary-agent -> popo-poet -> parallel poets
    -> consolidator -> final_poem.md.
    """

    def test_full_poem_workflow(
        self,
        e2e_dpack_dir: Path,
        e2e_image: str,
        tmp_path: Path,
    ) -> None:
        """Full poem workflow: popo-poet, parallel poets, consolidator."""
        work_dir: Path = tmp_path / "e2e-work"
        data_dir: Path = tmp_path / "empty-data"
        data_dir.mkdir()

        parser: argparse.ArgumentParser = create_parser()
        args: argparse.Namespace = parser.parse_args([
            "--dpack", str(e2e_dpack_dir),
            "--data", str(data_dir),
            "--prompt", "Write me a short poem about the ocean.",
            "--work-dir", str(work_dir),
            "--env-file", ENV_FILE,
            "--model", "anthropic/claude-sonnet-4-5",
        ])

        exit_code: int = cmd_run(args)

        assert exit_code == 0

        # --- Infrastructure artifacts ---

        assert (work_dir / ".state.json").exists()
        assert not container_exists(work_dir.name)

        # --- Main log ---

        main_log: Path = work_dir / "_opencode_logs" / "main.log"
        assert main_log.exists()
        log_content: str = main_log.read_text()

        # popo-poet runs via the task tool; evidence should be in main log
        assert "popo-poet" in log_content.lower()

        # --- Parallel agent run ---
        # The literary-agent should have spawned parallel poet instances.
        # Logs land in _opencode_logs/poet-parallel-run-{timestamp}/

        logs_dir: Path = work_dir / "_opencode_logs"
        parallel_log_dirs: list[Path] = [
            d for d in logs_dir.iterdir()
            if d.is_dir() and d.name.startswith("poet-parallel-run-")
        ]
        assert len(parallel_log_dirs) >= 1, "Expected at least one parallel poet run"

        run_log_dir: Path = parallel_log_dirs[0]
        instance_logs: list[Path] = sorted(run_log_dir.glob("instance-*.log"))
        num_instances: int = len(instance_logs)
        assert num_instances >= 2, f"Expected >= 2 poet instances, got {num_instances}"

        # Each instance log should be non-empty
        for log_file in instance_logs:
            assert log_file.stat().st_size > 0, f"{log_file.name} is empty"

        # Consolidator runs when > 2 instances
        consolidator_log: Path = run_log_dir / "consolidator.log"
        if num_instances > 2:
            assert consolidator_log.exists(), (
                f"Expected consolidator.log with {num_instances} instances"
            )
            assert consolidator_log.stat().st_size > 0

        # --- Parallel work directories ---
        # parallel/run-{timestamp}/instance-{N}/ should exist

        parallel_dir: Path = work_dir / "parallel"
        assert parallel_dir.exists(), "Expected parallel/ directory"

        run_dirs: list[Path] = [
            d for d in parallel_dir.iterdir()
            if d.is_dir() and d.name.startswith("run-")
        ]
        assert len(run_dirs) >= 1

        instance_dirs: list[Path] = sorted(run_dirs[0].glob("instance-*"))
        assert len(instance_dirs) >= 2

        # Each instance should have its own .opencode config and summary.md
        for inst_dir in instance_dirs:
            assert (inst_dir / ".opencode").exists()
            assert (inst_dir / "summary.md").exists(), (
                f"Missing summary.md in {inst_dir.name}"
            )

        # --- Final output ---

        assert (work_dir / "final_poem.md").exists()
        poem_content: str = (work_dir / "final_poem.md").read_text()
        assert len(poem_content.strip()) > 0
