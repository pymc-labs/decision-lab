"""
Deterministic session digest for the notebook composer (issue #85).

Builds an LLM-facing map of a completed dlab work directory on top of
``opencode_logparser`` — no LLM, no agent, pure mechanical extraction — and a
thin machine index so an agent can retrieve any element by ID via the
``digest-get`` tool. Written into the work dir before the composer runs:

    _digest/digest.md     — the map (per-agent sections, workflow tree)
    _digest/index.json    — { "<agent>/<id>": {log_file, line_no, event_type} }

ID scheme (spec §7.1): one shared counter per agent — ``t07`` (tool call),
``x08`` (text/reasoning), ``t09`` — the number IS the timeline. Artifacts get
``a1..`` (display only, not indexed); the differentiating prompt gets ``p0``
(indexed → the dlab_start line). Fully-qualified IDs are ``<agent>/<id>`` where
``<agent>`` is ``main`` or e.g. ``poet.r1.i2`` / ``poet.r1.cons``.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from dlab.opencode_logparser import (
    LogEvent,
    ms_to_datetime,
    parse_line,
    get_step_cost,
    get_text,
    get_tool_error,
    get_tool_input,
    get_tool_name,
    get_tool_status,
)

DIGEST_DIR = "_digest"

# The in-container retrieval tool (spec §7.2), shipped as package data and
# materialized into the composer's .opencode/tools/ by the composer step.
DIGEST_GET_SOURCE: str = files("dlab.js").joinpath("digest-get.ts").read_text()

_EXCERPT_LEN = 160
_TASK_LEN = 240
# Work-dir entries that are session internals, not agent artifacts.
_ROOT_SKIP = {
    "_opencode_logs", "_digest", "_docker", "_hooks", ".opencode",
    "parallel", "data", ".state.json", ".git",
}


@dataclass
class _IndexedEvent:
    line_no: int
    event: LogEvent


@dataclass
class _AgentDigest:
    """Everything computed for one agent's ``###`` section."""
    qual: str                                   # e.g. "main", "poet.r1.i2"
    role: str                                   # "orchestrator" | agent name
    heading: str                                # human heading suffix
    log_rel: str                                # log path relative to work_dir
    workdir_rel: str | None                     # instance workdir, if any
    model: str | None
    duration_s: float
    cost: float
    tool_count: int
    task_text: str | None                       # differentiating prompt (p0)
    task_line: int | None
    tool_counter: Counter                       # tool name -> n
    script_runs: list[dict[str, Any]]           # bash calls
    writes: dict[str, list[str]]                # file -> ["written t6", ...]
    excerpts: list[tuple[str, str]]             # (id, truncated text)
    index: dict[str, dict[str, Any]]            # local ids -> pointer
    summary_ok: bool = True


# ---------------------------------------------------------------------------
# Parsing with line numbers
# ---------------------------------------------------------------------------


def _iter_indexed(log_path: Path) -> list[_IndexedEvent]:
    """Every parseable line of a log as (1-based line number, event)."""
    out: list[_IndexedEvent] = []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for i, line in enumerate(text.splitlines(), start=1):
        ev = parse_line(line)
        if ev is not None:
            out.append(_IndexedEvent(i, ev))
    return out


def _differentiating_prompt(full_prompt: str) -> str:
    """Strip the injected subagent-context preamble and the shared suffix so
    the Task field shows what makes this instance distinct."""
    marker = "CRITICAL OUTPUT RULES"
    text = full_prompt
    # Drop the injected "IMPORTANT CONTEXT ... CRITICAL OUTPUT RULES ..." block
    # that parallel-agents.ts prepends; the real task follows it.
    if "IMPORTANT CONTEXT" in text and marker in text:
        # The suffix prompt is appended after the task; the task is the middle.
        after = text.split(marker, 1)[1]
        # everything after the rules block's blank-line separator
        parts = after.split("\n\n", 1)
        text = parts[1] if len(parts) > 1 else after
    return text.strip()


