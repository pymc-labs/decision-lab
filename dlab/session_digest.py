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

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
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
    excerpts: list[tuple[str, str]]             # (id, truncated text)
    index: dict[str, dict[str, Any]]            # local ids -> pointer
    # attribution inputs (cross-agent pass fills ``artifacts`` from these)
    run_id: str | None                          # fan-out run; siblings share it
    start_ts: int                               # first event timestamp
    log_path: Path                              # for the mention scan
    workdir_base: Path                          # dir walked for artifacts
    writes: dict[str, list[str]]                # basename -> ["written t6", ...]
    disk_files: list[Path]                      # files present in the workdir
    summary_ok: bool = True
    mentions: dict[str, int] = field(default_factory=dict)   # basename -> ts
    artifacts: list[dict[str, Any]] = field(default_factory=list)


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


def _walk_workdir_files(base: Path) -> list[Path]:
    """Every real file in an agent's workdir, pruning session internals.

    Enumerating the workdir on disk (not just tool inputs) is what surfaces
    script-produced outputs (figures, ``.nc``, ``.parquet``, ``roas.csv``):
    those never pass through a ``write``/``edit`` tool call, so a log-only view
    misses them. Session-internal dirs (``data``, ``_hooks``, ``parallel``, …)
    are pruned, and ``instance-*`` subdirs are skipped so a consolidator whose
    workdir is the run root does not swallow its siblings' files.
    """
    files: list[Path] = []
    if not base.is_dir():
        return files
    for entry in sorted(base.iterdir()):
        if entry.name in _ROOT_SKIP or entry.name.startswith("."):
            continue
        if entry.is_file():
            files.append(entry)
        elif entry.is_dir() and not entry.name.startswith("instance-"):
            for sub in sorted(entry.rglob("*")):
                rel_parts = sub.relative_to(base).parts
                if sub.is_file() and not any(p.startswith(".") for p in rel_parts):
                    files.append(sub)
    return files


def _digest_agent(qual: str, role: str, heading: str, log_path: Path,
                  work_dir: Path, workdir_rel: str | None, run_id: str | None,
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
    start_ts = min(ts) if ts else 0

    base = (work_dir / workdir_rel) if workdir_rel else work_dir
    disk_files = _walk_workdir_files(base)

    return _AgentDigest(
        qual=qual, role=role, heading=heading, log_rel=log_rel,
        workdir_rel=workdir_rel, model=model, duration_s=duration_s, cost=cost,
        tool_count=tool_count, task_text=task_text, task_line=task_line,
        tool_counter=tool_counter, script_runs=script_runs,
        excerpts=excerpts, index=index, run_id=run_id, start_ts=start_ts,
        log_path=log_path, workdir_base=base, writes=writes,
        disk_files=disk_files, summary_ok=summary_ok,
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
            run_id=None,
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
                    inst_log, work_dir, inst_work, run_id=d.name,
                    summary_ok=summary_ok,
                ))
            cons_log = d / "consolidator.log"
            if cons_log.exists():
                qual = f"{agent}.r{round_idx}.cons"
                agents.append(_digest_agent(
                    qual, agent, f"{agent} consolidator{retry}",
                    cons_log, work_dir, f"parallel/run-{ts}", run_id=d.name,
                ))
    return agents


# ---------------------------------------------------------------------------
# Artifact attribution (produced vs. inherited)
# ---------------------------------------------------------------------------


def _file_sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _same_content(a: Path, b: Path) -> bool:
    """True iff both files exist with identical size and sha256."""
    try:
        if not b.is_file() or a.stat().st_size != b.stat().st_size:
            return False
    except OSError:
        return False
    ha = _file_sha256(a)
    return ha is not None and ha == _file_sha256(b)


