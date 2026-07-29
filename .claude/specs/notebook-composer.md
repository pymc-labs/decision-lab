# Spec: Notebook Composer — `generate_jupyter_notebooks_from_run`

Status: **specced, not implemented** (spec discussion 2026-07-29, Ben + Claude).
Verbatim design conversation: [`notebook-composer-conversation.md`](notebook-composer-conversation.md)
(regenerable via [`extract_spec_conversation.py`](extract_spec_conversation.py)).

## What

A dlab-internal agent ("the composer"), enabled per decision-pack, that runs after
the orchestrator finishes and converts the session — logs, reasoning, scripts,
figures, reports — into Jupyter notebooks that *look executed* and can plausibly
be re-run. Target user: a data scientist who wants the automatic analysis first,
then wants to open a notebook and fiddle with the solution.

Notebooks are **composed, never executed**: outputs (figures as base64, captured
stdout) are embedded from the original run's artifacts, per the
[nbformat spec](https://nbformat.readthedocs.io/en/latest/format_description.html).

## Config

```yaml
# config.yaml
generate_jupyter_notebooks_from_run: true   # default: false

models:
  composer: anthropic/claude-haiku-4-5      # optional role, falls back to default_model
```

Minimal v1 surface: on/off + model role (riding the existing `models:` role
mechanism from #34). No per-dpack composer hints yet.

## Placement (decided, alternatives rejected)

The composer is a **dlab-sequenced step**: after the orchestrator's opencode
process exits (logs complete and flushed), and before post-run hooks/cleanup,
dlab launches a second `opencode run` in the **same container and workdir** with
the composer as `default_agent` — analogous to how `parallel-agents.ts` launches
the consolidator as its own opencode process.

Rejected alternatives, and why:

- **In-run subagent / amended orchestrator prompt**: (1) the composer's key
  input — the orchestrator's own log, including its final adopt/reject
  reasoning — does not exist until the run ends; (2) it makes the feature
  LLM-triggered instead of dlab-triggered (see: the consolidator that silently
  never ran, PR #38) — a config flag must mean "notebooks will exist";
  (3) prompt amendment spends orchestrator attention/context on presentation.
- **Separate decision-pack**: overkill; no Docker env of its own, distribution pain.

Constraint locked in by this placement: **the composer may only consume what
survives in the workdir** (`_opencode_logs/`, `parallel/`, reports, scripts,
figures) — never dlab in-memory state. This keeps the door open for a later
`dlab notebooks <work-dir>` subcommand that retrofits notebooks onto any
completed/historical session (same code path; deferred, not v1).

## Output layout

- `notebooks/00_overview.ipynb` — the end-to-end story: what was tried, what was
  adopted, **why**; argues the alternative paths in prose and links into
  `attempts/`.
- `notebooks/NN_<phase>.ipynb` — one notebook per workflow phase. "Phase" is
  derived from the session graph, not the orchestrator's prompt numbering:
  parallel runs are grouped by agent name (`{agent}-parallel-run-{timestamp}`),
  all runs of one agent = one logical phase, multiple timestamps = retry rounds
  in temporal order. Phase notebooks inline the **adopted** instance's work and
  *narrate* retries ("attempt 1 diverged — r̂ 1.4, see attempts/; attempt 2
  adopted").
- `notebooks/attempts/` — one notebook per non-adopted instance, each labeled
  with *why* it wasn't adopted: "not adopted — diverged" (failure) vs "not
  adopted — higher LOO" (true alternative). One folder, labeled, not two.
  Evidence for labels comes from instance summaries and consolidated comparisons.

## Runnability bar

- **Level A (hard guarantee)**: valid nbformat JSON, correct cell types,
  embedded base64 figures, execution counts, `$` escaped in markdown.
- **Level B (target)**: plausibly re-executable — cells in dependency order,
  imports present, paths relative to the workdir, code verbatim from scripts
  that actually ran (provenance comment per cell, e.g.
  `# from parallel/run-*/instance-2/fit_model.py`).
- **Level C (deferred)**: verified execution (`dlab notebooks --execute`,
  opt-in, runs in the container; skips cells tagged `long-running`).

Key patterns:

- **Fit-then-load**: expensive cells (PyMC fitting) included verbatim and tagged
  `tags: ["long-running"]`; the following cell loads the persisted artifact
  (`az.from_netcdf("…/idata.nc")`), and all downstream cells depend only on
  loaded artifacts — so a user can skip the fit and fiddle immediately.
- **Provenance header cell** in every notebook: "auto-composed from session
  artifacts; outputs embedded from the original run, not re-executed." These
  notebooks look executed; without this they'd be indistinguishable from
  genuinely executed ones.
- **Deterministic host-side validation** after composition (no LLM, no
  execution): `nbformat` schema check, `ast.parse` per code cell, referenced
  relative paths exist, imports resolvable in the container env. Failures are
  CLI warnings, non-fatal to the session.

## Notebook production: cell-level tools, never raw JSON

The LLM never writes ipynb JSON, never touches base64, never reads raw ipynb
(base64 in context = poison). Instead: custom opencode TS tools (shipped like
`parallel-agents.ts`, run in opencode's Bun runtime, zero container deps):

- `nb-add-markdown-cell(notebook, text)` — `$` escaped by default; `math: true`
  opt-out per cell.
- `nb-add-code-cell(notebook, code, outputs=[{image: <path>} | {stream: <text>}])`
  — tool reads the figure file and base64-encodes it; assigns sequential
  `execution_count`.
- `nb-edit-cell(notebook, index, …)`, `nb-finalize(notebook)`.
- `nb-read(notebook)` — **compact rendering with base64 stripped**
  ("cell 7 [code, 1 image output: figures/adstock.png]").

Research (2026-07-29): opencode has no notebook support (open feature requests
anomalyco/opencode#11409, #20487). Prior art validating the cell-tool design:
cursor-notebook-mcp (30+ nbformat-backed cell ops incl. output setting, no
kernel), easy-jupyter-editor-mcp, claude-code-notebook-mcp, mcp-jupyter-complete,
Claude Code's built-in NotebookEdit. Decision: build our own — MCP servers would
add a Python/MCP dependency to every frozen pack container, their generic APIs
let the agent construct output objects (reopening the base64 trap), and a
purpose-shaped 5-tool surface beats 30 generic ops.

## Session digest (internal plumbing, v1 not user-facing)

Deterministic, LLM-free pre-digest generated **host-side by dlab** before the
composer launches, built on `opencode_logparser`
(`dlab/session_digest.py`). Writes into the workdir:

- `_digest/digest.md` — the map the composer starts from.
- `_digest/index.json` — ID → `{log_file, line_no, event_type}` for every
  addressable element.

Digest format:

- Header: dpack, models, duration, total cost.
- Workflow tree: main → fan-outs grouped by agent (retry rounds labeled) →
  instances with status; consolidator entries.
- **Per-agent `###` sections, identical structure** (orchestrator and every
  instance): stats line (model, duration, cost, tool-call count); **Artifacts**
  with full write chains (`[a5] summary.md (written t12, overwritten t31)` —
  content attributed to last writer, earlier writers kept visible); **Script
  runs** (bash calls with ✓/✗, duration, stdout/stderr line counts); other
  tool-call counts; **Reasoning excerpts** (truncated verbatim text with IDs).
- **One shared event counter per agent — the numbering IS the timeline**:
  `t07` (tool) < `x08` (text) < `t09`. Kind-prefix says what, number says when.
  Categorical sections + ordered IDs give both the by-kind index and the
  chronology without duplicating views.
- `--brief` variant: keeps stats, artifacts with write chains, script runs,
  excerpts; collapses tool tables to counts. Index unaffected.

Retrieval: in-container `digest-get` tool (deliberately dumb, ~50 lines of
stdlib TS): look up ID in `index.json`, read that one NDJSON line, extract the
payload for the event type, render **decoded** (clean stdout/stderr, not
escaped JSON), slice via `--head/--tail/--range`. Agents never read raw NDJSON —
digest + `digest-get` are the only log interface, mirroring the ipynb rule.

Rejected: raw log line-number pointers (a single tool_use line can be 100KB of
escaped JSON); LLM-generated digest (cost + fabrication risk for a mechanical
extraction); digest as data layer for TUI/viewer (it's an LLM-facing rendering —
instead, lift shared derived-stats helpers (per-agent rollups, run grouping,
artifact discovery) into the parser layer incrementally so
timeline/viewer/digest converge on one stats layer; non-blocking refactor).

## Follow-ups (explicitly deferred)

1. `dlab notebooks <work-dir>` retrofit subcommand for completed sessions.
2. Level C: `dlab notebooks --execute` with `long-running` cell skipping.
3. Update the `run-analyzer` skill (predates `opencode_logparser`; should point
   at the digest once it exists).
4. Derived-stats layer refactor: `timeline.py` + `viewer/session_data.py` +
   digest share rollup helpers.
5. Possibly promote `dlab digest` to a documented subcommand.
