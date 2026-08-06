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
from string import Template
from typing import Any

from dlab.dpack_codemap import entry_params, load_code_map
from dlab.opencode_logparser import (
    get_tool_error,
    get_tool_input,
    get_tool_name,
    get_tool_output,
    parse_log_file,
)
from dlab.session_digest import _collect_agents

SKELETON_DIR = "skeleton"

_IMAGE_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml",
}
# A bash command that runs a python script: capture the script path.
_PY_SCRIPT = re.compile(r"\bpython3?\s+(?:-\S+\s+)*([\w./-]+\.py)\b")
# string.Template placeholders in an LLM-authored call template: $name / ${name}.
_PLACEHOLDER = re.compile(r"\$\{?(\w+)\}?")
# Filesystem/plumbing bash we don't surface as notebook cells.
_SKIP_BASH = re.compile(
    r"^\s*(cd|ls|cp|mv|rm|mkdir|cat|echo|git|pwd|export|chmod|touch|find|grep|"
    r"which|test|\[|sleep|wc|sort|head|tail|sed|awk)\b")
# dlab orchestration plumbing, not analysis the notebook should show.
_SKIP_TOOLS = {"parallel-agents", "task", "todowrite", "todoread"}
# shell decorations that don't change what the script did (redirects, pipes,
# timeouts, chaining) — stripped when keying a run for dedup.
_SHELL_OPS = ("2>&1", "2>", "1>", "&>", "|", ">", "<", ";", "&&", " & ")


def _script_run_args(cmd: str, script: str) -> str:
    """The script's real args (tokens after the ``.py`` path, up to the first shell
    redirect/pipe/operator), so ``foo.py`` re-run with different capture decorations
    keys the same, but ``foo.py --pct 5`` vs ``--pct 50`` keys differently."""
    after = cmd.split(script, 1)[1] if script in cmd else ""
    cut = len(after)
    for op in _SHELL_OPS:
        i = after.find(op)
        if i != -1:
            cut = min(cut, i)
    return after[:cut].strip()
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
    kind: str = ""                         # script | custom-tool | shell
    tid: str = ""                          # digest tool-call id (produced_by)
    stream_ids: list[str] = field(default_factory=list)  # digest rN ids for this call
    dedup_key: str = ""                    # collapse repeated runs (same script / same tool call)


@dataclass
class SkeletonNotebook:
    agent: str                             # e.g. "modeler/instance-4"
    cells: list[SkeletonCell] = field(default_factory=list)
    phase: str = ""                        # agent role (data-preparer, modeler); "" = orchestrator
    instance: str = ""                     # instance-N ("" = orchestrator)
    adopted: bool = True                   # False → a non-adopted attempt (goes to attempts/)
    qual: str = ""                         # digest agent id (e.g. "modeler.r1.i4") for digest-get


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


def _is_dotted_module(ref: str) -> bool:
    """True if ``ref`` is an importable dotted module (not a file path)."""
    return bool(ref) and "/" not in ref and not ref.endswith(".py")


