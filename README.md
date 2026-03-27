<img src="docs/_static/dai.png" alt="decision-lab logo" width="200">

# decision-lab

Coding agents write good code. They make bad analytical decisions.

Ask a coding agent to analyze your marketing data and it will fit a model, generate charts, and recommend budget reallocations — all in clean code. The problem is the model might be wrong, the assumptions unchecked, and the recommendations unsupported. Nobody notices for months.

decision-lab runs multiple modeling approaches in parallel, checks whether they converge, and only reports conclusions that survive across different assumptions. When they don't converge, it tells you what it doesn't know and what experiments would resolve the uncertainty.

<!-- TODO: Architecture diagram — orchestrator → parallel subagents → consolidator.
     Show: (1) single prompt + dataset enter the orchestrator,
     (2) fan-out to N parallel subagents, each with a different modeling approach,
     (3) consolidator compares results, produces one report with convergence/divergence assessment.
     Three stages, left to right. Keep it minimal. -->

## Why

We [tested this on marketing mix modeling](https://www.youtube.com/watch?v=ess4qV8JKQc). We gave vanilla Claude Code and our MMM agent the same adversarial dataset where no valid inference was possible. Claude Code fit a model and recommended budget reallocations. Our agent tried 11 approaches, found that none of the models converged, said so, and recommended experiments to collect better data.

That's the behavior we want: an agent that knows when to stop.

## How it works

You package everything an agent needs into a **decision-pack**: a frozen Docker environment, agent prompts, domain skills, and tools. The agent explores multiple approaches instead of committing to the first one that runs. A consolidator compares results across approaches and produces a single report with a convergence assessment.

**Skills** constrain the agent to methodologically sound paths — mandatory diagnostics, preferred model structures, informative priors.

**Parallel subagents** fan out with different approaches to the same problem (different priors, different data prep, different model structures). If results converge across approaches, you have evidence the conclusions are robust. If they diverge, the consolidator flags the disagreement and identifies what drives it. Supports running compute-heavy tasks on [Modal](https://modal.com).

**Frozen environments** pin the Docker image so the agent codes against the right library versions. No "works on my laptop."

## Install

```bash
pip install dlab-cli
```

- Python 3.10+
- [Install Docker](https://docs.docker.com/get-docker/) — we recommend running agents in a sandboxed container with a pinned environment for reproducibility. If you don't want to use Docker, run with `--no-sandboxing` and the agent will set up its own environment locally.

## Quick start

First, create a `.env` file with your API key:

```bash
echo "ANTHROPIC_API_KEY=your-key-here" > .env
```

Run the MMM decision-pack on the included example dataset:

```bash
dlab --dpack decision-packs/mmm \
  --data decision-packs/mmm/example-data/example_dataset.csv \
  --env-file .env \
  --work-dir ./mmm-run \
  --prompt "Analyze our marketing spend and recommend budget allocation"
```

> **Note:** The first run builds the Docker image, which can take several minutes. Subsequent runs use the cached image.

> **Heads up:** The MMM decision-pack runs up to 5 parallel model fits. Locally this needs a decent machine. For cloud fitting, the dpack supports [Modal](https://modal.com) — just add `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` to your `.env` and it switches automatically.

Watch it work in a separate terminal:

```bash
dlab connect ./mmm-run
```

## What's a decision-pack?

A directory with everything an agent needs: frozen environment, system prompts, domain skills, tools, and permissions.

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

See the [poem decision-pack](decision-packs/poem/) for a fully annotated example showing how all the pieces wire together.

Scaffold a new one interactively:

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

A Textual TUI that shows live log events, agent status, cost tracking, and artifacts. Browse between the orchestrator, parallel instances, and consolidator. Works with both running and completed sessions.


### Execution timeline

```bash
dlab timeline ./mmm-run
```

Gantt chart with timing, cost breakdown per agent, and idle periods.


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

decision-packs work with [Decision Hub](https://hub.decision.ai), a registry of validated skills for data science and AI. Agents can search and install skills at runtime.

```bash
dhub install pymc-labs/dhub-cli --agent opencode
```

### Environment variable forwarding

Variables starting with `DLAB_` are automatically forwarded to the Docker container:

```bash
DLAB_FIT_MODEL_LOCALLY=1 dlab --dpack mmm --data ./data --env-file .env --prompt "..."
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

dlab is developed by [PyMC Labs](https://www.pymc-labs.com), the team behind [PyMC](https://github.com/pymc-devs/pymc) and [pymc-marketing](https://github.com/pymc-labs/pymc-marketing).

## License

Apache 2.0
