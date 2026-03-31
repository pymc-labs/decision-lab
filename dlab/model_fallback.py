"""
Model validation and provider fallback for agent configs.

When a decision-pack references model providers whose API keys are not
in the .env file, this module replaces those model strings with the
orchestrator's model so users only need a single API key to get started.

Two-phase design:
1. preflight_check() — runs BEFORE session creation on source dpack files.
   Catches fatal errors (orchestrator key missing, unknown models) early.
2. process_opencode_dir() — runs DURING session setup on work-dir copies.
   Applies fallback replacements for missing provider keys.
"""

import difflib
import os
import re
from pathlib import Path

from dlab.create_dpack import KNOWN_PROVIDER_ENVS, get_model_list, get_provider_env_vars


# Matches provider/model-name patterns (e.g. "anthropic/claude-sonnet-4-5")
# Negative lookahead (?!/) excludes file paths like "opencode/agents/foo.md"
_MODEL_PATTERN: re.Pattern[str] = re.compile(
    r"\b([a-zA-Z0-9_-]+/[a-zA-Z0-9._-]+)\b(?!/)"
)


def parse_env_file(env_file: str | None) -> dict[str, str]:
    """
    Parse a .env file into a key-value dict.

    Parameters
    ----------
    env_file : str | None
        Path to .env file, or None.

    Returns
    -------
    dict[str, str]
        Parsed environment variables. Empty dict if env_file is None
        or file does not exist.
    """
    if not env_file:
        return {}
    path: Path = Path(env_file)
    if not path.exists():
        return {}

    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        env[key.strip()] = value
    return env


def get_available_providers(env_vars: dict[str, str]) -> set[str]:
    """
    Return the set of providers whose required API keys are present.

    Parameters
    ----------
    env_vars : dict[str, str]
        Parsed environment variables.

    Returns
    -------
    set[str]
        Provider names (e.g. {"anthropic", "google"}) with all required
        keys present and non-empty.
    """
    available: set[str] = set()
    for provider, required_keys in KNOWN_PROVIDER_ENVS.items():
        if all(env_vars.get(k) for k in required_keys):
            available.add(provider)
    return available


def _strip_comments(text: str) -> str:
    """Remove comment lines (# ...) from text before scanning for models."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped: str = line.lstrip()
        if not stripped.startswith("#"):
            lines.append(line)
    return "\n".join(lines)


def find_model_strings(text: str) -> list[str]:
    """
    Extract all provider/model-name strings from non-comment text.

    Parameters
    ----------
    text : str
        File content to scan.

    Returns
    -------
    list[str]
        Deduplicated list of model strings found.
    """
    matches: list[str] = _MODEL_PATTERN.findall(_strip_comments(text))
    # Only keep matches whose provider prefix is a known provider
    known_prefixes: set[str] = set(KNOWN_PROVIDER_ENVS.keys())
    models: list[str] = []
    seen: set[str] = set()
    for m in matches:
        provider: str = m.split("/")[0]
        if provider in known_prefixes and m not in seen:
            seen.add(m)
            models.append(m)
    return models


def _collect_models_from_dir(directory: Path) -> list[str]:
    """Scan all .yaml/.yml/.md files in a directory for model strings."""
    all_models: list[str] = []
    config_files: list[Path] = sorted(
        list(directory.rglob("*.yaml"))
        + list(directory.rglob("*.yml"))
        + list(directory.rglob("*.md"))
    )
    for f in config_files:
        all_models.extend(find_model_strings(f.read_text()))
    return list(dict.fromkeys(all_models))  # deduplicate, preserve order


def _format_env_setup_hint(model: str) -> str:
    """Format a hint showing which env var to set for a model's provider."""
    env_vars: list[str] = get_provider_env_vars(model)
    if env_vars:
        var_str: str = ", ".join(env_vars)
        return f"Set {var_str} in your .env file"
    return "Check provider documentation for required API key"