def _custom_tool_code(
    name: str, inp: dict[str, Any], code_map: dict[str, Any], dpack: Path,
) -> str | None:
    """A clean cell for a custom-tool call: import the real function it ran and
    call it. When the entry function's parameters *are* the tool's inputs, emit a
    runnable ``from module import fn`` + ``fn(**inputs)``. Otherwise (a CLI whose
    ``main()`` loads/transforms before calling the work function, so the signatures
    don't line up) fall back to importing the underlying function and documenting
    the exact invocation. Never a verbatim module dump."""
    tool = code_map.get("tools", {}).get(name) or {}
    ran = tool.get("runs") or (f"python -m {tool['module']}" if tool.get("module") else name)
    kwargs = ", ".join(f"{k}={v!r}" for k, v in inp.items())

    # An LLM-authored call template (from `map-dpack --model`) is a parametrized
    # load+call with $input placeholders — substitute this run's values (as Python
    # reprs) deterministically. Handles the CLI tools whose main() loads/transforms
    # so no direct fn(**inputs) call exists.
    template = tool.get("call_template")
    if template and inp:
        # Optional inputs the call omitted have no value to substitute; by the
        # template convention each placeholder sits on its own `kwarg=$name,`
        # line, so drop those lines (rather than let safe_substitute emit a bare
        # `$name`, which is invalid Python). Decide from the template text, before
        # substitution, so a literal `$` inside a substituted value can't trigger
        # a false drop. Keep any line that also carries a present placeholder.
        missing = {ph for ph in _PLACEHOLDER.findall(template) if ph not in inp}
        if missing:
            kept = []
            for line in template.splitlines():
                phs = set(_PLACEHOLDER.findall(line))
                if phs and phs <= missing:
                    continue
                kept.append(line)
            template = "\n".join(kept)
        filled = Template(template).safe_substitute({k: repr(v) for k, v in inp.items()})
        return filled if filled.endswith("\n") else filled + "\n"

    entry = tool.get("entry")
    if not entry:
        return f"# The `{name}` tool ran: {ran}\n# inputs: {kwargs}\n"

    func, defined_in = entry.get("function"), entry.get("defined_in", "")
    dotted = defined_in if _is_dotted_module(defined_in) else None
    params = entry_params(dpack, entry) or []
    call: str | None = None
    if dotted and func and inp:
        if set(inp) <= set(params):
            call = f"{func}({kwargs})"                  # names line up → kwargs
        elif len(inp) == 1 and len(params) >= 1:
            (val,) = inp.values()                       # single arg → positional
            call = f"{func}({val!r})"                    # (schema name may differ from param)
    if call is not None:
        return f"from {dotted} import {func}\n{call}\n"
    # fallback: import the underlying function (if importable) + the invocation
    lines = [f"# The `{name}` tool ran: {ran}", f"# inputs: {kwargs}"]
    if dotted and func:
        lines.append(f"from {dotted} import {func}   # the underlying function it ran")
    return "\n".join(lines) + "\n"


def _build_cells(
    log_path: Path, search_root: Path, code_map: dict[str, Any], dpack: Path | None,
    custom_tools: set[str], tool_calls: list[dict[str, Any]] | None = None,
) -> list[SkeletonCell]:
    events = parse_log_file(log_path)
    tool_calls = tool_calls or []
    written: dict[str, str] = {}
    cells: list[SkeletonCell] = []
    current: SkeletonCell | None = None
    tc_idx = 0  # tracks the digest tool-call for the current tool_use (aligned by order)

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
        # advance the digest tool-call cursor for EVERY tool_use (incl. skipped), so
        # tN ids stay aligned with the digest's per-agent counter.
        tc = tool_calls[tc_idx] if tc_idx < len(tool_calls) else {}
        tc_idx += 1
        name = get_tool_name(ev) or ""
        if name in _SKIP_TOOLS:
            continue
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
        kind = ""
        dedup = ""
        if name in custom_tools and dpack is not None:
            source = _custom_tool_code(name, inp, code_map, dpack)
            label, kind = f"custom tool: {name}", "custom-tool"
            # exact-arg dedup only: a retried identical call collapses; a sweep
            # (same tool, different args → distinct outputs) stays distinct.
            dedup = f"tool:{name}:" + json.dumps(inp, sort_keys=True, default=str)
        elif name == "bash":
            cmd = (inp.get("command") or "").strip()
            m = _PY_SCRIPT.search(cmd)
            if m:
                source = _script_source(m.group(1), written, search_root)
                label, kind = f"ran: {cmd}", "script"
                # Key on the script + its real args (shell decorations stripped):
                # progressive edits re-run the same invocation → collapse to the
                # final version; a script sweep (different args) stays distinct.
                dedup = f"script:{Path(m.group(1)).name}:{_script_run_args(cmd, m.group(1))}"
            elif "python" in cmd:
                source = f"# {cmd}\n"        # python -m / -c with no script file
                label, kind = f"ran: {cmd}", "shell"
            elif not _SKIP_BASH.match(cmd):
                source = f"!{cmd}"           # a substantive shell command
                label, kind = "shell", "shell"
        if source is None:
            continue

        close()
        start, end = _time_window(ev)
        stream = get_tool_error(ev) or ""
        if not stream:
            out = get_tool_output(ev) or ""
            stream = out
        current = SkeletonCell(
            source=source, stream=stream, start=start, end=end, label=label,
            kind=kind, tid=tc.get("id", ""), dedup_key=dedup,
            stream_ids=[b["id"] for b in tc.get("raw_ids", [])])
    close()
    return cells


