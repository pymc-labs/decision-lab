---
name: Analyze dlab session runs
description: Navigate and analyze completed dlab session directories. Use when pointed at a work directory to understand what happened during a run — explore logs, outputs, parallel agent results, and the skills/prompts that shaped the analysis.
---

# Analyzing dlab Session Runs

This skill tells you how to navigate a completed dlab session directory, understand what the agents did, and evaluate the quality of the results.

## Session directory layout

A session work directory has this structure:

```
work-dir/
├── state.json                         # Session metadata
├── .opencode/                         # Agent configs used in this session
│   ├── agents/                        # All agent .md system prompts
│   ├── skills/                        # Domain knowledge files
│   ├── tools/                         # Custom tools (TypeScript)
│   └── opencode.json                  # Permissions
├── _opencode_logs/                    # NDJSON execution logs
│   ├── main.log                       # Orchestrator log
│   └── <agent>-parallel-run-<ts>/     # Parallel run logs
│       ├── instance-1.log
│       ├── instance-2.log
│       └── consolidator.log
├── data/                              # Input data (copy from --data)
├── parallel/                          # Parallel agent outputs
│   └── run-<timestamp>/
│       ├── instance-1/
│       │   ├── data/                  # Copy of session data
│       │   ├── summary.md             # Instance results
│       │   └── [other outputs]
│       ├── instance-N/
│       └── consolidated_summary.md    # Consolidator output (if >= 3 instances)
└── [orchestrator outputs]             # Reports, models, analysis files
```

## Where to start

### 1. Read the agent prompts first

Before looking at outputs, read `.opencode/agents/` to understand what the agents were instructed to do. The orchestrator prompt (usually `orchestrator.md`, the one with `mode: primary`) tells you the intended workflow. Subagent prompts tell you what each parallel worker was supposed to produce.

Also read any skills in `.opencode/skills/` — these contain the domain knowledge the agents had access to. Understanding the skills gives you the same context the agents had.

### 2. Read the final reports

The orchestrator typically writes:
- `report.md` — business-facing findings and recommendations
- `technical_report.md` — methodology, all approaches tried, diagnostics

These are the main outputs. Read them to understand what the agents concluded.

### 3. Read state.json

```json
{
  "work_dir": "/path/to/session",
  "config_dir": "/path/to/decision-pack",
  "dpack_name": "mmm-agent-oc",
  "data_dir": "/path/to/original/data",
  "status": "created"
}
```

This tells you which decision-pack was used and where the original data came from.

## Understanding the logs

Logs are in `_opencode_logs/` as NDJSON (one JSON object per line).

### Log files

| File | What it contains |
|------|-----------------|
| `main.log` | The orchestrator's full execution |
| `<agent>-parallel-run-<ts>/instance-N.log` | Each parallel instance |
| `<agent>-parallel-run-<ts>/consolidator.log` | The consolidator's comparison |

### Event types

Each line is a JSON object with a `type` field:

**`step_start`** — Agent begins a thinking step.

**`step_finish`** — Agent completes a thinking step. Contains cost and token usage:
```json
{
  "type": "step_finish",
  "timestamp": 1773610334360,
  "part": {
    "reason": "tool-calls",
    "cost": 0.0888,
    "tokens": {
      "total": 22804,
      "input": 2,
      "output": 300,
      "cache": { "read": 0, "write": 22502 }
    }
  }
}
```
The `reason` field tells you why the step ended: `"stop"` (done), `"tool-calls"` (waiting on tools), `"max-tokens"` (hit limit), `"error"` (failed).

**`text`** — Agent's text output (reasoning, explanations):
```json
{
  "type": "text",
  "timestamp": 1773610336139,
  "part": {
    "text": "Let me start by exploring the data..."
  }
}
```

**`tool_use`** — A tool call. The `part.tool` field identifies which tool, `part.state.input` has the parameters, `part.state.output` has the result:
```json
{
  "type": "tool_use",
  "timestamp": 1773610334289,
  "part": {
    "tool": "bash",
    "state": {
      "status": "completed",
      "input": { "command": "python prepare_data.py" },
      "output": "Processing complete...",
      "time": { "start": 1773610334289, "end": 1773610340000 }
    }
  }
}
```

