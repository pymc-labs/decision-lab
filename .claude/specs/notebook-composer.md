# Spec: Notebook Composer — `generate_jupyter_notebooks_from_run`

Status: **specced, not implemented** (spec discussion 2026-07-29, Ben Maier + Claude).
GitHub issue: #68. Verbatim design conversation (source of truth for intent):
[`notebook-composer-conversation.md`](notebook-composer-conversation.md), regenerable via
[`extract_spec_conversation.py`](extract_spec_conversation.py).

> **For the implementing agent**: every decision below was argued and settled in the
> spec conversation. Where this document says "decided" or "rejected", do NOT
> re-litigate or substitute your own design. If something is genuinely
> unspecified, it is listed in §12 (Open implementation checks) — resolve those
> and only those. When in doubt, read the verbatim conversation.

---

## 1. Purpose and user story

A dlab-internal agent ("**the composer**"), enabled per decision-pack, that runs
after the orchestrator finishes and converts the session — logs, reasoning,
scripts, figures, reports — into Jupyter notebooks.

The driving user story (Ben, verbatim): *"data scientists want an automatic
analysis as a first step, and then they just want to open a notebook and fiddle
around with the solution themselves."*

The notebooks are **composed, never executed**. They must *look* like they have
been run: figures embedded as base64 in the correct nbformat output structure,
markdown in markdown cells, captured stdout as stream outputs, execution counts
set. Reference: <https://nbformat.readthedocs.io/en/latest/format_description.html>.

## 2. Config surface (decided)

```yaml
# config.yaml
generate_jupyter_notebooks_from_run: true   # default: false. Descriptive name chosen
                                            # deliberately over a terse `notebooks:` key.

models:
  composer: anthropic/claude-haiku-4-5      # optional role; falls back to default_model.
                                            # Rides the existing models: role mechanism
                                            # introduced for forecaster/consolidator (#34).
```

v1 surface is deliberately minimal: on/off + model role. Per-dpack composer
hints ("always show the adstock curves"), output-directory config, etc. are
explicitly deferred.

## 3. Placement in the run lifecycle (decided, with reasoning)

**Decision**: the composer is a **dlab-sequenced step**. After the
orchestrator's opencode process exits (its log is then complete and flushed),
and *before* post-run hooks and container cleanup, dlab launches a second
`opencode run` in the **same container and same workdir** with the composer as
the active agent. This is analogous to how `parallel-agents.ts` launches the
consolidator as its own opencode process.

Sequence in `cmd_run`:

```
[pre-run hooks] → [opencode run: orchestrator] → [if flag: generate digest (host-side)]
→ [if flag: opencode run: composer (in container)] → [host-side notebook validation]
→ [post-run hooks] → [cleanup/stop container]
```

Composer failure is **non-fatal**: warnings in CLI output, session exit code
unaffected.

**Rejected: in-run subagent / amending the orchestrator's system or user
message** (this was Ben's initial lean; he was argued off it and agreed). Three
reasons, all load-bearing:

1. *Log completeness*: the composer's most valuable input — the orchestrator's
   own log, including its final adopt/reject reasoning — does not exist until
   the run ends. An in-run subagent can only see a truncated version of the
   story it is supposed to narrate.
2. *Deterministic trigger*: any step that depends on the orchestrator LLM
   remembering to invoke it silently fails some fraction of the time (empirical
   precedent in this repo: the consolidator that never ran until PR #38, the
   hallucinated `models` arg). A config flag must mean "notebooks WILL exist",
   not "notebooks exist if the orchestrator felt like it".
3. *Context hygiene*: amending the orchestrator prompt spends its attention on
   presentation concerns during analysis, and its context on composer output.

**Rejected: shipping as a separate decision-pack** — overkill (Ben's word); no
Docker environment of its own, distribution pain.

**Constraint locked in by placement**: the composer may only consume what
survives in the workdir (`_opencode_logs/`, `parallel/`, reports, scripts,
figures, `.opencode/`) — never dlab in-memory state. This deliberately keeps
the door open for a later `dlab notebooks <work-dir>` subcommand that retrofits
notebooks onto completed/historical sessions using the same code path
(deferred, §11).

## 4. Output layout (decided)

```
work-dir/
  notebooks/
    00_overview.ipynb          # end-to-end story; the alternatives ARGUMENT lives here
    01_data_exploration.ipynb  # per-phase notebooks; adopted instance's work inlined
    02_data_prep.ipynb
    03_modeling.ipynb
    04_evaluation_and_findings.ipynb
    attempts/                  # ONE folder for all non-adopted material, labeled
      modeler-r1-instance-1.ipynb   # header: "not adopted — diverged (r̂ 1.4)"
      modeler-r2-instance-3.ipynb   # header: "not adopted — higher LOO than instance-2"
```

Decisions and reasoning:

- **What is a "phase"**: NOT the orchestrator's prompt-step numbering (not
  machine-readable, differs per dpack). Phases derive from the session graph:
  parallel run directories are named `{agent}-parallel-run-{timestamp}`, so
  **group runs by agent name**; all runs of one agent = one logical phase;
  multiple timestamps within a group = **retry rounds** in temporal order.
- **Retries are narrated, not hidden** (mmm's retry loops were the motivating
  case): the phase notebook tells the loop — "Attempt 1 (three modelers,
  saturating priors): none converged — r̂ up to 1.4, divergences; see
  `attempts/`. Attempt 2 (simplified adstock): modeler-2 converged and was
  adopted" — then inlines the adopted instance's work.
