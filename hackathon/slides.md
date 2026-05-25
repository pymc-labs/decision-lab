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
  pre { background: #1e1e3a; padding: 16px; border-radius: 8px; }
  pre code { background: transparent; padding: 0; }
  table { width: 100%; border-collapse: collapse; }
  th { background: #1e1e3a; color: #a78bfa; padding: 8px 12px; }
  td { padding: 8px 12px; border-bottom: 1px solid #2e2e4a; }
  tr:nth-child(even) td { background: #13132a; }
  blockquote { border-left: 4px solid #a78bfa; padding-left: 1em; color: #a0a0c0; }
  section.title { text-align: center; }
  section.center { text-align: center; }
---

<!-- _class: title -->

# 🧪 Decision-Lab DX Hackathon

## Making agents easy to build, run, and understand

> *Because the hardest part shouldn't be setting up Python*

---

<!-- _class: center -->

## The Current Vibe

![w:580](https://i.imgflip.com/2fm6x.jpg)

**Data scientists trying to start a new decision-lab project**

---

## Three Ideas. One Goal.

> **Reduce friction from "I have a problem" to "agents are running"**

| | What breaks today | What we fix |
|---|---|---|
| 🛠️ **CLI** | Creating a dpack is still mostly manual | Agent-driven scaffolding CLI |
| 📦 **Pixi** | Environments are brittle, unreproducible | `pixi.toml` as single source of truth |
| 🔭 **OTEL** | You can't see what your agents did | `dlab trace` → OpenLIT observability |

> One branch. One PR. `hackathon-devex`

---

## 🛠️ CLI: Give the Agent Hands

The TUI wizard leaves you with a blank prompt and a blinking cursor.
Writing agent prompts, wiring tools, configuring parallel agents: **still you.**

![w:340](https://i.imgflip.com/30b1gx.jpg)

**The fix:** composable CLI commands with structured JSON output — callable by agents *or* humans:

```bash
dlab dpack validate     dlab dpack preview
dlab agent edit         dlab dpack add-skill
```

*The brain (opencode agent) drives the hands (CLI).*

---

## 📦 Pixi: Reproducible by Default

```dockerfile
RUN conda install numpy pandas pymc   # no lockfile
RUN pip install some-other-thing      # no single source of truth
# --no-sandboxing rebuilds from scratch. every. single. run.
```

![w:320](https://i.imgflip.com/wxica.jpg)

**The fix:** `pixi.toml` as the canonical spec. Dockerfile becomes a thin wrapper.

```bash
pixi install && PYTHONPATH=. pixi run python -m dlab.cli --help
```

Python 3.11, all deps, otel extras — locked, reproducible, **one command.**

---

## 🔭 OTEL: See What Your Agents Did

```bash
$ grep step_finish workdir/_opencode_logs/main.log
{"type":"step_finish","part":{"tokens":{"input":3,"output":56},"cost":0.032}}
{"type":"step_finish","part":{"tokens":{"input":12,"output":201},"cost":0.045}}
```

**The fix:** `dlab trace <work-dir>` — reads session logs, emits standard OpenTelemetry.

```
session:dlab-base-pymc-workdir-004     $0.47 total
└── agent:main                         $0.12  claude-sonnet-4-6
    └── agent:modeler (×3, parallel)   $0.35
        └── tool:bash · tool:edit · tool:read ...
```

Turnkey: `docker compose -f docker-compose.openlit.yml up -d`
→ OpenLIT + ClickHouse. **Fully self-hosted. No data leaves your network.**
Swap for Datadog, Grafana, or Elastic — same command.

---

<!-- _class: center -->

## Live: OpenLIT Dashboard — actual penguins run

![w:900](./openlit-screenshot.png)

**cost per agent · tokens · duration · tool call breakdown · all queryable in ClickHouse**

---

## What's Shipped + What's Next

| | 🛠️ CLI | 📦 Pixi | 🔭 OTEL |
|---|---|---|---|
| **Status** | ✅ Done | ✅ Done | ✅ Done |
| **Demo-ability** | ⚡ Medium | 💤 Low | 🚀 **Live** |
| **Enterprise value** | ✅ DX | ✅✅ Reproducibility | ✅✅ Governance |

**Roadmap: self-auditing agents**
Evaluator agent cross-references every claim in `summary.md` against actual output files.
Catches fabricated R-hats, unsupported recommendations, overclaimed intervals.
Scores flow into `dlab trace` → OpenLIT hallucination widget. EU AI Act ready.

![w:300](https://i.imgflip.com/3si4.jpg)

> *Shut up and take my money.*
