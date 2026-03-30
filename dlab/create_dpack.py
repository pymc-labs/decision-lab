"""
decision-pack scaffolding logic for dlab.

Generates a valid decision-pack directory structure from a configuration dict.
The TUI wizard (CreateDpackApp) is separate and calls generate_dpack().
"""

import io
import json
import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

from dhub.cli.config import build_headers, get_api_url, get_optional_token, raise_for_status
import httpx
import yaml


def _load_bundled_models() -> dict[str, Any]:
    """Load the bundled models.dev fixture from package data."""
    data_text: str = files("dlab.data").joinpath("models.json").read_text()
    return json.loads(data_text)


_BUNDLED: dict[str, Any] = _load_bundled_models()
KNOWN_MODELS: list[str] = _BUNDLED["models"]
KNOWN_PROVIDER_ENVS: dict[str, list[str]] = _BUNDLED["provider_envs"]

CACHE_DIR: Path = Path.home() / ".cache" / "dlab"
MODEL_CACHE_FILE: Path = CACHE_DIR / "models.json"


def fetch_models_from_api() -> dict[str, Any]:
    """
    Fetch model list and provider env vars from models.dev API.

    Returns
    -------
    dict[str, Any]
        Dict with "models" (list[str]) and "provider_envs" (dict[str, list[str]]).
    """
    resp: httpx.Response = httpx.get("https://models.dev/api.json", timeout=10)
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()

    models: list[str] = []
    provider_envs: dict[str, list[str]] = {}

    for provider, pdata in data.items():
        if not isinstance(pdata, dict):
            continue
        env_vars: list[str] = pdata.get("env", [])
        if env_vars:
            provider_envs[provider] = env_vars
        provider_models: dict[str, Any] = pdata.get("models", {})
        for model_id, mdata in provider_models.items():
            if not isinstance(mdata, dict):
                continue
            # Skip cross-provider references (e.g. cloudflare listing
            # "anthropic/claude-sonnet-4-5" — those are pass-through IDs)
            if "/" in model_id:
                continue
            full_id: str = f"{provider}/{model_id}"
            if mdata.get("tool_call"):
                models.append(full_id)

    return {"models": sorted(set(models)), "provider_envs": provider_envs}


def load_cached_models() -> dict[str, Any]:
    """Load cached model list and provider envs from disk."""
    if MODEL_CACHE_FILE.exists():
        try:
            return json.loads(MODEL_CACHE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"models": [], "provider_envs": {}}


