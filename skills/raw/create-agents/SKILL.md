---
name: Design data science agent systems
description: Design agent system prompts, parallel architectures, and methodological guardrails for data science decision-packs. Use when creating orchestrator, subagent, or parallel agent systems for analytical workflows. Covers anti-fabrication rules, epistemic humility, when to stop, conflict detection, uncertainty reporting, retry protocols, prompt design principles, and the decision-lab runtime mechanics.
---

# Designing Agent Systems for Data Science

This skill covers how to write agent `.md` files and parallel-agent YAML configs for decision-packs that do data science work, AND the methodology that makes the difference between agents that produce useful analysis and agents that produce confident garbage.

The principles here come from building and benchmarking the MMM (Marketing Mix Modeling) agent system. They should apply to most data science domains where agents explore analytical decisions, fit models, and make recommendations.

---

# Part 1: Methodology

## The Cardinal Rule: Never Fabricate

Agents must NEVER fabricate data, mock parameters, silently swallow errors, or substitute made-up values when code fails. This must appear in every agent prompt.

The forbidden pattern:

```python
# NEVER DO THIS
try:
    n_missing = result.missing_count
except:
    n_missing = 0  # FABRICATED
```

When code fails: read the error, investigate, fix, retry. If unfixable after max 10 attempts: report the error and STOP.

Only three acceptable outcomes:
1. Code works → use the real value
2. Code fails → fix it and retry
3. Code fails and can't be fixed → report error and STOP

Never acceptable: code fails → substitute a made-up value and continue.

Every agent prompt — orchestrator, subagents, consolidator — must contain an explicit anti-fabrication section.

## The Goal Is Understanding, Not a Fitted Model

A running model that fit something is not the goal. The goal is understanding the data by means of mathematical modeling. When modeling approaches fail, that is a valuable insight. Agents must treat non-convergence, conflicting results, and degenerate problems as evidence, not as errors to hide.

A subagent that fails and writes a thorough diagnosis is more valuable than one that hacks its way to a "successful" fit by cutting corners.

## Retry Rounds: Escalating Simplification with Hard Limits

Set a hard limit on modeling/analysis rounds (recommend 3). Track rounds explicitly in a planning document so the agent cannot lose count.

**Round 1: Initial diverse strategies.** If all fail, diagnose the COMMON failure mode across instances.

After Round 1 failure:
- If the diagnosis is fundamental (data cannot support this analysis): STOP immediately. Do NOT retry.
- If the diagnosis suggests a structural fix: proceed to Round 2.

**Round 2: Targeted fixes** based on Round 1 diagnosis.

**Round 3: Aggressive simplification**. Results from heavily simplified approaches often have LIMITED value — they show directional patterns but cannot support specific recommendations. The report MUST explain what was lost and be EXTREMELY cautious on making recommendations.

**After Round 3: STOP.** Non-negotiable. Write the report with whatever evidence was gathered. Refrain from making recommendations other than those that would lead to more/better data.

Stop immediately without further rounds if the simplest possible approach was already tried and still failed.

## Epistemic Humility: When to Stop and Say "We Don't Know"

Every orchestrator prompt must include explicit stopping conditions:

- All approaches fail after the round limit
- Converged approaches give conflicting recommendations (degenerate problem)
- Sensitivity to assumptions dominates — different reasonable assumptions give completely different answers
- Too few observations to support the analysis complexity
- All results show implausible values (fitting noise, not signal)
- Even the simplest possible approach fails

### Conflict detection

For quantitative analyses, define objective criteria:

**Magnitude consistency:** Compare key metrics across approaches. If variation exceeds a domain-appropriate threshold, results are CONFLICTING.

**Directional agreement:** Do all approaches agree on the ACTION? (increase/maintain/decrease). Opposite actions = CONFLICTING.

**Ranking consistency:** Do approaches agree on which factors matter most? If not, CONFLICTING.

### The caveats trap

