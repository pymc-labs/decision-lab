# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

dlab is a Python CLI that runs [opencode](https://opencode.ai) in automated mode, sandboxed with Docker, with built-in parallel subagent capabilities. The CLI runs locally and orchestrates Docker containers running opencode via `docker exec`.

## Development Environment

- Python 3.10+, Docker required
- Virtual environment: Always use `venv/` (not `.venv/`)
- Activate: `source venv/bin/activate`
- Install dev dependencies: `pip install -e ".[dev]"`

### Running Tests

```bash
# All tests
~/miniconda3/envs/dlab-testing/bin/python -m pytest tests/ -v

# Single test file
~/miniconda3/envs/dlab-testing/bin/python -m pytest tests/test_config.py -v

# Single test
~/miniconda3/envs/dlab-testing/bin/python -m pytest tests/test_config.py::test_function_name -v
```

- NEVER use mocks - tests use real implementations
- NEVER skip tests - report failures and ask user whether to ignore or start resources
- Do NOT set `PYTESTER_FLAGS="cxx="` - C++ compilation is faster for PyTensor deterministics

## Running the CLI

**IMPORTANT: This is how you run the CLI. Do not forget.**

```bash
# Basic usage
dlab run --dpack <dpack> --data <data-dir> --env-file .env --work-dir <work-dir> --prompt "Your prompt here"

# Multiple data files
dlab run --dpack <dpack> --data file1.csv file2.csv --prompt "Compare these"

# Resume interrupted session
dlab run --dpack <dpack> --continue-dir ./dlab-mmm-workdir-001 --prompt "Continue"

# Prompt from file
dlab run --dpack <dpack> --data <data-dir> --prompt-file prompt.txt
```

The `run` subcommand may be omitted as a shorthand (`dlab --dpack ...` works identically).

Required flags:
- `--dpack` - Path to decision-pack config directory
- `--data` - Data files or directory (optional if decision-pack sets `requires_data: false`)
- `--env-file` - Environment file with API keys (auto-detected from decision-pack `.env`)
- `--prompt` or `--prompt-file` - Prompt text or file (optional if decision-pack sets `requires_prompt: false`)

Optional flags:
- `--model` - Override default model from config
- `--work-dir` - Explicit work directory path
- `--continue-dir` - Resume from a previous session's work directory
- `--rebuild` - Force rebuild Docker image
- `--no-sandboxing` - Run opencode locally without Docker (via `local.py`); copies `docker/` into the work dir as `_docker/` and instructs the agent to provision its own environment
- `--notebooks` / `--no-notebooks` - Compose Jupyter notebooks from the run when it finishes successfully (tri-state; overrides the pack's `generate_jupyter_notebooks_from_run` and `DLAB_ALWAYS_RUN_NOTEBOOKS_COMPOSER`)
- `--notebooks-model` - Model for the notebook composer (distinct from `--model`, the orchestrator; else `models.notebooks` / `DLAB_NOTEBOOKS_MODEL` / `default_model`)

Environment variables starting with `DLAB_` are automatically forwarded from the host to the Docker container. decision-packs can use these for configuration (e.g., `DLAB_FIT_MODEL_LOCALLY=1` in the MMM decision-pack). Two host-side `DLAB_` vars affect the notebook composer: `DLAB_NOTEBOOKS_MODEL` (global default composer model) and `DLAB_ALWAYS_RUN_NOTEBOOKS_COMPOSER=1` (compose after every successful run).

**Auto-composing notebooks after a run:** `dlab run` composes notebooks itself when the `--notebooks` flag, the `DLAB_ALWAYS_RUN_NOTEBOOKS_COMPOSER` env var, or the pack's `generate_jupyter_notebooks_from_run: true` config key asks for it (that precedence order; `--no-notebooks` force-disables). Only on exit code 0; a composer failure warns but never changes the run's exit code. Wired in `cli.py` via `_should_compose_notebooks()` + `_maybe_compose_notebooks()`, reusing `cmd_notebooks`.

### Subcommands

```bash
# Interactive wizard to create a new decision-pack
dlab create-dpack [OUTPUT_DIR]

# Compile a decision-pack's deterministic code map (code_map.json)
dlab map-dpack <dpack> [--check]

# Build deterministic notebooks (real code + real outputs, no LLM) into skeleton/
dlab skeleton <work-dir> [--dpack <dpack>]

# Compose narrated notebooks from a finished run (skeleton + LLM curation)
dlab notebooks <work-dir> --model <provider/model> [--dpack <dpack>] [--env-file <file>]

# Interactive wizard to create a parallel agent config
dlab create-parallel-agent [DPACK_DIR]

# Install decision-pack as a shortcut command
dlab install <dpack-path> [--bin-dir PATH]

# Live-monitor a session (TUI)
dlab connect <work-dir>
# (--log and --log-json flags exist but are not yet implemented)

# View execution timeline with Gantt chart
dlab timeline [work-dir]

# Browser-based session viewer (DAG visualization)
dlab view <work-dir> [--port PORT] [--no-open] [--export FILE]

# Print (or write) a deterministic session digest
dlab digest [work-dir] [--brief] [--write]
```

## Coding Style

### Formatting & Organization
- Manual PEP8 formatting (no Black/Ruff)
- Imports: Always at top of file, sorted with isort (stdlib, third-party, local)
- File organization: Constants -> Functions & Classes (grouped logically) -> main
- File naming: snake_case (my_module.py)
- String formatting: f-strings preferred

### Type Annotations
- Full type annotations on all functions and variables

### Documentation
- NumPy-style docstrings with Parameters/Returns sections

### Error Handling
- Use built-in exceptions (ValueError, TypeError, etc.) with descriptive messages
- NEVER catch errors for functions that have their own error handling
- NEVER wrap code in generic `try/except Exception: pass` or `except: pass`
- Minimal logging: only errors and critical info

### Patterns to AVOID
- Global mutable state, singletons
- Over-abstraction (unnecessary base classes/interfaces)
- Classes where simple functions suffice (project is function-heavy)
- Imports anywhere except top of file

### Configuration
- Plain dictionaries loaded from YAML (config.yaml)
- No pydantic or dataclasses for config

### Agent System Prompts (in opencode/agents/*.md)
- NEVER put hard-coded values in agent system prompts
- Use placeholder syntax like `<VALUE>`, `<CHANNEL_COLS>`, `<DATE_COLUMN>` instead
- Keep examples minimal with placeholders - prompts are templates, not implementations

## Project Architecture

- decision-pack config contains: `docker/`, `opencode/`, `config.yaml`
- decision-packs that bundle a custom Python library under `docker/` must ship a pytest suite in `<pack>/tests/` for its deterministic logic (reference: `decision-packs/mmm/tests/`)
- CLI orchestrates Docker containers running opencode
- Communication via `docker exec`
- Session state in JSON files for resumption
- Containers automatically stopped on completion, error, or interrupt (SIGINT/SIGTERM)
- Work directories are auto-numbered: `dlab-{dpack}-workdir-001`, `dlab-{dpack}-workdir-002`, etc.

## Modules (in `dlab/`)

- `cli.py` - Typer-based CLI, subcommands, Rich output
- `config.py` - decision-pack config loading and validation, model-role resolution (`resolve_model_roles`, `apply_model_roles_to_opencode`)
- `session.py` - Session creation and state management
- `docker.py` - Docker image building and container lifecycle
- `local.py` - Local (no-Docker) execution backend for `--no-sandboxing`
- `model_fallback.py` - Model validation and provider fallback (`preflight_check` before session creation, `process_opencode_dir` during setup) so a single API key suffices
- `figure_style.py` - decision-lab matplotlib house style (`figure_style_enabled`, `install_figure_style`, `figure_style_shell_exports`); vendored assets in `data/figure_style/` (matplotlibrc, dlab_plotstyle.py, SKILL.md)
- `opencode_logparser.py` - Canonical OpenCode NDJSON log parser (`LogEvent`, `SessionNode`, `parse_log_file`, `build_session_graph`); single source of truth used by `timeline.py`, `tui/`, and `viewer/`; `diagnose_fatal_error` maps opencode's opaque failures to readable hints
- `session_digest.py` - Deterministic session digest for the notebook composer (`build_digest`, `generate_digest`); builds `_digest/digest.md` + `_digest/index.json` on top of `opencode_logparser`. Surfaced by the `dlab digest` subcommand.
- `js/digest-get.ts` - In-container retrieval tool (loaded as `DIGEST_GET_SOURCE`) that reads one indexed NDJSON line by ID and renders it decoded/sliced
- `parallel_tool.py` - Loads parallel-agents.ts from `js/`
- `js/parallel-agents.ts` - TypeScript source bundled as package data
- `data/models.json` - Bundled models.dev model list (package data)
- `timeline.py` - Timeline visualization (parsing delegated to `opencode_logparser.py`)
- `dpack_codemap.py` - Decision-pack code map (`build_code_map`, `write_code_map`, `stale_sources`, `entry_params`, `extract_call_templates`); statically maps each custom tool to the real code it runs (the Python library behind `python -m LIB.MOD`, or the deployed function reached *through* a `modal.Function.from_name` dispatch). Compiled once per pack into `<dpack>/code_map.json` (with source-file sha256s for staleness). **Optional LLM pass** (`map-dpack --model`, opencode subprocess, once per pack): for CLI tools whose `main()` loads/transforms so there's no clean `fn(**inputs)` call, the model writes a parametrized `call_template` (load+call with `$input` placeholders) stored in the map; deterministic rebuilds preserve it. Consumed by the deterministic notebook builder. Exposed as `dlab map-dpack`.
- `notebook_skeleton.py` - **Deterministic** notebook builder (`build_skeleton`, `write_skeletons`); no LLM. Pairs the real code that ran (scripts the agent wrote; the code map's resolved library code for custom tools) with the real output it produced (captured stdout + figures attributed by execution time-window), one coarse cell per execution, one notebook per agent, into `<work_dir>/skeleton/`. Collapses fix-arc re-runs to the final version, keeps parameter sweeps, splits adopted path from `attempts/`, and tags each cell with digest-aligned context hints. Correct by construction (no hallucinated code, no orphaned figures, no empty-output cells); a shippable artifact and the substrate for the LLM-narrated notebook. Exposed as `dlab skeleton`.
- `notebooks.py` - The **notebook composer** step (`generate_notebooks`): digest → build the skeleton → seed `notebooks/` from it → launch the `notebooks` opencode agent (`dlab/agents/notebooks.md`) to **curate + narrate** that copy in place. The composer's frontmatter denies `nb-add-code-cell`/`nb-edit-cell`, so it structurally cannot write or alter code — it only inserts markdown (grounded via `digest-get` + the run's own report files), regroups, deduplicates noise, and authors `00_overview`; it never fabricates a number. Curated env + retry as before. Exposed as `dlab notebooks`.
- `create_dpack.py` - Programmatic decision-pack generation (used by wizard and skills); model catalog (bundled models.json + TTL-cached background refresh, `refresh_model_cache_if_stale`), pins `opencode_version` at creation (`resolve_latest_opencode_version`)
- `create_dpack_wizard.py` - TUI wizard for `create-dpack` command (8 screens, Textual-based)
- `create_parallel_agent_wizard.py` - TUI wizard for `create-parallel-agent` command
- `tui/` - TUI module for `connect` command:
  - `app.py` - Main Textual app
  - `log_watcher.py` - File watcher for live log updates
  - `models.py` - Data models for log events
  - `widgets/` - Agent list, log view, artifacts pane, search, status bar
- `viewer/` - Browser-based session viewer for `view` command:
  - `server.py` - FastAPI app with JSON API and file serving
  - `session_data.py` - SessionNode tree → flat node/edge dicts
  - `layout.py` - DAG layout algorithm (time axis + lane stacking)
  - `html/viewer.html` - Single-file frontend (SVG DAG + detail panel)

## Hooks (pre-run / post-run)

decision-packs can define hook scripts in `config.yaml` that run inside the container:

```yaml
hooks:
  pre-run: deploy_modal.sh          # single script
  post-run: [cleanup.sh, report.sh] # or a list
```

- Scripts live in the decision-pack root and are copied to `_hooks/` in the work dir
- If any hook fails (non-zero exit), the session aborts
- Hooks run once per session (parallel instances do not re-run them)

## Model Roles (config.yaml)

decision-packs can override models per role via an optional `models:` block in `config.yaml`:

```yaml
default_model: anthropic/claude-sonnet-4-5    # orchestrator model
models:
  forecaster: anthropic/claude-haiku-4-5      # parallel agent instances (optional)
  consolidator: anthropic/claude-sonnet-4-5   # consolidator (optional)
  notebooks: anthropic/claude-sonnet-4-5      # notebook composer (optional)
```

Omitted roles fall back to `default_model`. `resolve_model_roles()` in `config.py` resolves the roles; `apply_model_roles_to_opencode()` injects forecaster/consolidator into each YAML under `parallel_agents/` during session setup. The **composer** model (`dlab notebooks`) resolves via `_resolve_notebooks_model()` in `cli.py`: `--model` > the pack's explicit `models.notebooks` > the `DLAB_NOTEBOOKS_MODEL` env var (a user's global default) > `default_model`.

## Figure Style (config.yaml)

Sessions enforce the decision-lab matplotlib house style by default; packs opt out with `use_dlab_plot_style: false`. Enforcement is layered by robustness (environment > injected code > prompt):

1. `_style/matplotlibrc` written at session setup, activated via `MATPLOTLIBRC` exported in the opencode runner script — styles every figure with zero agent cooperation. `_style` is *prepended* to `PYTHONPATH` (never clobbered).
2. `_style/dlab_plotstyle.py` — palette by name (`PALETTE`/`PALETTE_LIGHT`/`PALETTE_DARK`), house colormaps (`dlab_seq` default for imshow, `dlab_div` for signed data), `add_axis_end_tick_caps`. On import it ENFORCES the forbidden things: band edges (`fill_between` edge/linewidth kwargs dropped even when explicit — arviz/pymc-marketing outline their HDI bands), legend frames (`frameon` dropped), text `bbox` boxes (dropped), suptitle ink.
3. `dlab-figure-style` skill injected into `.opencode/skills/` — judgment rules code cannot enforce (no `sns.set_theme()`/`plt.style.use()`, scatter `color=` trap, grid XOR reference lines, z-order, shared legends). `parallel-agents.ts` always copies this skill to instances.

Inter fonts are installed in the wrapper Docker image (warns instead of failing on download errors; DejaVu fallback), and the wrapper removes any matplotlib font cache baked into the base image — a stale cache silently hides the fonts (conda bases bake one). Both env vars reach parallel instances via the instance env allowlist (`MATPLOTLIBRC` is in `INSTANCE_ENV_EXACT`). The palette cycle order is CVD-validated — do not reorder it. Assets live in `dlab/data/figure_style/`; keep `PALETTE` in `dlab_plotstyle.py` and the rc `axes.prop_cycle` in sync (checked by `tests/test_figure_style.py`). `scripts/figure_style_gallery.py` renders a deterministic proofsheet for style iteration.

Migrating a pack: remove any style rules from its agent prompts (a system prompt beats the injected skill — the pre-migration MMM pack mandated `seaborn-v0_8-whitegrid` and won) and any import-time `plt.style.use`/`rcParams` writes from bundled libraries; libraries should use `"C0"`/`"C1"` cycle references and may activate enforcement at their boundary via a `find_spec`-guarded `import dlab_plotstyle` in `__init__.py` (see `mmm_lib`).

## Known Hacks / Technical Debt

### Git Init Hack in Parallel Agents (EVIL HACK - FIX LATER)

In `parallel_tool.py`, we run `git init` in each parallel instance directory. This is a horrible hack to work around OpenCode's config traversal behavior.

**The Problem**: OpenCode traverses UP the directory tree looking for `.opencode/` configs and merges them. Subagent instances can see the parent's agents and get confused about their role.

**The Hack**: Running `git init` makes OpenCode think it's a project root, stopping upward traversal.

**Proper Fix**: OpenCode should have a config option to disable parent directory traversal, or instances should run in completely isolated paths.

### Consolidator Setup (Auto-generated)

The consolidator agent is auto-generated from `summarizer_prompt` in parallel agent YAML config. It does NOT require a separate `consolidator.md` file.

`setupConsolidator()` in `js/parallel-agents.ts` creates:
- Inline `consolidator.md` agent (read + write, no bash)
- `opencode.json` with hardcoded permissions: reads and file writes allowed, bash/task denied. IMPORTANT: opencode gates the `write` tool behind the `edit` permission key — the consolidator must be able to write `consolidated_summary.md`, since only that file's content reaches the orchestrator (stdout is discarded). Denying `edit` silently discards the consolidator's entire output.
- No custom tools directory

The consolidator runs automatically when >2 parallel instances complete, reading all `summary.md` files and creating a consolidated comparison. Setting `consolidator: false` in the parallel agent YAML skips it entirely — the orchestrator then gets the per-instance summary paths and compares them itself.

## Documentation Maintenance

When making changes, update documentation as needed:

| Change Type | Files to Update |
|-------------|-----------------|
| New CLI command/flag | `.claude/CLAUDE.md`, `docs/cli-reference.md` |
| New module | `.claude/CLAUDE.md` (Modules section) |
| Parallel agents behavior | `docs/parallel-agents.md` |
| Log format/processing | `docs/log-processing.md` |
| Docker/container changes | `docs/docker.md` |
| Session/state changes | `docs/sessions.md` |
| decision-pack config changes | `docs/decision-packs.md` |
| Known hacks | `.claude/CLAUDE.md` (Known Hacks section) |
| Skill content (`.claude/skills/`) | `.claude/skills/` is the source of truth; after editing, run `python scripts/sync_skills.py --write` to republish `skills/dlab-cli/references/` (checked by `tests/test_skill_sync.py`) |

### Documentation Files

| File | Purpose |
|------|---------|
| `.claude/CLAUDE.md` | Primary LLM reference - architecture, coding style, CLI, known hacks |
| `README.md` | Primary human reference - overview, installation, quick start |
| `docs/cli-reference.md` | Complete CLI command reference |
| `docs/parallel-agents.md` | Parallel agent system, consolidator, timeline |
| `docs/log-processing.md` | Log file format, event types, TUI/timeline processing |
| `docs/docker.md` | Docker integration details |
| `docs/sessions.md` | Session lifecycle and state management |
| `docs/decision-packs.md` | decision-pack configuration guide |
| `docs/index.md` | Documentation index |

When asked to "update documentation":
1. Update `.claude/CLAUDE.md` first (primary LLM reference)
2. Update relevant `docs/*.md` files
3. Update `README.md` if it affects installation, quick start, or project overview
