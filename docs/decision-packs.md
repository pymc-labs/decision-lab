# decision-packs

A **decision-pack** is a reusable configuration that defines the environment for running opencode. decision-packs let you create specialized setups for different use cases.

## Creating a decision-pack

The easiest way to create a decision-pack is the interactive wizard:

```bash
dlab create-dpack
```

This walks through 8 screens covering name, container setup, features, model, permissions, directory skeletons, skill search, and review.

## Directory Structure

```
my-dpack/
  config.yaml              # Required: decision-pack metadata
  .env.example             # Auto-generated: Required API keys
  .gitignore               # Auto-generated: Excludes .env
  deploy_modal.sh          # Optional: Hook script (if Modal enabled)
  docker/
    Dockerfile             # Required: Base Docker image
    requirements.txt       # Dependencies (or environment.yml / pixi.toml)
    my_lib/                # Optional: Python library package
    modal_app/             # Optional: Modal serverless app
  opencode/
    opencode.json          # Required: Permissions and default agent
    agents/
      orchestrator.md      # Required: Main agent system prompt
      example-worker.md    # Optional: Subagent
    tools/                 # Optional: Custom TypeScript tools
      example-tool.ts
      run-on-modal.ts      # Auto-generated if Modal enabled
    skills/                # Optional: Knowledge files
      dhub-cli/            # Auto-downloaded if Decision Hub enabled
    parallel_agents/       # Optional: Parallel agent configs
      example-worker.yaml
```

## config.yaml

```yaml
# Required fields
name: my-dpack
description: What this decision-pack does
docker_image_name: dlab-my-dpack
default_model: opencode/big-pickle

# Optional fields
requires_data: true           # If false, --data becomes optional (default: true)
requires_prompt: true         # If false, --prompt becomes optional (default: true)
opencode_version: "1.2.10"    # Pin opencode version (default: latest)

# Hook scripts that run inside the container
hooks:
  pre-run: deploy_modal.sh           # Single script
  post-run: [cleanup.sh, report.sh]  # Or a list
```

### Field Reference

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | Yes | — | Unique identifier for the decision-pack |
| `description` | Yes | — | Human-readable description |
| `docker_image_name` | Yes | — | Tag for the Docker image |
| `default_model` | Yes | — | Default LLM model to use |
| `requires_data` | No | `true` | Whether `--data` is required |
| `requires_prompt` | No | `true` | Whether `--prompt` is required |
| `cli_name` | No | same as `name` | Override command name for `dlab install` |
| `opencode_version` | No | `latest` | opencode version to install |
| `hooks.pre-run` | No | — | Scripts to run before opencode |
| `hooks.post-run` | No | — | Scripts to run after opencode |

## opencode/opencode.json

Defines the default agent and permissions. All permissions must be explicitly `allow` or `deny` for automated mode (no interactive prompts).

```json
{
  "default_agent": "orchestrator",
  "permission": {
    "read": "allow",
    "glob": "allow",
    "grep": "allow",
    "edit": "allow",
    "bash": "allow",
    "list": "allow",
    "webfetch": "allow",
    "websearch": "allow",
    "task": "allow",
    "skill": "allow",
    "codesearch": "allow",
    "todoread": "allow",
    "todowrite": "allow",
    "lsp": "deny",
    "question": "deny"
  }
}
```

## Agent System Prompts

Agent prompts live in `opencode/agents/`. The frontmatter controls the agent's tools:

```markdown
---
description: Main orchestrator
mode: primary
tools:
  parallel-agents: true
---

You are an AI assistant. Follow the user's prompt carefully.
```

### Tools Frontmatter

The `tools:` section overrides `opencode.json` permissions per-agent:

| Skeleton Config | Tools Block |
|----------------|-------------|
| Parallel agents enabled | `parallel-agents: true` |
| Subagents only | `read: true`, `edit: true`, `bash: true`, `task: true` |
| Neither | `read: true` (placeholder) |

## Package Managers

The create-dpack wizard supports four package managers:

