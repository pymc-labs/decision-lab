---
name: Create data science agents
description: Design agent system prompts (.md files) and parallel-agent configs for data science decision-packs. Use when creating orchestrator, subagent, or parallel agent architectures for analytical workflows.
---

# Creating Agent System Prompts for Data Science

This skill covers how to write agent `.md` files and parallel-agent YAML configs for decision-packs that do data science work.

## Agent file format

Agent system prompts live in `opencode/agents/<name>.md` inside the decision-pack. Each is a markdown file with YAML frontmatter.

### Frontmatter

```yaml
---
description: One-line role description
mode: primary        # primary (orchestrator) or subagent (parallel worker)
tools:
  read: true
  edit: true
  bash: true
  parallel-agents: true    # only for orchestrator
  my-custom-tool: true     # custom tools from opencode/tools/
skills:
  - skill-name             # skills from opencode/skills/
---
```

- `mode: primary` — the main agent that coordinates the workflow. Only one per decision-pack.
- `mode: subagent` — a worker agent spawned by the orchestrator via `parallel-agents` tool.
- Tools listed here override the global `opencode.json` permissions for this agent.
- Skills reference directories under `opencode/skills/` that contain domain knowledge.

## When to use parallel agents

Parallelize when the task has multiple valid approaches and you want to explore them:

- **Different modeling strategies**: Different priors, model structures, or hyperparameters on the same data
- **Different data preparations**: Different feature engineering, column selection, or cleaning strategies
- **Different analytical lenses**: Agents focus on different aspects of the same dataset
- **Model diversity**: Run the same task with different LLMs to get diverse perspectives

Do NOT parallelize when steps are strictly sequential, the task is simple enough for one agent, or there is only one correct approach.

## Core principles for data science agent prompts

These come from building and benchmarking the MMM agent system against vanilla coding agents. They are the difference between agents that produce useful analysis and agents that produce confident garbage.

### 1. The goal is understanding, not a fitted model

A running model that fit something is not the goal. The goal is understanding the data by means of mathematical modeling. When modeling approaches fail, that is a valuable insight. Agents must treat non-convergence, conflicting results, and degenerate problems as evidence, not as errors to hide or work around.

Build this into every agent prompt: non-convergence is evidence about what doesn't work for this data. A model that refuses to fit is telling you something about the problem.

### 2. Transparency about what failed and why

Agents must always be transparent about what they tried, what failed, and why. This is part of the scientific process. Every attempt, every failure mode, every diagnostic should be documented. The orchestrator needs this information to make good decisions about whether to retry, simplify, or stop.

A subagent that fails and writes a thorough diagnosis is more valuable than one that hacks its way to a "successful" fit by cutting corners.

### 3. Never fabricate, mock, or fix parameter values

Agents must NEVER:
- Fabricate data or results to fill gaps
- Use mock or placeholder values for model parameters
- Fix parameters to convenient round numbers without explanation
- Report metrics they didn't actually compute
- Silently reduce model complexity to force convergence without disclosing it

If a parameter can't be estimated, say so. If a metric can't be computed, say so. Fabricated results are worse than no results.

### 4. Never put concrete numerical values in prompts

Agent prompts are templates. NEVER include hard-coded numerical values for parameters, thresholds, or example data. Use placeholder syntax: `<VALUE>`, `<COLUMN_NAME>`, `<N_INSTANCES>`. If you need to show a code pattern, use placeholders for all values the agent should derive from the data.

Keep examples minimal and structural. Show the shape of the code, not specific numbers. The agent should derive all values from the data and domain knowledge, not copy from the prompt.

### 5. Know when to stop

Every orchestrator prompt must include explicit criteria for when to stop trying and report that inference is not supported. This is the hardest part to get right, and the most important. Common stopping conditions:

- All models fail to converge after N rounds
- Converged models give conflicting recommendations (results are sensitive to arbitrary choices)
- Prior sensitivity dominates (different reasonable priors give completely different answers, meaning the data has no say)
- Too few observations to support the model complexity
- The simplest possible model still fails

