"""
Docker container management for dlab.

This module handles:
- Building Docker images from decision-pack config directories
- Starting/stopping containers with volume mounts
- Executing commands inside containers
- Automatic rebuild detection when docker/ contents change
"""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


# Template for the wrapper Dockerfile that adds opencode to the base image
# Dependencies:
#   - git: version control (used by coding agents)
#   - ripgrep: required by opencode for grep/glob/list tools
#   - curl: needed to install Node.js
#   - nodejs: required to run opencode (installed via npm)
OPENCODE_WRAPPER_DOCKERFILE: str = """FROM {base_image}

# Install git, ripgrep, and Node.js (required for opencode)
RUN apt-get update && apt-get install -y git ripgrep curl && \\
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \\
    apt-get install -y nodejs && \\
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install opencode
RUN npm install -g {opencode_package}

# Verify installation
RUN opencode --version
"""

# Label name for storing the source hash in Docker images
SOURCE_HASH_LABEL: str = "dlab.source-hash"


def compute_docker_dir_hash(
    docker_dir: Path, opencode_version: str = "latest",
) -> str:
    """
    Compute a SHA256 hash of all files in the docker/ directory plus opencode version.

    This hash is used to detect when the docker/ contents or opencode version
    have changed, triggering an automatic rebuild of the Docker image.

    Parameters
    ----------
    docker_dir : Path
        Path to the docker/ directory.
    opencode_version : str
        Version of opencode to install (included in hash so version
        changes trigger rebuilds).

    Returns
    -------
    str
        Hex-encoded SHA256 hash of the directory contents and opencode version.
    """
    hasher = hashlib.sha256()
    hasher.update(f"opencode_version={opencode_version}".encode("utf-8"))

    # Get all files sorted by path for deterministic ordering
    files: list[Path] = sorted(docker_dir.rglob("*"))

    for file_path in files:
        if file_path.is_file():
            # Skip __pycache__ directories (contain timestamps that change on import)
            if "__pycache__" in file_path.parts:
                continue
            # Skip .pyc files
            if file_path.suffix == ".pyc":
                continue
            # Include relative path in hash (so renames are detected)
            rel_path: str = str(file_path.relative_to(docker_dir))
            hasher.update(rel_path.encode("utf-8"))
            # Include file contents
            hasher.update(file_path.read_bytes())

    return hasher.hexdigest()


def get_image_source_hash(image_name: str) -> str | None:
    """
    Get the source hash label from a Docker image.

    Parameters
    ----------
    image_name : str
        Name of the Docker image.

    Returns
    -------
    str | None
        The source hash if the label exists, None otherwise.
    """
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["docker", "inspect", "--format", "{{json .Config.Labels}}", image_name],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return None

    try:
        labels: dict[str, str] = json.loads(result.stdout.strip())
        if labels is None:
            return None
        return labels.get(SOURCE_HASH_LABEL)
    except json.JSONDecodeError:
        return None


def needs_rebuild(
    config_dir: str, image_name: str, opencode_version: str = "latest",
) -> tuple[bool, str]:
    """
    Check if a Docker image needs to be rebuilt based on source changes.

    Parameters
    ----------
    config_dir : str
        Path to the decision-pack config directory (contains docker/ subdirectory).
    image_name : str
        Name of the Docker image.
    opencode_version : str
        Version of opencode to install (included in hash check).

    Returns
    -------
    tuple[bool, str]
        Tuple of (needs_rebuild, reason).
        reason is a human-readable explanation of why rebuild is needed.
    """
    docker_dir: Path = Path(config_dir) / "docker"

    if not docker_dir.exists():
        return True, "docker/ directory not found"

    # Check if image exists at all
    if not image_exists(image_name):
        return True, "image does not exist"

    # Compute current hash (includes opencode version)
    current_hash: str = compute_docker_dir_hash(docker_dir, opencode_version)

    # Get stored hash from image
    stored_hash: str | None = get_image_source_hash(image_name)

    if stored_hash is None:
        return True, "image missing source hash label (built before auto-rebuild)"

    if current_hash != stored_hash:
        return True, "docker/ contents or opencode version have changed"

    return False, "image is up to date"


