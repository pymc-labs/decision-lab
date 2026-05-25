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

```bash
# current "observability"
cat dlab-base-pymc-workdir-004/_opencode_logs/main.log | grep step_finish
{"type":"step_finish","timestamp":1779711606949,"part":{"tokens":{"total":8435,"input":3,"output":56},"cost":0.032259}}
{"type":"step_finish","timestamp":1779711612103,"part":{"tokens":{"total":10393,"input":12,"output":201},"cost":0.045403}}
...
```

No cross-session comparison. No dashboards. No cost rollups. **You're flying blind.**

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

```
session:dlab-base-pymc-workdir-004   $0.47  ~40s avg  3 agents
└── agent:main                       $0.12  anthropic/claude-sonnet-4-6
└── agent:modeler (×3, parallel)     $0.35  tool calls: bash·read·edit·skill
    └── tool:bash  tool:read  tool:edit  tool:skill ...
```

> **vs. the default:** `cat main.log | grep step_finish` and do the math yourself.

---

<!-- _class: center -->

## Live: OpenLIT Dashboard — actual penguins run

![w:900](./openlit-screenshot.png)

**2,292 spans · $0.47 actual cost · 42s avg duration · `anthropic/claude-sonnet-4-6`**

> Numbers inflated from repeated demo exports — a real single run is ~$0.47, ~8 spans

---

## Summary

| | 🛠️ CLI Tooling | 📦 Pixi Devops | 🔭 OTEL Observability |
|---|---|---|---|
| **Friction killed** | Creating a new dpack | Setting up environments | Understanding agent runs |
| **Risk** | 🟢 Low | 🟡 Medium | 🟢 Low |
| **Demo-ability** | ⚡ Medium | 💤 Low | 🚀 **Shipped** |
| **Standalone value** | ✅ Medium | ✅✅ High | ✅✅ High |
| **1-day feasibility** | 🟢 High | 🟡 Medium | 🟢 **Done** |

---

<!-- _class: center -->

# What's Next: Self-Auditing Agents

---

## The Problem with Parallel Agents

3 modelers run. They produce 3 different answers.

**Which one do you trust?**

The whole point of parallel exploration is that **no single agent is reliable.**
Adding a 4th "judge" agent doesn't help — it's just another unreliable agent.

> *If there were one agent that always got it right, you wouldn't need the others.*

---

## The Insight: Evaluate Process, Not Conclusions

An evaluator agent **can't** know which modeler got the right scientific answer.

But it **can** mechanically check:

- `summary.md` claims `R-hat = 1.002` → does `diagnostics.csv` agree?
- Summary cites `β = 2.1 [1.4, 2.8]` → does that interval appear in any output file?
- Summary says "strong positive effect" → does the posterior CI straddle zero?
- Recommendation made → was it ever computed, or just asserted?

**These are file existence checks and value lookups — not scientific judgment.**

---

## The Evaluator Agent

```
orchestrator
├── parallel: modeler (×3)          ← explore diverse approaches
│   └── consolidated_summary.md
└── parallel: evaluator (×1)        ← compliance checker, runs after
    └── evaluation_summary.md
```

The evaluator reads each modeler's output files and cross-references every
specific claim in its `summary.md` against the actual files on disk.

```
Instance 1:  hallucination_score: 0.67  ← 2/3 cited values not in any file
Instance 2:  hallucination_score: 0.0   ← all claims verified
Instance 3:  hallucination_score: 0.33  ← convergence claim unsupported
```

**Orchestrator discards high-hallucination instances before synthesizing report.**

---

## Why This Fits the Paradigm

The evaluator operationalises the distrust that's already built into the parallel architecture.

| | Today | With evaluator |
|---|---|---|
| Fabricated R-hat | Pollutes final report | Caught, instance discarded |
| Missing output file | Summary still accepted | Flagged as unsupported claim |
| "Strong effect" with CI [-0.3, 4.1] | Narrative accepted | Flagged as overclaiming |
| All 3 modelers fabricate | Fabrication wins | All flagged, orchestrator stops |

Scores flow into `dlab trace` → OpenLIT hallucination widget lights up.

**The dashboard stops being decorative. It becomes the audit trail.**

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