When the agent stops, it should:
- Explain what was tried and what failed
- Identify the root cause (data limitation, model misspecification, identification problem)
- Recommend specific experiments or data collection to resolve the issue
- State clearly what CAN and what CANNOT be concluded

Adding caveats to bad recommendations does not fix them. "We recommend X, with the caveat that we're uncertain" is wrong when X and not-X are equally supported by the data.

### 6. Report uncertainty, not point estimates

Agents should report confidence/credible intervals, not point estimates. "Channel X ROAS: 2.12 [1.74, 2.51]" is useful. "Channel X ROAS: 2.12" is not. When uncertainty is high, say so explicitly and explain what it means for decision-making.

## System prompt structure

A data science agent prompt should have these sections:

1. **Role and personality** — who the agent is and how it approaches work (methodical, transparent, honest about failures)
2. **Task** — what this agent does in the workflow, as a numbered list
3. **Critical rules** — non-negotiable constraints that prevent the most common failures. This is the most important section. Include library-specific rules (which imports are deprecated, what internal scaling the library does, what NOT to transform)
4. **Working directory rules** — parallel agents run in isolated directories; they must use relative paths and never traverse up with `../`
5. **Workflow phases** — step-by-step process with clear inputs and outputs per phase
6. **Output requirements** — exact structure of `summary.md` so the consolidator can compare across instances. Include what to write when things succeed AND when they fail

## Orchestrator prompt pattern

The orchestrator coordinates the workflow. Key elements:

- Spawns parallel agents with the `parallel-agents` tool
- Reviews consolidated results and makes go/no-go decisions based on objective criteria (not vibes)
- Implements a retry protocol with a hard round limit
- Detects conflicts across parallel results (e.g., do different approaches agree on the direction of effect?)
- Writes both a business-facing report and a technical report
- Has explicit "when to stop" criteria and a template for the "we cannot make recommendations" report

The orchestrator should NOT specify implementation details that the subagent should decide (e.g., sampling parameters, random seeds). It specifies what to explore, not how.

## Subagent prompt pattern

Subagents do focused work. Key elements:

- Receive a specific task from the orchestrator
- Execute ONE strategy per run (don't autonomously simplify and retry; the orchestrator coordinates retries)
- Write structured `summary.md` with identical sections across all instances
- Report failures with thorough diagnosis, not just "it didn't work"
- All file operations use relative paths within the working directory (never `../` or absolute paths)
- Read data from `data/` (a copy placed in their instance directory)
- Write all outputs to `.` or subdirectories (e.g., `./outputs/`, `./analysis_output/`)

## How parallel agents work at runtime

Understanding the directory structure is critical for writing correct agent prompts.

### Session directory layout

When the orchestrator spawns parallel agents, dlab creates this structure:

```
work-dir/                              # The session root
├── .opencode/                         # Orchestrator config (full permissions)
│   ├── agents/                        # ALL agent .md files
│   ├── skills/                        # ALL skills
│   ├── tools/                         # ALL custom tools
│   └── opencode.json                  # Full permissions
├── _opencode_logs/                    # JSON logs
│   ├── main.log                       # Orchestrator log
│   └── <agent>-parallel-run-<ts>/     # One dir per parallel run
│       ├── instance-1.log
│       ├── instance-2.log
│       └── consolidator.log
├── data/                              # Session data (from --data)
├── parallel/                          # Created dynamically by parallel-agents tool
│   └── run-<timestamp>/              # One dir per invocation
│       ├── instance-1/                # Isolated instance
│       │   ├── .opencode/             # FILTERED config (see below)
│       │   ├── data/                  # COPY of session data
│       │   ├── summary.md             # Instance output
│       │   └── [other outputs]
│       ├── instance-2/
│       │   └── [same structure]
│       ├── instance-N/
│       │   └── [same structure]
│       └── consolidated_summary.md    # Written by consolidator (if >= 3 instances)
├── report.md                          # Orchestrator output
└── technical_report.md
```

### Instance isolation

Each instance is fully isolated:

- **Separate data copy**: The entire `data/` directory is copied into each instance. Instances cannot see each other's files.
- **Filtered .opencode/**: Each instance gets only the tools, skills, and permissions declared in its agent frontmatter. The `parallel-agents` tool is always removed (instances cannot spawn their own subagents).
- **Mode promotion**: The agent's `mode` is changed from `subagent` to `primary` in the instance copy, since it runs as the sole agent in its OpenCode session.
- **Relative paths only**: Because instances run in `parallel/run-<ts>/instance-N/`, any use of `../` or absolute paths breaks isolation. Agent prompts must enforce relative paths.

### What the orchestrator sees after parallel runs

After all instances complete, the orchestrator can read:
- `parallel/run-<ts>/instance-N/summary.md` — each instance's structured output
- `parallel/run-<ts>/consolidated_summary.md` — the consolidator's comparison (if 3+ instances ran)
- Any other files the instances wrote (models, plots, cleaned data, etc.)

The orchestrator reads these to make decisions about next steps (proceed, retry with different strategies, or stop).

### The consolidator

The consolidator is auto-generated from the `summarizer_prompt` in the parallel agent YAML. It:
- Has **read-only permissions** (no edit, no bash, no custom tools)
- Reads all `summary.md` files from completed instances
- Writes `consolidated_summary.md` at the run root
- Only runs when **3 or more instances** complete
- Should compare and present trade-offs, never pick a winner

### Multiple parallel runs in one session

The orchestrator can invoke `parallel-agents` multiple times (e.g., first for data preparation, then for modeling). Each invocation creates a new `parallel/run-<timestamp>/` directory. The orchestrator reads results from one run to plan the next.

## Parallel agent YAML config

Each parallel agent needs a YAML config in `opencode/parallel_agents/`.

```yaml
# opencode/parallel_agents/<agent-name>.yaml

name: <agent-name>                    # Must match an agent .md file
description: "What these parallel instances do"
timeout_minutes: 60                   # Per-instance timeout
failure_behavior: continue            # continue | fail_fast | retry
max_instances: 5                      # Cap on simultaneous instances

# Optional: use different models per instance for diversity
instance_models:
  - "anthropic/claude-sonnet-4-5"
  - "google/gemini-2.5-pro"

# Appended to each instance's prompt — defines output format
subagent_suffix_prompt: |
  When you complete your task, write summary.md with:
  ## Approach
  ## Results
  ## Diagnostics
  ## Recommendations

# Instructions for the auto-generated consolidator
summarizer_prompt: |
  Read all summary.md files from the parallel instances.
  Create a consolidated comparison. Do NOT pick a winner —
  present all approaches with their trade-offs so the
  orchestrator can decide.

summarizer_model: "anthropic/claude-sonnet-4"
```

### Design decisions

**`subagent_suffix_prompt`**: Define exact output structure. The consolidator compares across instances, so all summaries must have the same sections. Be specific about what metrics and tables to include. Also specify what to write when the task fails (diagnosis sections).

**`summarizer_prompt`**: The consolidator compares, it does not decide. It has read-only permissions and cannot run code. Its job is to lay out the facts for the orchestrator.

**`failure_behavior`**:
- `continue` — independent tasks (different modeling approaches)
- `fail_fast` — dependent tasks (if one fails, others are useless)
- `retry` — flaky operations (API calls, cloud compute)

**`instance_models`**: Different LLMs per instance gives diversity in analytical approach. Particularly useful for data preparation where different models notice different things.

## Common mistakes

- Writing agent prompts with concrete example values that the agent copies instead of deriving from data
- Not including "when to stop" criteria in the orchestrator
- Not specifying what subagents should write when they fail
- Letting subagents autonomously retry instead of reporting back to the orchestrator
- Using absolute paths in subagent prompts (breaks parallel isolation)
- Specifying implementation details in orchestrator prompts that the subagent should decide
- Recommending actions without quantifying uncertainty
- Adding caveats to unsupported recommendations instead of refusing to recommend
