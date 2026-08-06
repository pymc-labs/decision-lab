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
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

CODE_MAP_FILENAME = "code_map.json"

# The template-extraction LLM subprocess gets a curated env (base vars + provider
# API keys only), same lesson as the notebook step's env leak.
_LLM_BASE_ENV = ("PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
                 "TERM", "TMPDIR")
_LLM_PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY",
                      "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
                      "OPENROUTER_API_KEY", "GROQ_API_KEY", "XAI_API_KEY",
                      "MISTRAL_API_KEY", "DEEPSEEK_API_KEY")


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


def _function_source(src: str, func: str) -> str | None:
    """The verbatim source of a top-level ``def func`` (or ``async def``) in
    ``src``, or ``None``."""
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func:
            return ast.get_source_segment(src, n)
    return None


def _pack_function_index(dpack: Path) -> dict[str, tuple[str, str]]:
    """Index every top-level ``def`` across the pack's Python sources → (relpath,
    source). First definition of a name wins. Used to follow an entry function's
    calls into the pack's own helpers (the code that actually plots/saves)."""
    docker = dpack / "docker"
    idx: dict[str, tuple[str, str]] = {}
    if not docker.is_dir():
        return idx
    for py in sorted(docker.rglob("*.py")):
        try:
            src = _read(py)
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name not in idx:
                seg = ast.get_source_segment(src, n)
                if seg:
                    idx[n.name] = (str(py.relative_to(dpack)), seg)
    return idx


def _called_names(func_src: str) -> set[str]:
    """Bare + attribute call targets in a function's source (``foo()`` → ``foo``,
    ``x.bar()`` → ``bar``)."""
    names: set[str] = set()
    try:
        tree = ast.parse(func_src)
    except SyntaxError:
        return names
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


# Follow an entry's call graph into first-party helpers up to this many bytes of
# collected source — enough to carry the real plotting/saving code without pulling
# the whole library.
_MAX_HELPER_BYTES = 60_000


def resolve_entry_code(dpack: str | Path, entry: dict[str, Any]) -> str | None:
    """Pull the real code an ``entry`` points at, as verbatim source, so it can be
    inlined into a notebook.

    Returns the work function's source (reached *through* a remote dispatch when
    ``reached_through == "dispatch"``, so a remote fit inlines as if run locally),
    **followed by the source of the pack's own helper functions it transitively
    calls** — because the figure/result-generating code (``az.plot_*``, ``savefig``,
    metric computations) usually lives in those helpers, not the entry itself.
    Third-party calls (``az.*``, ``pd.*``) are left as imports. For an inline module
    (work lives in the module body) returns the whole module source. ``None`` if
    unresolvable. Bounded by ``_MAX_HELPER_BYTES``.
    """
    dpack = Path(dpack).resolve()
    ref = entry.get("defined_in")
    if not ref:
        return None
    path = _resolve_source_path(dpack, ref)
    if path is None:
        return None
    src = _read(path)
    func = entry.get("function")
    if entry.get("inline") or func in (None, "<module>"):
        return src
    root = _function_source(src, func)
    if root is None:
        return src

    index = _pack_function_index(dpack)
    collected: list[tuple[str, str]] = []  # (name, source) in discovery order
    seen: set[str] = {func}
    queue: list[str] = sorted(_called_names(root) - seen)
    total = len(root)
    while queue and total < _MAX_HELPER_BYTES:
        name = queue.pop(0)
        if name in seen or name not in index:
            continue
        seen.add(name)
        _, helper_src = index[name]
        collected.append((name, helper_src))
        total += len(helper_src)
        queue.extend(sorted(_called_names(helper_src) - seen))

    if not collected:
        return root
    parts = [root, "",
             "# ---- pack helper functions called above (the real plotting / "
             "metric code) ----"]
    for name, helper_src in collected:
        parts.append(f"\n# helper: {name}\n{helper_src}")
    return "\n".join(parts)