- **Only adopted-path content in the main notebooks** (Ben's requirement).
  Alternative paths are argued about in the main notebooks — centralized in
  `00_overview.ipynb` — while the full analyses of non-adopted instances live
  in `attempts/` to avoid clutter.
- **One `attempts/` folder, labeled — not two folders**: non-adopted material
  has two flavors, *failed attempts* (diverged/crashed) and *true alternatives*
  (ran fine, lost the comparison). Each attempts-notebook header and its
  `00_overview` entry states which, with evidence ("not adopted — diverged" vs
  "not adopted — higher LOO"). Evidence source: instance `summary.md`s and
  `consolidated_summary.md`s.

## 5. Runnability bar (decided)

Ben, verbatim: *"it should be level C but that is infeasible because fitting in
pymc takes a lot of time, but the fitting step should be in there. so every cell
should be runnable in principle […] maybe we commit to level B first and then
tackle level C at a later stage."*

- **Level A — looks executed (hard guarantee)**: valid nbformat JSON, correct
  cell types, embedded base64 figures with execution counts, `$` escaped in
  markdown so it doesn't trigger math rendering.
- **Level B — plausibly re-executable (v1 target)**: cells in true dependency
  order, imports present, paths relative to the workdir, code taken **verbatim
  from scripts that actually ran**, with a provenance comment per code cell:
  `# from parallel/run-1784.../instance-2/fit_model.py`.
- **Level C — verified re-executable (deferred)**: `dlab notebooks --execute`,
  opt-in, runs in the container, skips cells tagged `long-running`.

**The fit-then-load pattern** (serves the "open it and fiddle" story — this is
how the expensive fitting step is "in there" without blocking fiddling):

```python
# cell N  — tagged: ["long-running"]
# from parallel/run-1784571692537/instance-2/fit_model.py
with model:
    idata = pm.sample(2000, tune=1000, target_accept=0.95)
idata.to_netcdf("parallel/run-1784571692537/instance-2/idata.nc")
```
```python
# cell N+1 — everything downstream depends ONLY on this
idata = az.from_netcdf("parallel/run-1784571692537/instance-2/idata.nc")
```

Rule for the composer: downstream cells must depend on **persisted artifacts**,
never on in-memory state produced by a `long-running` cell. The packs already
persist their results (mmm's `idata.nc`, event-forecaster's prediction files).

**Provenance header cell — mandatory in every notebook**: "auto-composed from
session artifacts; outputs are embedded from the original run, not re-executed."
Reasoning: these notebooks *look* executed; without the header they are
indistinguishable from genuinely executed ones — exactly the silent fiction
this project exists to avoid.

**Deterministic host-side validation** (no LLM, no execution) runs after the
composer exits; failures are CLI warnings, non-fatal:

1. `nbformat` schema validation (real nbformat library, host side — dlab dep).
2. `ast.parse` on every code cell (syntax).
3. Every relative path referenced in read/load calls exists in the workdir.
4. Imports resolvable in the container env (`importlib.util.find_spec` executed
   in the container via `docker exec`, or skipped with a warning in local mode).

## 6. Notebook production: cell-level tools (decided; two designs rejected)

Ben, verbatim: *"an LLM should never generate this in total or even in parts.
instead there should be tools that allow an agent to edit a notebook by amending
cells one-by-one (markdown-cell-tool would get only text, code-cell tool would
get code and output, including image paths) and then deterministically render
this into valid ipynb json."*

**Rejected design 1 — LLM writes raw ipynb JSON**: (a) base64 figures are
50–500KB each → physically impossible through a model; (b) nested JSON-string
escaping + execution_count bookkeeping is fragile at LLM temperatures, and one
slip produces a file Jupyter refuses to open; (c) burns composer context on
mechanics.

**Rejected design 2 — intermediate representation** (percent-format source
files + output manifest + builder; Claude's initial proposal): Ben rejected it
in favor of cell-by-cell tools. Do not resurrect it.

**Decided: custom opencode tools**, shipped exactly like `parallel-agents.ts`
(TypeScript, copied into `.opencode/tools/`, run in opencode's Bun runtime,
zero container dependencies — ipynb is just JSON; base64 encoding is a few
lines of Bun). Tool surface (~5 tools, deliberately small):

| Tool | Args | Behavior |
|---|---|---|
| `nb-add-markdown-cell` | `notebook, text, math?` | Appends markdown cell. Escapes `$` → `\$` by default (auto-mined text is almost always currency); `math: true` per cell opts into MathJax. |
| `nb-add-code-cell` | `notebook, code, outputs?, tags?` | Appends code cell. `outputs` is a list of `{image: <path>}` \| `{stream: <text>}`; the TOOL reads the figure file and base64-encodes it into a proper `display_data`/`stream` output — the model only ever passes paths. Assigns sequential `execution_count`. `tags` for `long-running`. |
| `nb-edit-cell` | `notebook, index, …` | Replace source/outputs of an existing cell (for fixes). |
| `nb-read` | `notebook` | **Compact rendering, base64 stripped**: `cell 7 [code, exec 7, 1 image output: figures/adstock.png]` + truncated sources. Agents must never read raw ipynb (base64 in context = the same poison we keep out of writing). |
| `nb-finalize` | `notebook` | Injects the provenance header cell (idempotent), final consistency pass, writes canonical JSON. |

**Research record (2026-07-29)** — checked before deciding to build:

- opencode has **no** notebook support; open feature requests:
  anomalyco/opencode#11409 (native ipynb), #20487 (NotebookEdit tool).
- Kernel-free cell-level MCP servers exist and validate the design:
  [cursor-notebook-mcp](https://github.com/jbeno/cursor-notebook-mcp) (30+
  nbformat-backed ops incl. `notebook_edit_cell_output`, no kernel),
  easy-jupyter-editor-mcp, claude-code-notebook-mcp, mcp-jupyter-complete,
  datalayer/jupyter-mcp-server (kernel-bound). Claude Code's built-in
  NotebookEdit is the same pattern.
- **Why build our own instead of shipping an MCP server**: (a) an MCP server
  means a Python process + nbformat + MCP wiring inside every *frozen* pack
  container vs. zero-dep Bun tools; (b) generic APIs let the agent construct
  output objects — reopening the base64-through-the-model trap; ours accepts
  *paths*; (c) 5 purpose-shaped tools beat 30 generic ops for a
  non-interactive agent; (d) we control opinionated defaults ($-escaping,
  execution_count, provenance header) that generic editors don't have.

## 7. Session digest (decided; internal plumbing)

Ben: *"I like the pre-digest a lot a lot a lot"* — and: *"for now the digest
should be internal plumbing"* (no public `dlab digest` subcommand in v1).

**Decision: the digest is deterministic dlab code — no LLM, not an agent, not a
skill.** A digest is mechanical extraction; an LLM in that seat adds cost,
latency, and summarize-then-fabricate risk, while deterministic code is
testable and free. It is generated **host-side** by dlab (where
`opencode_logparser` lives) after the orchestrator exits and before the
composer launches. Note: there is prior art to be aware of but NOT to reuse as
implementation: the `run-analyzer` Claude Code skill is manual navigation
guidance, predates the parser, and produces nothing on disk (see §10).

Outputs written into the workdir:

- `_digest/digest.md` — the LLM-facing map (format below).
- `_digest/index.json` — machine index: every ID → `{log_file, line_no,
  line_end?, event_type}`. **Thin index** (pointers, not payloads): a fat index
  storing extracted payloads would duplicate log content on disk. `line_end` is
  present for multi-line payloads — a `raw_text` block, or a `tool_use` whose
  mapped raw_text stream extends past its own line.

### 7.1 Digest format

> **Revised 2026-07-30** after reviewing the digest against a real completed mmm
> run (`dlab-mmm-agent-oc-workdir-008`). Changes, all validated on that run:
> artifacts are **provenance-first** (every file links to the tool call that
> produced/copied it; inherited untouched copies dropped by sha256; the parent's
> `cp`'d files stay, linked to the copy); **all producing tool calls are
> labeled** (not just bash), so every referenced ID is a visible row; and
> **`raw_text` (the majority of a real log — the tracebacks and sampler output)
> is a first-class `r`-id**, mapped to its tool call and retrievable, because it
> is what the composer embeds as a cell's `stream` output. The `dlab digest`
> command (spec §11.5) and the produced/inherited attribution already shipped in
> PR #87; the tool-call-labeling + `raw_text` mapping are the remaining build.

Header: dpack name, models, total duration, total cost. Workflow tree. Then
**one `###` section per agent (orchestrator AND every instance AND
consolidators), identical structure** (Ben's requirement).

**ID scheme — one shared event counter per agent; the numbering IS the
timeline** (load-bearing, resolved Ben's chronology concern): `t07` (tool
call), `x08` (text/reasoning), `r09` (raw_text stream) — the kind-prefix says
*what*, the shared number says *when*. Every event is addressable.

`raw_text` is the plain stdout/stderr the opencode process emits **outside** the
structured tool events. On a real mmm instance it is the *majority* of the log
(e.g. 166 of 266 lines) and holds the material that matters most — the
Modal/PyMC tracebacks, sampler diagnostics, "saved to fitted_model.nc" lines.
It carries **no timestamp**, so it is ordered by line position and a run of
consecutive raw_text is associated with the **most recent `tool_use` before it**
(positional; the parser already groups the run into one block). Each block gets
one `r`-id on the shared counter and is **mapped to its tool call**. This is the
material the composer embeds as a cell's `stream` output (§5). Remote Modal-side
fit logs are **not** fetched (out of scope) — only what the local session log
captured.

Artifact IDs (`a1`, `a2`, …) and the Task ID (`p0`) are per-agent and off the
event counter (files/prompts are not events); their provenance is expressed
through event IDs. Fully-qualified form for retrieval: `<agent-path>/<id>`,
e.g. `main/t17`, `poet.r2.i2/r4`.

**Task field** (per agent section, required): the *differentiating* portion of
the agent's prompt — for parallel instances, the orchestrator-supplied prompt
from the `dlab_start` event, minus the shared `subagent_suffix_prompt` and the
injected subagent context. ID `p0` (outside the event counter, like artifacts),
full prompt retrievable via `digest-get <agent>/p0`. Rationale: the composer
cannot narrate alternatives ("instance 2 tried geometric adstock, instance 3
Weibull") without knowing what each instance was asked to do.

**Artifact provenance (produced vs. inherited)** — every artifact links to the
tool call in *this agent* that produced or copied it:

- `write`/`edit` → chain by `filePath`: `written t6, edited t9` (full write
  history in order; content attributed to the last writer, earlier writers kept
  visible so the composer sees a retry replaced it).
- `bash` / custom tool (`fit-model-modal`, `analyze-model`) / `cp` → matched by
  **mtime ∈ [call.start, call.end]** — the file was written during that call's
  window: `← from t10 (bash: python fit_model.py)`, `← from t16
  (fit-model-modal)`. mtime is safe here because it is used **only on files
  already proven produced**, never to detect copies (Ben's tier-3, applied
  where it cannot misfire).

The **parent's `cp`'d artifacts stay visible**, linked to the copy call —
`best_model.nc ← from t52 (cp)` — because the copy IS a producing call.

A file is **dropped** only when it has **no producing call in this agent** *and*
is byte-identical (sha256) to the workspace-root seed — i.e. it arrived via the
invisible `copyWorkDir` fan-out and was never touched. Chronology +
sibling-isolation gate this so a creator never loses its own file to a later
`cp`, and isolated siblings never shadow each other. A seeded file the agent
then *edited* is kept — it has an edit call.

**Header + workflow-tree format** (schematic):

```markdown
# Session digest: <work-dir name>

- started: <ts> | orchestrator duration: <s> | orchestrator cost: $<c>
- orchestrator tool calls: <tool>×<n>, …
- files written by orchestrator: `<file>`, …

## Workflow tree

- **main** (orchestrator)
  - parallel fan-out: **<agent>** run `<timestamp>` [— retry round N]
    - instance-1: <s>, $<c>, <n> tool calls, wrote: `<files>` — summary written | NO summary.md (treat as failed)
      - log: `_opencode_logs/<agent>-parallel-run-<ts>/instance-1.log` | workdir: `parallel/run-<ts>/instance-1/`
    - consolidator: <s>, $<c> — `parallel/run-<ts>/consolidated_summary.md` | absent

## Final artifacts (workdir root)
- `<file>` (<size>)
```

**Per-agent section format** (agreed sketch, mmm-realistic; every agent gets
exactly this structure):

```markdown
### poet.r2.i2 — modeler, instance 2 (retry round 2)          [adoptable]
model: anthropic/claude-sonnet-4-5 | 214s | $0.31 | 19 tool calls
workdir: parallel/run-1784571692537/instance-2/

**Task** [p0]: "Fit a geometric-adstock MMM with saturating priors on /workspace/data;
run seeds [0,1,2] and report median F1…" (differentiating portion; full prompt
via digest-get poet.r2.i2/p0)

**Artifacts** (6 produced)
- [a1] fit_model.py            (4.1KB)  ← written t6, edited t9
- [a2] idata.nc               (2.3MB)  ← from t10 (bash: python fit_model.py)
- [a3] figures/adstock_curves.png (142KB) ← from t14 (bash: python make_figures.py)
- [a4] figures/posterior_roas.png (98KB)  ← from t14
- [a5] summary.md             (1.8KB)  ← written t16   (instance conclusion)
- [a6] analysis_output/analysis_summary.json (0.9KB) ← from t12 (analyze-model)
(cleaned_data.parquet, data_summary.md — inherited, untouched → hidden)

**Tool calls**  (producing calls, each addressable; raw_text stream mapped in)
- [t6]  write fit_model.py
- [t7]  bash  `python fit_model.py`     ✗ error  0s   → r8  (stderr 41 ln — KeyError: 'is_valid')
- [t9]  edit  fit_model.py              (fix)
- [t10] bash  `python fit_model.py`     ✓ 312s        → r11 (stdout 6,204 ln — sampler + diagnostics)
- [t12] analyze-model                   ✓             → analysis_output/
- [t14] bash  `python make_figures.py`  ✓ 8s          → r15 (stdout 12 ln)
- [t16] write summary.md
**Navigational**: read×4, todowrite×3, glob×1
**Reasoning excerpts**
- [x8]  "The first fit failed on the validation key; fixing and rerunning…"
- [x18] "r̂ ≤ 1.01 on all parameters, 0 divergences — converged. Writing summary…"
```

(The shared counter runs `t6 → t7 → r8 → x… → t9 → t10 → r11 …`: "wrote → ran →
it errored (r8) → reasoned → fixed → ran → it worked (r11)" reads straight off
the numbering — raw_text now included as a first-class element. Every `← from
tN` and every `→ rN` points at a labeled row, so no ID is referenced without
being shown.)

**`--brief` variant** (agreed): keeps per-agent header stats, Artifacts with
their provenance links, and the ✓/✗ + raw_text-tail for producing calls;
collapses the full Tool-calls table and Reasoning to one-line counts/first
lines. The index is unaffected — brief trims the *map*, not addressability.
Expected size: full digest for a big mmm run ≈ 500–1500 dense lines (acceptable:
it is the map, ~100× smaller than the logs).

### 7.2 Retrieval: the `digest-get` tool

Ben's design (agreed over line-number pointers): *"every
tool-call/artifact/element of the logs/digest would get an id and then an LLM
can ask the digest-tool to deliver the output/message/whatever from that id."*

**Rejected: line-number pointers into raw NDJSON** — pointers would be stable
(logs are immutable) but a single `tool_use` line can be 100KB of JSON with the
output embedded as an escaped string; reading it hands the composer a wall of
`\n`-escaped JSON. Same failure mode as reading raw ipynb.

`digest-get` (custom opencode tool, in-container, **deliberately dumb** — ~50
lines of stdlib TS, no parser port, no drift; intelligence stays in the
host-side Python indexer):

- Args: `id` (fully qualified, e.g. `poet.r2.i2/r8`), optional `head`, `tail`,
  `range` (line-based slicing of the payload).
- Behavior: look up ID in `_digest/index.json` → read the referenced NDJSON
  line(s), `line_no..line_end` → render the payload for the event type:
  `t`-ids → tool input + structured output **plus the mapped raw_text block**;
  `r`-ids → the raw_text block verbatim; `x`-ids → the verbatim text — all
  **decoded** (clean stdout/stderr, not escaped JSON) → slice.
- Why slicing is required: a PyMC fit's raw_text can be thousands of lines; the
  composer grabs `digest-get poet.r2.i2/r11 --tail 15` for a traceback without
  paying for sampler progress. (It is also how the composer pulls a cell's
  `stream` output — full or tail — to embed in the notebook, §5.)

**Text/reasoning events are first-class retrievable elements** (`x`-ids) — the
digest excerpts them truncated; the composer pulls full verbatim text by ID.
This is the material the notebooks narrate from.

**Invariant**: digest + `digest-get` are the composer's ONLY log interface.
The composer never reads raw NDJSON, mirroring "never read raw ipynb".

### 7.3 Relationship to timeline/TUI/viewer (agreed)

`timeline.py`, the connect TUI, and `viewer/session_data.py` do **not** consume
the digest (it is an LLM-facing rendering, a sibling projection — making the
TUI parse markdown would be backwards). What should eventually be shared is the
**derived-stats layer** (per-agent cost/duration rollups, tool-call inventories,
run-grouping-by-agent-name, artifact discovery), currently duplicated in
timeline.py and session_data.py and now needed a third time. Plan: digest ships
first computing its own stats; lifting shared helpers into the parser layer is
an **incremental, non-blocking** follow-up (§11.4).

## 8. Composer agent environment

- The composer is **dlab-internal**: its agent prompt is a template shipped as
  dlab package data (like `js/parallel-agents.ts`), NOT part of any dpack.
  Placeholder rules from CLAUDE.md apply (no hard-coded values; `<VALUE>`
  placeholders).
- dlab materializes the composer environment into the workdir at composer-launch
  time (analogous to `setupConsolidator`): composer agent `.md`, the five `nb-*`
  tools, `digest-get`, and permission config.
- **Permissions** (lesson from PR #38 encoded here): the composer does NOT need
  the `edit` permission — all its file writes go through the custom `nb-*`
  tools, which are not gated by the `edit` permission key. So: `read`/`glob`/
  `grep`/`list` allow; `edit` **deny**; `bash` **deny**; `task` **deny**;
  custom tools allowed. This is stronger sandboxing than the consolidator can
  have (which must write via the opencode `write` tool and therefore needs
  `edit` allowed).
- Model: resolved from `models.composer` role, falling back to `default_model`;
  passed via `--model` on the composer's `opencode run` invocation.
- The composer reads freely (digest, summaries, reports, scripts) but composes
  exclusively through tools.

## 9. Implementation map — where what changes

New files:

| Path | Contents |
|---|---|
| `dlab/session_digest.py` | Digest + index generation on top of `opencode_logparser` (`build_session_graph`, `parse_log_file`, tool/text/cost getters). Groups runs by agent name; shared per-agent event counter; artifact write chains from write/edit inputs; `--brief` flag as function arg. |
| `dlab/composer.py` | Orchestrates the composer step: generate digest, materialize composer env into workdir, launch `opencode run` (container via `exec_command`/`run_opencode`, or host in `--no-sandboxing` mode), collect/validate results, emit warnings. |
| `dlab/notebook_validation.py` | Host-side validation (§5): nbformat schema, ast.parse, path existence, import check via container exec. |
| `dlab/agents/composer.md` | Composer system-prompt template (package data; new `dlab/agents/` package-data dir, registered in pyproject like `js/`). |
| `dlab/js/nb_tools/*.ts` (or flat in `js/`) | `nb-add-markdown-cell`, `nb-add-code-cell`, `nb-edit-cell`, `nb-read`, `nb-finalize`, `digest-get` (package data). |
| `tests/test_session_digest.py` | Digest against fixture logs AND against a real bundled session fixture; ID stability; write-chain attribution; retry grouping; --brief. |
| `tests/test_notebook_validation.py` | Validation catches: invalid JSON, syntax errors, missing paths. |
| `tests/test_composer.py` | Env materialization, permission config (edit denied!), model role resolution, flag gating, non-fatal failure. |
| Source-level TS tests | In the style of `test_parallel_tool.py` for the new tools (registered as package data, key behaviors asserted in source). |

Changed files:

| Path | Change |
|---|---|
| `dlab/config.py` | Parse/validate `generate_jupyter_notebooks_from_run` (bool, default false). Extend `resolve_model_roles()` with `composer` role (falls back to `default_model`). Note: `apply_model_roles_to_opencode()` is NOT involved — composer model is passed on its own CLI invocation. |
| `dlab/cli.py` | `cmd_run`: after the orchestrator's opencode run and before post-run hooks, if flag set → digest → composer → validation (all non-fatal). CLI output gets a phase line (e.g. `[4/6] Composing notebooks …`). Works in both Docker and `--no-sandboxing` paths. |
| `dlab/model_fallback.py` | `preflight_check` must validate the `composer` role model like forecaster/consolidator. |
| `pyproject.toml` | Add `nbformat` to dependencies (host-side validation); register `dlab/agents/` + new TS files as package data; version bump on release. |
| `tests/test_config.py`, `tests/test_model_fallback.py`, `tests/test_session.py` | New key + role coverage, mirroring the #34 forecaster/consolidator tests. |
| `docs/decision-packs.md` | Field-reference rows: `generate_jupyter_notebooks_from_run`, `models.composer`; section on the notebooks output. |
| `docs/` (new page `docs/notebooks.md` + index) | User-facing docs: what gets generated, layout, runnability levels, provenance header, fit-then-load. |
| `.claude/CLAUDE.md` | Modules section (new modules), config key, model role, one-paragraph feature note. |
| **`.claude/skills/run-analyzer/SKILL.md`** | **Required update (Ben: "remember the run-analyzer skill needs updating")**: the skill predates `opencode_logparser` and documents manual NDJSON spelunking. Update it to (a) mention `_digest/digest.md` + `_digest/index.json` when present and prefer them over raw logs, (b) mention `notebooks/` as a first-class output to inspect, (c) stop hand-documenting the raw log format as the primary path. Then `python scripts/sync_skills.py --write` to republish `skills/dlab-cli/references/run-analyzer.md` (enforced by `tests/test_skill_sync.py`). |

## 10. Testing strategy

- Digest: golden-file test against a committed small fixture session (a
  trimmed poem run is a good candidate); property tests for ID monotonicity
  per agent and write-chain ordering.
- Notebook tools: source-level assertions (style of `test_parallel_tool.py`)
  plus, where cheap, executing the TS via `bun`/`node` in a temp dir to build a
  notebook and validating the result with `nbformat` in the test env.
- End-to-end: extend the poem pack manual validation flow (run with
  `generate_jupyter_notebooks_from_run: true`, assert `notebooks/00_overview.ipynb`
  exists and passes validation). Poem is the cheap E2E vehicle, as in PR #38.
- Per repo policy: no mocks; real files, real parser, real fixtures.

## 11. Explicitly deferred (do not build in v1)

1. `dlab notebooks <work-dir>` retrofit subcommand for completed sessions
   (design keeps it possible; not in v1).
2. Level C: `dlab notebooks --execute` with `long-running` skipping.
3. Per-dpack composer hints / output-dir config.
4. Derived-stats layer refactor (timeline + viewer + digest sharing rollups).
5. ~~Promoting `dlab digest` to a documented subcommand.~~ **Done** (Ben pulled
   this forward and shipped it with #85): `dlab digest [WORK_DIR] [--brief]
   [--write]` prints the digest to stdout, or with `--write` materializes the
   `_digest/` pair. The digest remains internal plumbing for the composer step;
   this is only a read/inspect surface over the same `build_digest`/
   `generate_digest` functions.

## 12. Open implementation checks (the only genuinely open points)

1. **Agent selection for the composer invocation**: prefer
   `opencode run --agent composer` if the pinned opencode version supports an
   agent flag; otherwise temporarily set `default_agent: composer` in the
   workdir's `opencode.json` (and add the composer agent/tools), restoring the
   original config afterwards (`try/finally`). Must not permanently mutate the
   session's `.opencode` (breaks `--continue-dir`).
2. Whether the composer needs the parent-traversal `git init` hack like
   parallel instances do (it runs in the workdir root, which dlab already
   `git init`s? — verify against the Known Hacks section behavior).
3. Exact `nb-read` truncation lengths and digest excerpt lengths (pick
   something, document in the tool descriptions; not worth spec ceremony).
4. `--no-sandboxing` composer path: import-check validation step degrades to a
   warning (no container to exec into) — confirm acceptable.

## 13. Prior art: `../ben-deepagent-MMM/` (recommended reading for the implementer)

Ben's ~2025 "MMM DeepAgent" project (sibling directory
`../ben-deepagent-MMM/`; backend `mmm-deepagent/src/mmm_deepagent/`, SvelteKit
frontend in `frontend/`) built an adjacent system: LLM agents editing real
notebooks via MCP cell tools, LangGraph traces normalized into a SQLite event
DB, and a web frontend reconstructing notebook views from the trace. Different
stack (LangGraph/deepagents/MCP/kernel-executed), so **reuse ideas, not code** —
but several pieces are directly instructive:

**Study for the `nb-*` cell tools** (§6):
- `server/app.py:209-930` — its cell-tool suite (`create_code_cell`,
  `create_markdown_cell`, `update_cell_source`, `execute_cell`,
  `write_notebook`). Same shape as ours: index-addressed cells, full-source
  replacement (no diffs). Also a nice **debug-cell convention**
  (`metadata.is_debug_cell=True`, filtered out at save, `app.py:741-745`) —
  consider if the composer ever needs scratch cells.
- **Pitfall recorded there**: purely positional `cell_index` addressing shifts
  on insert — brittle over long edit sessions. Our composer mostly *appends*,
  which sidesteps this; keep `nb-edit-cell` index-based but be aware.
- `server/output_minimizer.py:41-336` + `frontend/src/lib/messageParser.ts:222-263`
  — the **"placeholder in agent context, bytes on the side"** protocol
  (`<IMAGE: hash=…, size=…, dims=…>` placeholders, hash-correlated rehydration).
  This is independent validation of our two rules: LLM passes figure *paths*,
  and `nb-read` renders base64-stripped.

**Study for the digest** (§7):
- `frontend_server/database.py:36-63, 214-365` + migrations — event-stream
  schema: `messages.sequence` as the ordering/event ID and `tool_call_id` as
  the call↔result join key. Structurally identical to our
  shared-event-counter + ID-addressing decision; their
  `find_ai_message_with_tool_call` and `cli_export.build_tool_call_lookup`
  (`cli_export.py:33-72`) show clean call/result reassembly from a flat log.
- `message_handling.py` (esp. docstring lines 1-62) — provider-agnostic
  normalization of message streams into typed blocks; the cleanest module
  there, relevant to `digest-get`'s payload extraction.
- `frontend/src/lib/stores/notebooks.svelte.ts` — reconstructs a notebook view
  purely from the event trace (never reads ipynb), via tool_call_id
  correlation: the closest existing thing to "compose a notebook without
  executing it".

**Study only when building Level C `--execute`** (§11.2):
- `server/execution.py:32-133` — kernel hygiene lessons: forcing
  matplotlib inline/Agg + packaged matplotlibrc for reproducible plots,
  suppressing OpenMP/Fortran stdout that corrupts structured output; and
  `server/pre_minimizer.py` collapsing PyMC's 1000+ progress-bar updates.

**Does NOT transfer**: the MMM-domain analysis tools (`analysis/`,
`app.py:932-1530`), vision-based plot comparison, the vendored deepagents/
LangGraph plumbing. **Notably absent there**: `$`/math escaping and cell
schema validation do not exist in that codebase (markdown rendered raw) —
Ben's recollection of escaping logic was a gap he *hit*, not one he solved;
our §5/§6 escaping + validation requirements are new and necessary.

## 14. Traceability

The complete design dialogue, including every argument and rejected
alternative referenced above, is preserved verbatim in
[`notebook-composer-conversation.md`](notebook-composer-conversation.md).
It was extracted from the Claude Code session transcript with
[`extract_spec_conversation.py`](extract_spec_conversation.py) and can be
regenerated from `~/.claude/projects/<project>/0bad235c-8809-4ab7-a576-7cce0dc53ca2.jsonl`.
