# Handover — deterministic notebook skeleton + composer-on-skeleton (issue #68)

Written 2026-08-05 by Claude, at a clean checkpoint. Read `.claude/CLAUDE.md`
first, then the spec `.claude/specs/notebook-composer.md` (esp. §8.5), then this.
This session replaced the "LLM assembles notebooks from scratch" design with a
**deterministic-first** one: the host builds correct notebooks; the LLM only
curates + narrates.

## 0. The big idea (why this exists)

The old composer had the LLM *assemble* notebooks from the digest, and it kept
failing at the same class of things: hallucinated code, orphaned figures (a
`Image()` with no generating code), empty-output cells, non-adherence. Root cause:
we were asking the model to redo, by hand, a join that is **deterministic**. So we
inverted it:

1. **Deterministic (host, no LLM, hallucination-impossible):** compile a per-pack
   *code map* (tool → the real code it ran), then from a finished run build a
   *skeleton* — real code paired with the real output it produced — grouped into
   the adopted path + `attempts/`, with context hints back to the digest.
2. **LLM (the composer):** hand it the seeded notebooks and let it **curate +
   narrate** — it has *no tool to add or edit a code cell*, so it structurally
   cannot touch code. It inserts markdown (grounded via `digest-get` on each
   cell's hints), regroups, and authors `00_overview`.

Net: every failure class disappears by construction, the model step is ~3× cheaper
(~$1–1.5 vs ~$2.6 Sonnet / ~$8.8 Opus), and any model can produce a correct
notebook because it only writes prose + moves cells.

## 1. Branch / worktree state (ABSOLUTE PATHS)

- Repo root (main checkout): `/Users/bfmaier/Dropbox/business/projects_and_clients/pymc/decisionai/decision-lab`
- Session scratchpad: `/private/tmp/claude-501/-Users-bfmaier-Dropbox-business-projects-and-clients-pymc-decisionai-decision-lab/0bad235c-8809-4ab7-a576-7cce0dc53ca2/scratchpad`
- **Working branch:** `feat/notebook-skeleton` in worktree `<scratch>/wt-skeleton` (HEAD `93307a8`).
  It is **stacked on `feat/composer-step`** (which itself merges #87 session-digest
  + #89 nb-tools, neither merged yet). So the PR order is: merge #87, #89 →
  rebase `feat/composer-step` → rebase `feat/notebook-skeleton` → open its PR.
- Other worktrees (older, stacked): `wt-composer` (feat/composer-step), `wt-codemap`
  (feat/dpack-codemap, already merged into composer-step), `wt-digest-cmd` (#87),
  `wt-nb-tools` (#89).
- CRITICAL: shared checkout. Always `git branch --show-current` before git ops; do
  branch work only in worktrees; run worktree code from inside the worktree
  (`cd <wt> && ~/miniconda3/envs/dlab-testing/bin/python -m dlab.cli …`) so cwd wins
  on sys.path.

## 2. The pipeline and where each piece lives

All on `feat/notebook-skeleton`. Commits are one per step (see `git log
feat/composer-step..HEAD`).

**A. Per-pack code map — `dlab/dpack_codemap.py`, cmd `dlab map-dpack`**
Static, deterministic map of each custom tool → the real code it runs: parse the
TS wrapper (inputs, `python -m LIB.MOD`, inline `python -c`), resolve the Python
module (argparse, the level-2 entry function), and **reach *through* a
`modal.Function.from_name` dispatch** to the deployed body. Writes
`<dpack>/code_map.json` with source sha256s (staleness via `--check`).
- **Optional LLM pass** (`dlab map-dpack <dpack> --model … --env-file …`, opencode
  subprocess, once per pack): for CLI tools whose `main()` loads/transforms so
  there's no clean `fn(**inputs)` call, the model writes a parametrized
  `call_template` (load+call with `$input` placeholders) stored in the map. The
  per-run skeleton substitutes values deterministically. Deterministic rebuilds
  **preserve** templates. Running without `--model` prints a warning + suggests
  models from the provider keys it detects.

**B. Deterministic skeleton — `dlab/notebook_skeleton.py`, cmd `dlab skeleton`**
From a finished workdir + `--dpack`, build one notebook per agent into
`<workdir>/skeleton/`:
- **Cell = real code + real output.** Source = the script the agent wrote (replayed
  from write+edit events, keyed by basename so a `python foo.py` run shows the code
  *as of that run*), or — for a custom tool — a clean `from mod import fn; fn(args)`
  when the entry signature matches the inputs, else the LLM `call_template` filled
  with this call's values, else import+documented-invocation. Output = captured
  stdout/stderr + figures attributed by execution time-window (copies dropped).
- **Fix-arc dedup:** repeated runs of the same script (progressively edited to fix
  bugs) collapse to the **final** run. Keyed on script + real args with shell
  decorations (`2>&1 | head`, `timeout`) stripped. A **sweep** (same tool/script,
  *different args* → distinct outputs, e.g. budget at each risk level) is KEPT.
- **Phase-grouping + adopted/attempts:** the adopted instance is the one an agent
  promoted to the workdir root via `cp/mv/rsync <instance>/… <root>` (parsed,
  robust to compound `&&`). Adopted → numbered phase notebooks; the rest →
  `skeleton/attempts/`.
- **Context hints:** each code cell's `metadata.dlab` = `{kind, produced_by (digest
  tN id), streams (rN ids)}`, notebook-level `{agent qual, task=<agent>/p0, phase,
  adopted}`. Ids come from the digest's `_collect_agents` (qual + tool_calls) zipped
  to cells by order — VERIFIED to resolve in the digest index (test guards drift).

**C. Inspection + editing nb-* tools — `dlab/js/nb-*.ts`**
`nb-list` (survey), `nb-read` (base64-free + shows hints), `nb-insert-markdown-cell`,
`nb-move-cell` (verbatim move), `nb-delete-cell`, `nb-new`. Registered in
`notebooks.NB_TOOLS`. Tests run the REAL `.ts` via node on real `.ipynb` fixtures.

**D. Composer rewire — `dlab/notebooks.py`, agent `dlab/agents/notebooks.md`**
`generate_notebooks` now: digest → `write_skeletons` → seed `notebooks/` from
`skeleton/` (`_seed_notebooks_from_skeleton`) → launch the `notebooks` agent to
**curate that copy in place**. The prompt is "you are handed correct notebooks;
curate + narrate": inspect via nb-list/nb-read, `digest-get` each cell's hints for
the *why*, insert markdown, keep every distinct run (sweeps!), author `00_overview`,
finalize. **Frontmatter DENIES `nb-add-code-cell` + `nb-edit-cell`** → immutable
code. `skeleton/` stays as the pristine deterministic artifact.

## 3. Key decisions Ben made this session (don't re-litigate)

- **Invert to skeleton + LLM-curates** (not a plan-DSL; editing-in-place IS it).
- **marimo: NO** as the format — its `.py` stores no outputs and export re-executes;
  we assemble without executing (Modal fit ran for hours). ipynb-with-embedded-
  outputs stays. (marimo could be an optional "runnable" export later.)
- **LLM in the mapping, deterministic per run** — the code-map templates are the
  "few LLM steps" done once per pack, committed + reviewable.
- **Coarse cells first** (one per tool-call), not LLM-split per figure.
- **Ship the code-only skeleton as its own artifact** (`skeleton/`).
- **Code cells immutable** (composer has no code tool) — the guarantee.
- **Host pre-groups** phase + adopted/attempts (deterministic).
- **Custom-tool cells import+call**, not verbatim module dumps (his ask).
- **Fix-arc collapses to final; sweep (budget at N amounts) is KEPT** — the last
  refinement: bug-fix re-runs are noise; a parameter sweep is the comparison.

## 4. How to run / test

- Test env: `~/miniconda3/envs/dlab-testing/bin/python -m pytest tests/ -v`
  (Python 3.11 conda env; NOT bare python3). node installed (nb-tool tests use it).
- **Build a skeleton:** `cd <scratch>/wt-skeleton && dlab skeleton <workdir> --dpack <mmm-copy>`
- **Full composer run:** `dlab notebooks <workdir> --model anthropic/claude-sonnet-4-5 --dpack <mmm-copy> --env-file <repo>/.env`
- **The mmm dpack copy WITH LLM templates** is at `<scratch>/mmm-pack-copy`
  (its `code_map.json` has `call_template`s for the 5 CLI tools; rebuilt via
  `dlab map-dpack <mmm-copy> --model anthropic/claude-sonnet-4-5 --env-file <repo>/.env`).
- Validated runs (trimmed copies, in scratchpad): `nb-run-002` (from
  `~/dlab-demo/mmm-style-run-002`), `nb-sunrise` (from `~/dlab-demo/mmm-sunrise-run-001`).
  Trim recipe: `rsync -a --exclude='*.nc' --exclude='*.pkl' --exclude='*.parquet' --exclude='notebooks' --exclude='skeleton' --exclude='_digest' <src>/ <dst>/` (KEEP pngs).
- API keys in repo-root `.env`: ANTHROPIC + GOOGLE/GEMINI + a REAL OPENAI_API_KEY +
  `opencode_zen` (the gateway key, real). opencode exposes providers `anthropic`,
  `openai/*`, `google/*` directly (keys forwarded by the curated env), and
  `opencode/*` (gateway, incl. `deepseek-v4-pro/flash`, via stored login). Curated
  env forwards base vars + provider keys only.

## 5. Validation results (real)

- **Immutability proven byte-level** on both runs: 0 curated code cells differ from
  a skeleton cell in source OR outputs (composer only deletes/adds-markdown).
- **Fix-arc solved:** data-preparer 10→5 cells (6 `prepare_data.py` runs → 1);
  analysis notebooks have 0 near-duplicate code cells.
- **`00_overview`** reads like a decision memo (which alternatives failed & why,
  why the adopted instance won), narrative grounded in real numbers via the hints.
- **Cost** ~$0.95 (run-002) / ~$1.50 (sunrise), Sonnet.
- **Model comparison** (earlier, on the composer): Opus inlines best but slow/$8+;
  Sonnet solid; DeepSeek-pro tidy-but-shallow; DeepSeek-flash weak. Moot now — the
  deterministic skeleton makes the model choice far less critical.

## 6. Remaining work on #68 (rough order)

1. **Verify the sweep fix** — one more `dlab notebooks` run to confirm the composer
   now KEEPS all budget-sweep runs (prompt fix `93307a8` is untested by a run).
2. **Host-side nbformat validation** (spec §5) — `dlab/notebook_validation.py`, add
   `nbformat` dep; validate the curated notebooks.
3. **Wire the config flag** `generate_jupyter_notebooks_from_run` — auto-run
   `generate_notebooks` after the orchestrator in `cmd_run` (Docker + `--no-sandboxing`),
   non-fatal.
4. **Commit code maps into the in-repo dpacks** (with `--model` templates) so they
   ship; the mmm one currently lives only in the scratch copy.
5. **run-analyzer skill update** — point at `_digest/`, `skeleton/`, `notebooks/`.
6. **Rebase + PR** once #87/#89 merge; update `docs/` + spec §8.6 for this pipeline.
7. **Optional:** marimo runnable-export; full-fidelity in-container run.

## 7. How Ben works (match this)

Designs by arguing — bring a recommendation + push back; many good calls came from
him overruling a first proposal (import+call over dumps; keep the sweep; the whole
inversion). Corrects, expects clean concession (he caught the edit-replay bug and
the sweep over-deletion by reading output). Scopes crisply (yes/defer/explain).
Proper over quick. Tests where they earn it — behavioral for real logic, and he
explicitly asked the nb-tools to be tested on real `.ipynb` fixtures. Inspects the
actual output (`open .`, reads notebooks) — surface real artifacts via SendUserFile,
not claims. Sends mid-turn messages — fold them in. Cost-aware — report the real
number, flag before burning paid runs. Coordination-aware — worktrees only, never
clobber another branch; `merge those` = HIS PRs (#87/#89), not contributors'
(#31/#29). When posting to GitHub for him, lead with a note it's Claude writing.