def image_exists(image_name: str) -> bool:
    """
    Check if a Docker image exists locally.

    Parameters
    ----------
    image_name : str
        Name of the Docker image to check.

    Returns
    -------
    bool
        True if image exists, False otherwise.
    """
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["docker", "images", "-q", image_name],
        capture_output=True,
        text=True,
    )
    # docker images -q returns image ID if found, empty string if not
    return bool(result.stdout.strip())


def _get_image_id(image_name: str) -> str | None:
    """Get the image ID for a given image name, or None if not found."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["docker", "images", "-q", "--no-trunc", image_name],
        capture_output=True,
        text=True,
    )
    image_id: str = result.stdout.strip()
    return image_id if image_id else None


def count_dangling_images() -> int:
    """Return the number of dangling (untagged) Docker images."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["docker", "images", "-q", "--filter", "dangling=true"],
        capture_output=True,
        text=True,
    )
    return len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0


def _remove_dangling_image(old_id: str | None, current_name: str) -> None:
    """Remove an old image by ID if it's now dangling (untagged)."""
    if old_id is None:
        return
    new_id: str | None = _get_image_id(current_name)
    if new_id == old_id:
        return
    # Old ID is now dangling — remove it
    subprocess.run(["docker", "rmi", old_id], capture_output=True)


def _run_docker_build(
    cmd: list[str],
    on_output: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    """
    Run a docker build command, streaming output line by line.

    Parameters
    ----------
    cmd : list[str]
        Docker build command.
    on_output : Callable[[str], None] | None
        Called for each output line.

    Returns
    -------
    tuple[int, str]
        (return_code, stderr_text).
    """
    proc: subprocess.Popen[str] = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output_lines: list[str] = []
    for line in proc.stdout:  # type: ignore[union-attr]
        line = line.rstrip("\n")
        output_lines.append(line)
        if on_output:
            on_output(line)
    proc.wait()
    return proc.returncode, "\n".join(output_lines)


def build_image(
    config_dir: str,
    image_name: str,
    opencode_version: str = "latest",
    on_output: Callable[[str], None] | None = None,
) -> None:
    """
    Build a Docker image from a decision-pack's docker/ directory with opencode installed.

    This function:
    1. Builds the decision-pack's Dockerfile as a base image
    2. Creates a wrapper Dockerfile that adds opencode
    3. Builds the final image with opencode installed
    4. Removes previous image IDs if they became dangling

    Parameters
    ----------
    config_dir : str
        Path to the decision-pack config directory (contains docker/ subdirectory).
    image_name : str
        Name to tag the built image with.
    opencode_version : str
        Version of opencode to install (default: "latest").
    on_output : Callable[[str], None] | None
        Optional callback invoked for each line of build output.

    Raises
    ------
    ValueError
        If the docker/ directory doesn't exist or build fails.
    """
    docker_dir: Path = Path(config_dir) / "docker"

    if not docker_dir.exists():
        raise ValueError(f"docker/ directory not found in: {config_dir}")

    base_image_name: str = f"{image_name}-base"

    # Capture old image IDs so we can clean up dangling images after build
    old_base_id: str | None = _get_image_id(base_image_name)
    old_wrapper_id: str | None = _get_image_id(image_name)

    # Step 1: Build the base image from decision-pack's Dockerfile
    returncode, stderr = _run_docker_build(
        ["docker", "build", "-t", base_image_name, str(docker_dir)],
        on_output=on_output,
    )

    if returncode != 0:
        raise ValueError(f"Docker build failed: {stderr}")

    # Step 2: Create wrapper Dockerfile that adds opencode
    if opencode_version == "latest":
        opencode_package: str = "opencode-ai@latest"
    else:
        opencode_package = f"opencode-ai@{opencode_version}"

    wrapper_dockerfile: str = OPENCODE_WRAPPER_DOCKERFILE.format(
        base_image=base_image_name,
        opencode_package=opencode_package,
    )

    # Step 3: Compute source hash for auto-rebuild detection
    source_hash: str = compute_docker_dir_hash(docker_dir, opencode_version)

    # Step 4: Build final image with opencode and source hash label
    with tempfile.TemporaryDirectory() as tmpdir:
        dockerfile_path: Path = Path(tmpdir) / "Dockerfile"
        dockerfile_path.write_text(wrapper_dockerfile)

        returncode, stderr = _run_docker_build(
            [
                "docker", "build",
                "-t", image_name,
                "--label", f"{SOURCE_HASH_LABEL}={source_hash}",
                tmpdir,
            ],
            on_output=on_output,
        )

        if returncode != 0:
            raise ValueError(f"Docker build (opencode wrapper) failed: {stderr}")

    # Step 5: Remove old images if they became dangling after re-tagging
    _remove_dangling_image(old_base_id, base_image_name)
    _remove_dangling_image(old_wrapper_id, image_name)


def container_exists(container_name: str) -> bool:
    """
    Check if a Docker container exists (running or stopped).

    Parameters
    ----------
    container_name : str
        Name of the container to check.

    Returns
    -------
    bool
        True if container exists, False otherwise.
    """
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["docker", "ps", "-a", "-q", "-f", f"name=^{container_name}$"],
        capture_output=True,
        text=True,
    )
    # docker ps -q returns container ID if found, empty string if not
    return bool(result.stdout.strip())


