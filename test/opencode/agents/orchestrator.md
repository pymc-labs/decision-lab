---
description: Main orchestrator for test
mode: primary
tools:
  # Tool settings here override the permission rules in opencode.json
  parallel-agents: true
---

You are an AI assistant. Follow the user's prompt carefully.

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
```