def save_model_cache(data: dict[str, Any]) -> None:
    """Save model list and provider envs to disk cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_CACHE_FILE.write_text(json.dumps(data))


def _model_sort_key(model_id: str) -> tuple[int, str]:
    """Sort key: (provider_rank, model_id) for popularity-based ordering."""
    provider: str = model_id.split("/")[0] if "/" in model_id else model_id
    rank: int = PROVIDER_RANK.get(provider, _DEFAULT_RANK)
    return (rank, model_id)


def get_model_list() -> list[str]:
    """
    Return merged model list from KNOWN_MODELS + cache, sorted by popularity.

    Returns
    -------
    list[str]
        Deduplicated model IDs, sorted by provider popularity then alphabetically.
    """
    cached: dict[str, Any] = load_cached_models()
    all_models: set[str] = set(KNOWN_MODELS) | set(cached.get("models", []))
    return sorted(all_models, key=_model_sort_key)


def get_provider_env_vars(model_id: str) -> list[str]:
    """
    Get required env vars for a model's provider.

    Parameters
    ----------
    model_id : str
        Model ID in provider/name format.

    Returns
    -------
    list[str]
        Environment variable names needed.
    """
    provider: str = model_id.split("/")[0] if "/" in model_id else model_id
    # Check cache first
    cached: dict[str, Any] = load_cached_models()
    cached_envs: dict[str, list[str]] = cached.get("provider_envs", {})
    if provider in cached_envs:
        return cached_envs[provider]
    return KNOWN_PROVIDER_ENVS.get(provider, [])


# Provider popularity ranking (lower = more popular)
PROVIDER_RANK: dict[str, int] = {
    "opencode": 0,
    "anthropic": 1,
    "openai": 2,
    "google": 3,
    "deepseek": 4,
    "mistralai": 5,
    "meta": 6,
    "xai": 7,
    "groq": 8,
    "openrouter": 9,
}
_DEFAULT_RANK: int = 50

KNOWN_BASE_IMAGES: list[str] = [
    "python:3.11-slim",
    "python:3.12-slim",
    "python:3.13-slim",
    "ubuntu:22.04",
    "ubuntu:24.04",
    "debian:bookworm-slim",
    "node:20-slim",
]

NAME_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


# ---------------------------------------------------------------------------
# OpenCode permission definitions
# ---------------------------------------------------------------------------

# Permissions the user can toggle in the wizard.
# Each entry: (key, label, description, default_value)
# default_value is "allow" or "deny".
# Ordered by importance — high-impact first, internal/basic last.
# The wizard renders a visual separator at HIGH_IMPACT_PERMISSION_COUNT.
HIGH_IMPACT_PERMISSION_COUNT: int = 6

CONFIGURABLE_PERMISSIONS: list[tuple[str, str, str, str]] = [
    # --- High-impact (affect agent capabilities) ---
    ("webfetch", "Fetch URLs",
     "Fetch content from URLs. Useful for downloading data, reading documentation, "
     "or accessing APIs.",
     "allow"),
    ("websearch", "Web search",
     "Search the web. Useful for finding documentation, examples, or troubleshooting errors.",
     "allow"),
    ("bash", "Shell commands",
     "Run bash commands. Needed for pip install, running scripts, data processing. "
     "Disable to restrict the agent to file operations only.",
     "allow"),
    ("edit", "Edit files",
     "Create and modify files in /workspace. Disable for read-only analysis agents.",
     "allow"),
    ("external_directory", "External directory access",
     "Read files outside /workspace (e.g. Python site-packages, system configs). "
     "Useful for exploring installed libraries programmatically.",
     "allow"),
    ("task", "Spawn subagent tasks",
     "Let the agent spawn subagent tasks. Required for multi-agent workflows.",
     "allow"),
    # --- Internal/basic (rarely need to change) ---
    ("skill", "Use skills",
     "Let the agent use opencode skills (knowledge files). "
     "Disable if the agent should rely only on its system prompt.",
     "allow"),
    ("codesearch", "Code search",
     "Semantic code search across the codebase.",
     "allow"),
    ("lsp", "Language server",
     "Query language servers for code intelligence (definitions, references, hover). "
     "Requires configured LSP servers in the container.",
     "deny"),
    ("todoread", "Read todos",
     "Read the internal task/todo list. Used by the agent to track its own progress.",
     "allow"),
    ("todowrite", "Write todos",
     "Write to the internal task/todo list. Used by the agent to plan multi-step work.",
     "allow"),
]

# Permissions always set to the same value (not shown in wizard).
HARDCODED_PERMISSIONS: dict[str, str] = {
    "read": "allow",
    "glob": "allow",
    "grep": "allow",
    "list": "allow",
    "question": "deny",   # meaningless in automated mode
    # TODO: decide on doom_loop default. OpenCode defaults to "ask" (auto-approved
    # in run mode). Setting "deny" would stop agents stuck in loops but might block
    # legitimate retries. Leaving it out for now to use OpenCode's default.
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_dpack_name(name: str) -> str | None:
    """
    Validate a decision-pack name.

    Parameters
    ----------
    name : str
        Proposed decision-pack name.

    Returns
    -------
    str | None
        Error message if invalid, None if valid.
    """
    if not name:
        return "Name is required"
    if not NAME_PATTERN.match(name):
        return "Name must be alphanumeric (hyphens and underscores allowed, cannot start with - or _)"
    return None


def filter_models(query: str, models: list[str] | None = None) -> list[str]:
    """
    Filter models by a case-insensitive substring match.

    Parameters
    ----------
    query : str
        Search query.
    models : list[str] | None
        Model list to filter. Defaults to KNOWN_MODELS.

    Returns
    -------
    list[str]
        Matching model names.
    """
    source: list[str] = models if models is not None else KNOWN_MODELS
    if not query:
        return sorted(source, key=_model_sort_key)
    q: str = query.lower()

    provider_starts: list[str] = []
    provider_contains: list[str] = []
    name_contains: list[str] = []

    for m in source:
        provider: str = m.split("/")[0].lower() if "/" in m else m.lower()
        if provider.startswith(q):
            provider_starts.append(m)
        elif q in provider:
            provider_contains.append(m)
        elif q in m.lower():
            name_contains.append(m)

    return (
        sorted(provider_starts, key=_model_sort_key)
        + sorted(provider_contains, key=_model_sort_key)
        + sorted(name_contains, key=_model_sort_key)
    )


# ---------------------------------------------------------------------------
# Decision Hub API helpers
# ---------------------------------------------------------------------------

def _dhub_headers() -> dict[str, str]:
    """Build Decision Hub API headers using dhub-cli config."""
    return build_headers(get_optional_token())


def search_skills(query: str, page_size: int = 20) -> list[dict[str, Any]]:
    """
    Search the Decision Hub for skills.

    Parameters
    ----------
    query : str
        Search query.
    page_size : int
        Maximum results to return.

    Returns
    -------
    list[dict[str, Any]]
        List of skill summaries with keys: org_slug, skill_name,
        description, safety_rating, download_count, category.
    """
    resp: httpx.Response = httpx.get(
        f"{get_api_url()}/v1/skills",
        params={"search": query, "page_size": page_size},
        headers=_dhub_headers(),
        timeout=15,
    )
    raise_for_status(resp)
    data: Any = resp.json()
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    return []


def ask_skills(query: str) -> list[dict[str, Any]]:
    """
    Natural-language skill search via Decision Hub /v1/ask endpoint.

    Parameters
    ----------
    query : str
        Natural language query.

    Returns
    -------
    list[dict[str, Any]]
        List of skill references with keys: org_slug, skill_name,
        description, reason.
    """
    resp: httpx.Response = httpx.get(
        f"{get_api_url()}/v1/ask",
        params={"q": query},
        headers=_dhub_headers(),
        timeout=30,
    )
    raise_for_status(resp)
    data: Any = resp.json()
    if isinstance(data, dict) and "skills" in data:
        return data["skills"]
    if isinstance(data, list):
        return data
    return []


def download_skill(org: str, name: str, dest: Path) -> Path:
    """
    Download a skill from Decision Hub and extract it.

    Parameters
    ----------
    org : str
        Organization slug.
    name : str
        Skill name.
    dest : Path
        Parent directory to extract into (e.g. opencode/skills/).

    Returns
    -------
    Path
        Path to the extracted skill directory.
    """
    resp: httpx.Response = httpx.get(
        f"{get_api_url()}/v1/skills/{org}/{name}/download",
        headers=_dhub_headers(),
        timeout=30,
        follow_redirects=True,
    )
    raise_for_status(resp)

    skill_dir: Path = dest / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    content_type: str = resp.headers.get("content-type", "")
    if "zip" in content_type or resp.content[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(skill_dir)
    else:
        # Assume it's a single markdown file
        (skill_dir / "SKILL.md").write_bytes(resp.content)

    return skill_dir


# ---------------------------------------------------------------------------
# File content generators
# ---------------------------------------------------------------------------

def _build_config_yaml(config: dict[str, Any]) -> str:
    """Build config.yaml content."""
    data: dict[str, Any] = {
        "name": config["name"],
        "description": config["description"],
        "docker_image_name": config["docker_image_name"],
        "default_model": config["default_model"],
        "requires_data": config.get("requires_data", True),
        "requires_prompt": config.get("requires_prompt", True),
    }
    cli_name: str = config.get("cli_name", "")
    if cli_name and cli_name != config["name"]:
        data["cli_name"] = cli_name
    content: str = yaml.dump(data, default_flow_style=False, sort_keys=False)

    if config.get("modal_integration"):
        content += (
            "\n# Scripts listed here run inside the container before/after the agent's run.\n"
            "hooks:\n"
            "  pre-run: deploy_modal.sh\n"
            "  # post-run: cleanup.sh\n"
        )
    else:
        content += (
            "\n# Scripts listed here run inside the container before/after the agent's run.\n"
            "# hooks:\n"
            "#   pre-run: setup.sh\n"
            "#   post-run: cleanup.sh\n"
        )
    return content


PACKAGE_MANAGER_BASE_IMAGES: dict[str, str] = {
    "conda": "continuumio/miniconda3:latest",
    "pip": "python:3.11-slim",
    "uv": "python:3.11-slim",
    "pixi": "debian:bookworm-slim",
}


def _build_dockerfile(config: dict[str, Any]) -> str:
    """Build Dockerfile content based on package manager choice."""
    pkg_mgr: str = config.get("package_manager", "pip")
    python_lib: bool = config.get("python_lib", False)
    python_lib_name: str = config.get("python_lib_name", "")
    modal_integration: bool = config.get("modal_integration", False)
    base_image: str = config.get("base_image", PACKAGE_MANAGER_BASE_IMAGES.get(pkg_mgr, "python:3.11-slim"))

    lines: list[str] = [f"FROM {base_image}", "", "WORKDIR /workspace", ""]

    if pkg_mgr == "conda":
        lines.extend([
            "COPY environment.yml /tmp/environment.yml",
            "RUN conda env update -n base -f /tmp/environment.yml && \\",
            "    conda clean -afy",
            "",
        ])
    elif pkg_mgr == "uv":
        lines.extend([
            "COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv",
            "COPY requirements.txt /tmp/requirements.txt",
            "RUN uv pip install --system --no-cache -r /tmp/requirements.txt",
            "",
        ])
    elif pkg_mgr == "pixi":
        lines.extend([
            "RUN apt-get update && apt-get install -y curl && \\",
            "    curl -fsSL https://pixi.sh/install.sh | bash && \\",
            "    rm -rf /var/lib/apt/lists/*",
            'ENV PATH="/root/.pixi/bin:$PATH"',
            "",
            "# Install pixi packages to /opt/pixi (not /workspace, which gets volume-mounted)",
            "COPY pixi.toml /opt/pixi/pixi.toml",
            "RUN cd /opt/pixi && pixi install",
            'ENV PATH="/opt/pixi/.pixi/envs/default/bin:$PATH"',
            "",
        ])
    else:  # pip
        lines.extend([
            "COPY requirements.txt /tmp/requirements.txt",
            "RUN pip install --no-cache-dir -r /tmp/requirements.txt",
            "",
        ])

    # Optional: python lib and modal app
    pythonpath_parts: list[str] = []
    if python_lib and python_lib_name:
        lines.append(f"COPY {python_lib_name}/ /opt/{python_lib_name}/")
        pythonpath_parts.append("/opt")
    if modal_integration:
        lines.append("COPY modal_app/ /opt/modal_app/")
        if "/opt" not in pythonpath_parts:
            pythonpath_parts.append("/opt")
    if pythonpath_parts:
        lines.append(f'ENV PYTHONPATH="{":".join(pythonpath_parts)}"')
    if python_lib or modal_integration:
        lines.append("")

    lines.append('CMD ["/bin/bash"]')
    lines.append("")

    return "\n".join(lines)


def _build_env_file(config: dict[str, Any]) -> tuple[str, str]:
    """Build the environment/dependency file for the chosen package manager.

    Returns
    -------
    tuple[str, str]
        (filename, content) — e.g. ("environment.yml", "...") or
        ("requirements.txt", "...").
    """
    pkg_mgr: str = config.get("package_manager", "pip")
    docker_image_name: str = config.get("docker_image_name", f"dlab-{config.get('name', 'dpack')}")
    modal: bool = config.get("modal_integration", False)
    dhub: bool = config.get("dhub_integration", False)

    # Collect pip-only packages
    pip_pkgs: list[str] = []
    if dhub:
        pip_pkgs.append("dhub-cli")
    if modal:
        pip_pkgs.append("modal")

    if pkg_mgr == "conda":
        pip_section: str = ""
        if pip_pkgs:
            pip_lines: str = "\n".join(f"    - {p}" for p in pip_pkgs)
            pip_section = f"  - pip:\n{pip_lines}\n"
        content: str = (
            "# Installed into base conda env (no named env needed)\n"
            "channels:\n"
            "  - conda-forge\n"
            "dependencies:\n"
            "  - python=3.11\n"
            "  # Add your conda packages here\n"
            "  # - numpy\n"
            "  # - pandas\n"
            f"{pip_section}"
        )
        return ("environment.yml", content)

    if pkg_mgr == "pixi":
        pypi_section: str = ""
        if pip_pkgs:
            pypi_lines: str = "\n".join(f'{p} = "*"' for p in pip_pkgs)
            pypi_section = f"\n[pypi-dependencies]\n{pypi_lines}\n"
        import platform
        machine: str = platform.machine()
        if machine == "aarch64" or machine == "arm64":
            pixi_platform: str = "linux-aarch64"
        else:
            pixi_platform = "linux-64"

        content = (
            "[project]\n"
            f'name = "{docker_image_name}"\n'
            'channels = ["conda-forge"]\n'
            f'platforms = ["{pixi_platform}"]\n'
            "\n"
            "[dependencies]\n"
            'python = "3.11.*"\n'
            "# Add your packages here\n"
            '# numpy = "*"\n'
            '# pandas = "*"\n'
            f"{pypi_section}"
        )
        return ("pixi.toml", content)

    # pip or uv
    pip_lines_str: str = "\n".join(pip_pkgs) + "\n" if pip_pkgs else ""
    content = (
        f"{pip_lines_str}"
        "# Add your pip packages here\n"
        "# numpy\n"
        "# pandas\n"
    )
    return ("requirements.txt", content)


def _build_opencode_json(config: dict[str, Any]) -> str:
    """Build opencode.json content.

    Writes ALL permissions explicitly as "allow" or "deny" to avoid
    any "ask" defaults that would block automated (opencode run) mode.
    """
    user_perms: dict[str, str] = config.get("permissions", {})

    # Build the full permission block
    perm: dict[str, Any] = dict(HARDCODED_PERMISSIONS)

    # Add configurable permissions — use user value or default
    for key, _label, _desc, default in CONFIGURABLE_PERMISSIONS:
        perm[key] = user_perms.get(key, default)

    data: dict[str, Any] = {
        "default_agent": config["agent_name"],
        "permission": perm,
    }

    return json.dumps(data, indent=2) + "\n"


def _build_agent_md(config: dict[str, Any]) -> str:
    """Build the main agent .md file."""
    skeletons: dict[str, bool] = config.get("skeletons", {})
    parallel: bool = skeletons.get("parallel_agents", False)
    subagents: bool = skeletons.get("subagents", False)

    tools_block: str = "  # Tool settings here override the permission rules in opencode.json\n"
    if parallel:
        tools_block += "  parallel-agents: true"
    elif subagents:
        tools_block += "  read: true\n  edit: true\n  bash: true\n  task: true"
    else:
        tools_block += "  read: true"

    prompt: str = "You are an AI assistant. Follow the user's prompt carefully."

    if parallel:
        prompt += """

