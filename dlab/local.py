"""
Local execution backend for running opencode without Docker.

Used when --no-sandboxing is passed or Docker is not available.
Instead of replicating the Docker environment, this copies the docker/
directory into the work dir as _docker/ and prepends instructions to the
prompt telling the agent to set up its own environment.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def is_docker_available() -> bool:
    """
    Check if Docker CLI exists and the daemon is running.

    Returns
    -------
    bool
        True if docker is installed and the daemon responds.
    """
    if shutil.which("docker") is None:
        return False
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def detect_package_manager(config_dir: str) -> str:
    """
    Detect package manager from docker/ contents.

    Parameters
    ----------
    config_dir : str
        Path to decision-pack directory.

    Returns
    -------
    str
        One of "conda", "pixi", "pip".
    """
    docker_dir: Path = Path(config_dir) / "docker"
    if (docker_dir / "environment.yml").exists():
        return "conda"
    if (docker_dir / "pixi.toml").exists():
        return "pixi"
    return "pip"


def copy_docker_dir(config_dir: str, work_dir: str) -> None:
    """
    Copy the decision-pack's docker/ directory into the work dir as _docker/.

    Parameters
    ----------
    config_dir : str
        Path to decision-pack directory.
    work_dir : str
        Session work directory.
    """
    docker_src: Path = Path(config_dir) / "docker"
    docker_dst: Path = Path(work_dir) / "_docker"
    if docker_src.exists():
        if docker_dst.exists():
            shutil.rmtree(docker_dst)
        shutil.copytree(str(docker_src), str(docker_dst))


def build_local_prompt(prompt: str, config: dict[str, Any]) -> str:
    """
    Prepend system instructions for unsandboxed local execution.

    Parameters
    ----------
    prompt : str
        Original user prompt.
    config : dict[str, Any]
        decision-pack configuration.

    Returns
    -------
    str
        Prompt with system instructions prepended.
    """
    pkg_mgr: str = config.get(
        "package_manager",
        detect_package_manager(config["config_dir"]),
    )

    system_instructions: str = (
        "IMPORTANT --- SYSTEM INSTRUCTIONS: "
        "You're running in a work directory that was supposed to run in a "
        f"docker container with python managed by {pkg_mgr}. "
        "This has not been set up. Please read the contents in _docker/ and "
        "see whether you're already operating in a similar environment. "
        "If not, try to set up the environment as best as possible. "
        "Also read _hooks/, which contains scripts that are supposed to run "
        "before the actual work begins, respectively after it's done."
    )

    return f"{system_instructions}\n\nNow follows the User's request:\n{prompt}"


def build_local_env(env_file: str | None = None) -> dict[str, str]:
    """
    Build environment variables dict for local execution.

    Parameters
    ----------
    env_file : str | None
        Optional .env file to parse and include.

    Returns
    -------
    dict[str, str]
        Environment variables.
    """
    env: dict[str, str] = dict(os.environ)

    if env_file:
        for line in Path(env_file).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip("'\"")
            env[key.strip()] = value

    return env


def run_local_command(
    command: list[str],
    work_dir: str,
    env: dict[str, str],
    timeout: int | None = None,
) -> tuple[int, str, str]:
    """
    Run a command locally in the work directory.

    Parameters
    ----------
    command : list[str]
        Command and arguments.
    work_dir : str
        Working directory.
    env : dict[str, str]
        Environment variables.
    timeout : int | None
        Timeout in seconds.

    Returns
    -------
    tuple[int, str, str]
        (exit_code, stdout, stderr).
    """
    result: subprocess.CompletedProcess[str] = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=work_dir,
        env=env,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def run_opencode_local(
    work_dir: str,
    prompt: str,
    model: str,
    env: dict[str, str],
    timeout: int | None = None,
    log_prefix: str = "main",
) -> tuple[int, str, str]:
    """
    Run opencode locally in the work directory.

    Parameters
    ----------
    work_dir : str
        Session work directory.
    prompt : str
        Prompt text (already includes system instructions).
    model : str
        LLM model identifier.
    env : dict[str, str]
        Environment variables.
    timeout : int | None
        Timeout in seconds.
    log_prefix : str
        Log file prefix.

    Returns
    -------
    tuple[int, str, str]
        (exit_code, stdout, stderr).
    """
    work_path: Path = Path(work_dir)
    logs_dir: Path = work_path / "_opencode_logs"

    # Write prompt to file (avoids shell quoting issues)
    prompt_file: Path = work_path / ".prompt.txt"
    prompt_file.write_text(prompt)

    # Build runner script
    log_path: str = str(logs_dir / f"{log_prefix}.log")
    runner_script: str = f'''#!/bin/bash
set -o pipefail
prompt=$(cat "{prompt_file}")
opencode run --format json --log-level DEBUG --model "{model}" "$prompt" 2>&1 | tee "{log_path}"
'''
    runner_file: Path = work_path / ".run_opencode.sh"
    runner_file.write_text(runner_script)
    runner_file.chmod(0o755)

    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["bash", str(runner_file)],
        capture_output=True,
        text=True,
        cwd=work_dir,
        env=env,
        timeout=timeout,
    )

    return result.returncode, result.stdout, result.stderr
