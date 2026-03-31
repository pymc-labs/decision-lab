"""
Session management for dlab work directories.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from dlab.model_fallback import process_opencode_dir
from dlab.parallel_tool import PARALLEL_AGENTS_SOURCE


STATE_FILE: str = ".state.json"


def _session_dir_prefix(dpack_name: str) -> str:
    """Build session directory prefix from decision-pack name."""
    return f"dlab-{dpack_name}-workdir-"


def get_next_sequence_number(base_dir: str, dpack_name: str = "analysis") -> int:
    """
    Find the next available sequence number for session directories.

    Parameters
    ----------
    base_dir : str
        Directory to search for existing session directories.
    dpack_name : str
        decision-pack name used as directory prefix.

    Returns
    -------
    int
        Next available sequence number (starts at 1).
    """
    base_path: Path = Path(base_dir)
    if not base_path.exists():
        return 1

    prefix: str = _session_dir_prefix(dpack_name)
    pattern: re.Pattern[str] = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    max_seq: int = 0

    for item in base_path.iterdir():
        if item.is_dir():
            match: re.Match[str] | None = pattern.match(item.name)
            if match:
                seq: int = int(match.group(1))
                max_seq = max(max_seq, seq)

    return max_seq + 1


def copy_data_to_workdir(data_dir: str, work_dir: str) -> None:
    """
    Copy source data directory to the work directory.

    Parameters
    ----------
    data_dir : str
        Path to the source data directory.
    work_dir : str
        Path to the work directory.

    Raises
    ------
    ValueError
        If data_dir does not exist or is not a directory.
    """
    data_path: Path = Path(data_dir)
    if not data_path.exists():
        raise ValueError(f"Data directory does not exist: {data_dir}")
    if not data_path.is_dir():
        raise ValueError(f"Data path is not a directory: {data_dir}")

    dest_path: Path = Path(work_dir) / "data"
    shutil.copytree(data_path, dest_path)


def copy_data_paths_to_workdir(paths: list[str], work_dir: str) -> None:
    """
    Copy data files and/or directories into the work directory.

    Parameters
    ----------
    paths : list[str]
        Paths to files or directories.
    work_dir : str
        Path to the work directory.

    Raises
    ------
    ValueError
        If any path does not exist.
    """
    dest_path: Path = Path(work_dir) / "data"
    dest_path.mkdir(parents=True, exist_ok=True)

    for p in paths:
        src: Path = Path(p)
        if not src.exists():
            raise ValueError(f"Data path does not exist: {p}")
        if src.is_dir():
            shutil.copytree(src, dest_path / src.name)
        else:
            shutil.copy2(src, dest_path / src.name)


def copy_opencode_config(config_dir: str, work_dir: str) -> None:
    """
    Copy opencode configuration from decision-pack to work directory.

    Parameters
    ----------
    config_dir : str
        Path to the decision-pack config directory.
    work_dir : str
        Path to the work directory.

    Raises
    ------
    ValueError
        If opencode directory does not exist in config_dir.
    """
    opencode_src: Path = Path(config_dir) / "opencode"
    if not opencode_src.exists():
        raise ValueError(f"opencode directory not found in: {config_dir}")

    opencode_dest: Path = Path(work_dir) / ".opencode"
    shutil.copytree(opencode_src, opencode_dest)


def copy_hook_scripts(config: dict[str, Any], work_dir: str) -> None:
    """
    Copy hook scripts from decision-pack to work directory.

    Copies pre-run and post-run scripts referenced in config hooks
    to a _hooks/ directory in the work dir, preserving execute permissions.

    Parameters
    ----------
    config : dict[str, Any]
        decision-pack configuration (from load_dpack_config).
    work_dir : str
        Path to the work directory.
    """
    hooks: dict[str, Any] = config.get("hooks", {})
    config_dir: Path = Path(config["config_dir"])
    work_path: Path = Path(work_dir)

    all_scripts: list[str] = hooks.get("pre-run", []) + hooks.get("post-run", [])
    if not all_scripts:
        return

    hooks_dest: Path = work_path / "_hooks"
    hooks_dest.mkdir(exist_ok=True)

    for script_name in all_scripts:
        src: Path = config_dir / script_name
        if not src.exists():
            raise ValueError(f"Hook script not found: {script_name}")
        shutil.copy2(src, hooks_dest / src.name)


def setup_opencode_config(
    config_dir: str,
    work_dir: str,
    orchestrator_model: str | None = None,
    env_file: str | None = None,
    no_sandboxing: bool = False,
) -> list[str]:
    """
    Set up opencode configuration in work directory.

    Copies the opencode config from decision-pack, validates model names,
    applies provider fallback, generates parallel-agents.ts if needed,
    and sets up package.json dependencies.

    Parameters
    ----------
    config_dir : str
        Path to the decision-pack config directory.
    work_dir : str
        Path to the work directory.
    orchestrator_model : str | None
        The orchestrator's model. If provided, agent configs referencing
        providers without API keys in env_file will be replaced with this.
    env_file : str | None
        Path to .env file for checking available provider keys.
    no_sandboxing : bool
        If True, also check os.environ for API keys.

    Returns
    -------
    list[str]
        Messages from model validation and fallback (warnings, replacements).
    """
    copy_opencode_config(config_dir, work_dir)

    # Validate model names and apply provider fallback
    messages: list[str] = []
    opencode_dest: Path = Path(work_dir) / ".opencode"
    if orchestrator_model:
        messages = process_opencode_dir(
            str(opencode_dest), orchestrator_model, env_file, no_sandboxing,
        )

    # Generate parallel-agents.ts if decision-pack has parallel_agents/ configs
    parallel_configs_dir: Path = opencode_dest / "parallel_agents"
    if parallel_configs_dir.exists() and any(parallel_configs_dir.glob("*.yaml")):
        tools_dir: Path = opencode_dest / "tools"
        tools_dir.mkdir(exist_ok=True)
        (tools_dir / "parallel-agents.ts").write_text(PARALLEL_AGENTS_SOURCE)

        # Ensure yaml dependency exists in package.json (needed by parallel-agents.ts)
        package_json_path: Path = opencode_dest / "package.json"
        if package_json_path.exists():
            pkg: dict[str, Any] = json.loads(package_json_path.read_text())
            if "dependencies" not in pkg:
                pkg["dependencies"] = {}
            if "yaml" not in pkg["dependencies"]:
                pkg["dependencies"]["yaml"] = "^2.0.0"
                package_json_path.write_text(json.dumps(pkg, indent=2))
        else:
            pkg = {"dependencies": {"yaml": "^2.0.0"}}
            package_json_path.write_text(json.dumps(pkg, indent=2))

    return messages


def save_state(work_dir: str, state: dict[str, Any]) -> None:
    """
    Save session state to .state.json in work directory.

    Parameters
    ----------
    work_dir : str
        Path to the work directory.
    state : dict[str, Any]
        Session state to persist.
    """
    state_path: Path = Path(work_dir) / STATE_FILE
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def load_state(work_dir: str) -> dict[str, Any]:
    """
    Load session state from work directory.

    Parameters
    ----------
    work_dir : str
        Path to the work directory.

    Returns
    -------
    dict[str, Any]
        Session state.

    Raises
    ------
    ValueError
        If .state.json does not exist or is invalid.
    """
    state_path: Path = Path(work_dir) / STATE_FILE
    if not state_path.exists():
        raise ValueError(f"No .state.json found in: {work_dir}")

    try:
        with open(state_path, "r") as f:
            state: dict[str, Any] = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in .state.json: {e}")

    return state


def create_session(
    config: dict[str, Any],
    data_dir: str | list[str] | None,
    work_dir: str | None = None,
    base_dir: str | None = None,
    orchestrator_model: str | None = None,
    env_file: str | None = None,
    no_sandboxing: bool = False,
) -> dict[str, Any]:
    """
    Create a new session with work directory.

    Parameters
    ----------
    config : dict[str, Any]
        decision-pack configuration (from load_dpack_config).
    data_dir : str | list[str] | None
        Path to data directory, list of file/dir paths, or None.
    work_dir : str | None
        Explicit work directory path. If None, auto-generates one.
    base_dir : str | None
        Base directory for auto-generated work dirs. Defaults to current directory.
    orchestrator_model : str | None
        The orchestrator's model for provider fallback.
    env_file : str | None
        Path to .env file for checking available provider keys.
    no_sandboxing : bool
        If True, also check os.environ for API keys.

    Returns
    -------
    dict[str, Any]
        Session state including work_dir, config_dir, dpack_name, data_dir,
        status, and model_fallback_messages.

    Raises
    ------
    ValueError
        If data_dir is invalid or work_dir already exists.
    """
    if base_dir is None:
        base_dir = "."

    if work_dir is None:
        dpack_name: str = config.get("name", "analysis")
        prefix: str = _session_dir_prefix(dpack_name)
        seq: int = get_next_sequence_number(base_dir, dpack_name)
        work_dir = str(Path(base_dir) / f"{prefix}{seq:03d}")

    work_path: Path = Path(work_dir).resolve()
    if work_path.exists():
        raise ValueError(f"Work directory already exists: {work_dir}")

    work_path.mkdir(parents=True)
    try:
        (work_path / "_opencode_logs").mkdir()

        # Initialize git repo so OpenCode treats this as a project root.
        # This prevents config traversal to parent directories.
        if not (work_path / ".git").exists():
            subprocess.run(
                ["git", "init"],
                cwd=work_path,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        if data_dir is not None:
            if isinstance(data_dir, list):
                # Multiple paths or single file — check if it's a single directory
                if len(data_dir) == 1 and Path(data_dir[0]).is_dir():
                    copy_data_to_workdir(data_dir[0], str(work_path))
                else:
                    copy_data_paths_to_workdir(data_dir, str(work_path))
            else:
                copy_data_to_workdir(data_dir, str(work_path))

        fallback_messages: list[str] = setup_opencode_config(
            config["config_dir"], str(work_path), orchestrator_model, env_file,
            no_sandboxing,
        )
        copy_hook_scripts(config, str(work_path))
    except Exception:
        # Clean up the work dir we just created so the user can retry
        # without hitting "already exists"
        shutil.rmtree(work_path, ignore_errors=True)
        raise

    data_dir_str: str = ""
    if data_dir is not None:
        if isinstance(data_dir, list):
            data_dir_str = ", ".join(str(Path(p).resolve()) for p in data_dir)
        else:
            data_dir_str = str(Path(data_dir).resolve())

    state: dict[str, Any] = {
        "work_dir": str(work_path),
        "config_dir": config["config_dir"],
        "dpack_name": config["name"],
        "data_dir": data_dir_str,
        "status": "created",
        "model_fallback_messages": fallback_messages,
    }

    save_state(str(work_path), state)

    return state
