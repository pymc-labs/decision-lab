# CLI Reference

Complete reference for all dlab commands and options.

## Global Usage

```bash
dlab [command] [options]
```

If no command is specified and run-mode arguments are provided, dlab runs in **run mode**.

## Run Mode

Execute opencode in a Docker container with your data and prompt.

```bash
dlab --dpack PATH --data PATH [PATH ...] --prompt TEXT [options]
```

### Required Arguments

| Argument | Description |
|----------|-------------|
| `--dpack PATH` | Path to the decision-pack configuration directory |
| `--data PATH [PATH ...]` | Data files or directory (multiple paths accepted) |
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

### Environment Variable Forwarding

All environment variables starting with `DLAB_` are automatically forwarded from the host to the Docker container. This lets decision-packs define their own configuration variables without framework changes.

```bash
# Example: MMM decision-pack uses this to control local vs Modal fitting
DLAB_FIT_MODEL_LOCALLY=1 dlab --dpack mmm --data ./data --prompt "..."
```

### Continue Mode

Resume an interrupted session:

```bash
dlab --dpack ./my-dpack --continue-dir ./analysis-001 --prompt "Continue"
```

This refreshes the `.opencode` config and hook scripts from the decision-pack, then runs opencode in the existing work directory. Cannot be combined with `--data`.

### Examples

```bash
# Basic usage
dlab --dpack ./my-dpack --data ./data --prompt "Analyze this CSV"

# Multiple data files
dlab --dpack ./my-dpack --data file1.csv file2.csv --prompt "Compare"

# With model override
dlab --dpack ./my-dpack --data ./data \
         --prompt "Build a model" \
         --model anthropic/claude-opus-4

# Resume interrupted session
dlab --dpack ./my-dpack --continue-dir ./analysis-001 \
         --prompt "Continue the analysis"

# Environment file (auto-detected from decision-pack .env if present)
dlab --dpack ./my-dpack --data ./data --prompt "Analyze"
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

## Help

```bash
dlab --help
dlab create-dpack --help
dlab create-parallel-agent --help
dlab connect --help
dlab timeline --help
dlab install --help
```
