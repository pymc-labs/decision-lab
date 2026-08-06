# CLI Reference

Complete reference for all dlab commands and options.

## Global Usage

```bash
dlab [command] [options]
```

The primary command is `dlab run`. As a backward-compatible shorthand, its options may also be passed directly at the root — `dlab --dpack ...` is equivalent to `dlab run --dpack ...`.

## run

Execute opencode in a Docker container with your data and prompt.

```bash
dlab run --dpack PATH --data PATH [--data PATH ...] --prompt TEXT [options]
```

### Required Arguments

| Argument | Description |
|----------|-------------|
| `--dpack PATH` | Path to the decision-pack configuration directory |
| `--data PATH` | Data file or directory to copy into the workspace (repeat for multiple files: `--data a.csv --data b.csv`) |
| `--prompt TEXT` | Prompt text for the agent |

`--data` is required unless the decision-pack sets `requires_data: false` in config.yaml. `--prompt` (or `--prompt-file`) is required unless the decision-pack sets `requires_prompt: false`.

### Optional Arguments

| Argument | Description |
|----------|-------------|
| `--prompt-file PATH` | Read prompt from file (mutually exclusive with `--prompt`) |
| `--model MODEL` | Override the default_model from config |
| `--work-dir PATH` | Explicit work directory path (default: auto-generated) |
| `--continue-dir PATH` | Resume a previous session from this directory |
| `--rebuild` | Force rebuild Docker image even if cached |
| `--env-file PATH` | Path to environment file (auto-detected from decision-pack `.env` if not specified) |
| `--no-sandboxing` | Run opencode locally without Docker (see below) |
| `--notebooks` / `--no-notebooks` | Compose Jupyter notebooks when the run finishes successfully. Tri-state: overrides the pack's `generate_jupyter_notebooks_from_run` and `DLAB_ALWAYS_RUN_NOTEBOOKS_COMPOSER`; `--no-notebooks` force-disables (see below) |
| `--notebooks-model MODEL` | Model for the notebook composer (distinct from `--model`, the orchestrator; else `models.notebooks` / `DLAB_NOTEBOOKS_MODEL` / `default_model`) |

### Composing notebooks after a run