Adding caveats to unsupported recommendations does NOT fix them. "We recommend X, with the caveat that we're uncertain" is WRONG when X and not-X are equally supported. The right response: "We cannot make a recommendation. Here's what experiment would resolve this."

### What the stop report must contain

- What was tried and what failed (every approach, including failures)
- Root cause: why the data doesn't support reliable inference
- What CAN be concluded (robust across all approaches)
- What CANNOT be concluded (and why)
- Specific, realistic experiments that would resolve the uncertainty (not "collect more data" but "run a geo-holdout test on factor X for 8 weeks")

## Prompt Design: Templates, Not Implementations

Agent prompts must never contain concrete numerical values. Concrete examples with actual numbers get copied verbatim, creating deterministic behavior. At that point, fixed code would be better and cheaper.

The test: if you change a number in a prompt example, does the agent's output change accordingly? If yes, the agent is copying, not reasoning.

Use placeholder syntax: `<VALUE>`, `<COLUMN_NAME>`, `<N_INSTANCES>`. Show structure and patterns, not implementations.

Skills and agent prompts should encode generic best practices:
- Good: "Run convergence diagnostics after fitting. Check that R-hat < threshold and ESS > threshold."
- Bad: "Check that R-hat < 1.05 and ESS > 400."

Too many skills or poorly written skills DEGRADE performance. Skills are guardrails, not scripts.

## Reporting Uncertainty and Making Recommendations

### Two types of uncertainty

**Model uncertainty** (from posterior/confidence intervals): "Factor X has effect 2.1 [1.7, 2.5]." Supports decision-making — wide intervals mean proceed with caution.

**Structural uncertainty** (from model disagreement): "Different approaches give effect from <STRICTLY NEGATIVE EFFECT> to <STRICTLY POSITIVE EFFECT>." Does NOT support decision-making. You cannot choose between opposite conclusions by adding caveats.

### Recommendation constraints

- Never recommend actions you haven't computed or simulated
- No napkin math — don't just multiply a metric by some number to obtain an action-recommendation; run an actual optimization if possible
- Must discuss MULTIPLE scenarios at different constraint levels, not one "best" answer
- Recommendations must be realistic and domain-sensible (e.g. concentrating all resources in one area is nonsensical and will not be accepted by human decision makers)
- Always report intervals, never point estimates alone
- Base actionable recommendations on conservative scenarios, not unconstrained optimizations

## When the Problem Is Degenerate

A degenerate problem is one where multiple valid approaches give opposite conclusions. The agent must identify the ROOT CAUSE:

- High correlation between inputs (cannot separate individual effects)
- Insufficient variation in key variables
- Confounding with external factors
- Too few observations for the complexity required
- Prior sensitivity (data has no say)

The agent must recommend SPECIFIC experiments:
- Holdout tests: pause or vary one factor while others continue
- Geographic/segment experiments: vary factors across matched regions or other domain-related segments
- Controlled variation: randomly vary inputs by ±N% to create identifying variation
- Time-based experiments: measure before/after a deliberate change
- Be creative with regard to experiments, think what other experiments would make sense for the problem given

These must be realistic for the domain — not experiments that would never be approved.

## Designing Parallel Exploration

Parallel approaches must be STRUCTURALLY diverse: different model forms, different data prep, different priors. Minor parameter tweaks waste parallel capacity.

You may use different LLMs per instance for genuine diversity. The orchestrator can combine data prep diversity with modeling diversity (pipe different data prep outputs into different models). This is NOT a necessity however.

Each instance runs in isolation — own data copy, own config, relative paths only.

## Transparency: Document Everything

Every approach tried must be documented, including failures. The orchestrator writes two reports:
- **Business report** — executive summary, recommendations with uncertainty, caveats, experiments
- **Technical report** — all strategies explored, quality details, model selection rationale, sensitivity analysis, limitations

Agents must explain reasoning at every decision point.

## The Code Workflow