def _dedup_reruns(cells: list[SkeletonCell]) -> list[SkeletonCell]:
    """Collapse repeated runs of the same script (progressively edited to fix bugs)
    and identical tool retries to the FINAL run — the version that produced the
    output. A parameter sweep (same tool, different args) has distinct dedup keys,
    so it is left intact for the composer to summarize."""
    last: dict[str, int] = {}
    for i, c in enumerate(cells):
        if c.dedup_key:
            last[c.dedup_key] = i
    return [c for i, c in enumerate(cells)
            if not c.dedup_key or last[c.dedup_key] == i]


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


# A copy FROM an instance dir (group 1=run ts, 2=instance) to a dest token
# (group 3). Non-greedy up to the source path, not crossing && or | so a compound
# command's later segments don't bleed in.
_CP_ADOPT = re.compile(
    r"\b(?:cp|mv|rsync)\b[^|&]*?parallel/run-(\d+)/(instance-\d+)/\S*\s+(\S+)")


def _adopted_instances(work_dir: Path) -> set[tuple[str, str]]:
    """Which ``(run_ts, instance)`` an agent promoted to the workdir root — the
    adopted path. Signal: a ``cp``/``mv``/``rsync`` FROM an instance dir to a
    destination that is NOT itself under ``parallel/`` (i.e. the run root). Fully
    general — no pack knowledge."""
    adopted: set[tuple[str, str]] = set()
    logs_dir = work_dir / "_opencode_logs"
    for log in logs_dir.rglob("*.log"):
        for ev in parse_log_file(log):
            if ev.event_type != "tool_use" or get_tool_name(ev) != "bash":
                continue
            cmd = (get_tool_input(ev) or {}).get("command", "")
            for m in _CP_ADOPT.finditer(cmd):
                if "parallel/run-" not in m.group(3):   # dest is the run root
                    adopted.add((m.group(1), m.group(2)))
    return adopted