def entry_params(dpack: str | Path, entry: dict[str, Any]) -> list[str] | None:
    """The parameter names of an entry's work function, so a caller can tell
    whether a tool's inputs map cleanly onto a direct ``fn(**inputs)`` call.
    Resolves the function's definition even when ``defined_in`` names a package
    that only re-exports it (via the pack-wide function index). ``None`` if the
    function can't be located."""
    dpack = Path(dpack).resolve()
    func = entry.get("function")
    if not func:
        return None
    src: str | None = None
    path = _resolve_source_path(dpack, entry.get("defined_in", ""))
    if path is not None:
        src = _function_source(_read(path), func)
    if src is None:
        idx = _pack_function_index(dpack)
        if func in idx:
            src = idx[func][1]
    if src is None:
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == func), None)
    if node is None:
        return None
    a = node.args
    return [p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)]


def write_code_map(
    dpack: str | Path, *, model: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[Path, list[str]]:
    """Build and write ``<dpack>/code_map.json``. When ``model`` is given, run the
    LLM template pass for tools that can't render as a clean deterministic call.
    Returns (path, tool names that got an LLM template)."""
    dpack = Path(dpack).resolve()
    code_map = build_code_map(dpack)
    templated: list[str] = []
    if model:
        templated = extract_call_templates(dpack, code_map, model=model, env=env)
    else:
        # a deterministic rebuild must not drop expensive LLM templates — carry
        # forward any already committed for tools that still exist.
        _carry_forward_templates(dpack, code_map)
    dest = dpack / CODE_MAP_FILENAME
    dest.write_text(json.dumps(code_map, indent=2) + "\n", encoding="utf-8")
    return dest, templated


def _carry_forward_templates(dpack: Path, code_map: dict[str, Any]) -> None:
    existing = dpack / CODE_MAP_FILENAME
    if not existing.is_file():
        return
    prev = json.loads(_read(existing)).get("tools", {})
    for name, tool in code_map.get("tools", {}).items():
        old = prev.get(name, {}).get("call_template")
        if old and not tool.get("call_template"):
            tool["call_template"] = old


def _clean_call_possible(dpack: Path, tool: dict[str, Any]) -> bool:
    """True if the skeleton can already emit a clean deterministic ``fn(**inputs)``
    (names match) or single-arg positional call — i.e. no LLM template is needed."""
    entry = tool.get("entry")
    if not entry:
        return False
    defined_in = entry.get("defined_in", "")
    if "/" in defined_in or defined_in.endswith(".py"):
        return False  # not a clean dotted import (e.g. a modal-app file)
    input_names = {i["name"] for i in tool.get("inputs", [])}
    if len(input_names) == 1:
        return True
    params = set(entry_params(dpack, entry) or [])
    return bool(input_names) and input_names <= params


def tools_needing_template(dpack: str | Path, code_map: dict[str, Any]) -> list[str]:
    """Tools whose real invocation can't be rendered as a clean deterministic call
    (a CLI whose ``main()`` loads/transforms, a modal dispatch, ambiguous
    candidates) — these are the ones an LLM template pass resolves."""
    dpack = Path(dpack).resolve()
    out: list[str] = []
    for name, tool in code_map.get("tools", {}).items():
        if tool.get("kind") == "pure-ts" or tool.get("call_template"):
            continue
        if tool.get("entry") or tool.get("entry_candidates"):
            if not _clean_call_possible(dpack, tool):
                out.append(name)
    return out


def _template_prompt(dpack: Path, code_map: dict[str, Any], names: list[str]) -> str:
    """Assemble the extraction prompt: for each tool, its inputs and the real
    source (the CLI module the tool ran + the work function), so the LLM can write
    a load+call template."""
    blocks: list[str] = []
    for name in names:
        tool = code_map["tools"][name]
        inputs = ", ".join(f"{i['name']} ({i['type']})" for i in tool.get("inputs", []))
        parts = [f"=== tool: {name} ===",
                 f"inputs: {inputs}",
                 f"runs: {tool.get('runs') or name}"]
        cli_file = tool.get("file")
        if cli_file and (dpack / cli_file).is_file():
            parts.append(f"--- CLI module ({cli_file}) ---\n{_read(dpack / cli_file)}")
        entry = tool.get("entry") or {}
        if entry.get("function"):
            code = resolve_entry_code(dpack, entry)
            if code:
                parts.append(f"--- work function `{entry['function']}` ---\n{code[:6000]}")
        blocks.append("\n".join(parts))
    body = "\n\n".join(blocks)
    return (
        "You are extracting deterministic notebook cell templates for a set of "
        "decision-pack tools. Each tool ran a Python CLI; a notebook should show "
        "the equivalent code, not the CLI call.\n\n"
        "For EACH tool below, write a Python 'call template': runnable code that "
        "reproduces what the tool did, based on the CLI module's main() — replicate "
        "its load / transform / call of the work function, NOT its argparse. Use "
        "`$inputname` placeholders (Python string.Template) wherever one of the "
        "tool's input values belongs; they are substituted with the Python repr() "
        "of the value, so place them where a Python literal goes (e.g. "
        "`MMM.load($model_path)`, `risk_pct=$risk_pct`). Import what is needed. Keep "
        "it short and faithful — no invented steps.\n\n"
        "Respond with ONLY a single JSON object mapping each tool name to its "
        "template string. No prose, no code fences.\n\n" + body)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """The first balanced ``{...}`` in ``text`` that parses as a JSON object."""
    for start in (i for i, ch in enumerate(text) if ch == "{"):
        depth = 0
        for end in range(start, len(text)):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:end + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, dict):
                        return obj
                    break
    return None