Write code to disk as `.py` files, execute, check output. No inline evaluation. Scripts stay on disk for audit trail.

Subagents use relative paths only. Retry limit: max 10 per error, then stop and report.

---

# Part 2: Technical Setup in decision-lab

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

## System prompt structure

A data science agent prompt should have these sections:

1. **Role and personality** — methodical, transparent, honest about failures
2. **Task** — what this agent does, as a numbered list
3. **Critical rules** — non-negotiable constraints including anti-fabrication. Include library-specific rules (deprecated imports, internal scaling, what NOT to transform)
4. **Working directory rules** — relative paths, never `../`
5. **Workflow phases** — step-by-step with clear inputs and outputs
6. **Output requirements** — exact `summary.md` structure for BOTH success AND failure

## Orchestrator prompt pattern

- Spawns parallel agents with the `parallel-agents` tool
- Reviews consolidated results with objective conflict detection criteria
- Implements retry protocol with hard round limit
- Writes both business and technical reports
- Has explicit "when to stop" criteria and a degenerate problem report template
- Does NOT specify implementation details the subagent should decide

## Subagent prompt pattern

- Executes ONE strategy per run (does not autonomously simplify and retry)
- Writes structured `summary.md` with identical sections across all instances
- Reports failures with thorough diagnosis (symptom, likely cause, what might help)
- All file operations use relative paths
- Reads data from `data/` (a copy placed in the instance directory)

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
- **Relative paths only**: Because instances run in `parallel/run-<ts>/instance-N/`, any use of `../` or absolute paths breaks isolation.

### What the orchestrator sees after parallel runs

After all instances complete, the orchestrator can read:
- `parallel/run-<ts>/instance-N/summary.md` — each instance's structured output
- `parallel/run-<ts>/consolidated_summary.md` — the consolidator's comparison (if 3+ instances ran)
- Any other files the instances wrote (models, plots, cleaned data, etc.)

### The consolidator

The consolidator is auto-generated from the `summarizer_prompt` in the parallel agent YAML. It:
- Has **read-only permissions** (no edit, no bash, no custom tools)
- Reads all `summary.md` files from completed instances
- Writes `consolidated_summary.md` at the run root
- Only runs when **3 or more instances** complete
- Should compare and present trade-offs, never pick a winner

### Multiple parallel runs in one session

The orchestrator can invoke `parallel-agents` multiple times (e.g., first for data preparation, then for modeling). Each invocation creates a new `parallel/run-<timestamp>/` directory.

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

summarizer_model: "anthropic/claude-sonnet-4-5"
```

### Design decisions

**`subagent_suffix_prompt`**: Define exact output structure. The consolidator compares across instances, so all summaries must have the same sections. Include sections for both success and failure.

**`summarizer_prompt`**: The consolidator compares, it does not decide. It has read-only permissions and cannot run code.

**`failure_behavior`**:
- `continue` — independent tasks (different modeling approaches)
- `fail_fast` — dependent tasks (if one fails, others are useless)
- `retry` — flaky operations (API calls, cloud compute)

**`instance_models`**: Different LLMs per instance gives diversity in analytical approach.

---

# Common Mistakes

- Writing prompts with concrete example values that agents copy instead of reasoning
- Not including anti-fabrication rules in every agent prompt
- Not including "when to stop" criteria in the orchestrator
- Not specifying what subagents should write when they fail
- Letting subagents autonomously retry instead of reporting back to the orchestrator
- Using absolute paths in subagent prompts (breaks parallel isolation)
- Specifying implementation details in orchestrator prompts that the subagent should decide
- Recommending actions without computing them (napkin math)
- Adding caveats to unsupported recommendations instead of refusing to recommend
- Presenting one "best" answer instead of multiple scenarios
- Using minor parameter tweaks as "diverse" parallel strategies
- Allowing try/except patterns that silently substitute values
- Not including library-specific rules in subagent prompts
- Suggesting vague experiments ("collect more data") instead of specific ones
- Skipping the technical report
