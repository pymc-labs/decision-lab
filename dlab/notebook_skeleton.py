"""
Deterministic notebook skeleton (issue #68).

Build Jupyter notebooks from a finished run using ONLY deterministic data: the
real code that ran — scripts the agent wrote, and the code map's resolved library
code for custom tools — paired with the real output it produced (captured
stdout/stderr and the figures it wrote). No LLM, so it is correct by construction:
no hallucinated code, no orphaned figures, no empty-output cells. This is both a
shippable artifact in its own right and the substrate the (optional) LLM-narrated
notebook is layered onto.

Granularity is coarse by decision: one code cell per *execution* — a script run
(``python foo.py``) or a custom-tool call — carrying that execution's code and all
of its outputs, in chronological order, one notebook per agent that ran code.
Splitting a multi-figure script into per-figure cells is deferred (it needs
per-line output attribution that isn't deterministic).
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dlab.dpack_codemap import load_code_map, resolve_entry_code
from dlab.opencode_logparser import (
    get_tool_error,
    get_tool_input,
    get_tool_name,
    get_tool_output,
    parse_log_file,
)

SKELETON_DIR = "skeleton"

_IMAGE_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml",
}
# A bash command that runs a python script: capture the script path.
_PY_SCRIPT = re.compile(r"\bpython3?\s+(?:-\S+\s+)*([\w./-]+\.py)\b")
# Filesystem/plumbing bash we don't surface as notebook cells.
_SKIP_BASH = re.compile(
    r"^\s*(cd|ls|cp|mv|rm|mkdir|cat|echo|git|pwd|export|chmod|touch|find|grep|"
    r"which|test|\[|sleep|wc|sort|head|tail|sed|awk)\b")
_OUTPUT_CAP = 200  # lines of captured stdout/stderr kept per cell
# Not real analysis output — skip when walking a work dir for produced figures.
_EXCLUDE_DIRS = {"_digest", "notebooks", SKELETON_DIR, "_opencode_logs",
                 ".opencode", "_hooks", "_docker", "parallel", ".git", "__pycache__"}
_FIGURE_SLACK_MS = 2000  # a figure may be flushed just after the tool's end


@dataclass
class SkeletonCell:
    """One deterministic code cell: real source + the outputs it produced."""
    source: str
    stream: str = ""                       # captured stdout/stderr
    figures: list[Path] = field(default_factory=list)
    start: int | None = None               # ms; for figure attribution
    end: int | None = None
    label: str = ""                        # short provenance note


@dataclass
class SkeletonNotebook:
    agent: str                             # e.g. "modeler.r2.i2"
    cells: list[SkeletonCell] = field(default_factory=list)


def _time_window(ev: Any) -> tuple[int | None, int | None]:
    tt = ev.part.get("state", {}).get("time", {}) if isinstance(ev.part, dict) else {}
    if isinstance(tt, dict):
        return tt.get("start"), tt.get("end")
    return None, None


def _script_source(script: str, written: dict[str, str], search_root: Path) -> str | None:
    """The content of a script *as of the run that referenced it*: the replayed
    write+edit content if we tracked it (keyed by basename, since runs reference
    the script relatively but writes log an absolute path), else the file on disk.
    """
    name = Path(script).name
    if name in written:
        return written[name]
    for cand in (search_root / script, *search_root.rglob(name)):
        if cand.is_file():
            try:
                return cand.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
    return None


def _custom_tool_code(
    name: str, inp: dict[str, Any], code_map: dict[str, Any], dpack: Path,
) -> str | None:
    """The resolved library code a custom tool ran, headed by its invocation."""
    entry = (code_map.get("tools", {}).get(name) or {}).get("entry")
    if not entry:
        return None
    code = resolve_entry_code(dpack, entry)
    if not code:
        return None
    args = ", ".join(f"{k}={v!r}" for k, v in inp.items())
    header = (f"# Ran by the `{name}` tool as: {name}({args})\n"
              f"# Real code it executed (resolved from the decision-pack library):")
    return f"{header}\n{code}"


def _build_cells(
    log_path: Path, search_root: Path, code_map: dict[str, Any], dpack: Path | None,
    custom_tools: set[str],
) -> list[SkeletonCell]:
    events = parse_log_file(log_path)
    written: dict[str, str] = {}
    cells: list[SkeletonCell] = []
    current: SkeletonCell | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            cells.append(current)
            current = None

    for ev in events:
        if ev.event_type == "raw_text" and current is not None:
            current.stream += ev.part.get("text", "")
            continue
        if ev.event_type != "tool_use":
            continue
        name = get_tool_name(ev) or ""
        inp = get_tool_input(ev) or {}
        # Replay file state by basename so a later `python script.py` run resolves
        # to the code AS OF that run (writes set it; edits patch it in place).
        if name == "write":
            fp = inp.get("filePath")
            if fp and inp.get("content") is not None:
                written[Path(fp).name] = inp["content"]
            continue
        if name == "edit":
            fp = inp.get("filePath")
            old, new = inp.get("oldString"), inp.get("newString")
            if fp and old is not None and new is not None:
                key = Path(fp).name
                base = written.get(key)
                if base is None:  # first seen via edit — seed from disk, then patch
                    base = _script_source(key, {}, search_root)
                if base is not None:
                    written[key] = base.replace(old, new)
            continue

        source: str | None = None
        label = ""
        if name in custom_tools and dpack is not None:
            source = _custom_tool_code(name, inp, code_map, dpack)
            label = f"custom tool: {name}"
        elif name == "bash":
            cmd = (inp.get("command") or "").strip()
            m = _PY_SCRIPT.search(cmd)
            if m:
                source = _script_source(m.group(1), written, search_root)
                label = f"ran: {cmd}"
            elif "python" in cmd and _PY_SCRIPT.search(cmd) is None:
                source = f"# {cmd}\n"        # python -m / -c with no script file
                label = f"ran: {cmd}"
            elif not _SKIP_BASH.match(cmd):
                source = f"!{cmd}"           # a substantive shell command
                label = "shell"
        if source is None:
            continue

        close()
        start, end = _time_window(ev)
        stream = get_tool_error(ev) or ""
        if not stream:
            out = get_tool_output(ev) or ""
            stream = out
        current = SkeletonCell(source=source, stream=stream, start=start,
                               end=end, label=label)
    close()
    return cells


def _figure_files(search_root: Path) -> list[tuple[float, Path]]:
    out: list[tuple[float, Path]] = []
    for f in search_root.rglob("*"):
        if f.suffix.lower() not in _IMAGE_MIME or not f.is_file():
            continue
        rel = f.relative_to(search_root)
        if any(part in _EXCLUDE_DIRS for part in rel.parts):
            continue
        try:
            out.append((f.stat().st_mtime * 1000, f))
        except OSError:
            continue
    return out


def _attribute_figures(cells: list[SkeletonCell], search_root: Path) -> None:
    """Attach each image to the execution whose time window *produced* it — mtime
    within ``[start, end + slack]``. Figures outside every execution window (e.g.
    copies made afterwards) are dropped: they weren't produced by a shown cell."""
    windowed = [c for c in cells if c.start is not None and c.end is not None]
    for mtime_ms, f in sorted(_figure_files(search_root)):
        for c in windowed:
            if c.start <= mtime_ms <= c.end + _FIGURE_SLACK_MS:
                c.figures.append(f)
                break


