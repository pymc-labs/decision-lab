"""
Configuration loading and validation for decision-pack config directories.
"""

import re
from pathlib import Path
from typing import Any

import yaml


REQUIRED_DIRS: list[str] = ["docker", "opencode"]
REQUIRED_FILES: list[str] = ["config.yaml"]
CONFIG_KEYS: list[str] = ["name", "description", "docker_image_name", "default_model"]


def list_config_issues(config_dir: str) -> list[str]:
    """
    Check a decision-pack directory and return a list of issues found.

    Parameters
    ----------
    config_dir : str
        Path to the decision-pack config directory.

    Returns
    -------
    list[str]
        List of issue descriptions. Empty if valid.
    """
    issues: list[str] = []
    config_path: Path = Path(config_dir)

    if not config_path.exists():
        return [f"Directory does not exist: {config_dir}"]
    if not config_path.is_dir():
        return [f"Path is not a directory: {config_dir}"]

    for required_dir in REQUIRED_DIRS:
        dir_path: Path = config_path / required_dir
        if not dir_path.exists():
            issues.append(f"Missing directory: {required_dir}/")
        elif not dir_path.is_dir():
            issues.append(f"Expected directory but found file: {required_dir}")

    for required_file in REQUIRED_FILES:
        file_path: Path = config_path / required_file
        if not file_path.exists():
            issues.append(f"Missing file: {required_file}")
        elif not file_path.is_file():
            issues.append(f"Expected file but found directory: {required_file}")

    return issues


def validate_config_structure(config_dir: str) -> None:
    """
    Validate that a decision-pack config directory has the required structure.

    Parameters
    ----------
    config_dir : str
        Path to the decision-pack config directory.

    Raises
    ------
    ValueError
        If the directory structure is invalid.
    """
    config_path: Path = Path(config_dir)

    if not config_path.exists():
        raise ValueError(f"Config directory does not exist: {config_dir}")

    if not config_path.is_dir():
        raise ValueError(f"Config path is not a directory: {config_dir}")

    for required_dir in REQUIRED_DIRS:
        dir_path: Path = config_path / required_dir
        if not dir_path.exists():
            raise ValueError(f"Missing required directory: {required_dir}")
        if not dir_path.is_dir():
            raise ValueError(f"Expected directory but found file: {required_dir}")

    for required_file in REQUIRED_FILES:
        file_path: Path = config_path / required_file
        if not file_path.exists():
            raise ValueError(f"Missing required file: {required_file}")
        if not file_path.is_file():
            raise ValueError(f"Expected file but found directory: {required_file}")


def load_config_yaml(config_dir: str) -> dict[str, Any]:
    """
    Load and validate config.yaml from a decision-pack config directory.

    Parameters
    ----------
    config_dir : str
        Path to the decision-pack config directory.

    Returns
    -------
    dict[str, Any]
        The parsed config.yaml contents.

    Raises
    ------
    ValueError
        If config.yaml is invalid or missing required keys.
    """
    config_path: Path = Path(config_dir) / "config.yaml"

    try:
        with open(config_path, "r") as f:
            config: dict[str, Any] = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in config.yaml: {e}")

    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a YAML mapping")

    missing_keys: list[str] = [key for key in CONFIG_KEYS if key not in config]
    if missing_keys:
        raise ValueError(f"config.yaml missing required keys: {missing_keys}")

    return config