| Manager | Base Image | Env File | Best For |
|---------|-----------|----------|----------|
| conda | `continuumio/miniconda3:latest` | `environment.yml` | Scientific Python |
| pip | `python:3.11-slim` | `requirements.txt` | General projects |
| uv | `python:3.11-slim` | `requirements.txt` | Fast pip alternative |
| pixi | `debian:bookworm-slim` | `pixi.toml` | Modern conda-forge |

## Environment Variables

### .env.example

Auto-generated based on the selected model's provider. Contains the required API keys:

```bash
# Environment variables for my-dpack
# Copy this file to .env and fill in your keys:
#   cp .env.example .env
OPENCODE_API_KEY=your-key-here
```

If Modal integration is enabled, also includes:

```bash
MODAL_TOKEN_ID=your-key-here
MODAL_TOKEN_SECRET=your-key-here
```

### Auto-detection

If a `.env` file exists in the decision-pack directory, the CLI automatically uses it as the `--env-file` (unless explicitly overridden).

## Hooks

Scripts that run inside the container before or after the agent. Scripts live in the decision-pack root (next to `config.yaml`) and are copied to `_hooks/` in the work directory.

```yaml
hooks:
  pre-run: deploy_modal.sh
  post-run: [cleanup.sh, report.sh]
```

If any hook exits with a non-zero code, the session aborts. Hooks run once per session.

### Example: Modal Deployment

```bash
#!/bin/bash
# deploy_modal.sh
set -e
MODAL_APP="/opt/modal_app/example.py"
if [ -f "$MODAL_APP" ]; then
    echo "Deploying Modal app..."
    modal deploy "$MODAL_APP"
fi
```

### Conda Named Environments in Hooks

If your Dockerfile creates a named conda environment (e.g., `conda env create -n myenv`), hook scripts must activate it explicitly. dlab keeps the container alive with `tail -f /dev/null`, which bypasses the Dockerfile's `SHELL` and `CMD` directives. As a result, `docker exec bash -c "..."` runs in the **base** conda environment.

Add this to the top of your hook script (after `set -e`):

```bash
eval "$(conda shell.bash hook 2> /dev/null)"
conda activate myenv
```

Alternatively, install dependencies directly into the base conda environment (as the MMM decision-pack does) to avoid this entirely.

## Decision Hub Integration

When enabled, the decision-pack includes `dhub-cli` as a container dependency. This allows the agent to search and install skills from hub.decision.ai at runtime:

```bash
# Inside the container, the agent can run:
dhub install pymc-labs/some-skill --agent opencode
```

The `dhub-cli` skill is also pre-downloaded to `opencode/skills/dhub-cli/` so the agent knows how to use the tool.

## Modal Integration

When enabled, the decision-pack includes:

- `docker/modal_app/` with an example serverless function
- `deploy_modal.sh` pre-run hook
- `opencode/tools/run-on-modal.ts` tool for calling Modal functions
- `modal` added to container dependencies
- `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` in `.env.example`

## Installing a decision-pack

Create a wrapper script for easy access:

```bash
dlab install ./my-dpack
# Now run: my-dpack --data ./data --prompt "..."
```

## Environment Variable Forwarding

All environment variables starting with `DLAB_` are automatically forwarded from the host to the Docker container. decision-packs can use these for runtime configuration without framework changes.

For example, the MMM decision-pack uses `DLAB_FIT_MODEL_LOCALLY=1` to switch between Modal cloud fitting and local fitting. The generated modal deploy hook uses `DLAB_RUN_MODAL_TOOL_LOCALLY`.

To use from the command line:

```bash
DLAB_FIT_MODEL_LOCALLY=1 dlab --dpack mmm --data ./data --prompt "..."
```

Or add to your `.env` file:

```bash
DLAB_FIT_MODEL_LOCALLY=1
```

## Best Practices

1. **Keep images focused**: Include only what's needed for the use case
2. **Pin versions**: Use specific package versions for reproducibility
3. **Use hooks for setup**: Deploy services before the agent needs them
4. **Set requires_data / requires_prompt**: Use `requires_data: false` or `requires_prompt: false` for decision-packs that don't need them
5. **Use .env.example**: Document required environment variables
6. **Use `DLAB_*` env vars**: For decision-pack-specific configuration that users can toggle at runtime