def build_skeleton(
    work_dir: str | Path, *, dpack: str | Path | None = None,
) -> list[SkeletonNotebook]:
    """Build one deterministic notebook per agent that ran code."""
    work_dir = Path(work_dir).resolve()
    logs_dir = work_dir / "_opencode_logs"
    code_map: dict[str, Any] = load_code_map(dpack) if dpack else {"tools": {}}
    dpack_path = Path(dpack).resolve() if dpack else None
    custom_tools = {p.stem for p in (work_dir / ".opencode" / "tools").glob("*.ts")}

    notebooks: list[SkeletonNotebook] = []
    logs: list[tuple[str, Path, Path]] = []
    main = logs_dir / "main.log"
    if main.exists():
        logs.append(("orchestrator", main, work_dir))
    # Parallel instances: log at _opencode_logs/<agent>-parallel-run-<ts>/instance-N.log,
    # its workdir at parallel/run-<ts>/instance-N/.
    for d in sorted(logs_dir.glob("*-parallel-run-*")):
        agent, _, ts = d.name.rpartition("-parallel-run-")
        for log in sorted(d.glob("instance-*.log")):
            inst_wd = work_dir / "parallel" / f"run-{ts}" / log.stem
            root = inst_wd if inst_wd.is_dir() else work_dir
            logs.append((f"{agent}/{log.stem}", log, root))

    for agent, log_path, root in logs:
        cells = _build_cells(log_path, root, code_map, dpack_path, custom_tools)
        _attribute_figures(cells, root)
        cells = [c for c in cells if c.figures or c.stream.strip() or c.source.strip()]
        if cells:
            notebooks.append(SkeletonNotebook(agent=agent, cells=cells))
    return notebooks


