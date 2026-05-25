---
marp: true
theme: default
paginate: true
style: |
  section {
    font-family: 'Segoe UI', sans-serif;
    background: #0f0f1a;
    color: #e8e8f0;
  }
  h1 { color: #a78bfa; font-size: 2.4em; }
  h2 { color: #7dd3fc; }
  h3 { color: #86efac; }
  strong { color: #fbbf24; }
  code { background: #1e1e3a; color: #f472b6; padding: 2px 6px; border-radius: 4px; }
  table { width: 100%; border-collapse: collapse; }
  th { background: #1e1e3a; color: #a78bfa; padding: 8px 12px; }
  td { padding: 8px 12px; border-bottom: 1px solid #2e2e4a; }
  tr:nth-child(even) td { background: #13132a; }
  .meme { text-align: center; }
  section.title { text-align: center; }
  section.center { text-align: center; }
---

<!-- _class: title -->

# 🧪 Decision-Lab DX Hackathon

## Making agents easy to build, run, and understand

> *Because the hardest part shouldn't be setting up Python*

---

## The Current Vibe

<!-- _class: center -->

![w:600](https://i.imgflip.com/2fm6x.jpg)

**Data scientists trying to start a new decision-lab project**

---

## Three Ideas. One Goal.

> **Reduce friction from "I have a problem" to "agents are running"**

| | What breaks today | What we fix |
|---|---|---|
| 🛠️ **Idea 1** | Creating a dpack is still mostly manual | Agent-driven CLI tooling |
| 📦 **Idea 2** | Environments are brittle, unreproducible | Pixi-first dependency management |
| 🔭 **Idea 3** | You can't see what your agents did | OTEL + OpenLIT observability |

---

<!-- _class: center -->

# 🛠️ Idea 1
## Agent-Facing CLI for Decision-Pack Creation

*Give the agent hands, not just a brain*

---

## Idea 1: The Pain

The TUI wizard scaffolds a directory.
Then it leaves you with a **blank system prompt and a blinking cursor.**

- Writing agent prompts? You.
- Wiring tools correctly? You.
- Configuring parallel agents? Still you.

We're building an autonomous agent to create decision-packs —
**but it has no structured interface to drive the process.**

![w:380](https://i.imgflip.com/30b1gx.jpg)

---

## Idea 1: The Fix

A set of **composable CLI commands** with structured JSON output — callable by agents *or* humans:

```bash
dlab dpack validate          # check for config issues
dlab dpack preview           # dry-run, no files written
dlab agent edit              # update frontmatter/system prompt from CLI
dlab dpack add-skill         # incremental additions
dlab dpack add-tool          # no need to re-run the wizard
```

**Separation of concerns:** the "brain" (opencode agent) drives the "hands" (CLI).

---

## Idea 1: The Payoff

<!-- _class: center -->

![w:600](https://i.imgflip.com/1ur9b0.jpg)

**A human runs a wizard → an agent calls a CLI → an agent orchestrates other agents**

---

<!-- _class: center -->

# 📦 Idea 2
## Pixi-First Environment Management

*Because "works on my machine" is not a deployment strategy*

---

## Idea 2: The Pain

```dockerfile
RUN conda install numpy pandas pymc
RUN pip install some-other-thing
```

- No lockfile. No single source of truth.
- Starting a project = manually writing dependency lines into a Dockerfile.
- `--no-sandboxing` mode **rebuilds the environment from scratch every run.**

![w:420](https://i.imgflip.com/wxica.jpg)

---

## Idea 2: The Fix

**`pixi.toml` as the canonical spec. Dockerfile becomes a thin wrapper.**

```bash
dlab deps add pymc           # adds to pixi.toml, invalidates only the right layer
dlab deps sync               # regenerates Dockerfile from pixi.toml
```

- Bring your own `pixi.toml` from an existing project
- Smarter Docker cache invalidation — track `pixi.toml` changes separately
- `--no-sandboxing`: detect and **reuse** an existing pixi env instead of rebuilding

> Reproducible, lockfile-backed environments. Standard practice. Decision-lab should support it from day one.

---

## Idea 2: The Demo Moment

<!-- _class: center -->

![w:500](https://i.imgflip.com/22bdq6.jpg)

**`pip install` vs `conda install` vs just... `dlab deps add`**

---

<!-- _class: center -->

# 🔭 Idea 3
## OTEL + OpenLIT Observability

*Your agents ran. But what did they actually do?*

---

## Idea 3: The Pain

Decision-lab captures rich data per agent:
cost, tokens, tool calls, duration, model...

**...locked in flat NDJSON log files.**

- No cross-session comparison
- No dashboards
- No way to plug into standard observability tooling

You're flying blind.

![w:400](https://i.imgflip.com/26jxvz.jpg)

---

## Idea 3: The Fix

A **post-processing OTEL exporter** that reads a session's logs and emits standard traces to any OTLP backend — with **OpenLIT as the turnkey default:**

```bash
dlab trace ./work-dir        # export a session as OTEL traces
```

```yaml
# docker-compose.openlit.yml — one command to spin up the full stack
```

**Span hierarchy:**
`session → agent run → step → tool call` (parallel fan-outs as linked child traces)

**GenAI semantic conventions:** `gen_ai.request.model`, `gen_ai.usage.input_tokens`, cost, finish reason — all wired up.

---

## Idea 3: The Payoff

One `dlab trace` command. Every session becomes a **first-class distributed trace.**

Visible in Grafana, OpenLIT, Jaeger, or any OTLP backend.
**Zero changes to the runtime.**

<!-- _class: center -->

![w:500](https://i.imgflip.com/1ihzfe.jpg)

---

## Summary

| | 🛠️ CLI Tooling | 📦 Pixi Devops | 🔭 OTEL Observability |
|---|---|---|---|
| **Friction killed** | Creating a new dpack | Setting up environments | Understanding agent runs |
| **Risk** | 🟢 Low | 🟡 Medium | 🟢 Low |
| **Demo-ability** | ⚡ Medium | 💤 Low | 🚀 High |
| **Standalone value** | ✅ Medium | ✅✅ High | ✅✅ High |
| **1-day feasibility** | 🟢 High | 🟡 Medium | 🟢 High |

---

<!-- _class: center -->

# Let's build it. 🚀

> *The best DX is the one you never have to think about.*

![w:450](https://i.imgflip.com/3si4.jpg)

---

<!-- _class: center -->

# 🏗️ What We Built

---

## Delivered: Two PRs on `hackathon-devex`

| | What | Status |
|---|---|---|
| 📦 | `decision-packs/base-pymc` — hierarchical Bayesian regression template | ✅ Done |
| 🔭 | `dlab trace` — OTEL post-processing exporter | ✅ Done |
| ⚙️ | Root `pixi.toml` — zero-friction dev env | ✅ Done |

> **One branch. One PR. Everything self-contained.**

---

## `base-pymc`: What It Does

Palmer Penguins dataset. Hierarchical Bayesian regression.
**No data file. No Modal. No external services.**

```
orchestrator
├── spawns 3 parallel modelers (different prior specs)
│   ├── modeler 1: weakly informative priors
│   ├── modeler 2: informative priors (data-scale)
│   └── modeler 3: strong pooling priors
├── consolidator compares posteriors (no winner picking)
└── convergence gate: R-hat < 1.05, ESS > 400, directional agreement
    ├── PASS → report.md with HDI estimates + partial pooling analysis
    └── FAIL → inconclusive_report.md (no fabricated conclusions)
```

Runs in ~5–10 min. Flexible — pass `--prompt` for your own modeling question.

---

## `dlab trace`: What It Does

Reads completed session NDJSON logs → emits OTEL traces + logs to OpenLIT.

**Span hierarchy:**
```
session:<work-dir>
└── agent:orchestrator
    ├── tool:bash  · tool:read  · tool:edit ...
    └── agent:modeler (× 3, parallel)
        └── tool:bash  · tool:edit ...
```

**Zero runtime changes.** `dlab_end` sentinel written by `finally:` block.
OpenLIT + ClickHouse in two Docker services.

---

## The Pixi Story

Before today, starting a new dlab project required:

1. Install the right Python version (pyenv, hope for the best)
2. Figure out why `dhub-cli` is missing
3. Give up and use the existing mmm pack as a template

After today:

```bash
pixi install
PYTHONPATH=. pixi run python -m dlab.cli --help
```

**That's it. Python 3.11, all deps, otel extras — locked and reproducible.**

---

<!-- _class: center -->

# 🎬 Live Demo

---

## Demo: `base-pymc` + `dlab trace`

**Step 1 — Set up the env (one-time)**

```bash
pixi install
```

**Step 2 — Start OpenLIT stack**

```bash
docker compose -f docker-compose.openlit.yml up -d
# UI at http://localhost:3000  (user@openlit.io / openlituser)
```

**Step 3 — Run the penguins analysis**

```bash
PYTHONPATH=. pixi run python -m dlab.cli \
  --dpack decision-packs/base-pymc \
  --env-file decision-packs/base-pymc/.env
```

**Step 4 — Export traces**

```bash
PYTHONPATH=. pixi run python -m dlab.cli trace <work-dir>
```

**Step 5 — Open OpenLIT and explore**

```
http://localhost:3000
```