def start_container(
    image_name: str,
    work_dir: str,
    container_name: str,
    env_file: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> None:
    """
    Start a new Docker container with volume mounts.

    The container runs in detached mode with `tail -f /dev/null` to keep it
    alive for subsequent `docker exec` commands.

    Parameters
    ----------
    image_name : str
        Name of the Docker image to use.
    work_dir : str
        Path to the work directory to mount at /workspace.
    container_name : str
        Name to give the container.
    env_file : str | None
        Optional path to an environment file to pass to the container.
    extra_env : dict[str, str] | None
        Additional environment variables to pass via -e flags.

    Raises
    ------
    ValueError
        If the container already exists, env file not found, or fails to start.
    """
    if container_exists(container_name):
        raise ValueError(f"Container already exists: {container_name}")

    if env_file is not None:
        env_path: Path = Path(env_file).resolve()
        if not env_path.exists():
            raise ValueError(f"Environment file not found: {env_file}")

    work_path: Path = Path(work_dir).resolve()

    # Build the docker run command
    cmd: list[str] = [
        "docker", "run",
        "-d",                                    # Detached mode
        "--name", container_name,                # Container name
        "-v", f"{work_path}:/workspace",         # Mount work_dir at /workspace
        "-v", f"{work_path}/_opencode_logs:/_opencode_logs",     # Mount logs at /_opencode_logs
        "-w", "/workspace",                      # Set working directory
    ]

    # Add env file if provided
    if env_file is not None:
        cmd.extend(["--env-file", str(env_path)])

    # Add extra environment variables
    if extra_env:
        for key, value in extra_env.items():
            cmd.extend(["-e", f"{key}={value}"])

    cmd.extend([
        image_name,
        "tail", "-f", "/dev/null",               # Keep container running
    ])

    result: subprocess.CompletedProcess[str] = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise ValueError(f"Failed to start container: {result.stderr}")


def exec_command(
    container_name: str,
    command: list[str],
    timeout: int | None = None,
) -> tuple[int, str, str]:
    """
    Execute a command inside a running container.

    Parameters
    ----------
    container_name : str
        Name of the running container.
    command : list[str]
        Command and arguments to execute.
    timeout : int | None
        Timeout in seconds. None means no timeout.

    Returns
    -------
    tuple[int, str, str]
        Tuple of (exit_code, stdout, stderr).
    """
    cmd: list[str] = ["docker", "exec", container_name] + command

    result: subprocess.CompletedProcess[str] = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    return result.returncode, result.stdout, result.stderr


def stop_container(container_name: str) -> None:
    """
    Stop and remove a Docker container.

    Parameters
    ----------
    container_name : str
        Name of the container to stop and remove.

    Notes
    -----
    This function is idempotent - it silently succeeds if the container
    doesn't exist or is already stopped.
    """
    # Stop the container (ignore errors if already stopped)
    subprocess.run(
        ["docker", "stop", container_name],
        capture_output=True,
        text=True,
    )

    # Remove the container (ignore errors if doesn't exist)
    subprocess.run(
        ["docker", "rm", container_name],
        capture_output=True,
        text=True,
    )


def build_runner_script(
    prompt_file: str,
    model: str,
    log_prefix: str,
) -> str:
    """
    Build the bash runner script that runs opencode inside a container.

    Parameters
    ----------
    prompt_file : str
        Path to the prompt file inside the container.
    model : str
        The model to use.
    log_prefix : str
        Prefix for log files.

    Returns
    -------
    str
        The bash script content.
    """
    return f'''#!/bin/bash
set -o pipefail
prompt=$(cat {prompt_file})
echo "$prompt" | python3 -c "import json,sys; print(json.dumps({{'type':'dlab_start','timestamp':int(__import__('time').time()*1000),'model':'{model}','agent':'{log_prefix}','prompt':sys.stdin.read().strip()}}))" > /_opencode_logs/{log_prefix}.log
opencode run --format json --log-level DEBUG --model "{model}" "$prompt" 2>&1 | tee -a /_opencode_logs/{log_prefix}.log
'''


def run_opencode(
    container_name: str,
    prompt: str,
    model: str,
    timeout: int | None = None,
    log_prefix: str = "main",
) -> tuple[int, str, str]:
    """
    Run opencode with a prompt inside a container, logging output to _opencode_logs.

    Parameters
    ----------
    container_name : str
        Name of the running container.
    prompt : str
        The prompt to send to opencode.
    model : str
        The model to use (e.g., "anthropic/claude-sonnet-4-5").
    timeout : int | None
        Timeout in seconds. None means no timeout.
    log_prefix : str
        Prefix for log files (default: "main").

    Returns
    -------
    tuple[int, str, str]
        Tuple of (exit_code, stdout, stderr).
    """
    # Write prompt to a file to avoid shell quoting issues
    # (prompts can contain quotes, $, backticks, newlines, etc.)
    # The file is written via docker exec with stdin - completely safe
    prompt_file: str = "/.prompt.txt"

    # Write prompt file using cat with stdin (bypasses all shell escaping)
    write_result: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["docker", "exec", "-i", container_name, "sh", "-c", f"cat > {prompt_file}"],
        input=prompt.encode(),
        capture_output=True,
    )
    if write_result.returncode != 0:
        return write_result.returncode, "", write_result.stderr.decode()

    # Build the runner script that reads the prompt file and runs opencode
    # This avoids any shell expansion of the prompt content
    runner_script: str = build_runner_script(prompt_file, model, log_prefix)
    runner_file: str = "/.run_opencode.sh"

    write_runner: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["docker", "exec", "-i", container_name, "sh", "-c", f"cat > {runner_file} && chmod +x {runner_file}"],
        input=runner_script.encode(),
        capture_output=True,
    )
    if write_runner.returncode != 0:
        return write_runner.returncode, "", write_runner.stderr.decode()

    # Run the script
    command: list[str] = ["bash", runner_file]

    return exec_command(container_name, command, timeout=timeout)
