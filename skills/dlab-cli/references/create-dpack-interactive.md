
# Create decision-pack Interactively

You are helping a human create a **decision-pack** — a reusable configuration directory that defines a Docker-sandboxed environment for running AI agents via `dlab`. Your job is to interview the human, understand what they need, and then call `generate_dpack()` with the right config.

## The Interview

Ask these questions **conversationally**, not as a rigid checklist. Group related questions together. Skip anything the human already answered. Infer sensible defaults from context (e.g., if they mention "PyMC" you know they need conda and scientific Python packages).

### 1. What's this decision-pack for?

Get the name and purpose. From this you can often infer most of the config.

- **Name**: alphanumeric with hyphens/underscores (e.g., `data-analysis`, `web_scraper`)
- **Description**: one sentence about what the agent will do

### 2. What tools/packages does the agent need?

This determines the package manager and base image.

- If they mention scientific Python (PyMC, JAX, NumPy, scipy) → suggest **conda**
- If they mention a simple Python project → suggest **pip**
- If they mention fast installs or modern tooling → suggest **uv**
- If they mention conda-forge with lockfiles → suggest **pixi**

The package manager determines the base image automatically:

| Manager | Base Image | Env File |
|---------|-----------|----------|
| conda | continuumio/miniconda3:latest | environment.yml |
| pip | python:3.11-slim | requirements.txt |
| uv | python:3.11-slim | requirements.txt |
| pixi | debian:bookworm-slim | pixi.toml |

### 3. Which model should the agent use?

Default is `opencode/big-pickle`. If they have a preference (Claude, GPT, Gemini, etc.), use the `provider/model-name` format. Common choices:

- `anthropic/claude-sonnet-4-5` or `anthropic/claude-opus-4-6`
- `openai/gpt-5` or `openai/gpt-5.1-codex`
- `google/gemini-2.5-pro`
- `deepseek/deepseek-chat`

### 4. CLI name (optional — only ask if relevant)

If they plan to install the decision-pack with `dlab install`, ask if they want a shorter command name. For example, a decision-pack named `marketing-mix-model` might want to install as `mmm`. Set `cli_name` in the config. If not specified, the decision-pack name is used.

### 5. Does the agent need data files to work?

If yes (default), the user must pass `--data` when running. If the agent only needs a prompt (e.g., a poetry generator), set `requires_data: false`.

### 5. Optional features — only ask if relevant

- **Decision Hub integration** (default: on) — lets the agent search and install skills from hub.decision.ai at runtime. Usually leave this on unless they have a reason to disable it.
- **Python library** — creates a `{name}_lib/` package in `docker/`. Ask only if they mention needing custom Python modules.
- **Modal integration** — for serverless cloud compute (MCMC sampling, heavy ML). Ask only if they mention cloud execution, Modal, or heavy compute. Local execution is the default (`DLAB_RUN_MODAL_TOOL_LOCALLY=1`); Modal is opt-in via `.env` (`DLAB_RUN_MODAL_TOOL_LOCALLY=0` + Modal tokens).
- **Parallel agents** — running multiple agent instances simultaneously. Ask if they mention comparing approaches, ensemble methods, or divide-and-conquer.

### 6. Permissions — usually skip

The defaults are sensible (allow bash, edit, read, web access, etc.; deny lsp). Only ask about permissions if the human mentions security concerns or wants to restrict the agent.

## Generating the decision-pack

Once you have enough information, call `generate_dpack()`. Here's the template:

```python
from pathlib import Path
from dlab.create_dpack import generate_dpack

config = {
    "name": "<name>",
    "description": "<description>",
    "default_model": "<model>",
    "package_manager": "<pip|conda|uv|pixi>",
    "requires_data": True,  # or False
    "dhub_integration": True,  # Decision Hub
    "skeletons": {
        "skills": True,
        "tools": True,
        "subagents": <True if they need subagents>,
        "parallel_agents": <True if they need parallel execution>,
    },
    # Only include if explicitly requested:
    # "python_lib": True,
    # "python_lib_name": "<name>_lib",
    # "modal_integration": True,
}

dpack_path = generate_dpack(Path("."), config, on_progress=print)
print(f"decision-pack created at: {dpack_path}")
```

You don't need to set `docker_image_name`, `base_image`, `agent_name`, `agent_description`, or `permissions` — the defaults are derived from the name and package manager.

## After Creation

Tell the human:

1. **What was created** — list the key files (config.yaml, Dockerfile, orchestrator.md, etc.)
2. **What to edit** — the main thing they'll want to customize is `opencode/agents/orchestrator.md` (the agent's system prompt)
3. **How to run** — show the command:
   ```bash
   cp <dpack>/.env.example <dpack>/.env
   # Fill in API keys in .env
   dlab --dpack <dpack> --data ./your-data --prompt "Your task"
   ```
4. **How to add packages** — point them to the right file (requirements.txt, environment.yml, or pixi.toml) in `docker/`

## Key Things to Remember

- The decision-pack is created in a temp directory first and moved atomically on success — no partial directories on failure
- `generate_dpack()` validates the name and raises `ValueError` if invalid or if the directory already exists (unless `overwrite_existing=True`)
- The `.env.example` is auto-generated based on the model's provider (e.g., `ANTHROPIC_API_KEY` for Anthropic models)
- If Modal is enabled, tools must also be enabled (it auto-enables them)
- If parallel_agents is enabled, subagents is auto-enabled too
- The agent frontmatter tools section is auto-generated based on skeleton choices:
  - parallel_agents → only `parallel-agents: true`
  - subagents only → `read: true, edit: true, bash: true, task: true`
  - neither → just `read: true` as placeholder

## Example Conversation

**Human**: "I want to create a decision-pack for marketing mix modeling with PyMC"

**You**: Great — I'll set up a decision-pack for MMM with PyMC. A few quick questions:

1. What should I call it? Something like `mmm` or `marketing-mix`?
2. Do you need Modal for cloud MCMC sampling, or will local fitting be enough?
3. Should the agent be able to run multiple modeling approaches in parallel?

**Human**: "Call it mmm. Yes to Modal and parallel agents."

**You**: Perfect. I'll create `mmm` with:
- conda (best for PyMC/scientific Python)
- Modal integration for cloud sampling
- Parallel agents for comparing approaches
- Decision Hub skills enabled

Let me generate it...

```python
from pathlib import Path
from dlab.create_dpack import generate_dpack

dpack_path = generate_dpack(Path("."), {
    "name": "mmm",
    "description": "Marketing Mix Modeling with PyMC-Marketing",
    "default_model": "anthropic/claude-opus-4-5",
    "package_manager": "conda",
    "requires_data": True,
    "dhub_integration": True,
    "modal_integration": True,
    "skeletons": {
        "skills": True,
        "tools": True,
        "subagents": True,
        "parallel_agents": True,
    },
}, on_progress=print)
```

Created! Here's what to do next:
1. Edit `mmm/opencode/agents/orchestrator.md` — write the agent's system prompt
2. Add your Python packages to `mmm/docker/environment.yml`
3. Copy `.env.example` to `.env` and add your API keys
4. Run: `dlab --dpack mmm --data ./your-data --prompt "Build an MMM"`
