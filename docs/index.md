# dlab Documentation

dlab is a Python CLI that runs [opencode](https://opencode.ai) in automated mode, sandboxed with Docker, with built-in parallel subagent capabilities.

## Overview

dlab solves the problem of running AI coding agents in a controlled, reproducible environment:

- **Isolation**: Each session runs in its own Docker container
- **Reproducibility**: decision-pack configs define exact environments
- **Safety**: Sandboxed execution prevents unintended system changes
- **Flexibility**: Define custom decision-packs for different use cases
- **Parallel execution**: Run multiple agents simultaneously with automatic consolidation
- **Interactive setup**: TUI wizards for creating decision-packs and parallel agents

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│  Local Machine                                              │
│  ┌─────────────┐                                            │
│  │    dlab     │──── Creates session ────┐                  │
│  │    CLI      │                         │                  │
│  └──────┬──────┘                         ▼                  │
│         │                    ┌───────────────────┐          │
│         │                    │  Work Directory   │          │
│         │                    │  analysis-001/    │          │
│         │                    │    data/          │          │
│         │                    │    .opencode/     │          │
│         │                    │    _opencode_logs/│          │
│         │                    │    _hooks/        │          │
│         │                    └─────────┬─────────┘          │
│         │                              │                    │
│         ▼                              │ mounted as         │
│  ┌─────────────────────────────────────┼──────────────────┐ │
│  │  Docker Container                   ▼                  │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  /workspace (session data + opencode config)     │  │ │
│  │  │                                                  │  │ │
│  │  │  1. Pre-run hooks (deploy Modal, etc.)           │  │ │
│  │  │  2. opencode run --model X --prompt "..."        │  │ │
│  │  │  3. Post-run hooks (cleanup, etc.)               │  │ │
│  │  │                                                  │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Documentation

- [Installation](installation.md) - Setup and requirements
- [decision-packs](decision-packs.md) - Creating and configuring decision-packs
- [CLI Reference](cli-reference.md) - Complete command reference
- [Docker Integration](docker.md) - How Docker images are built and managed
- [Sessions](sessions.md) - Session lifecycle and state management
- [Parallel Agents](parallel-agents.md) - Running multiple agents in parallel
- [Log Processing](log-processing.md) - Log format and TUI/timeline processing

## Quick Start

```bash
# Create a new decision-pack interactively
dlab create-dpack

# Run with a decision-pack
dlab --dpack ./my-dpack \
         --data ./my-data \
         --prompt "Analyze this data"

# Monitor the run live
dlab connect ./analysis-001

# View execution timeline after the run
dlab timeline ./analysis-001

# Resume an interrupted session
dlab --dpack ./my-dpack \
         --continue-dir ./analysis-001 \
         --prompt "Continue the analysis"
```