# ---------------------------------------------------------------------------
# Per-agent digest
# ---------------------------------------------------------------------------


def _digest_agent(qual: str, role: str, heading: str, log_path: Path,
                  work_dir: Path, workdir_rel: str | None,
                  summary_ok: bool = True) -> _AgentDigest:
    indexed = _iter_indexed(log_path)
    log_rel = _rel(log_path, work_dir)

    counter = 0
    cost = 0.0
    tool_count = 0
    model: str | None = None
    task_text: str | None = None
    task_line: int | None = None
    tool_counter: Counter = Counter()
    script_runs: list[dict[str, Any]] = []
    writes: dict[str, list[str]] = {}
    excerpts: list[tuple[str, str]] = []
    index: dict[str, dict[str, Any]] = {}

    for ie in indexed:
        ev = ie.event
        et = ev.event_type
        if et == "dlab_start":
            model = ev.raw.get("model") or ev.part.get("model")
            prompt = ev.raw.get("prompt") or ev.part.get("prompt") or ""
            if prompt:
                task_text = _differentiating_prompt(prompt)
                task_line = ie.line_no
                index[f"{qual}/p0"] = {
                    "log_file": log_rel, "line_no": ie.line_no,
                    "event_type": "dlab_start",
                }
        elif et == "step_finish":
            cost += get_step_cost(ev) or 0.0
        elif et == "tool_use":
            counter += 1
            tid = f"t{counter}"
            index[f"{qual}/{tid}"] = {
                "log_file": log_rel, "line_no": ie.line_no,
                "event_type": "tool_use",
            }
            tool_count += 1
            name = get_tool_name(ev) or "?"
            tool_counter[name] += 1
            if name == "bash":
                script_runs.append(_script_run(tid, ev))
            if name in ("write", "edit"):
                fp = (get_tool_input(ev) or {}).get("filePath")
                if fp:
                    verb = "written" if name == "write" else "edited"
                    writes.setdefault(_basename(fp), []).append(f"{verb} {tid}")
        elif et == "text":
            counter += 1
            xid = f"x{counter}"
            index[f"{qual}/{xid}"] = {
                "log_file": log_rel, "line_no": ie.line_no,
                "event_type": "text",
            }
            txt = (get_text(ev) or "").strip()
            if txt:
                excerpts.append((xid, _truncate(txt, _EXCERPT_LEN)))

    ts = [ie.event.timestamp for ie in indexed if ie.event.timestamp]
    duration_s = (max(ts) - min(ts)) / 1000 if len(ts) > 1 else 0.0

    return _AgentDigest(
        qual=qual, role=role, heading=heading, log_rel=log_rel,
        workdir_rel=workdir_rel, model=model, duration_s=duration_s, cost=cost,
        tool_count=tool_count, task_text=task_text, task_line=task_line,
        tool_counter=tool_counter, script_runs=script_runs, writes=writes,
        excerpts=excerpts, index=index, summary_ok=summary_ok,
    )


def _script_run(tid: str, ev: LogEvent) -> dict[str, Any]:
    inp = get_tool_input(ev) or {}
    status = get_tool_status(ev)
    ok = status == "completed" and not get_tool_error(ev)
    from dlab.opencode_logparser import get_tool_output
    out = get_tool_output(ev) or ""
    err = get_tool_error(ev) or ""
    stream = err if err else out
    n_lines = len(stream.splitlines()) if stream else 0
    which = "stderr" if err else "stdout"
    tail = ""
    if stream:
        last = stream.splitlines()[-1].strip()
        tail = _truncate(last, 80)
    start, end = None, None
    tt = ev.part.get("state", {}).get("time", {}) if isinstance(ev.part, dict) else {}
    if isinstance(tt, dict):
        start, end = tt.get("start"), tt.get("end")
    dur = (end - start) / 1000 if start and end else None
    return {
        "id": tid,
        "cmd": inp.get("command") or inp.get("description") or "",
        "ok": ok, "duration_s": dur, "stream": which,
        "n_lines": n_lines, "tail": tail,
    }