## Spawning Parallel Agents

Use the `parallel-agents` tool to run multiple instances of a subagent in parallel.
Each instance gets its own isolated working directory with a copy of your data.

Example — spawn 3 instances of the "example-worker" agent:

```json
{
  "agent": "example-worker",
  "prompts": [
    "Approach A: ...",
    "Approach B: ...",
    "Approach C: ..."
  ]
}
```

Each instance writes a `summary.md` with its findings. When all instances complete,
a consolidator agent automatically reads every `summary.md` and produces a
consolidated comparison in `parallel/consolidated_summary.md`.

You can also override models per instance:

```json
{
  "agent": "example-worker",
  "prompts": ["...", "..."],
  "models": ["anthropic/claude-sonnet-4-5", "google/gemini-2.5-pro"]
}
```"""
    elif subagents:
        prompt += """

## Using Subagents

Use the `task` tool to delegate work to the "example-worker" subagent.
Rename and customize `opencode/agents/example-worker.md` for your use case."""

    description: str = config.get("agent_description", f"Main orchestrator for {config['name']}")

    return f"""---
description: {description}
mode: primary
tools:
{tools_block}
---

{prompt}
"""


EXAMPLE_WORKER_MD: str = """---
description: Example subagent
mode: subagent
tools:
  # Tool settings here override the permission rules in opencode.json
  read: true
  edit: true
  bash: true
  parallel-agents: false