def _llm_env(env: dict[str, str] | None) -> dict[str, str]:
    out = {k: os.environ[k] for k in _LLM_BASE_ENV if k in os.environ}
    for k in _LLM_PROVIDER_KEYS:
        if env and k in env:
            out[k] = env[k]
        elif k in os.environ:
            out[k] = os.environ[k]
    return out


def extract_call_templates(
    dpack: str | Path, code_map: dict[str, Any], *, model: str,
    env: dict[str, str] | None = None, timeout: int = 600,
) -> list[str]:
    """LLM pass of the mapping (opt-in, once per pack): for the tools that can't
    render as a clean deterministic call, ask ``model`` (via an opencode subprocess)
    for a parametrized load+call template and store it under each tool's
    ``call_template``. The per-run skeleton then substitutes values deterministically.
    Returns the tool names a template was produced for.
    """
    dpack = Path(dpack).resolve()
    names = tools_needing_template(dpack, code_map)
    if not names:
        return []
    prompt = _template_prompt(dpack, code_map, names)
    run_env = _llm_env(env)
    with tempfile.TemporaryDirectory() as td:  # run outside the pack: no dpack tools loaded
        proc = subprocess.run(
            ["opencode", "run", "--model", model, prompt],
            cwd=td, capture_output=True, text=True, timeout=timeout, env=run_env,
        )
    templates = _extract_json_object(proc.stdout + proc.stderr) or {}
    applied: list[str] = []
    for name in names:
        tmpl = templates.get(name)
        if isinstance(tmpl, str) and tmpl.strip():
            code_map["tools"][name]["call_template"] = tmpl
            applied.append(name)
    return applied


def load_code_map(dpack: str | Path) -> dict[str, Any]:
    """Load a pack's committed ``code_map.json`` (what ships with the pack); build
    it on the fly if none is committed yet."""
    dpack = Path(dpack).resolve()
    p = dpack / CODE_MAP_FILENAME
    if p.is_file():
        return json.loads(_read(p))
    return build_code_map(dpack)