# ---------------------------------------------------------------------------
# Graph traversal → agents
# ---------------------------------------------------------------------------


def _collect_agents(work_dir: Path) -> list[_AgentDigest]:
    logs_dir = work_dir / "_opencode_logs"
    agents: list[_AgentDigest] = []

    main_log = logs_dir / "main.log"
    if main_log.exists():
        agents.append(_digest_agent(
            "main", "orchestrator", "orchestrator", main_log, work_dir, None,
        ))

    # Group parallel run dirs by agent name; rank timestamps → round number.
    run_dirs = sorted(d for d in logs_dir.glob("*-parallel-run-*") if d.is_dir())
    by_agent: dict[str, list[tuple[str, Path]]] = {}
    for d in run_dirs:
        agent, _, ts = d.name.rpartition("-parallel-run-")
        by_agent.setdefault(agent, []).append((ts, d))

    for agent, runs in by_agent.items():
        runs.sort(key=lambda r: r[0])
        for round_idx, (ts, d) in enumerate(runs, start=1):
            retry = f" (retry round {round_idx})" if len(runs) > 1 else ""
            for inst_log in sorted(d.glob("instance-*.log")):
                n = inst_log.stem.split("-")[-1]
                qual = f"{agent}.r{round_idx}.i{n}"
                inst_work = f"parallel/run-{ts}/instance-{n}"
                summary_ok = (work_dir / inst_work / "summary.md").exists()
                agents.append(_digest_agent(
                    qual, agent, f"{agent}, instance {n}{retry}",
                    inst_log, work_dir, inst_work, summary_ok,
                ))
            cons_log = d / "consolidator.log"
            if cons_log.exists():
                qual = f"{agent}.r{round_idx}.cons"
                agents.append(_digest_agent(
                    qual, agent, f"{agent} consolidator{retry}",
                    cons_log, work_dir, f"parallel/run-{ts}", True,
                ))
    return agents


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def build_digest(work_dir: str | Path, *, brief: bool = False) -> tuple[str, dict[str, dict[str, Any]]]:
    """
    Build the digest markdown and index for a completed work directory.

    Parameters
    ----------
    work_dir : str | Path
        Completed session work directory.
    brief : bool
        If True, collapse the full tool tables to one-line counts.

    Returns
    -------
    tuple[str, dict]
        (digest_markdown, index) — index maps "<agent>/<id>" to a pointer
        dict {log_file, line_no, event_type}.
    """
    work_dir = Path(work_dir)
    agents = _collect_agents(work_dir)
    index: dict[str, dict[str, Any]] = {}
    for a in agents:
        index.update(a.index)

    total_cost = sum(a.cost for a in agents)
    orch = next((a for a in agents if a.qual == "main"), None)

    lines: list[str] = [f"# Session digest: {work_dir.name}", ""]
    if orch:
        lines.append(
            f"- orchestrator: {orch.model or 'unknown'} | "
            f"{orch.duration_s:.0f}s | ${orch.cost:.3f}"
        )
    lines.append(f"- agents: {len(agents)} | total cost: ${total_cost:.3f}")
    lines.append("")

    lines += _render_tree(work_dir, agents)
    lines.append("")
    lines += _render_root_artifacts(work_dir)

    for a in agents:
        lines.append("")
        lines += _render_agent(a, brief)

    return "\n".join(lines) + "\n", index


