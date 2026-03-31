---
name: dlab-cli
description: Complete reference for decision-lab (dlab). Use when the user asks about creating decision-packs, designing data science agents, running sessions, analyzing results, or anything related to dlab CLI, agent architecture, parallel subagents, or decision-pack configuration. Covers the full workflow from scaffolding to analysis.
---

# decision-lab (dlab)

dlab runs autonomous coding agents in frozen Docker environments with domain-specific skills and parallel subagents. You package the environment, prompts, and skills into a **decision-pack**, point it at data, and get back reports and recommendations that hold up to scrutiny.

## When to use this skill

- Creating a new decision-pack (interactive or programmatic)
- Designing agent system prompts for data science workflows
- Understanding how parallel agents, consolidators, and retry protocols work
- Analyzing a completed session's logs, outputs, and artifacts
- Running or configuring dlab CLI commands

## Workflow overview

1. **Create a decision-pack** — scaffold with `dlab create-dpack` wizard or `generate_dpack()` programmatically
2. **Design agents** — write orchestrator, subagent, and parallel agent configs
3. **Run a session** — `dlab --dpack <path> --data <data> --prompt "..."`
4. **Monitor** — `dlab connect <work-dir>` (live TUI) or `dlab timeline <work-dir>` (Gantt chart)
5. **Analyze results** — browse session directory, logs, parallel instance outputs

## Key concepts

**decision-pack**: A directory containing `config.yaml`, `docker/`, and `opencode/` (agents, skills, tools, permissions). Everything an agent needs to run.

**Orchestrator** (`mode: primary`): Coordinates the workflow, spawns parallel agents, evaluates results, writes reports. One per decision-pack.

**Subagents** (`mode: subagent`): Execute focused tasks. Each runs ONE strategy per run. If it fails, it writes diagnosis and stops — the orchestrator coordinates retries.

**Consolidator**: Auto-generated read-only agent that compares parallel instance results. Never picks a winner.

**Parallel exploration**: Fan out multiple agents with structurally diverse approaches (different priors, models, data prep). Check if they agree before recommending.

## Critical methodology rules

These are non-negotiable for any data science agent system:

1. **Never fabricate** — no mocking data, no silently swallowing errors, no `try/except: value = 0`
2. **Understanding over fitting** — a model that doesn't converge is evidence, not failure
3. **Know when to stop** — hard round limits, conflict detection, degenerate problem reports
4. **Templates, not implementations** — no concrete numbers in prompts, use `<PLACEHOLDER>` syntax
5. **Uncertainty, not point estimates** — always report intervals, distinguish model vs structural uncertainty
6. **Recommendations must be computed** — no napkin math, multiple scenarios, realistic actions
7. **Document everything** — including failures, two reports (business + technical)

Load `references/agent-design.md` for the full methodology guide.

## References

Load these as needed — don't read all upfront:

- `references/agent-design.md` — Full methodology: anti-fabrication, retry protocol, epistemic humility, conflict detection, prompt design, parallel exploration, degenerate problems, agent prompt structure, runtime directory layout, YAML config
- `references/create-dpack.md` — Programmatic decision-pack creation: `generate_dpack()` API, config keys, package managers, permissions, Modal integration
- `references/create-dpack-interactive.md` — Interactive wizard guide: how to interview a user and call `generate_dpack()` with the right config
- `references/run-analyzer.md` — Session analysis: directory layout, log format (NDJSON events), how to navigate parallel runs, what to look for
