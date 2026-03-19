# decision-lab

Coding agents write good code. They make bad analytical decisions. decision-lab gives you the tools to fix the second part.

decision-lab runs autonomous coding agents in frozen Docker environments with domain-specific skills and parallel subagents. You package the environment, the prompts, and the skills into a **decision-pack**, point it at your data, and get back reports, figures, and recommendations that hold up to scrutiny.

<!-- demo gif here -->

## Why

There are many ways to analyze a dataset. Most of them are wrong. An unsupervised agent picks one path through the analytical space and commits to it. If that path happens to be wrong, you get a nice-looking report with bad conclusions. Nobody notices for months.

We tested this on marketing mix modeling. We gave vanilla Claude Code and our MMM agent the same adversarial dataset where no valid inference was possible. Claude Code fit a model and recommended budget reallocations. Our agent tried 11 approaches, found that none of the models converged, said so, and recommended experiments to collect better data.

decision-lab (`dlab`) is the framework we built to make agents behave like that.

## How it works

**Skills.** decision-packs include domain-specific skills: mandatory diagnostics, preferred model structures, informative priors. These constrain the agent to methodologically sound paths.

**Parallel subagents.** decision-lab lets the coding agent fan out multiple subagents with different approaches to the same problem (different priors, different data prep, different model structures) and consolidates their results. Structured exploration instead of a single random walk. Supports running compute-heavy tasks in the cloud on [modal](https://modal.com).

<!--**Uncertainty awareness.** Bayesian models give the agent a principled way to know when inference isn't supported. The agent reports uncertainty and recommends experiments instead of guessing.-->

**Frozen environments.** Every session runs in a pinned Docker image. Library APIs change constantly and LLMs are trained on old versions. decision-packs lock the environment so the agent codes against the right API.

## Install

**Requires [Docker](https://docs.docker.com/get-docker/)** and Python 3.10+

```bash
pip install dlab-cli
```

## Quick start

```bash
# Run a decision-pack on your data
dlab --dpack dpacks/mmm --data ./marketing-spend.csv --prompt "Build a marketing mix model" --workdir ./analysis

# Monitor it work live
dlab connect ./analysis
```

Or build your own decision-pack. Ask Claude to scaffold one for you:

```bash
dhub install pymc-labs/decision-lab
claude
# > "Create a decision-pack for time series forecasting with statsforecast"
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

Install validated decision-packs from [Decision Hub](https://hub.decision.ai), or create your own with `dlab create-dpack`.

## CLI

```bash
dlab --dpack PATH --data PATH --prompt TEXT --env .env  # Run a session
dlab connect WORK_DIR                         # Live TUI monitor
dlab timeline [WORK_DIR]                      # Execution Gantt chart
dlab create-dpack [OUTPUT_DIR]                # Interactive wizard
dlab create-parallel-agent [DPACK_DIR]        # Parallel agent wizard
dlab install DPACK_PATH                       # Create shortcut command
```

## Docs

Full documentation at [`docs/`](docs/index.md).

## Built by PyMC Labs

dlab is developed by [PyMC Labs](https://www.pymc-labs.com), the team behind [PyMC](https://github.com/pymc-devs/pymc) and [pymc-marketing](https://github.com/pymc-labs/pymc-marketing).

## License

Apache 2.0