Common tools: `bash`, `read`, `write`, `edit`, `parallel-agents`, `task`, plus any custom tools from `.opencode/tools/`.

**`error`** — Something crashed.

### Timestamps

All timestamps are **Unix milliseconds**. Convert: `datetime.fromtimestamp(ts / 1000)`.

### Checking if a log completed successfully

The last `step_finish` event should have `"reason": "stop"`. If the last reason is `"error"` or the log just ends mid-step, the agent crashed or was interrupted.

## Navigating parallel runs

### Finding what was tried

The orchestrator calls the `parallel-agents` tool. In `main.log`, look for `tool_use` events where `part.tool` is `"parallel-agents"`. The input contains:
- `agent`: which agent was parallelized
- `prompts`: the prompt array (one per instance — this tells you what each instance was asked to do)

The output lists exit codes and summary file paths for each instance.

### Reading instance results

Each instance writes `summary.md` in its directory:
```
parallel/run-<ts>/instance-N/summary.md
```

The consolidator (if it ran) writes:
```
parallel/run-<ts>/consolidated_summary.md
```

Read the consolidated summary first for a comparison view, then dive into individual instance summaries for detail.

### Instance isolation

Each instance has its own `.opencode/` with filtered permissions and a copy of the data. The instance's `.opencode/agents/` contains only the subagent's `.md` file, with its `mode` changed from `subagent` to `primary`. This means the instance ran as a standalone agent with only the tools and skills declared in its frontmatter.

## What to look for when analyzing a run

### Did the orchestrator follow its workflow?

Read the orchestrator prompt in `.opencode/agents/`, then trace the `main.log` to see if each step was executed. Look for:
- Data exploration (early `bash` and `read` tool calls)
- Parallel agent spawning (`parallel-agents` tool calls)
- Result evaluation (reads of `summary.md` and `consolidated_summary.md`)
- Retry rounds (multiple `parallel-agents` calls for the same agent type)
- Report writing (`write` tool calls for `report.md`, `technical_report.md`)

### Did subagents produce useful output?

Read each instance's `summary.md`. Check:
- Are all required sections present (as defined by the `subagent_suffix_prompt` in the parallel agent YAML)?
- Did the instance report failure honestly, or did it fabricate results?
- Are uncertainty estimates included?
- Is the diagnosis thorough when things failed?

### Cost and duration

Sum `cost` from all `step_finish` events across all log files to get total API cost. The difference between the first and last timestamp gives wall-clock duration.

You can also use the CLI tools:
```bash
dlab timeline <work-dir>    # Shows Gantt chart with timing and cost
dlab connect <work-dir>     # TUI browser for logs and artifacts
```

### Did the agent know when to stop?

This is the most important quality check. If the data didn't support inference, did the orchestrator:
- Stop trying after the configured round limit?
- Write a report explaining why recommendations can't be made?
- Recommend experiments to collect better data?

Or did it push through and make unsupported recommendations with caveats?

## Useful patterns for exploring a session

### Quick overview
1. `state.json` — what decision-pack, what data
2. `report.md` / `technical_report.md` — what the agents concluded
3. `_opencode_logs/main.log` — skim `text` events for the orchestrator's reasoning

### Deep dive into a parallel run
1. Read the `parallel-agents` tool call in `main.log` to see what prompts were sent
2. Read `parallel/run-<ts>/consolidated_summary.md` for the comparison
3. Read individual `instance-N/summary.md` files for detail
4. Check instance logs for errors or unexpected behavior

### Understanding agent behavior
1. Read `.opencode/agents/orchestrator.md` (or whichever is `mode: primary`)
2. Read `.opencode/skills/` to understand domain knowledge available
3. Trace `main.log` event by event to see how the agent applied its instructions

### Checking for problems
1. Grep logs for `"status": "failed"` to find tool failures
2. Grep for `"reason": "error"` in `step_finish` events
3. Look for `parallel-agents` calls with non-zero exit codes in the output
4. Check if any instance summaries are missing (instance crashed before writing)
