# Telemetry (OpenTelemetry export)

dlab can export a session to any OpenTelemetry collector. It is **off by
default** and costs nothing when off: the OpenTelemetry packages live in the
`otel` extra and are only imported once an endpoint is configured.

```bash
pip install "dlab-cli[otel]"          # or: uv pip install -e ".[otel]"
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
dlab run --dpack decision-packs/poem --prompt "..."
```

## What is exported

Two things, from two sources, joined by one id:

1. **opencode's own spans.** opencode has a native OTLP exporter that reads
   `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS` and
   `OTEL_RESOURCE_ATTRIBUTES`. dlab forwards these to every parallel instance
   (they are on the instance environment allowlist) and appends per-process
   resource attributes so each process is identifiable:
   `dlab.role` (`orchestrator`, `instance`, `consolidator`), `dlab.agent`,
   `dlab.instance`. Each opencode process emits its own traces; opencode does
   not join a parent trace, so the join key is the session id. This needs
   opencode 1.17 or later; a pack that pins an older version (the `mmm` pack
   pins 1.2.10) still gets the dlab session tree, just not opencode's own spans.
2. **The dlab session tree** (`dlab/telemetry.py`), derived from the NDJSON
   logs the session already writes: `session` → `agent:<name>` → `step` →
   `tool:<name>`, with `gen_ai.*` attributes (model, tokens, finish reason,
   cost), log records for errors (and text with prompts on), and two counters
   (`gen_ai.client.token.usage`, `dlab.cost.usd`). The root span carries the
   outcome, exit code, agent count and totals.

Both carry the resource attributes `pymc.workload=dlab`, `dlab.session.id`,
`dlab.dpack` and `dlab.role`, added to whatever `OTEL_RESOURCE_ATTRIBUTES`
already holds (existing keys win). The session id is `DLAB_SESSION_ID` when
set (a scheduler sets it to its run name), otherwise a random id minted once
per work dir and kept in `.dlab_session_id` there. The session trace id is
derived from it, so a later re-export lands in the same trace. The work-dir
name is deliberately not used: work dirs are numbered per pack, so every
first run of a pack would collide on a shared collector.

## Environment variables

| Variable | Meaning | Default |
| --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Collector base URL (`/v1/traces` etc. are appended) | unset = off |
| `OTEL_SERVICE_NAME` | `service.name` of the dlab tree | `dlab` |
| `OTEL_RESOURCE_ATTRIBUTES` | Extra resource attributes, merged | unset |
| `DLAB_SESSION_ID` | Session id used as `dlab.session.id` | random, kept in `.dlab_session_id` |
| `DLAB_OTEL_FOLLOW` | `1` = stream completed steps/tools while the session runs | off (export once at the end) |
| `DLAB_OTEL_INTERVAL` | Follow-mode poll interval in seconds (min 1) | `15` |
| `DLAB_OTEL_PROMPTS` | `1` = include prompt, agent text, reasoning and tool output in log records | off |
| `TRACEPARENT` | Launcher context, recorded as a link on the session root | unset |

`OTEL_EXPORTER_OTLP_HEADERS` is forwarded to instances too; a subagent with
bash could read a backend token placed there. Prefer an in-cluster collector
that needs no headers.

## Notes

- Export failures never fail a run; they are printed as `OTEL:` warnings.
- Docker mode forwards `OTEL_*` into the container like `DLAB_*`; the
  endpoint must then be reachable from inside the container.
- Prompt content and agent text are not in any span; with
  `DLAB_OTEL_PROMPTS=1` they go into log records only.
- A continued session (`--continue-dir`) is a new session with a new id
  (with `DLAB_SESSION_ID` set, that id plus a `-c<hex>` suffix); instance
  logs left by earlier runs of that work dir are not exported again.