def build_skeleton(
    work_dir: str | Path, *, dpack: str | Path | None = None,
) -> list[SkeletonNotebook]:
    """Build one deterministic notebook per agent that ran code, tagged with its
    phase (agent role) and whether it is the adopted instance or an attempt."""
    work_dir = Path(work_dir).resolve()
    logs_dir = work_dir / "_opencode_logs"
    code_map: dict[str, Any] = load_code_map(dpack) if dpack else {"tools": {}}
    dpack_path = Path(dpack).resolve() if dpack else None
    custom_tools = {p.stem for p in (work_dir / ".opencode" / "tools").glob("*.ts")}
    adopted = _adopted_instances(work_dir)
    # digest agents give the qual + per-agent tool-call ids (tN/rN) the hints point
    # at, so the composer can digest-get the context for each cell.
    digest_by_log = {a.log_path.resolve(): a for a in _collect_agents(work_dir)}

    # (agent label, phase, instance, adopted, log, workdir root)
    logs: list[tuple[str, str, str, bool, Path, Path]] = []
    main = logs_dir / "main.log"
    if main.exists():
        logs.append(("orchestrator", "", "", True, main, work_dir))
    # Parallel instances: log at _opencode_logs/<agent>-parallel-run-<ts>/instance-N.log,
    # its workdir at parallel/run-<ts>/instance-N/.
    for d in sorted(logs_dir.glob("*-parallel-run-*")):
        agent, _, ts = d.name.rpartition("-parallel-run-")
        for log in sorted(d.glob("instance-*.log")):
            inst_wd = work_dir / "parallel" / f"run-{ts}" / log.stem
            root = inst_wd if inst_wd.is_dir() else work_dir
            is_adopted = (ts, log.stem) in adopted
            logs.append((f"{agent}/{log.stem}", agent, log.stem, is_adopted, log, root))

    notebooks: list[SkeletonNotebook] = []
    for label, phase, instance, is_adopted, log_path, root in logs:
        ad = digest_by_log.get(log_path.resolve())
        cells = _build_cells(log_path, root, code_map, dpack_path, custom_tools,
                             ad.tool_calls if ad else None)
        cells = _dedup_reruns(cells)   # keep only the final run of each script
        _attribute_figures(cells, root)
        cells = [c for c in cells if c.figures or c.stream.strip() or c.source.strip()]
        if cells:
            notebooks.append(SkeletonNotebook(
                agent=label, cells=cells, phase=phase, instance=instance,
                adopted=is_adopted, qual=ad.qual if ad else label))
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
    status = ("orchestrator" if not nb.phase
              else f"{nb.phase} · {nb.instance} · "
                   + ("**adopted**" if nb.adopted else "**not adopted (attempt)**"))
    cells: list[dict[str, Any]] = [{
        "cell_type": "markdown", "metadata": {},
        "source": [f"# {nb.agent} — deterministic skeleton\n\n",
                   f"*{status}*\n\n",
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
        # Context hints for the composer: where to digest-get the WHY for this cell.
        hint: dict[str, Any] = {"kind": c.kind}
        if nb.qual and c.tid:
            hint["produced_by"] = f"{nb.qual}/{c.tid}"
        if nb.qual and c.stream_ids:
            hint["streams"] = [f"{nb.qual}/{r}" for r in c.stream_ids]
        cells.append({
            "cell_type": "code", "execution_count": exec_count,
            "metadata": {"dlab": hint}, "outputs": outputs,
            "source": c.source.splitlines(keepends=True),
        })
    return {
        "cells": cells, "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python"},
            "dlab": {"skeleton": True, "agent": nb.agent, "qual": nb.qual,
                     "phase": nb.phase, "adopted": nb.adopted,
                     "task": f"{nb.qual}/p0" if nb.qual else None},
        }, "nbformat": 4, "nbformat_minor": 5,
    }


def write_skeletons(
    work_dir: str | Path, *, dpack: str | Path | None = None,
) -> list[Path]:
    """Build and write the deterministic skeleton notebooks into
    ``<work_dir>/skeleton/``: the adopted path as numbered phase notebooks, and
    non-adopted instances under ``skeleton/attempts/``. Returns the written paths."""
    work_dir = Path(work_dir).resolve()
    notebooks = build_skeleton(work_dir, dpack=dpack)
    out_dir = work_dir / SKELETON_DIR
    out_dir.mkdir(exist_ok=True)
    written: list[Path] = []

    def _write(nb: SkeletonNotebook, dest: Path) -> None:
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(json.dumps(_render_notebook(nb), indent=1) + "\n",
                        encoding="utf-8")
        written.append(dest)

    for i, nb in enumerate(n for n in notebooks if n.adopted):
        name = nb.phase or "orchestrator"
        _write(nb, out_dir / f"{i:02d}_{name}.ipynb")
    for nb in (n for n in notebooks if not n.adopted):
        _write(nb, out_dir / "attempts" / f"{nb.phase}_{nb.instance}.ipynb")
    return written
