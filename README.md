# decision-lab

Coding agents write good code. They make bad analytical decisions.

Ask a coding agent to analyze your marketing data and it will fit a model, generate charts, and recommend budget reallocations — all in clean, well-documented code. The problem is the model might be wrong, the assumptions unchecked, and the recommendations unsupported. Nobody notices for months.

decision-lab red-teams your analysis. It tries to break its own conclusions before showing them to you — so the reports you get actually hold up to scrutiny.

## What you get

We tested this on marketing mix modeling. We gave vanilla Claude Code and a decision-lab agent the same adversarial dataset where **no valid inference was possible**.

**Claude Code** fit a model and recommended budget reallocations. Confidently wrong.

**decision-lab** explored 11 modeling approaches, found that none converged, and told you:

```
⚠ No valid model found
  11 modeling approaches attempted — 0 converged
  Root cause: insufficient signal in current data (see report §4)
  Recommendation: run a geo-holdout experiment to isolate channel effects
```

That's the difference: an agent that knows when to say "we don't know."

<!-- demo gif here -->

## How it works

You define what the agent should stress-test — which diagnostics to run, what priors to use, what assumptions to challenge. The agent explores multiple approaches instead of committing to the first one that runs, actively tries to falsify its own results, and consolidates everything into a single report. If it can't break the conclusions, you can trust them. If it can, it tells you why.

This is packaged as a **decision-pack**: a directory containing domain skills, agent prompts, and a pinned environment so the agent codes against the right library versions.

Point it at your data:

```bash
dlab --dpack decision-packs/mmm \
  --data your_marketing_data.csv \
  --prompt "Analyze our marketing spend and recommend budget allocation"
```

And monitor it while it runs:

```bash
dlab connect ./mmm-run        # Live TUI: agent status, logs, cost tracking
dlab timeline ./mmm-run       # Gantt chart of the full session
```

## Get started

```bash
pip install dlab-cli

# Run the MMM decision-pack on the included example dataset
dlab --dpack decision-packs/mmm \
  --data decision-packs/mmm/example-data/example_dataset.csv \
  --env-file .env \
  --work-dir ./mmm-run \
  --prompt "Analyze our marketing spend and recommend budget allocation"

# Watch it work
dlab connect ./mmm-run
```

Runs in Docker under the hood — [install Docker](https://docs.docker.com/get-docker/) if you don't have it. Requires Python 3.10+.

## Build your own decision-pack

A decision-pack is a directory with a config, a Docker environment, agent prompts, and domain skills:

```
my-dpack/
  config.yaml           # Name, model, hooks
  docker/
    Dockerfile          # Frozen environment
    requirements.txt    # Pinned dependencies
  opencode/
    opencode.json       # Permissions
    agents/
      orchestrator.md   # Main agent system prompt
    tools/              # Custom tools
    skills/             # Domain knowledge
    parallel_agents/    # Fan-out configs
```

Scaffold one interactively:

```bash
dlab create-dpack
```

Or ask Claude to build one for you:

```bash
dhub install pymc-labs/decision-lab
claude
# > "Create a decision-pack for time series forecasting with statsforecast"
```

## Features

### Live monitoring

```bash
dlab connect ./mmm-run
```

A Textual TUI that shows live log events, agent status, cost tracking, and artifacts as the session runs. Browse between the orchestrator, parallel instances, and consolidator. Works with both running and completed sessions.

### Execution timeline

```bash
dlab timeline ./mmm-run
```

Displays a Gantt chart of the session with timing, cost breakdown per agent, and idle periods.

### Creation wizards

```bash
dlab create-dpack              # Scaffold a new decision-pack
dlab create-parallel-agent     # Add parallel agent configs to an existing pack
```

### Install as shortcut

```bash
dlab install ./my-dpack
# Now run directly:
my-dpack --data ./data --prompt "..."
```

### Decision Hub integration

decision-packs work with [Decision Hub](https://hub.decision.ai), a registry of validated skills for data science and AI. Agents can search and install skills from the hub at runtime. The hub has 2,200+ skills from 38 organizations with automated evals that verify skills actually improve agent performance.

```bash
dhub install pymc-labs/dhub-cli --agent opencode
```

### Cloud compute

Supports running compute-heavy tasks on [Modal](https://modal.com) so model fitting doesn't bottleneck on your laptop.

### Environment variable forwarding

Variables starting with `DLAB_` are automatically forwarded to the Docker container:

```bash
DLAB_FIT_MODEL_LOCALLY=1 dlab --dpack mmm --data ./data --prompt "..."
```

## CLI reference

```bash
dlab --dpack PATH --data PATH --prompt TEXT   # Run a session
dlab connect WORK_DIR                         # Live TUI monitor
dlab timeline [WORK_DIR]                      # Execution Gantt chart
dlab create-dpack [OUTPUT_DIR]                # Interactive wizard
dlab create-parallel-agent [DPACK_DIR]        # Parallel agent wizard
dlab install DPACK_PATH                       # Create shortcut command
```

## Docs

| Guide | What it covers |
|-------|---------------|
| [CLI Reference](docs/cli-reference.md) | All commands, flags, env var forwarding |
| [decision-packs](docs/decision-packs.md) | Config format, hooks, permissions, Modal integration |
| [Parallel Agents](docs/parallel-agents.md) | Fan-out architecture, YAML config, consolidator |
| [Docker](docs/docker.md) | Image building, container lifecycle, volume mounts |
| [Sessions](docs/sessions.md) | Work directories, state management, resuming runs |
| [Log Processing](docs/log-processing.md) | NDJSON log format, event types, TUI/timeline parsing |
| [Installation](docs/installation.md) | Setup, prerequisites, development install |

## Built by PyMC Labs

decision-lab is developed by [PyMC Labs](https://www.pymc-labs.com), the team behind [PyMC](https://github.com/pymc-devs/pymc) and [pymc-marketing](https://github.com/pymc-labs/pymc-marketing).

## License

Apache 2.0