def _scan_mentions(log_path: Path, pattern: "re.Pattern | None") -> dict[str, int]:
    """Earliest timestamp at which each known basename appears anywhere in this
    agent's events — bash commands, tool ``filePath``s, the contents of scripts
    it wrote, and tool outputs (all live in the raw NDJSON line)."""
    mentions: dict[str, int] = {}
    if pattern is None:
        return mentions
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return mentions
    for line in text.splitlines():
        ev = parse_line(line)
        if ev is None or not ev.timestamp:
            continue
        ts = ev.timestamp
        for m in pattern.finditer(line):
            name = m.group(0)
            if name not in mentions or ts < mentions[name]:
                mentions[name] = ts
    return mentions


def _attribute_artifacts(agents: list[_AgentDigest], work_dir: Path) -> None:
    """Fill each agent's ``artifacts`` list, dropping inherited copies.

    A file ``f`` in agent ``A`` is *inherited* iff some agent **outside A's
    fan-out run** mentioned ``f``'s name **before A started** (chronology +
    sibling isolation — the later ``cp`` that lifts an instance's output to the
    root cannot steal authorship, and isolated siblings cannot seed each other).
    An inherited file is dropped only when it is byte-identical to the
    workspace-root copy that seeded A; if A changed it, that is real derived
    work and it is kept, flagged ``modified from inherited``.
    """
    universe = {f.name for a in agents for f in a.disk_files}
    pattern = (
        re.compile("|".join(re.escape(n) for n in
                            sorted(universe, key=len, reverse=True)))
        if universe else None
    )
    for a in agents:
        a.mentions = _scan_mentions(a.log_path, pattern)

    for a in agents:
        arts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for f in sorted(a.disk_files,
                        key=lambda p: str(p.relative_to(a.workdir_base))):
            rel = str(f.relative_to(a.workdir_base))
            name = f.name
            seen.add(name)
            # Inheritance needs BOTH: an external (non-sibling) agent named the
            # file before A started (so it pre-existed A's work, not a basename
            # collision with an independently-produced sibling/later file), AND
            # the workspace-root seed actually holds it at the same path.
            foreign = [b.mentions[name] for b in agents
                       if b is not a and b.run_id != a.run_id
                       and name in b.mentions]
            ref = work_dir / rel
            note: str | None = None
            if foreign and min(foreign) < a.start_ts and ref.is_file():
                if _same_content(f, ref):
                    continue  # untouched copy of the seed — drop silently
                note = "modified from inherited"
            try:
                size: int | None = f.stat().st_size
            except OSError:
                size = None
            arts.append({"path": rel, "size": size,
                         "chain": a.writes.get(name), "note": note})
        # Files written via tool but no longer on disk (renamed/deleted) keep
        # their provenance so the story isn't lost.
        for nm, chain in sorted(a.writes.items()):
            if nm not in seen:
                arts.append({"path": nm, "size": None, "chain": chain,
                             "note": None})
        a.artifacts = arts


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
    _attribute_artifacts(agents, work_dir)
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

    if a.artifacts:
        lines.append(f"**Artifacts** ({len(a.artifacts)})")
        for i, art in enumerate(a.artifacts, start=1):
            bits: list[str] = []
            if art["size"] is not None:
                bits.append(_human_size(art["size"]))
            if art["chain"]:
                bits.extend(art["chain"])
            if art.get("note"):
                bits.append(art["note"])
            meta = ", ".join(bits) if bits else "—"
            lines.append(f"- [a{i}] {art['path']} ({meta})")
        lines.append("")

    if a.script_runs:
        lines.append("**Script runs**")
        for s in a.script_runs:
            mark = "✓" if s["ok"] else "✗ error"
            dur = f"{s['duration_s']:.0f}s" if s["duration_s"] is not None else ""
            detail = f"{s['stream']} {s['n_lines']} lines" if s["n_lines"] else "no output"
            if s["tail"]:
                detail += f" — {s['tail']}"
            # Full command verbatim (whitespace-collapsed to one line) — the
            # composer needs the exact command that ran, not a preview.
            cmd = " ".join(s["cmd"].split())
            lines.append(f"- [{s['id']}] bash `{cmd}`  {mark}  {dur}  ({detail})")
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
