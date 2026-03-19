---
name: Create decision-pack Programmatically
description: How to create a dlab decision-pack directory using generate_dpack() from Python code
---

# Creating a decision-pack Programmatically

Reference: `dlab/create_dpack.py`

## What Is a decision-pack

A decision-pack is a directory that defines everything needed to run an agent in a Docker container:

```
my-dpack/
  config.yaml              # Name, model, hooks
  .env.example             # Required API keys
  .gitignore               # Excludes .env
  docker/
    Dockerfile             # Container setup
    requirements.txt       # Dependencies (or environment.yml / pixi.toml)
    modal_app/             # (optional) Modal serverless compute
  opencode/
    opencode.json          # Permissions and default agent
    agents/
      orchestrator.md      # Main agent system prompt
      example-worker.md    # (optional) Subagent
    tools/                 # (optional) Custom TypeScript tools
    skills/                # (optional) Knowledge files
    parallel_agents/       # (optional) Parallel agent configs
```

## generate_dpack()

```python
from pathlib import Path
from dlab.create_dpack import generate_dpack

dpack_path = generate_dpack(
    output_dir=Path("."),
    config={
        # Required
        "name": "my-dpack",

        # Optional (shown with defaults)
        "description": "dlab decision-pack: my-dpack",
        "docker_image_name": "dlab-my-dpack",
        "default_model": "opencode/big-pickle",
        "requires_data": True,
        "requires_prompt": True,
        "cli_name": "",                 # Override command name for install (default: name)
        "package_manager": "pip",       # pip | conda | uv | pixi
        "base_image": "python:3.11-slim",
        "agent_name": "orchestrator",
        "agent_description": "Main orchestrator for my-dpack",

        # Skeletons — which directories to scaffold
        "skeletons": {
            "skills": True,             # opencode/skills/ with example
            "tools": True,              # opencode/tools/ with example-tool.ts
            "subagents": True,          # opencode/agents/example-worker.md
            "parallel_agents": True,    # opencode/parallel_agents/ + parallel tool
        },

        # Permissions — written to opencode.json
        "permissions": {
            "bash": "allow",
            "edit": "allow",
            "webfetch": "allow",
            "websearch": "allow",
            "external_directory": "allow",
            "task": "allow",
            "skill": "allow",
            "codesearch": "allow",
            "lsp": "deny",
            "todoread": "allow",
            "todowrite": "allow",
        },

        # Optional features
        "python_lib": False,
        "python_lib_name": "",          # e.g. "my_dpack_lib"
        "modal_integration": False,
        "selected_skills": [],          # List of {"org_slug": "...", "skill_name": "..."}

        # Overwrite existing directory
        "overwrite_existing": False,
    },
    on_progress=print,  # Optional callback for progress messages
)
```

## Config Keys Detail

### config.yaml

Generated with these keys:
- `name`, `description`, `docker_image_name`, `default_model`, `requires_data`, `requires_prompt`
- `hooks` section: active `pre-run: deploy_modal.sh` when modal enabled, commented template otherwise

### Package Managers

| Manager | Base Image | Env File | Notes |
|---------|-----------|----------|-------|
| `pip` | `python:3.11-slim` | `requirements.txt` | Simplest |
| `conda` | `continuumio/miniconda3:latest` | `environment.yml` | Scientific Python |
| `uv` | `python:3.11-slim` | `requirements.txt` | Fast pip replacement |
| `pixi` | `debian:bookworm-slim` | `pixi.toml` | Modern conda-forge |

When `modal_integration=True`, `modal` is automatically added to the env file.

### Agent .md Frontmatter (tools section)

The tools section in `orchestrator.md` depends on skeleton selections:

| Skeletons | Tools Block |
|-----------|-------------|
| `parallel_agents=True` (with or without subagents) | `parallel-agents: true` only |
| `subagents=True` only | `read: true`, `edit: true`, `bash: true`, `task: true` |
| Neither | `read: true` (placeholder) |

### Permissions

Defined in `CONFIGURABLE_PERMISSIONS` (list of tuples). First 6 are high-impact:
`webfetch`, `websearch`, `bash`, `edit`, `external_directory`, `task`

Remaining are internal: `skill`, `codesearch`, `lsp` (default deny), `todoread`, `todowrite`

Hardcoded (always set): `read`, `glob`, `grep`, `list` = allow; `question` = deny

### Modal Integration

When `modal_integration=True`, generates:
- `docker/modal_app/__init__.py` + `example.py` with hash-based cache busting
- `deploy_modal.sh` pre-run hook (respects `DLAB_RUN_MODAL_TOOL_LOCALLY` env var — skips deploy when set to `1`)
- `opencode/tools/run-on-modal.ts` (if tools skeleton enabled) — uses `modal.Function.from_name("{name}-compute", "run_compute")`
- `modal` added to env file
- `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET` in `.env.example`

The generated `deploy_modal.sh` hook checks `DLAB_RUN_MODAL_TOOL_LOCALLY` (default: `1` = local). Set to `0` in the `.env` file to enable Modal cloud execution. The hook also checks for Modal tokens and skips deployment if they're missing. decision-packs can rename this variable to something domain-specific (e.g., the MMM dpack uses `DLAB_FIT_MODEL_LOCALLY`).

**Note:** All environment variables starting with `DLAB_` are automatically forwarded from the host to the Docker container by the dlab CLI. decision-packs can define their own `DLAB_*` variables for configuration without any framework changes.

### .env.example

Auto-generated from the selected model's provider. Uses `get_provider_env_vars(model_id)` which checks:
1. Cached provider env vars from models.dev API
2. Fallback `KNOWN_PROVIDER_ENVS` dict (anthropic, openai, opencode, google, deepseek, etc.)

### Skills from Decision Hub

Pass `selected_skills` as a list of dicts with `org_slug` and `skill_name`. These are downloaded via the Decision Hub API and extracted into `opencode/skills/`.

## Creation Process

1. Validates decision-pack name (alphanumeric, hyphens, underscores)
2. Creates everything in a temp directory (`tempfile.TemporaryDirectory`)
3. On success: atomically moves to final location (with overwrite support)
4. On failure: temp dir is auto-cleaned

## Helper Functions

```python
from dlab.create_dpack import (
    validate_dpack_name,    # Returns error string or None
    filter_models,           # Case-insensitive substring filter
    get_model_list,          # KNOWN_MODELS + cached API models
    get_provider_env_vars,   # Env vars needed for a model's provider
    fetch_models_from_api,   # Fetch from models.dev (network call)
    ask_skills,              # Natural-language skill search via Decision Hub
)
```
