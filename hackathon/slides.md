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

# 🔭 Decision-Lab Observability

## From flat logs to a full audit trail — in one command

---

## The Problem

Decision-lab captures rich data per agent run.
**But it's locked in flat NDJSON files you can't query.**

```bash
# current "observability"
$ grep step_finish workdir/_opencode_logs/main.log
{"type":"step_finish","part":{"tokens":{"input":3,"output":56},"cost":0.032}}
{"type":"step_finish","part":{"tokens":{"input":12,"output":201},"cost":0.045}}
```

No cost rollups. No cross-session comparison. No dashboards.
No way to know which of your 3 parallel modelers was cheapest, fastest, or fabricating results.

---

## What We Built

**`dlab trace <work-dir>`** — reads a completed session and emits standard OpenTelemetry traces to any OTLP backend.

```
session:dlab-base-pymc-workdir-004          $0.47 total
└── agent:main                              $0.12  claude-sonnet-4-6
    ├── tool:skill  tool:read  tool:bash
    └── agent:modeler (×3, parallel)        $0.35
        └── tool:bash  tool:edit  tool:read ...
```

**Turnkey stack:** `docker compose -f docker-compose.openlit.yml up -d`
→ OpenLIT UI + ClickHouse, fully self-hosted, no data leaves your network.

**Standard protocol:** swap OpenLIT for Datadog, Grafana, or Elastic — same command.

---

<!-- _class: center -->

## Live dashboard — actual penguins run

![w:900](./openlit-screenshot.png)

**cost per agent · tokens · duration · tool call breakdown — all queryable in ClickHouse**

---

## What's Next: Self-Auditing Agents

The dashboard currently shows *what happened*. Next step: **did the agents lie?**

Parallel modelers can fabricate — cite `R-hat = 1.002` when the diagnostics file says `1.34`, or recommend actions never computed. An **evaluator agent** runs after the modelers and cross-references every specific claim in each `summary.md` against the actual output files on disk.

```
Instance 1:  hallucination_score: 0.67  ← 2/3 cited values not in any file
Instance 2:  hallucination_score: 0.0   ← all claims verified
Instance 3:  hallucination_score: 0.33  ← convergence claim unsupported
```

Scores flow into `dlab trace` → OpenLIT hallucination widget.
Orchestrator discards high-scoring instances before writing the final report.

> This is governance built into the methodology — not bolted on after the fact.
> Directly addresses EU AI Act model auditability requirements.
