"""
Deterministic decision-pack code map (issue #68).

An opencode agent can only run two kinds of code: scripts it writes itself
(captured verbatim as ``write``/``edit`` tool calls in the log) and the custom
tools a decision-pack ships (each a ``.ts`` wrapper that usually shells out to the
pack's Python library, e.g. ``python -m LIB.MOD``). The first kind needs no
resolution — the code is already in the log. The second does: to inline *the real
code a tool ran* into a notebook, we must map each tool to the library code behind
it.

That wiring is **static and per-pack** (it does not change between runs), so it is
compiled once, here, by parsing the TypeScript wrappers and the Python modules they
invoke. The result is a ``code_map.json`` in the pack root. At notebook time
``dlab notebooks`` joins a run's actual tool calls against this map and pulls the
resolved code from source.

The extraction is deliberately deterministic — no LLM. Across the in-repo packs the
only genuinely ambiguous case is a module that dispatches to several work functions
chosen at runtime (recorded in the call's args, so it resolves at join time). Such
cases are recorded as ``entry_candidates`` with a ``residue`` note for an optional
LLM pass to refine later.

Pack shapes
-----------
- ``script-only``   — no custom tools (or only pure-TS helpers): every code block is
  a ``write`` tool call; the map's ``tools`` is empty and resolution is skipped.
- ``tool-backed``   — tools shell out to ``python -m LIB.MOD``.
- ``modal-inline``  — a tool dispatches to a named function deployed elsewhere
  (``modal.Function.from_name("app", "fn")``); the real code is that deployed
  function's body, reached *through* the dispatch and inlined to run locally.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

CODE_MAP_FILENAME = "code_map.json"


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_source_path(dpack: Path, ref: str) -> Path | None:
    """Resolve a map reference (a dpack-relative path OR a dotted module/package)
    to a file on disk, so its checksum can be taken."""
    direct = dpack / ref
    if direct.is_file():
        return direct
    base = (dpack / "docker").joinpath(*ref.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def _braced_block(src: str, key: str) -> str | None:
    """Return the text inside the first ``{...}`` following ``key:`` in ``src``,
    matching braces so nested objects are captured. ``None`` if ``key`` absent."""
    m = re.search(rf"\b{re.escape(key)}\s*:\s*\{{", src)
    if not m:
        return None
    depth = 0
    start = m.end() - 1
    for i in range(start, len(src)):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start + 1:i]
    return None


# --------------------------------------------------------------------------- #
# TypeScript wrapper extraction
# --------------------------------------------------------------------------- #

_PY_MODULE_RE = re.compile(r"python3?\s+-m\s+([\w.]+)")
_PY_INLINE_RE = re.compile(r"python3?\s+-c\b")
_PY_SCRIPT_RE = re.compile(r"python3?\s+([\w./-]+\.py)\b")
_INPUT_RE = re.compile(r"^\s*(\w+)\s*:\s*tool\.schema\.(\w+)\(", re.M)
_WRITE_OUT_RE = re.compile(r"""writeFileSync\(\s*(?:join\([^,]+,\s*)?["'`]([^"'`]+)["'`]""")


def _inline_python(src: str) -> str | None:
    """Capture the code a ``python -c`` invocation runs, resolving a ``${var}``
    reference back to its ``const var = `...``` definition when needed."""
    m = re.search(r"python3?\s+-c\s+", src)
    if not m:
        return None
    rest = src[m.end():]
    var = re.match(r"""["'`]?\$\{(\w+)""", rest)
    if var:
        cm = (re.search(rf"\b(?:const|let|var)\s+{var.group(1)}\s*=\s*`([^`]*)`", src, re.S)
              or re.search(rf"\b(?:const|let|var)\s+{var.group(1)}\s*=\s*\"([^\"]*)\"", src, re.S))
        return cm.group(1).strip() if cm else None
    lit = re.match(r"`([^`]*)`", rest) or re.match(r"\"([^\"]*)\"", rest)
    return lit.group(1).strip() if lit else None


def extract_ts_tool(ts_path: Path) -> dict[str, Any]:
    """Statically extract a tool wrapper's interface and what it invokes.

    Returns keys: ``name``, ``inputs`` (name/type/optional), ``runs`` (the module
    or inline marker), ``module`` (dotted, if ``python -m``), ``kind`` hint,
    ``inline_code`` (for ``python -c``), ``declared_outputs``.
    """
    src = _read(ts_path)
    out: dict[str, Any] = {"name": ts_path.stem}

    # inputs from the args: { ... } schema block
    args_block = _braced_block(src, "args") or ""
    inputs: list[dict[str, Any]] = []
    for name, typ in _INPUT_RE.findall(args_block):
        # find this input's own line to check for .optional()
        line = next((ln for ln in args_block.splitlines()
                     if re.match(rf"\s*{name}\s*:", ln)), "")
        inputs.append({"name": name, "type": typ, "optional": ".optional(" in line})
    out["inputs"] = inputs

    # what it runs
    mod = _PY_MODULE_RE.search(src)
    if mod:
        out["module"] = mod.group(1)
        out["runs"] = f"python -m {mod.group(1)}"
        out["kind"] = "python-module"
    elif _PY_INLINE_RE.search(src):
        out["kind"] = "python-inline"
        out["runs"] = "python -c <inline>"
        out["inline_code"] = _inline_python(src)
    else:
        script = _PY_SCRIPT_RE.search(src)
        if script:
            out["kind"] = "python-script"
            out["runs"] = f"python {script.group(1)}"
            out["script"] = script.group(1)
        else:
            out["kind"] = "pure-ts"
            out["runs"] = None

    out["declared_outputs"] = sorted(set(_WRITE_OUT_RE.findall(src)))
    return out


# --------------------------------------------------------------------------- #
# modal dispatch resolution (reach THROUGH a remote call to the deployed body)
# --------------------------------------------------------------------------- #

_FROM_NAME_RE = re.compile(
    r"""(?:modal\.Function\.)?from_name\(\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']""")


def _modal_app_files(dpack: Path) -> dict[str, Path]:
    """Map every ``modal.App("NAME")`` declared under ``docker/`` to its file."""
    apps: dict[str, Path] = {}
    docker = dpack / "docker"
    if not docker.is_dir():
        return apps
    for py in docker.rglob("*.py"):
        try:
            text = _read(py)
        except OSError:
            continue
        for name in re.findall(r"""modal\.App\(\s*["']([^"']+)["']""", text):
            apps[name] = py
    return apps


def _find_def(py: Path, func: str) -> bool:
    try:
        tree = ast.parse(_read(py))
    except (OSError, SyntaxError):
        return False
    return any(isinstance(n, ast.FunctionDef) and n.name == func
               for n in ast.walk(tree))


def resolve_dispatch(source: str, dpack: Path) -> dict[str, Any] | None:
    """If ``source`` dispatches to a named deployed function
    (``from_name("app", "fn")``), resolve that function's defining file so its body
    can be inlined to run locally. Returns the dispatch record or ``None``."""
    m = _FROM_NAME_RE.search(source)
    if not m:
        return None
    app_name, func = m.group(1), m.group(2)
    apps = _modal_app_files(dpack)
    target = apps.get(app_name)
    if target is None:
        # app name not found by declaration — fall back to any file defining func
        target = next((p for p in (dpack / "docker").rglob("*.py")
                       if _find_def(p, func)), None)
    defined_in = str(target.relative_to(dpack)) if target else None
    return {
        "via": "modal.from_name", "app": app_name, "function": func,
        "defined_in": defined_in,
        "resolved": bool(target and _find_def(target, func)),
    }


# --------------------------------------------------------------------------- #
# Python module extraction
# --------------------------------------------------------------------------- #

def module_file(dpack: Path, dotted: str) -> Path | None:
    """Resolve a dotted module (``mmm_lib.analyze_model_cli``) to a file under
    ``docker/``."""
    p = (dpack / "docker").joinpath(*dotted.split(".")).with_suffix(".py")
    return p if p.exists() else None


def _entry_point_func(tree: ast.Module) -> ast.FunctionDef | None:
    """The function invoked from ``if __name__ == "__main__":`` (or ``main`` /
    ``main_cli`` by convention)."""
    called: str | None = None
    for n in tree.body:
        if isinstance(n, ast.If) and _is_main_guard(n.test):
            for stmt in ast.walk(n):
                if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Name):
                    called = stmt.func.id
                    break
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    if called and called in funcs:
        return funcs[called]
    for conventional in ("main", "main_cli", "cli", "run"):
        if conventional in funcs:
            return funcs[conventional]
    return None


def _is_main_guard(test: ast.expr) -> bool:
    return (isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name) and test.left.id == "__name__")


def _first_party_imports(tree: ast.Module, top_pkg: str) -> dict[str, str]:
    """Map imported name -> defining dotted module, for first-party imports
    (relative, or under the pack's top package)."""
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if not isinstance(n, ast.ImportFrom):
            continue
        is_relative = (n.level or 0) > 0
        mod = n.module or ""
        if is_relative or mod.split(".")[0] == top_pkg:
            dotted = mod if not is_relative else f"{top_pkg}.{mod}" if mod else top_pkg
            for alias in n.names:
                out[alias.name] = dotted
    return out


_OUTPUT_CALLS = {"savefig", "to_csv", "to_netcdf", "save", "write_text", "dump"}


def extract_py_module(dpack: Path, dotted: str) -> dict[str, Any]:
    """Statically extract a CLI module's inputs, level-2 entry function, and any
    remote dispatch."""
    out: dict[str, Any] = {"module": dotted, "residue": []}
    path = module_file(dpack, dotted)
    if not path:
        out["residue"].append(f"module {dotted} not found under docker/")
        return out
    out["file"] = str(path.relative_to(dpack))
    src = _read(path)
    tree = ast.parse(src)
    top_pkg = dotted.split(".")[0]

    entry = _entry_point_func(tree)
    scan = entry if entry else tree
    firstparty = _first_party_imports(tree, top_pkg)

    inputs: list[str] = []
    work_calls: list[str] = []
    outputs: list[str] = []
    for n in ast.walk(scan):
        if not isinstance(n, ast.Call):
            continue
        fn = n.func
        fname = (fn.attr if isinstance(fn, ast.Attribute)
                 else fn.id if isinstance(fn, ast.Name) else None)
        if fname == "add_argument" and n.args and isinstance(n.args[0], ast.Constant):
            inputs.append(n.args[0].value)
        if isinstance(fn, ast.Name) and fn.id in firstparty:
            work_calls.append(fn.id)
        if fname in _OUTPUT_CALLS:
            for a in n.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    outputs.append(a.value)
    out["argparse"] = inputs
    out["literal_outputs"] = sorted(set(outputs))

    # level-2 entry: the first-party work function(s) called in the entry point.
    work = sorted(set(work_calls))
    if len(work) == 1:
        out["entry"] = {"function": work[0], "defined_in": firstparty[work[0]]}
    elif len(work) > 1:
        out["entry_candidates"] = [
            {"function": w, "defined_in": firstparty[w]} for w in work]
        out["residue"].append(
            f"{len(work)} first-party work-function candidates {work} — likely "
            "runtime-selected by an arg; resolve at join time or with an LLM pass")
    else:
        # no delegation: the work is inline in this module → the module body IS
        # the level-2 entry.
        out["entry"] = {"function": entry.name if entry else "<module>",
                        "defined_in": out["file"], "inline": True}

    dispatch = resolve_dispatch(src, dpack)
    if dispatch:
        out["dispatch"] = dispatch
    return out


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #

def _docker_packages(dpack: Path) -> set[str]:
    """Top-level Python package names shipped under ``docker/`` (dirs with
    ``__init__.py``) — the pack's first-party libraries."""
    docker = dpack / "docker"
    if not docker.is_dir():
        return set()
    return {p.name for p in docker.iterdir()
            if p.is_dir() and (p / "__init__.py").is_file()}


def _inline_entry(inline_code: str, dpack: Path) -> dict[str, Any] | None:
    """Resolve a first-party entry from inline ``python -c`` code that imports and
    calls a pack library function (``from LIB import fn; fn(...)``)."""
    pkgs = _docker_packages(dpack)
    for m in re.finditer(r"from\s+([\w.]+)\s+import\s+([\w ,]+)", inline_code):
        mod, names = m.group(1), [n.strip() for n in m.group(2).split(",")]
        if mod.split(".")[0] not in pkgs:
            continue
        for name in names:
            if re.search(rf"\b{re.escape(name)}\s*\(", inline_code):
                return {"function": name, "defined_in": mod}
    return None


def _tool_files(dpack: Path) -> list[Path]:
    tdir = dpack / "opencode" / "tools"
    if not tdir.is_dir():
        return []
    # parallel-agents.ts is dlab infrastructure, not a pack capability
    return [p for p in sorted(tdir.glob("*.ts")) if p.stem != "parallel-agents"]


def _classify_tool(ts: dict[str, Any], entry: dict[str, Any]) -> str:
    if entry.get("dispatch"):
        return "remote-dispatch"
    return ts["kind"]


def build_code_map(dpack: str | Path) -> dict[str, Any]:
    """Build the deterministic code map for a decision-pack."""
    dpack = Path(dpack).resolve()
    tools_out: dict[str, Any] = {}
    for ts_path in _tool_files(dpack):
        ts = extract_ts_tool(ts_path)
        entry: dict[str, Any] = {
            "kind": ts["kind"],
            "inputs": ts["inputs"],
            "runs": ts["runs"],
            "declared_outputs": ts["declared_outputs"],
        }
        py: dict[str, Any] | None = None
        if ts.get("module"):
            py = extract_py_module(dpack, ts["module"])
            entry.update({k: py[k] for k in
                          ("module", "file", "argparse", "literal_outputs",
                           "entry", "entry_candidates", "dispatch", "residue")
                          if k in py})
        else:
            # inline / script / pure-ts: the dispatch (if any) lives in the wrapper
            # itself (a `from_name(...)` inside the inline python).
            dispatch = resolve_dispatch(_read(ts_path), dpack)
            if dispatch:
                entry["dispatch"] = dispatch
            if ts.get("inline_code"):
                entry["inline_code"] = ts["inline_code"]
                inline_entry = _inline_entry(ts["inline_code"], dpack)
                if inline_entry and not dispatch:
                    entry["entry"] = inline_entry

        entry["kind"] = _classify_tool(ts, entry)
        # a remote dispatch's real entry is the deployed body — reach through it.
        disp = (py or entry).get("dispatch") if py else entry.get("dispatch")
        if entry["kind"] == "remote-dispatch" and disp and disp.get("defined_in"):
            entry["dispatch"] = disp
            entry["entry"] = {"function": disp["function"],
                              "defined_in": disp["defined_in"],
                              "reached_through": "dispatch"}
            entry["disclose"] = "executed remotely; inlined to run locally"
        tools_out[ts["name"]] = entry

    shape = _classify_shape(tools_out)
    sources = _collect_sources(dpack, tools_out)
    return {"dpack": dpack.name, "shape": shape, "tools": tools_out,
            "sources": sources}


def _collect_sources(dpack: Path, tools: dict[str, Any]) -> dict[str, str]:
    """sha256 of every source file the map depends on — the tool wrappers plus each
    Python file the map resolves to — so staleness can be detected later. Keyed by
    dpack-relative path, sorted."""
    refs: set[str] = {str(p.relative_to(dpack)) for p in _tool_files(dpack)}
    for entry in tools.values():
        candidates = list(entry.get("entry_candidates", []))
        if entry.get("entry"):
            candidates.append(entry["entry"])
        for c in candidates:
            if c.get("defined_in"):
                refs.add(c["defined_in"])
        if entry.get("file"):
            refs.add(entry["file"])
        if entry.get("dispatch", {}).get("defined_in"):
            refs.add(entry["dispatch"]["defined_in"])

    sources: dict[str, str] = {}
    for ref in refs:
        path = _resolve_source_path(dpack, ref)
        if path is not None:
            sources[str(path.relative_to(dpack))] = _sha256(path)
    return dict(sorted(sources.items()))


def stale_sources(dpack: str | Path) -> list[str]:
    """Return the source files whose checksums no longer match a pack's committed
    ``code_map.json`` (changed or missing) — i.e. the map should be rebuilt. Empty
    list means the map is current; a single ``"<no code_map.json>"`` entry means no
    map exists yet."""
    dpack = Path(dpack).resolve()
    map_path = dpack / CODE_MAP_FILENAME
    if not map_path.is_file():
        return ["<no code_map.json>"]
    recorded: dict[str, str] = json.loads(_read(map_path)).get("sources", {})
    changed: list[str] = []
    for rel, digest in recorded.items():
        path = dpack / rel
        if not path.is_file() or _sha256(path) != digest:
            changed.append(rel)
    return sorted(changed)


def _classify_shape(tools: dict[str, Any]) -> str:
    kinds = {t["kind"] for t in tools.values()}
    real = kinds - {"pure-ts"}
    if not real:
        return "script-only"
    if "remote-dispatch" in kinds and real <= {"remote-dispatch", "python-inline"}:
        return "modal-inline"
    if len(real) > 1 or ("remote-dispatch" in kinds and "python-module" in kinds):
        return "mixed"
    return "tool-backed"


def write_code_map(dpack: str | Path) -> Path:
    """Build and write ``<dpack>/code_map.json``; return its path."""
    dpack = Path(dpack).resolve()
    code_map = build_code_map(dpack)
    dest = dpack / CODE_MAP_FILENAME
    dest.write_text(json.dumps(code_map, indent=2) + "\n", encoding="utf-8")
    return dest