# --------------------------------------------------------------------------- #
# ipynb rendering (deterministic; embeds the run's real outputs)
# --------------------------------------------------------------------------- #

def _image_output(f: Path) -> dict[str, Any] | None:
    mime = _IMAGE_MIME.get(f.suffix.lower())
    if not mime:
        return None
    try:
        raw = f.read_bytes()
    except OSError:
        return None
    data = raw.decode("utf-8", "replace") if mime == "image/svg+xml" \
        else base64.b64encode(raw).decode("ascii")
    return {"output_type": "display_data", "data": {mime: data},
            "metadata": {"dlab_source": str(f)}}


def _render_notebook(nb: SkeletonNotebook) -> dict[str, Any]:
    cells: list[dict[str, Any]] = [{
        "cell_type": "markdown", "metadata": {},
        "source": [f"# {nb.agent} — deterministic skeleton\n\n",
                   "Assembled from the run's real code and outputs — **not executed**. ",
                   "Every code cell is the exact code that ran, with the output it produced."],
    }]
    exec_count = 0
    for c in nb.cells:
        exec_count += 1
        outputs: list[dict[str, Any]] = []
        stream = "\n".join(c.stream.splitlines()[-_OUTPUT_CAP:]).strip()
        if stream:
            outputs.append({"output_type": "stream", "name": "stdout",
                            "text": stream})
        for f in c.figures:
            img = _image_output(f)
            if img:
                outputs.append(img)
        if c.label:
            cells.append({"cell_type": "markdown", "metadata": {},
                          "source": [f"*{c.label}*"]})
        cells.append({
            "cell_type": "code", "execution_count": exec_count,
            "metadata": {}, "outputs": outputs,
            "source": c.source.splitlines(keepends=True),
        })
    return {
        "cells": cells, "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python"},
            "dlab": {"skeleton": True, "agent": nb.agent},
        }, "nbformat": 4, "nbformat_minor": 5,
    }


def write_skeletons(
    work_dir: str | Path, *, dpack: str | Path | None = None,
) -> list[Path]:
    """Build and write the deterministic skeleton notebooks into
    ``<work_dir>/skeleton/``; return the written paths."""
    work_dir = Path(work_dir).resolve()
    notebooks = build_skeleton(work_dir, dpack=dpack)
    out_dir = work_dir / SKELETON_DIR
    out_dir.mkdir(exist_ok=True)
    written: list[Path] = []
    for i, nb in enumerate(notebooks):
        safe = nb.agent.replace("/", "_")
        dest = out_dir / f"{i:02d}_{safe}.ipynb"
        dest.write_text(json.dumps(_render_notebook(nb), indent=1) + "\n",
                        encoding="utf-8")
        written.append(dest)
    return written