By default `dlab run` stops at the finished work dir and you compose notebooks separately with [`dlab notebooks`](#notebooks). To have a **successful** run compose them itself, opt in via any of (highest precedence first): `--notebooks` → `DLAB_ALWAYS_RUN_NOTEBOOKS_COMPOSER=1` (a user-global switch) → `generate_jupyter_notebooks_from_run: true` in the pack's `config.yaml`. `--no-notebooks` disables it for a single run even when the env or config opts in. Composition runs only on exit code 0 (skipped for failed or interrupted runs), and a composer failure is surfaced as a warning without changing the run's exit code. The composer model resolves via `--notebooks-model` → `models.notebooks` → `DLAB_NOTEBOOKS_MODEL` → `default_model`.

### Local Mode (`--no-sandboxing`)

With `--no-sandboxing`, dlab skips Docker entirely and runs opencode directly on the host. The decision-pack's `docker/` directory is copied into the work dir as `_docker/`, and instructions are prepended to the prompt telling the agent to provision its own environment from it. Pre-run and post-run hooks are **not** executed in local mode.

Use this when Docker is unavailable or for quick iteration; the sandboxing and reproducibility guarantees of the Docker environment do not apply.

### Environment Variable Forwarding

All environment variables starting with `DLAB_` are automatically forwarded from the host to the Docker container. This lets decision-packs define their own configuration variables without framework changes.

```bash
# Example: MMM decision-pack uses this to control local vs Modal fitting
DLAB_FIT_MODEL_LOCALLY=1 dlab run --dpack mmm --data ./data --prompt "..."
```

### Continue Mode

Resume an interrupted session:

```bash
dlab run --dpack ./my-dpack --continue-dir ./analysis-001 --prompt "Continue"
```

This refreshes the `.opencode` config and hook scripts from the decision-pack, then runs opencode in the existing work directory. Cannot be combined with `--data`.

### Examples

```bash
# Basic usage
dlab run --dpack ./my-dpack --data ./data --prompt "Analyze this CSV"

# Multiple data files (repeat --data for each file)
dlab run --dpack ./my-dpack --data file1.csv --data file2.csv --prompt "Compare"

# With model override
dlab run --dpack ./my-dpack --data ./data \
         --prompt "Build a model" \
         --model anthropic/claude-opus-4

# Resume interrupted session
dlab run --dpack ./my-dpack --continue-dir ./analysis-001 \
         --prompt "Continue the analysis"

# Environment file (auto-detected from decision-pack .env if present)
dlab run --dpack ./my-dpack --data ./data --prompt "Analyze"
```

### CLI Output

The run command shows phased progress with Rich formatting:

```
dlab . my-dpack . opencode/big-pickle
Session:    ./analysis-001

[1/4] Setting up environment
      Image: dlab-my-dpack (cached)
      Warning: 3 dangling Docker image(s) using disk space
      Clean up with: docker image prune -f
      Container started: analysis-001
[2/4] Pre-run hooks
      deploy_modal.sh
        Deploying Modal app...
        Modal app deployed.
[3/4] Running agent ...
      ╭────────────── Monitoring ───────────────╮
      │ dlab connect ./analysis-001         │
      │   Live-monitor the run                  │
      │                                         │
      │ dlab timeline ./analysis-001        │
      │   View execution timeline after the run │
      ╰─────────────────────────────────────────╯
[4/4] Cleanup
      Stopping container...
      Done.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | CLI error (missing args, invalid config, etc.) |
| 128+N | Terminated by signal N (e.g., 130 = Ctrl+C) |

`dlab run` returns opencode's exit code, so an agent-level failure (invalid
API key, unknown model) exits non-zero even when the session lifecycle
(image build, container, hooks, cleanup) completed — dlab's exit code
deliberately mirrors the agent's outcome. On failure, dlab scans the session
log for known fatal signatures (model not in opencode's catalog, rejected
API key, exhausted credits) and prints a "Likely cause" hint.

Model preflight validates against the bundled catalog merged with a
user-level cache (`~/.cache/dlab/models.json`); when the cache is older than
seven days, `dlab run` refreshes it from models.dev in the background — the
refresh never blocks or fails a run.

---

## create-dpack

Interactive TUI wizard to create a new decision-pack directory.

```bash
dlab create-dpack [OUTPUT_DIR]
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `OUTPUT_DIR` | `.` | Directory where the decision-pack will be created |

### Wizard Screens

1. **Basics** — decision-pack name, description
2. **Container** — package manager (conda/pip/uv/pixi), base Docker image
3. **Features** — Decision Hub integration, Python library, Modal, requires_data, requires_prompt
4. **Model** — default model with live search from models.dev API
5. **Permissions** — opencode.json permission configuration
6. **Skeletons** — directory scaffolding (skills, tools, subagents, parallel agents)
7. **Skills** — search and download skills from Decision Hub
8. **Review** — summary and create

### Navigation

| Key | Action |
|-----|--------|
| Tab / Shift+Tab | Navigate between fields |
| Arrow keys | Navigate between fields, select in lists |
| Enter | Confirm selection |
| Ctrl+Q | Quit wizard |
| Esc | Go back to previous screen |

---

## create-parallel-agent

Interactive TUI wizard to create a parallel agent configuration.

```bash
dlab create-parallel-agent [DPACK_DIR]
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `DPACK_DIR` | `.` | Path to the decision-pack config directory |

### What It Configures

- **Agent** — select an existing agent or create a new one (agents already configured are greyed out)
- **Description** — optional documentation
- **Timeout** — maximum runtime per instance (minutes)
- **Failure behavior** — continue, fail fast, or retry
- **Suffix prompt** — instructions appended to each worker's prompt (pre-filled template)
- **Consolidator prompt** — instructions for combining results (pre-filled template)
- **Consolidator model** — model for the consolidation step

### Output

Creates `opencode/parallel_agents/{name}.yaml` and optionally `opencode/agents/{name}.md` (if creating a new agent).

---

## install

Install a decision-pack as a wrapper script for convenient access.

```bash
dlab install PATH [--bin-dir PATH]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PATH` | Path to the decision-pack configuration directory |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--bin-dir PATH` | `~/.local/bin` | Directory to install the wrapper script |

### Examples

```bash
dlab install ./my-dpack

# After installation:
my-dpack --data ./data --prompt "Analyze this"
```

---

## connect

Launch a TUI to monitor running or completed sessions.

```bash
dlab connect WORK_DIR
```

The `--log` and `--log-json` flags are reserved but **not yet implemented** — passing them prints an error and exits.

### TUI Layout

- **Left sidebar**: Agent selector showing all agents (main, parallel instances, consolidator)
- **Main area**: Log events for selected agent with timestamps
- **Right sidebar** (toggleable): Artifacts pane showing files created by agent
- **Bottom**: Status bar (running/completed, cost, duration)

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit |
| `/` | Focus search |
| `Esc` | Clear search |
| `a` | Toggle artifacts pane |
| `e` / `c` | Expand / collapse all events |
| `j` / `k` | Next / previous agent |
| `Enter` | Expand/collapse selected event |
| `Tab` | Focus artifacts pane (when visible) |

---

## timeline

Display execution timeline and Gantt chart for a session.

```bash
dlab timeline [WORK_DIR]
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `WORK_DIR` | Current directory | Path to session work directory |

### Output

1. **Log file summaries**: Start time, duration, event count, and cost per agent
2. **Event timeline**: Chronological trace of tool calls and text outputs
3. **Cost breakdown**: Total and per-agent API costs
4. **Gantt chart**: Visual representation of parallel execution

---

## view

Open a browser-based session viewer with a DAG visualization of the session (orchestrator, parallel instances, consolidator) and a detail panel per node.

```bash
dlab view WORK_DIR [--port PORT] [--no-open] [--export FILE]
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `WORK_DIR` | — | Path to session work directory |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--port PORT` | auto-select | Port for the viewer server |
| `--no-open` | — | Start the server without opening a browser |
| `--export FILE` | — | Write a self-contained HTML file instead of starting a server |

---

## digest

Build a deterministic session digest — an LLM-facing map of a completed run (per-agent sections, workflow tree, artifact write-chains, script runs, reasoning excerpts). This is the same digest the notebook composer consumes; the command exposes it for inspection and for materializing the `_digest/` plumbing by hand. No LLM, no execution — pure extraction on top of `opencode_logparser`.

```bash
dlab digest [WORK_DIR] [--brief] [--write]
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `WORK_DIR` | Current directory (if it contains `_opencode_logs`) | Path to session work directory |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--brief` | — | Collapse the per-agent tool tables to one-line counts |
| `--write`, `-w` | — | Write `_digest/digest.md` and `_digest/index.json` into the work dir instead of printing the digest to stdout |

Without `--write`, the digest markdown is printed to stdout (pipe-friendly: `dlab digest ./run | less`). The machine index (`index.json`) is only emitted in `--write` mode, since it is only meaningful as a file alongside the markdown (it is what the `digest-get` tool reads).

---

## map-dpack

Compile a decision-pack's **code map** — the static wiring from each custom tool to the real code it runs (the Python library behind `python -m LIB.MOD`, or the function deployed behind a `modal.Function.from_name` dispatch). Written to `<dpack>/code_map.json` (with source-file checksums for staleness). This is what lets `dlab notebooks` show a tool call as the real library code rather than a bare CLI invocation. Deterministic by default; the notebook step auto-builds one on the fly if a pack has none, but committing the map (and running the optional LLM pass below) is recommended.

```bash
dlab map-dpack <DPACK> [--check] [--model <provider/model>] [--env-file <file>]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--check` | — | Don't rebuild; report whether the committed `code_map.json` is stale vs its sources (exit 1 if it is) |
| `--model` | — | Run the **one-time LLM template pass**: for CLI tools whose `main()` loads/transforms (so there's no clean `fn(**inputs)` call), the model writes a parametrized `call_template` stored in the map. Deterministic-only if omitted; deterministic rebuilds preserve existing templates |
| `--env-file` | dpack's `.env` | Provider keys for the `--model` pass |

Run without `--model`, it prints a warning naming the tools that would benefit and suggests models from the provider keys it detects. Re-run after changing a pack's tools or library (or use `--check` in CI).

---

## skeleton

Build **deterministic notebooks** from a finished run — real code paired with the real output it produced (captured stdout/stderr + figures) — with no LLM. One notebook per agent into `<work-dir>/skeleton/`: the adopted path as numbered phase notebooks, non-adopted instances under `skeleton/attempts/`. Correct by construction (no hallucinated code, no orphaned figures, no empty-output cells). This is the substrate the `notebooks` composer curates; it's also useful on its own.

```bash
dlab skeleton <WORK_DIR> [--dpack <dpack>]
```

Pass `--dpack` so custom-tool cells resolve to the real library code they ran (via the pack's code map) instead of just the invocation.

---

## notebooks

Turn a finished run into narrated Jupyter notebooks. Two stages: **(1) deterministic** — generate the digest, build the skeleton, seed `notebooks/` from it; **(2) LLM** — launch the `notebooks` composer agent to *curate and narrate* that copy in place. The composer has no tool to add or edit a code cell, so the code stays exactly what ran (it only inserts markdown, regroups, deduplicates noise, and authors `00_overview`). It grounds numbers in the run's own outputs/reports — it never fabricates.

```bash
dlab notebooks <WORK_DIR> --model <provider/model> [--dpack <dpack>] [--env-file <file>] [--timeout <s>]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--model` | see below | The composer model (`provider/model`) |
| `--dpack` | — | Decision-pack; resolves the model and lets custom-tool cells carry real library code (via its code map). Warns if a mapped tool has no template |
| `--env-file` | dpack's `.env` | Provider keys for the composer run |
| `--timeout` | 3600 | Seconds before the composer run is aborted (raise for slower/thorough models) |

**Model resolution** (highest wins): `--model` → the dpack's explicit `models.notebooks` → the `DLAB_NOTEBOOKS_MODEL` environment variable (a user's global default) → the dpack's `default_model`.

Output: `notebooks/` (curated) and `skeleton/` (the pristine deterministic artifact). See [Notebook composition](decision-packs.md#notebook-composition) for the full pipeline.

---

## Help

```bash
dlab --help
dlab create-dpack --help
dlab create-parallel-agent --help
dlab connect --help
dlab timeline --help
dlab view --help
dlab digest --help
dlab map-dpack --help
dlab skeleton --help
dlab notebooks --help
dlab install --help
```