---

You are a worker agent. Complete the task described in the prompt.
"""

EXAMPLE_WORKER_YAML: str = """name: example-worker
description: "Run multiple worker instances in parallel"
timeout_minutes: 60
failure_behavior: continue

max_instances: 3
default_model: "anthropic/claude-sonnet-4-5"

subagent_suffix_prompt: |
  When you complete your task, write summary.md with:
  ## Approach
  ## Results
  ## Recommendations

summarizer_prompt: |
  Read all summary.md files from the parallel instances.
  Create a consolidated comparison of the different approaches.
  Present facts only — the orchestrator will make the final decision.

summarizer_model: "anthropic/claude-sonnet-4-5"
"""

def _build_deploy_modal_sh() -> str:
    """Build the deploy_modal.sh hook script.

    Returns
    -------
    str
        Shell script content.
    """
    lines: list[str] = [
        "#!/bin/bash",
        "# Pre-run hook: deploy Modal app for cloud compute",
        "set -e",
        "",
        "# Default to local execution — skip Modal deploy",
        'if [ "${DLAB_RUN_MODAL_TOOL_LOCALLY:-1}" = "1" ]; then',
        '    echo "Local mode (DLAB_RUN_MODAL_TOOL_LOCALLY=1). Skipping Modal deployment."',
        "    exit 0",
        "fi",
        "",
        "# Check Modal credentials",
        'if [ -z "$MODAL_TOKEN_ID" ] || [ -z "$MODAL_TOKEN_SECRET" ]; then',
        '    echo "Warning: Modal tokens not set. Skipping Modal deployment."',
        "    exit 0",
        "fi",
        "",
    ]
    lines.extend([
        'MODAL_APP="/opt/modal_app/example.py"',
        "",
        'if [ -f "$MODAL_APP" ]; then',
        '    echo "Deploying Modal app..."',
        '    modal deploy "$MODAL_APP"',
        '    echo "Modal app deployed."',
        "else",
        '    echo "Warning: Modal app not found at $MODAL_APP, skipping deploy"',
        "fi",
        "",
    ])
    return "\n".join(lines)

def _build_modal_example(dpack_name: str, package_manager: str) -> str:
    """Build the Modal example.py content.

    Parameters
    ----------
    dpack_name : str
        decision-pack name (used for the Modal app name).
    package_manager : str
        Package manager choice — "conda" uses micromamba image with
        .micromamba_install(); everything else uses debian_slim with
        .pip_install().
    """
    if package_manager == "conda":
        image_block = (
            '# Conda packages — use micromamba for properly linked BLAS, MKL, etc.\n'
            'CONDA_PACKAGES = [\n'
            '    "python=3.11",\n'
            '    # Add your conda packages here\n'
            '    # "numpy",\n'
            '    # "pandas",\n'
            ']\n'
            '\n'
            '# Packages that need pip (not on conda-forge or need specific versions)\n'
            'PIP_PACKAGES = [\n'
            '    # "some-pip-only-package",\n'
            ']\n'
            '\n'
            'image = (\n'
            '    modal.Image.micromamba(python_version="3.11")\n'
            '    .run_commands(f"echo \'modal_app hash: {_modal_app_hash}\'")'
            '  # Cache buster\n'
            '    .micromamba_install(*CONDA_PACKAGES, channels=["conda-forge"])\n'
            '    .pip_install(*PIP_PACKAGES)\n'
            ')'
        )
    else:
        image_block = (
            'image = (\n'
            '    modal.Image.debian_slim(python_version="3.11")\n'
            '    .run_commands(f"echo \'modal_app hash: {_modal_app_hash}\'")'
            '  # Cache buster\n'
            '    .pip_install(\n'
            '        # Add your packages here\n'
            '        "numpy",\n'
            '    )\n'
            ')'
        )

    return f'''"""