def load_dpack_config(config_dir: str) -> dict[str, Any]:
    """
    Load and validate a complete decision-pack configuration.

    Parameters
    ----------
    config_dir : str
        Path to the decision-pack config directory.

    Returns
    -------
    dict[str, Any]
        Complete decision-pack configuration including:
        - config_dir: Absolute path to config directory
        - name: decision-pack name
        - description: decision-pack description
        - docker_image_name: Name for the Docker image
        - default_model: Default LLM model to use
        - opencode_version: Version of opencode to install (optional, defaults to "latest")

    Raises
    ------
    ValueError
        If the configuration is invalid.
    """
    config_path: Path = Path(config_dir).resolve()
    config_dir_str: str = str(config_path)

    validate_config_structure(config_dir_str)
    config: dict[str, Any] = load_config_yaml(config_dir_str)

    config["config_dir"] = config_dir_str

    # Autodetect package_manager from docker/ contents if not specified
    if "package_manager" not in config:
        docker_dir: Path = config_path / "docker"
        if (docker_dir / "environment.yml").exists():
            config["package_manager"] = "conda"
        elif (docker_dir / "pixi.toml").exists():
            config["package_manager"] = "pixi"
        else:
            config["package_manager"] = "pip"

    # Default opencode_version to "latest" if not specified
    if "opencode_version" not in config:
        config["opencode_version"] = "latest"

    # Normalize hooks: string -> list, missing -> empty list
    hooks: dict[str, Any] = config.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
    for key in ("pre-run", "post-run"):
        value: Any = hooks.get(key, [])
        if isinstance(value, str):
            hooks[key] = [value]
        elif isinstance(value, list):
            hooks[key] = value
        else:
            hooks[key] = []
    config["hooks"] = hooks

    return config


def resolve_model_roles(config: dict[str, Any]) -> dict[str, str]:
    """
    Resolve orchestrator, forecaster, and consolidator models from config.

    ``default_model`` is the orchestrator model. Optional ``models.forecaster``
    and ``models.consolidator`` override parallel agent instance and
    consolidator models; each falls back to ``default_model`` when omitted.
    """
    default: str = config["default_model"]
    models: Any = config.get("models", {})
    if not isinstance(models, dict):
        models = {}
    return {
        "orchestrator": default,
        "forecaster": models.get("forecaster", default),
        "consolidator": models.get("consolidator", default),
    }


def upsert_yaml_scalar(
    text: str,
    key: str,
    value: str,
    *,
    insert_after: str | None = None,
    insert_before: str | None = None,
) -> str:
    """Set or insert a top-level YAML scalar key with a quoted value."""
    quoted: str = f'"{value}"'
    pattern: re.Pattern[str] = re.compile(rf"^{re.escape(key)}:\s*.+$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(f"{key}: {quoted}", text, count=1)

    new_line: str = f"{key}: {quoted}\n"
    if insert_before:
        before_pattern: re.Pattern[str] = re.compile(
            rf"^{re.escape(insert_before)}:\s*", re.MULTILINE,
        )
        match: re.Match[str] | None = before_pattern.search(text)
        if match:
            return text[: match.start()] + new_line + text[match.start() :]

    if insert_after:
        after_pattern: re.Pattern[str] = re.compile(
            rf"^{re.escape(insert_after)}:\s*.+\n", re.MULTILINE,
        )
        match = after_pattern.search(text)
        if match:
            return text[: match.end()] + new_line + text[match.end() :]

    return new_line + text


def apply_model_roles_to_opencode(opencode_dir: str, model_roles: dict[str, str]) -> None:
    """
    Inject forecaster and consolidator models into parallel agent YAML configs.

    Writes ``default_model`` and ``summarizer_model`` in each file under
    ``parallel_agents/`` from the resolved model roles in config.yaml.
    """
    parallel_dir: Path = Path(opencode_dir) / "parallel_agents"
    if not parallel_dir.exists():
        return

    for yaml_path in sorted(parallel_dir.glob("*.yaml")):
        text: str = yaml_path.read_text()
        text = upsert_yaml_scalar(
            text, "default_model", model_roles["forecaster"],
            insert_after="failure_behavior",
        )
        if "summarizer_prompt" in text:
            text = upsert_yaml_scalar(
                text, "summarizer_model", model_roles["consolidator"],
                insert_before="summarizer_prompt",
            )
        yaml_path.write_text(text)