def _render_tree(work_dir: Path, agents: list[_AgentDigest]) -> list[str]:
    lines = ["## Workflow tree", "", "- **main** (orchestrator)"]
    # group non-main agents by their run (agent.rN)
    groups: dict[str, list[_AgentDigest]] = {}
    for a in agents:
        if a.qual == "main":
            continue
        run_key = a.qual.rsplit(".", 1)[0]  # agent.rN
        groups.setdefault(run_key, []).append(a)
    for run_key, members in groups.items():
        agent = run_key.split(".")[0]
        lines.append(f"  - parallel fan-out: **{agent}** ({run_key})")
        for a in members:
            if a.qual.endswith(".cons"):
                lines.append(f"    - {a.qual}: {a.duration_s:.0f}s, ${a.cost:.3f} — consolidator")
            else:
                status = "summary written" if a.summary_ok else "NO summary.md (treat as failed)"
                lines.append(
                    f"    - {a.qual}: {a.duration_s:.0f}s, ${a.cost:.3f}, "
                    f"{a.tool_count} tool calls — {status}"
                )
                lines.append(f"      - log: `{a.log_rel}` | workdir: `{a.workdir_rel}/`")
    return lines


def _render_root_artifacts(work_dir: Path) -> list[str]:
    lines = ["## Final artifacts (workdir root)", ""]
    found = False
    for f in sorted(work_dir.iterdir()):
        if f.name in _ROOT_SKIP or f.name.startswith("."):
            continue
        if f.is_file():
            lines.append(f"- `{f.name}` ({_human_size(f.stat().st_size)})")
            found = True
    if not found:
        lines.append("- (none)")
    return lines


def _render_agent(a: _AgentDigest, brief: bool) -> list[str]:
    lines = [f"### {a.qual} — {a.heading}"]
    lines.append(
        f"model: {a.model or 'unknown'} | {a.duration_s:.0f}s | "
        f"${a.cost:.3f} | {a.tool_count} tool calls"
    )
    if a.workdir_rel:
        lines.append(f"workdir: {a.workdir_rel}/")
    lines.append("")

    if a.task_text:
        lines.append(
            f'**Task** [p0]: "{_truncate(a.task_text, _TASK_LEN)}" '
            f"(full prompt via digest-get {a.qual}/p0)"
        )
        lines.append("")

    if a.writes:
        lines.append("**Artifacts**")
        for i, (fname, chain) in enumerate(sorted(a.writes.items()), start=1):
            lines.append(f"- [a{i}] {fname} ({', '.join(chain)})")
        lines.append("")

    if a.script_runs:
        lines.append("**Script runs**")
        for s in a.script_runs:
            mark = "✓" if s["ok"] else "✗ error"
            dur = f"{s['duration_s']:.0f}s" if s["duration_s"] is not None else ""
            detail = f"{s['stream']} {s['n_lines']} lines" if s["n_lines"] else "no output"
            if s["tail"]:
                detail += f" — {s['tail']}"
            lines.append(f"- [{s['id']}] bash `{_truncate(s['cmd'], 60)}`  {mark}  {dur}  ({detail})")
        lines.append("")

    if brief:
        counts = ", ".join(f"{k}×{v}" for k, v in a.tool_counter.most_common())
        if counts:
            lines.append(f"**Tool calls**: {counts}")
    else:
        other = {k: v for k, v in a.tool_counter.items() if k not in ("bash",)}
        if other:
            counts = ", ".join(f"{k}×{v}" for k, v in Counter(other).most_common())
            lines.append(f"**Other tool calls**: {counts}")

    if a.excerpts:
        lines.append("**Reasoning excerpts**")
        for xid, txt in a.excerpts:
            lines.append(f"- [{xid}] \"{txt}\"")
    return lines


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_digest(work_dir: str | Path, *, brief: bool = False) -> Path:
    """
    Write ``_digest/digest.md`` and ``_digest/index.json`` into ``work_dir``.

    Returns the path to the digest directory.
    """
    work_dir = Path(work_dir)
    md, index = build_digest(work_dir, brief=brief)
    out_dir = work_dir / DIGEST_DIR
    out_dir.mkdir(exist_ok=True)
    (out_dir / "digest.md").write_text(md, encoding="utf-8")
    (out_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return out_dir


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _truncate(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _human_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f}MB"
    if n >= 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n}B"