Example Modal app for serverless cloud execution.

Deploy with: modal deploy example.py

Cache Busting
-------------
Modal caches images by their definition. If you change only the Python code
(not the package list), Modal won't rebuild the image. The self-hash trick
below forces a rebuild whenever this file changes.

Package Versions
----------------
If you use cloudpickle to send objects between the Docker container and Modal,
package versions here MUST match the Dockerfile. Otherwise unpickling will fail.
"""

import hashlib
from pathlib import Path

import modal

# Hash this file to force image rebuild when code changes.
# Without this, Modal uses a cached image even when the code is different.
_modal_app_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]

{image_block}

app = modal.App("{dpack_name}-compute")


@app.function(image=image, timeout=3600)
def run_compute(data: dict) -> dict:
    """Example compute function. Replace with your own logic."""
    return {{"status": "done", "input_keys": list(data.keys())}}
'''

RUN_ON_MODAL_TS: str = """import { tool } from "@opencode-ai/plugin"

export default tool({
  description: `Run a computation on Modal cloud.

Calls the run_compute() function deployed in docker/modal_app/example.py.
Pass a JSON string with the data to send to the Modal function.

The Modal app must be deployed first (happens automatically via the
pre-run hook deploy_modal.sh).`,

  args: {
    data: tool.schema.string().describe("JSON string with input data for the Modal function"),
  },

  async execute(args) {
    const pyCode = `
import json, modal
f = modal.Function.from_name("<APP_NAME>", "run_compute")
data = json.loads('${args.data.replace(/'/g, "\\'")}')
result = f.remote(data)
print(json.dumps(result))
`.trim()
    const result = await Bun.$`python -c "${pyCode}" 2>&1`.nothrow()
    const output = result.text().trim()
    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\\n${output}`
    }
    return output
  },
})
"""

EXAMPLE_TOOL_TS: str = """import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "An example custom tool. Replace with your own logic.",
  args: {
    input: tool.schema.string().describe("Input to process"),
  },
  async run({ input }) {
    return `Processed: ${input}`
  },
})
"""

EXAMPLE_SKILL_MD: str = """---
name: Example Skill
description: An example skill. Replace with domain-specific knowledge.
---

# Example Skill

Add domain-specific knowledge, best practices, API references,
or other context that helps the agent do its job better.
"""


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_dpack(
    output_dir: Path,
    config: dict[str, Any],
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """
    Generate a complete decision-pack directory structure.

    Creates in a temp directory first, then moves to final location on success.

    Parameters
    ----------
    output_dir : Path
        Parent directory where the decision-pack directory will be created.
    config : dict[str, Any]
        Configuration dict. See source for supported keys.
    on_progress : Callable[[str], None] | None
        Optional callback for progress messages.

    Returns
    -------
    Path
        Path to the created decision-pack directory.

    Raises
    ------
    ValueError
        If name is invalid or directory already exists.
    """
    name: str = config["name"]
    error: str | None = validate_dpack_name(name)
    if error:
        raise ValueError(error)

    # Apply defaults
    config.setdefault("description", f"dlab decision-pack: {name}")
    config.setdefault("docker_image_name", f"dlab-{name}")
    config.setdefault("package_manager", "pip")
    pkg_mgr: str = config["package_manager"]
    config.setdefault("base_image", PACKAGE_MANAGER_BASE_IMAGES.get(pkg_mgr, "python:3.11-slim"))
    config.setdefault("default_model", "opencode/big-pickle")
    config.setdefault("requires_data", True)
    config.setdefault("requires_prompt", True)
    config.setdefault("cli_name", "")
    config.setdefault("agent_name", "orchestrator")
    config.setdefault("agent_description", f"Main orchestrator for {name}")
    config.setdefault("permissions", {})
    config.setdefault("skeletons", {})
    config.setdefault("selected_skills", [])
    config.setdefault("python_lib", False)
    config.setdefault("python_lib_name", "")
    config.setdefault("modal_integration", False)
    config.setdefault("dhub_integration", False)

    skeletons: dict[str, bool] = config["skeletons"]

    def _progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    final_dir: Path = output_dir / name
    overwrite: bool = config.get("overwrite_existing", False)
    if final_dir.exists() and not overwrite:
        raise ValueError(f"Directory already exists: {final_dir}")

    # Build in a temp directory, move to final location on success
    with tempfile.TemporaryDirectory(prefix=f"dlab-{name}-") as tmp:
        dpack_dir: Path = Path(tmp) / name

        _progress("Creating directory structure...")
        dpack_dir.mkdir(parents=True)
        (dpack_dir / "docker").mkdir()
        opencode_dir: Path = dpack_dir / "opencode"
        opencode_dir.mkdir()
        agents_dir: Path = opencode_dir / "agents"
        agents_dir.mkdir()

        _progress("Writing config.yaml...")
        (dpack_dir / "config.yaml").write_text(_build_config_yaml(config))

        _progress("Writing Dockerfile...")
        (dpack_dir / "docker" / "Dockerfile").write_text(_build_dockerfile(config))

        env_filename: str
        env_content: str
        env_filename, env_content = _build_env_file(config)
        (dpack_dir / "docker" / env_filename).write_text(env_content)

        if config.get("python_lib") and config.get("python_lib_name"):
            lib_name: str = config["python_lib_name"]
            lib_dir: Path = dpack_dir / "docker" / lib_name
            lib_dir.mkdir()
            (lib_dir / "__init__.py").write_text(
                f'"""{lib_name} — custom Python library for {name}."""\n'
            )

        if config.get("modal_integration"):
            _progress("Setting up Modal integration...")
            modal_dir: Path = dpack_dir / "docker" / "modal_app"
            modal_dir.mkdir()
            (modal_dir / "__init__.py").write_text("")
            (modal_dir / "example.py").write_text(
                _build_modal_example(name, config["package_manager"])
            )
            (dpack_dir / "deploy_modal.sh").write_text(
                _build_deploy_modal_sh()
            )

        _progress("Writing opencode config...")
        (opencode_dir / "opencode.json").write_text(_build_opencode_json(config))

        agent_name: str = config["agent_name"]
        (agents_dir / f"{agent_name}.md").write_text(_build_agent_md(config))

        has_subagents: bool = skeletons.get("subagents", False) or skeletons.get("parallel_agents", False)
        if has_subagents:
            (agents_dir / "example-worker.md").write_text(EXAMPLE_WORKER_MD)

        if skeletons.get("parallel_agents", False):
            pa_dir: Path = opencode_dir / "parallel_agents"
            pa_dir.mkdir()
            (pa_dir / "example-worker.yaml").write_text(EXAMPLE_WORKER_YAML)

        if skeletons.get("tools", False):
            _progress("Creating tool templates...")
            tools_dir: Path = opencode_dir / "tools"
            tools_dir.mkdir()
            (tools_dir / "example-tool.ts").write_text(EXAMPLE_TOOL_TS)

            if config.get("modal_integration"):
                modal_app_name: str = f"{name}-compute"
                (tools_dir / "run-on-modal.ts").write_text(
                    RUN_ON_MODAL_TS.replace("<APP_NAME>", modal_app_name)
                )

        if skeletons.get("skills", False):
            skills_dir: Path = opencode_dir / "skills"
            skills_dir.mkdir(exist_ok=True)
            example_skill_dir: Path = skills_dir / "example-skill"
            example_skill_dir.mkdir()
            (example_skill_dir / "SKILL.md").write_text(EXAMPLE_SKILL_MD)

        # Decision Hub integration: download dhub-cli skill
        if config.get("dhub_integration"):
            _progress("Downloading dhub-cli skill...")
            skills_dir = opencode_dir / "skills"
            skills_dir.mkdir(exist_ok=True)
            download_skill("pymc-labs", "dhub-cli", skills_dir)

        # User-selected skills from Decision Hub
        selected_skills: list[dict[str, Any]] = config["selected_skills"]
        if selected_skills:
            _progress("Downloading skills from Decision Hub...")
            skills_dir = opencode_dir / "skills"
            skills_dir.mkdir(exist_ok=True)
            for skill in selected_skills:
                org: str = skill["org_slug"]
                sname: str = skill["skill_name"]
                download_skill(org, sname, skills_dir)

        # .env.example
        env_vars: list[str] = list(get_provider_env_vars(config["default_model"]))
        if config.get("modal_integration"):
            env_vars.extend(["MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"])
        if env_vars:
            env_lines: list[str] = [
                f"# Environment variables for {name}",
                "# Copy this file to .env and fill in your keys:",
                "#   cp .env.example .env",
                "",
            ]
            for var in env_vars:
                env_lines.append(f"{var}=your-key-here")
            env_lines.append("")
            (dpack_dir / ".env.example").write_text("\n".join(env_lines))

        (dpack_dir / ".gitignore").write_text(".env\n*.env\n!.env.example\n")

        # Move to final location
        _progress("Finalizing...")
        if final_dir.exists() and overwrite:
            shutil.rmtree(final_dir)
        try:
            dpack_dir.rename(final_dir)
        except OSError:
            shutil.copytree(dpack_dir, final_dir)

    return final_dir
