# opencode/ directory layout

This directory contains the OpenCode configuration that runs inside the Docker
container. dlab copies it into the session work directory as `.opencode/`.

## How everything is wired

```
opencode/
├── opencode.json              ← Entry point: sets default_agent to "literary-agent"
├── agents/
│   ├── literary-agent.md      ← Orchestrator (mode: primary). Runs first.
│   │                             Calls popo-poet via "task" tool, then spawns
│   │                             parallel "poet" agents via "parallel-agents" tool.
│   ├── popo-poet.md           ← Subagent. Called by literary-agent via "task".
│   │                             Writes intentionally bad poems.
│   └── poet.md                ← Subagent (mode: subagent). Spawned N times in
│                                 parallel by literary-agent. Each instance gets
│                                 a different style prompt and writes summary.md.
└── parallel_agents/
    └── poet.yaml              ← Parallel agent config for "poet". Defines:
                                  - How many instances (max_instances: 5)
                                  - What each instance must output (subagent_suffix_prompt)
                                  - How to compare results (summarizer_prompt)
                                  - When the consolidator runs (auto, if 3+ instances)
```

## Execution flow

1. dlab starts the container and runs opencode with the user's prompt
2. opencode reads `opencode.json` → starts `literary-agent` (the default_agent)
3. literary-agent calls popo-poet via the `task` tool (single subagent)
4. literary-agent reads popo-poet's result, decides it's bad
5. literary-agent calls `parallel-agents` tool with agent="poet" and N prompts
6. dlab creates `parallel/run-{timestamp}/instance-{1..N}/` directories
7. Each instance gets:
   - A copy of the data (empty in this case)
   - A filtered `.opencode/` with only poet.md (mode changed to "primary")
   - Only the tools listed in poet.md's frontmatter
8. Each instance writes `summary.md` (as required by poet.yaml's subagent_suffix_prompt)
9. If 3+ instances complete, a consolidator agent runs (read-only, auto-generated
   from poet.yaml's summarizer_prompt) and writes `consolidated_summary.md`
10. literary-agent reads the results and writes `final_poem.md`
11. Post-run hook `print_result.sh` prints the final poem

## Agent frontmatter

Each agent .md file has YAML frontmatter that controls:

```yaml
---
description: One-line role description
mode: primary          # "primary" = orchestrator, "subagent" = parallel worker
tools:
  read: true           # Can read files
  edit: true           # Can write/edit files
  bash: false          # Cannot run shell commands
  parallel-agents: true  # Can spawn parallel agents (orchestrator only)
---
```

The `tools:` section overrides opencode.json permissions for this specific agent.
When a subagent is spawned in parallel, its mode is changed from "subagent" to
"primary" in the instance copy, and only the tools listed here are available.

## Parallel agent config (poet.yaml)

The YAML config in `parallel_agents/` defines how the parallel-agents tool
behaves when called with `agent: "poet"`:

- `name`: Must match an agent .md file in `agents/`
- `subagent_suffix_prompt`: Appended to each instance's prompt. Defines what
  output format the consolidator expects (all instances must write summary.md
  with the same structure)
- `summarizer_prompt`: Instructions for the auto-generated consolidator agent.
  The consolidator has read-only access and should compare, not decide.
- `summarizer_model`: Which LLM the consolidator uses
- `timeout_minutes`: Per-instance timeout
- `failure_behavior`: "continue" (others keep going if one fails),
  "fail_fast" (stop all), or "retry" (retry failed ones)

See: docs/parallel-agents.md for full reference
