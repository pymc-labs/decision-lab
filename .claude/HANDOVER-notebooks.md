# Handover — notebook composer (`dlab notebooks`, issue #68)

_Written 2026-08-01 by Claude, mid-feature, so the next session can continue seamlessly. Read `.claude/CLAUDE.md` first (primary LLM reference), then the spec `.claude/specs/notebook-composer.md` (implementation-grade; §8.5 is the as-built delta), then this note._

## 0. Re-scan first

This note is state + decisions, not a substitute for reading the code. Before acting, re-read the spec (`.claude/specs/notebook-composer.md`) and the four key modules (`dlab/notebooks.py`, `dlab/session_digest.py`, `dlab/js/digest-get.ts`, `dlab/agents/notebooks.md`). **Directories to IGNORE** (run workdirs, not source): `~/dlab-demo/`, anything under the scratchpad that is a run (`nb-*`, `compose-*`, `gemini-composer-run`), and inside any workdir: `_digest/`, `_opencode_logs/`, `_docker/`, `_hooks/`, `parallel/`, `.opencode/`, `notebooks/`, `_notebooks.log`.

## 1. What this is

The **notebook composer** turns a finished dlab run into Jupyter notebooks that read like an analyst wrote them — narrated markdown + the run's **real code** + embedded figures — *assembled, never executed*. It runs as an opencode agent (the "notebook agent") that reads the run only through a deterministic **digest** + a `digest-get` retrieval tool, and writes only through cell-level `nb-*` tools. Parent issue: **#68**.

## 2. Branch / PR / worktree state (ABSOLUTE PATHS)

- **Repo root (main checkout, on `main`):** `/Users/bfmaier/Dropbox/business/projects_and_clients/pymc/decisionai/decision-lab`
- **Session scratchpad (worktrees + all run outputs live here):** `/private/tmp/claude-501/-Users-bfmaier-Dropbox-business-projects-and-clients-pymc-decisionai-decision-lab/0bad235c-8809-4ab7-a576-7cce0dc53ca2/scratchpad`

Three stacked feature branches, each in its own git worktree:

| Worktree (absolute) | Branch | PR | Contents |
|---|---|---|---|
| `…/scratchpad/wt-digest-cmd` | `feat/session-digest` | **#87 (open)** | session digest + `dlab digest` + provenance redesign + custom-tool-source |
| `…/scratchpad/wt-nb-tools` | `feat/nb-tools` | **#89 (open)** | the six `nb-*` tools + `dlab/agents/notebooks.md` (the agent prompt) |
| `…/scratchpad/wt-composer` | `feat/composer-step` | **not yet PR'd** | `dlab notebooks` command + `dlab/notebooks.py`; **merges #87 + #89** and holds the newest spec + this handover |

**`feat/composer-step` is the working branch** — it has everything merged and is where all recent code lives. It is stacked on two unmerged PRs, so its own PR is deferred: **once Ben merges #87 and #89, rebase `feat/composer-step` onto `main` and open the clean `dlab notebooks` PR** (just `dlab/notebooks.py` + the command + config role + tests + spec + this handover).

**CRITICAL — shared checkout / worktrees:** always `git branch --show-current` before any git op; do all branch work in worktrees; never switch the main checkout's branch. The Bash tool resets cwd to the repo root each call, so use absolute paths or `cd` inside a compound command. To run worktree code without repointing the editable install, run from inside the worktree (`cd <wt> && ~/miniconda3/envs/dlab-testing/bin/python -m dlab.cli …`) — cwd wins on `sys.path`.

## 3. What changed vs the ORIGINAL spec (the deltas that matter)

The spec has been revised to match reality (§7.1 note dated 07-30, §7.4, §8.5, §8.5.1, §11.1). Summary of everything that moved off the original plan:

1. **`dlab digest` shipped** (was deferred §11.5) — read/inspect surface over the digest.
2. **Digest redesign (provenance-first)** — every artifact links to the tool call that produced it (`← written tN` / `← from tN` via mtime-in-window); parent's `cp`'d files show, linked to the copy; untouched inherited copies dropped by sha256; **raw_text is a first-class `r`-id** (the majority of a real log — tracebacks, sampler output — mapped to its tool call); all producing tool calls labeled; **custom-tool source bundled into the `tN` retrieval** so the agent can reproduce what a tool ran.
3. **`nb-note` (6th tool) + preamble invariant** — first cell is always a markdown preamble (provenance + disclosures).
4. **Retrievable small text artifacts** — `.json/.csv/.md` ≤32KB get a shape hint + a retrievable `aN` id.
5. **The whole feature renamed** `compose`/`composer` → `notebooks` (Ben: "compose is WAY too ambiguous", option B / global). Command `dlab notebooks`, module `dlab/notebooks.py`, `generate_notebooks()`, agent file `dlab/agents/notebooks.md`, `--agent notebooks`, config role **`models.notebooks`**. Default model example changed Haiku → **Sonnet** (empirically the best grounded/cost tradeoff).
6. **The step was built as a standalone command FIRST** (Ben's call) rather than wired into the run lifecycle. The config flag `generate_jupyter_notebooks_from_run` is **not yet wired**.
7. **Robustness fixes found by running on Anthropic** (Gemini's leniency hid them): tool isolation, curated subprocess env, retry+backoff, `_notebooks.log` persistence (see §8.5).
8. **The prompt now HARD-forbids inventing code** (replaced the softer "verbatim from scripts" wording). Discovered a real run had 8 retrievals / 41 code cells → mostly hallucinated model code. After the rule, Sonnet and Opus both inline the **verbatim** scripts.

## 4. THE CURRENT LIVE PROBLEM (where we stopped)

Notebooks only reach **level-1** reproduction of tool-generated outputs — a CLI invocation like `!python -m mmm_lib.analyze_model_cli …` — instead of the actual library code, because the agent **can't reach the dpack's library source**. The run's workdir has only the tool *wrapper* (`fit-model-modal.ts`, which shells out to `python -m mmm_lib.MOD`), and `mmm_lib` isn't installed in a local run. **The real source exists in the dpack:** `/Users/bfmaier/Dropbox/business/projects_and_clients/pymc/decisionai/decision-lab/decision-packs/mmm/docker/mmm_lib/{fit_model_modal.py,analyze_model_cli.py}` — it was just never exposed.

**Agreed direction (spec §8.5.1), general, no `mmm_lib` hardcoding:** when `--dpack` is given, copy the pack's library source (ships under `docker/`) into a readable workdir spot (e.g. `_dpack_source/`) and tell the agent in `notebooks.md`: "if a custom tool shells out to `python -m LIB.MOD`, its real source is under `_dpack_source/LIB/MOD.py` — read it and inline the actual code (level 2/3)." Clean up after.

**DECISION STILL OWED BY BEN:** the *analysis* tool is local plotting (`az.plot_*`) and should inline; the *fit* tool runs remotely **on Modal**, so inlining its body fabricates a local fit that never happened — its faithful form is the invocation + a note. Rule stays "deepest *faithful* level." Ben needs to say whether the Modal fit stays an invocation or inlines `fit_model_modal.py`. **Do not implement the depth fix until that's settled.**

## 5. Key source files (all under the repo root or a worktree)

- `dlab/notebooks.py` (was `composer.py`) — `generate_notebooks(work_dir, *, model, dpack, env, timeout)`; `materialize_notebook_env`, `_isolate_notebook_tools`, `_notebook_env` (curated env), retry loop, `_notebooks.log`. On `feat/composer-step`.
- `dlab/agents/notebooks.md` — the notebook agent's system prompt (the "NEVER invent code" rule, digest-only, `nb-*`, 3→2→1, disclosure). On `feat/nb-tools` (#89) and merged into composer-step.
- `dlab/session_digest.py` — `build_digest`/`generate_digest` (+ `generate_digest` now copies custom-tool sources to `_digest/tool_sources/`). On #87 + merged.
- `dlab/js/digest-get.ts`, `dlab/js/nb-*.ts` (6 tools) — package data, run under opencode/Bun.
- `dlab/config.py` — `resolve_model_roles()` now returns a `notebooks` key.
- `dlab/cli.py` — `dlab notebooks` command (`cmd_notebooks`).
- Tests: `tests/test_notebooks.py`, `tests/test_nb_tools.py`, `tests/test_session_digest.py`, `tests/test_config.py`.
- Spec: `.claude/specs/notebook-composer.md` (see §8.5 / §8.5.1); verbatim design dialogue in `.claude/specs/notebook-composer-conversation.md`.

## 6. How to run / test it

- **Test env:** `~/miniconda3/envs/dlab-testing/bin/python -m pytest tests/ -v` (Python 3.11 conda env, NOT bare python3). node is installed (the nb-tool tests run real TS via node's type-stripping); `nbformat` is NOT installed.
- **Run the command (from the composer worktree so cwd wins on sys.path):**
  ```
  cd …/scratchpad/wt-composer
  ~/miniconda3/envs/dlab-testing/bin/python -m dlab.cli notebooks <WORKDIR> --model anthropic/claude-sonnet-4-5 --env-file <repo>/.env
  ```
  It needs a completed workdir with `_opencode_logs/` and the dpack's `.opencode/tools/`. A good source run: `~/dlab-demo/dlab-mmm-agent-oc-workdir-008`. Build a test copy with `rsync -a --exclude='*.nc' --exclude='*.pkl' --exclude='_digest' --exclude='notebooks' <src>/ <dst>/` (keep `.opencode/` so custom-tool sources surface; drop the huge binaries).
- **API keys:** repo-root `.env` has ANTHROPIC + GOOGLE(GEMINI) keys. It ALSO has junk (`opencode_zen`, `MODAL_*`, `OPENAI_API_KEY`) — the curated env drops all of it; do not forward the whole env to opencode.
- **opencode is installed locally** at `~/.opencode/bin/opencode` (v1.18.9). Models it knows: `anthropic/claude-{sonnet,opus}-4-…`, `google/gemini-3-flash-preview`, etc. The agent name comes from the `.md` filename (`notebooks.md` → `--agent notebooks`).
- **Existing run outputs to compare (in scratchpad):** `nb-opus/` (Opus 4.8, 7 notebooks incl. separate `attempt_*`), `nb-sonnet-noinvent/` (Sonnet, grounded), plus older `nb-sonnet-*`, `gemini-composer-run/`. A Python mirror of digest-get for inspecting runs: `…/scratchpad/digest_get.py`.

## 7. Model / cost findings (real, from run logs)

Same source run, all with the no-invent prompt, code now **grounded** (verbatim scripts, 3/3 real helpers):
- **gemini-3-flash-preview:** ~$0.05–0.15/run; composes but narrates least; doesn't use `nb-note`.
- **claude-sonnet-4-5:** ~$2.6/run; grounded; solid; folds alternatives into one summary.
- **claude-opus-4-8:** ~$8.8/run; most thorough — 7 notebooks incl. separate `attempt_*` per non-adopted plan, retrieves the failed instance's real error. ~3.3× Sonnet.

Recommendation encoded in spec §2: **Sonnet as a sensible grounded default; Opus when thoroughness is worth 3×.** Cost is dominated by cache-reads (context re-sent per turn but cached).

## 8. Remaining work on #68 (rough order)

1. **The reproduction-depth fix (§4 above)** — pending Ben's Modal decision.
2. **Wire the config flag** `generate_jupyter_notebooks_from_run` — auto-run the step after the orchestrator in `cmd_run` (both Docker and `--no-sandboxing`), non-fatal.
3. **Full-fidelity / container path** — run the step inside the dpack container (where the library is installed) instead of locally; this also solves §4 more cleanly than copying source.
4. **Host-side nbformat validation** (spec §5) — `dlab/notebook_validation.py`, add `nbformat` dep.
5. **`run-analyzer` skill update** (spec §9 / §10) — point it at `_digest/` + `notebooks/`.
6. **Rebase `feat/composer-step` onto main and open its PR** once #87 + #89 merge.
7. Cut the **v0.3.0 GitHub release** (still owed from the audit sweep; PyPI publishes on release).

## 9. How Ben works (match this)

- **Designs by arguing.** For anything non-trivial he wants to debate the approach *before* code — placement, tradeoffs, rejected alternatives. Bring a recommendation and push back with reasoning; don't just execute. Many good calls came from him overruling a first proposal (cell-by-cell tools; "more files" expander; keeping stdout/stderr merged; the general `3→2→1` reproduction; the hard "never invent code" rule).
- **Corrects, expects clean concession.** When he says "you're wrong because…" he's usually right about the local detail — verify, concede plainly, fold it in. (E.g. he caught the hallucinated code by *reading the notebooks*; he was right.)
- **Scopes crisply.** Rapid fix/won't-fix/defer/explain verdicts. "I don't get it" = give a concrete explanation of that one thing, then he decides.
- **Proper over quick.** Accepted new deps (ruamel.yaml) to do it right vs a hack. Offer the right solution and note the cost.
- **Tests where they earn it.** Behavioral tests for real logic; source-guards for structural fixes; nothing for nits. For correctness-critical things the test must *demonstrate* the failure is gone.
- **Inspects the actual output.** He opens the notebooks/dirs (`open .`, `open <dir>`) and reads them; surface real artifacts (SendUserFile renders + `open`), not just claims. He caught two real bugs (orphaned figures, hallucinated code) by looking.
- **Sends mid-turn messages.** New instructions arrive while you work — fold them in.
- **Cost-aware.** He asks "how much is a run" — report the real number from the log, and flag before burning multiple paid runs.
- **Coordination-aware.** Runs multiple agents in one checkout; never clobber another branch; worktrees only.
- **Cadence:** small PRs, merge often, keep the board clean. "merge those" = HIS PRs, not contributors' (#31/#29). When posting to GitHub on his behalf, lead with a note that it's Claude writing for Ben.

## 10. Optional immediate next step

The natural continuation is **the reproduction-depth fix (§4)** — but it is **blocked on Ben's Modal decision** (invocation vs inline `fit_model_modal.py`). Ask that first. Everything else (config-flag wiring, container path, validation, skill, PR rebase) is unblocked but lower-priority than closing the depth gap he just flagged.
