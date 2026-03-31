# Parallel Agents

Parallel agents allow you to run multiple opencode instances simultaneously, then combine their results. This is useful for:

- **Exploration**: Try multiple approaches in parallel
- **Ensemble**: Get diverse perspectives on a problem
- **Divide and conquer**: Split a large task into subtasks

## Overview

```
                    ┌─────────────────┐
                    │  Orchestrator   │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Instance │  │ Instance │  │ Instance │
        │    1     │  │    2     │  │    3     │
        └────┬─────┘  └────┬─────┘  └────┬─────┘
             │             │             │
             ▼             ▼             ▼
        summary.md    summary.md    summary.md
              │             │             │
              └──────────────┼──────────────┘
                             ▼
                    ┌─────────────────┐
                    │  Consolidator   │
                    │  (auto-run if   │
                    │   3+ instances) │
                    └────────┬────────┘
                             │
                             ▼
                 consolidated_summary.md
```

## Creating a Parallel Agent

### Interactive Wizard

```bash
dlab create-parallel-agent ./my-dpack
```

The TUI wizard lets you select an existing agent or create a new one, configure timeout, failure behavior, and edit pre-filled prompt templates.

### Manual YAML

```yaml
# my-dpack/opencode/parallel_agents/modeler.yaml

name: modeler
description: "Run multiple modeling approaches in parallel"
timeout_minutes: 60
failure_behavior: continue

subagent_suffix_prompt: |
  When you complete your task, write a summary.md file with:
  ## Approach
  ## Results
  ## Recommendations

summarizer_prompt: |
  Read all summary.md files from the parallel instances.
  Create a consolidated comparison highlighting key differences,
  agreements, and overall recommendations.

summarizer_model: "anthropic/claude-sonnet-4-5"
```

You also need a corresponding agent `.md` file at `opencode/agents/modeler.md`.

## Configuration Reference

### Required Fields

| Field | Description |
|-------|-------------|
| `name` | Identifier (must match an agent `.md` file) |
| `subagent_suffix_prompt` | Instructions appended to each instance's prompt |
| `summarizer_prompt` | Instructions for the consolidator agent |
| `summarizer_model` | Model for the consolidation step |

### Optional Fields

| Field | Default | Description |
|-------|---------|-------------|
| `description` | — | Human-readable description |
| `timeout_minutes` | 90 | Maximum runtime per instance |
| `failure_behavior` | `continue` | How to handle failures |
| `max_retries` | 2 | Retry count (only if `failure_behavior=retry`) |
| `max_instances` | — | Maximum number of parallel instances |
| `default_model` | — | Default model for instances |
| `instance_models` | — | Per-instance model overrides (list) |

### Failure Behaviors

| Behavior | Description |
|----------|-------------|
| `continue` | Other instances continue if one fails |
| `fail_fast` | Stop all instances on first failure |
| `retry` | Retry failed instances up to `max_retries` times |

## How It Works

1. The orchestrator calls the `parallel-agents` tool with an array of prompts
2. Each instance runs in `parallel/run-{timestamp}/instance-{n}/` with its own copy of the data
3. Instances write `summary.md` with their findings
4. **When 3 or more instances complete**, a consolidator agent reads all summaries and produces `parallel/run-{timestamp}/consolidated_summary.md`

The consolidator does **not** run if fewer than 3 instances complete.

## Consolidator

The consolidator is auto-generated at runtime from the `summarizer_prompt`. You do NOT need to create a separate agent file.

### Permissions

The consolidator has **read-only permissions**:

| Permission | Status |
|------------|--------|
| Read files | Allowed |
| Glob/Grep search | Allowed |
| Edit files | **Denied** |
| Bash commands | **Denied** |
| Spawn subagents | **Denied** |
| Custom tools | **Not available** |

This ensures the consolidator only synthesizes results without modifying instance output.

## Directory Structure

```
session-dir/
  parallel/
    run-{timestamp}/
      instance-1/
        data/           # Copy of session data
        .opencode/      # Agent config
        summary.md      # Instance output
      instance-2/
        ...
      instance-3/
        ...
      consolidator/
        .opencode/      # Read-only config
      consolidated_summary.md
```

## Examples

### Multi-Model Comparison

```yaml
name: model-comparison
timeout_minutes: 60
failure_behavior: continue

subagent_suffix_prompt: |
  Build and evaluate your model. Write summary.md with:
  - Model configuration
  - Performance metrics (R², MAPE, etc.)
  - Key findings

summarizer_prompt: |
  Create a comparison table of all models and their metrics.
  Recommend the best approach for production use.

summarizer_model: "anthropic/claude-sonnet-4-5"
```

### Per-Instance Model Overrides

```yaml
name: exploration
instance_models:
  - "anthropic/claude-sonnet-4-5"
  - "google/gemini-2.5-pro"
  - "deepseek/deepseek-chat"
```

## Analyzing Execution

```bash
# View timeline with Gantt chart
dlab timeline ./analysis-001

# Monitor live
dlab connect ./analysis-001
```

Example Gantt output:

```
main                              |████████████████████████████| 18.1m
modeler-run-123/instance-1        |  ███████████████            | 8.1m
modeler-run-123/instance-2        |  ████████████               | 5.8m
modeler-run-123/instance-3        |  ████████████████████████   | 13.9m
modeler-run-123/consolidator      |                        ████ | 1.3m
```

## Best Practices

1. **Structured output**: Define a clear summary.md format so the consolidator can compare easily
2. **Appropriate timeouts**: Quick analysis 15-30m, model building 60-90m, complex exploration 120m+
3. **Failure handling**: Use `continue` for independent tasks, `fail_fast` for dependencies, `retry` for flaky APIs
4. **3+ instances**: The consolidator only runs with 3+ instances — use at least 3 for automatic comparison

## Known Issues

### Git Init Hack

Each parallel instance runs `git init` to prevent opencode's upward config traversal. This is a workaround — opencode should have a config option to disable parent directory traversal. See `parallel-agents.ts` for the implementation.
