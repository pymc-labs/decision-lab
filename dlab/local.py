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

    work_dir_abs: str = str(Path(config["config_dir"]).resolve().parent)
    # Use the actual work dir if available, fall back to config dir parent
    # (the caller should pass work_dir in config if needed)

    system_instructions: str = (
        "IMPORTANT --- SYSTEM INSTRUCTIONS (NO-SANDBOXING MODE):\n\n"
        "You're running locally, NOT inside a Docker container. The decision-pack "
        f"was designed for a Docker environment with python managed by {pkg_mgr}.\n\n"
        "## Step 1: Set up the environment\n\n"
        "Read `_docker/Dockerfile` carefully. It shows:\n"
        "- Which base image and package manager was intended\n"
        "- Which dependency file to install from (requirements.txt, environment.yml, pixi.toml)\n"
        "- Which directories from _docker/ would have been COPY'd into the container "
        "(e.g., custom Python libraries like `COPY <SUB_DIR>/ /opt/<SUB_DIR>/`)\n\n"
        f"Use `{pkg_mgr}` to create and install a local environment from the dependency "
        "file in `_docker/`. For example:\n"
        "- pip: `python -m venv .venv && .venv/bin/pip install -r _docker/requirements.txt`\n"
        "- conda: `conda create -p .conda-env --yes && conda env update -p .conda-env -f _docker/environment.yml`\n"
        "- uv: `uv venv .venv && uv pip install --python .venv/bin/python -r _docker/requirements.txt`\n"
        "- pixi: `cp _docker/pixi.toml . && pixi install`\n\n"
        "If the Dockerfile COPY'd any Python libraries from _docker/ into the container, "
        "you need to make those importable by setting the ABSOLUTE path to _docker/ in "
        "PYTHONPATH when running scripts:\n"
        "`PYTHONPATH=/absolute/path/to/workdir/_docker:$PYTHONPATH python my_script.py`\n\n"
        "## Step 2: Verify the environment works\n\n"
        "After setting up, run a small test script that imports the key packages from the "
        "dependency file to confirm everything is installed correctly. Fix any import errors "
        "before proceeding.\n\n"
        "## Step 3: Read the hooks\n\n"
        "Read `_hooks/` — these are scripts that would have run inside the container before "
        "and after the agent session. Adapt and run pre-run hooks if they make sense locally "
        "(e.g., skip Modal deployment if not applicable, but run data setup scripts).\n\n"
        "## Step 4: Subagent environment instructions\n\n"
        "When you call parallel-agents or task subagents, you MUST include in each prompt:\n"
        "- The absolute path to the correct python binary (e.g., `/absolute/path/to/.venv/bin/python`)\n"
        "- The correct PYTHONPATH value (e.g., `PYTHONPATH=/absolute/path/to/workdir/_docker:$PYTHONPATH`)\n"
        "- Instructions to use this python for all script execution\n\n"
        "Subagents do NOT inherit your environment setup. They start fresh and need explicit "
        "instructions on which python to use.\n\n"
        "---\n\n"
        "Now follows the User's request:\n"
    )

    return f"{system_instructions}{prompt}"


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
echo "$prompt" | python3 -c "import json,sys; print(json.dumps({{'type':'dlab_start','timestamp':int(__import__('time').time()*1000),'model':'{model}','agent':'{log_prefix}','prompt':sys.stdin.read().strip()}}))" > "{log_path}"
opencode run --format json --log-level DEBUG --model "{model}" "$prompt" 2>&1 | tee -a "{log_path}"
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