def preflight_check(
    orchestrator_model: str,
    config_dir: str,
    env_file: str | None,
    no_sandboxing: bool = False,
) -> tuple[list[str], list[str]]:
    """
    Validate models before session creation. Runs on source dpack files.

    Returns errors (fatal, abort run) and warnings (informational, continue).

    Parameters
    ----------
    orchestrator_model : str
        The orchestrator's model (from --model or config default_model).
    config_dir : str
        Path to the decision-pack config directory.
    env_file : str | None
        Path to .env file.
    no_sandboxing : bool
        If True, also check os.environ for API keys (local mode inherits
        the shell environment).

    Returns
    -------
    tuple[list[str], list[str]]
        (errors, warnings). Errors are fatal and should abort the run.
        Warnings are informational (e.g. fallback will be applied).
    """
    errors: list[str] = []
    warnings: list[str] = []

    env_vars: dict[str, str] = {}
    if no_sandboxing:
        env_vars.update(os.environ)
    env_vars.update(parse_env_file(env_file))
    available: set[str] = get_available_providers(env_vars)

    # Validate orchestrator model name
    all_known: list[str] = get_model_list()
    known: set[str] = set(all_known)
    if orchestrator_model not in known:
        suggestions: list[str] = sorted(difflib.get_close_matches(
            orchestrator_model, all_known, n=3, cutoff=0.6,
        ))
        if suggestions:
            alt: str = ", ".join(suggestions)
            errors.append(
                f"Unknown model {orchestrator_model} — did you mean: {alt}?"
            )
        else:
            errors.append(f"Unknown model {orchestrator_model}")
        return errors, warnings

    # Check orchestrator model's provider key
    orchestrator_provider: str = orchestrator_model.split("/")[0]
    if orchestrator_provider in KNOWN_PROVIDER_ENVS and orchestrator_provider not in available:
        env_hint: str = _format_env_setup_hint(orchestrator_model)
        errors.append(
            f"Orchestrator model {orchestrator_model} requires an API key "
            f"that is not set. {env_hint}"
        )
        return errors, warnings

    # Scan source opencode/ dir for model strings
    opencode_dir: Path = Path(config_dir) / "opencode"
    if not opencode_dir.exists():
        return errors, warnings

    all_models: list[str] = _collect_models_from_dir(opencode_dir)

    # Validate agent model names exist in known list
    for model in all_models:
        if model not in known:
            suggestions: list[str] = sorted(difflib.get_close_matches(
                model, all_known, n=3, cutoff=0.6,
            ))
            if suggestions:
                alt: str = ", ".join(suggestions)
                errors.append(
                    f"Unknown model {model} — did you mean: {alt}?"
                )
            else:
                errors.append(f"Unknown model {model}")

    # Check which agent models will need fallback
    unavailable: set[str] = set(KNOWN_PROVIDER_ENVS.keys()) - available
    models_needing_fallback: list[str] = []
    for model in all_models:
        provider: str = model.split("/")[0]
        if provider in unavailable and model != orchestrator_model:
            models_needing_fallback.append(model)

    if models_needing_fallback:
        seen: set[str] = set()
        for model in models_needing_fallback:
            if model in seen:
                continue
            seen.add(model)
            env_hint = _format_env_setup_hint(model)
            warnings.append(
                f"{model} -> {orchestrator_model} ({env_hint})"
            )

    return errors, warnings


def apply_model_fallback(
    text: str,
    orchestrator_model: str,
    unavailable_providers: set[str],
) -> tuple[str, list[str]]:
    """
    Replace model strings whose providers are unavailable.

    Parameters
    ----------
    text : str
        File content.
    orchestrator_model : str
        Model to substitute in place of unavailable ones.
    unavailable_providers : set[str]
        Provider names whose API keys are missing.

    Returns
    -------
    tuple[str, list[str]]
        (modified_text, list of replacement descriptions).
    """
    if not unavailable_providers:
        return text, []

    replacements: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        model_str: str = match.group(1)
        provider: str = model_str.split("/")[0]
        if provider in unavailable_providers:
            replacements.append(f"{model_str} -> {orchestrator_model}")
            return orchestrator_model
        return model_str

    # Only replace on non-comment lines
    new_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("#"):
            new_lines.append(line)
        else:
            new_lines.append(_MODEL_PATTERN.sub(_replace, line))

    return "".join(new_lines), replacements


def process_opencode_dir(
    opencode_dir: str,
    orchestrator_model: str,
    env_file: str | None,
    no_sandboxing: bool = False,
) -> list[str]:
    """
    Apply model fallback to all config files in .opencode/ (work-dir copies).

    Assumes preflight_check() has already validated the orchestrator model.
    Only applies replacements — no validation here.

    Parameters
    ----------
    opencode_dir : str
        Path to the .opencode/ directory in the work dir.
    orchestrator_model : str
        The orchestrator's model (fallback target).
    env_file : str | None
        Path to .env file.
    no_sandboxing : bool
        If True, also check os.environ for API keys.

    Returns
    -------
    list[str]
        Replacement messages (e.g. "parallel_agents/poet.yaml: google/gemini-2.0-flash -> ...").
    """
    opencode_path: Path = Path(opencode_dir)
    if not opencode_path.exists():
        return []

    env_vars: dict[str, str] = {}
    if no_sandboxing:
        env_vars.update(os.environ)
    env_vars.update(parse_env_file(env_file))
    available: set[str] = get_available_providers(env_vars)

    orchestrator_provider: str = orchestrator_model.split("/")[0]
    if orchestrator_provider in KNOWN_PROVIDER_ENVS and orchestrator_provider not in available:
        return []

    unavailable: set[str] = set(KNOWN_PROVIDER_ENVS.keys()) - available
    if not unavailable:
        return []

    messages: list[str] = []
    config_files: list[Path] = sorted(
        list(opencode_path.rglob("*.yaml"))
        + list(opencode_path.rglob("*.yml"))
        + list(opencode_path.rglob("*.md"))
    )

    for f in config_files:
        text: str = f.read_text()
        new_text, replacements = apply_model_fallback(
            text, orchestrator_model, unavailable,
        )
        if replacements:
            f.write_text(new_text)
            rel: str = str(f.relative_to(opencode_path))
            for r in replacements:
                messages.append(f"{rel}: {r}")

    return messages
