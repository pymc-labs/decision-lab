# dlab v0.4.0

The first release since v0.2.0 (0.3.0 was an internal version bump that was never published), so this roll-up covers everything landed since v0.2.0. The headline is **automatic, trustworthy Jupyter notebooks from any run** — alongside a large batch of features, robustness, and polish.

## ✨ Headline: deterministic notebook composition (#94)

`dlab notebooks <work-dir>` (or `dlab run --notebooks`) turns a finished run into narrated Jupyter notebooks — **deterministic-first**: the host assembles correct notebooks from what actually ran, and an LLM only curates and narrates them. It has no tool that can write or edit a code cell, so **the code in a notebook is always exactly the code that ran** — no hallucinated cells, no orphaned figures, no empty outputs, no fabricated numbers.

- **`dlab digest`** — a deterministic, LLM-facing map of a run.
- **`dlab map-dpack`** — wires each custom tool to the real library code it ran (reaching *through* Modal dispatches), committed per pack; an optional one-time LLM pass produces clean `load+call` cells.
- **`dlab skeleton`** — pairs real code with the real output it produced, one notebook per agent; collapses buggy-then-fixed reruns to the final version, keeps parameter sweeps, separates the adopted path from `attempts/`.
- **Composer** — inserts markdown grounded in the run's own reports, deduplicates noise, authors an overview; **never fabricates a number**.
- **Auto-compose** — `dlab run --notebooks` / `--no-notebooks`, `--notebooks-model`, `DLAB_ALWAYS_RUN_NOTEBOOKS_COMPOSER`, or `generate_jupyter_notebooks_from_run: true` in a pack.

## 🎨 Other features

- **House figure style** (#90) — every session (orchestrator + parallel instances + library plots) renders a consistent, colorblind-validated matplotlib style; opt out with `use_dlab_plot_style: false`.
- **Explicit `dlab run` subcommand** on a Typer-based CLI (#39, #30) — the bare `dlab --dpack …` shorthand still works.
- **Model-catalog freshness, failure diagnosis & opencode version pinning** — packs pin the opencode release current at creation; clearer messages when a model id dies upstream; opencode's opaque failures mapped to readable hints.
- **event-forecaster decision pack** (#34).
- **Faster, more robust TUI** (#33).

## 🔧 Fixes & hardening

- Curate the environment passed to parallel subagents (#71 / #56); consolidator write-permission fix + opt-out (#38).
- Artifacts: open without a shell (#70 / #57 / #62), bound reads by size with a card for large/binary files (#77 / #55), "more files" expander for non-curated artifacts (#78 / #48).
- Logs / TUI: find the start model past leading log noise (#73 / #61), dedup events by content not timestamp (#72 / #58), guard parallel-agents stream readers (#83 / #45), full-text search (#60).
- Gantt running bar + wizard task-permission footgun (#84 / #64 / #47); model fallback only rewrites `.md` frontmatter (#75 / #51); proper YAML parsing + deduped dev deps (#82); spinner thread leak & copy excludes (#81); empty-log timeline, pixi PATH, non-interactive `--continue-dir` (#74).

## 🧪 Testing

- Committed golden session fixture + integration tests (#79); headless boot smoke test for the `connect` TUI (#76).
