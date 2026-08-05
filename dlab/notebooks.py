"""
Notebook composer step (issue #68).

Turns a finished work directory into Jupyter notebooks in two stages:

1. **Deterministic (host-side):** generate the session digest, build the
   deterministic skeleton (`notebook_skeleton`: real code + real outputs, the
   adopted path as phase notebooks + ``attempts/``, context hints), and seed
   ``notebooks/`` from it.
2. **LLM (the composer):** launch the ``notebooks`` opencode agent to CURATE and
   NARRATE that copy in place — it inspects with ``nb-list``/``nb-read``, weaves
   markdown (grounded via ``digest-get`` on each cell's hints), deduplicates /
   reorders, and authors ``00_overview``. It has no tool to add or edit a code
   cell, so the code stays exactly what ran (hallucination-impossible).

Exposed standalone as ``dlab generate_notebooks <work-dir>`` so it can be driven from the
CLI for testing; wiring it into the run lifecycle (a config flag, running inside
the dpack container) is a follow-up.

Note on environment (see ``dlab generate_notebooks`` warning): a run's tool-generated
figures were produced by the dpack's library (e.g. what its custom tools shell
out to). If the notebook agent runs **without that library importable** — a local run
with no dpack environment — it can still write the notebooks, but it cannot read
the library to reach the most granular reproduction level, and imports cannot be
validated. Pass a dpack for full fidelity.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from dlab.notebook_skeleton import SKELETON_DIR, write_skeletons
from dlab.session_digest import DIGEST_GET_SOURCE, generate_digest

# The notebook agent's authoring tools, shipped as package data (dlab/js/*.ts).
NB_TOOLS: list[str] = [
    "nb-add-markdown-cell", "nb-add-code-cell", "nb-edit-cell",
    "nb-note", "nb-read", "nb-finalize",
    # editing tools for composing on top of the deterministic skeleton (#68)
    "nb-list", "nb-insert-markdown-cell", "nb-move-cell", "nb-delete-cell", "nb-new",
]

# Retry the notebook agent run on a transient provider error (an error event with no
# notebooks produced) — Anthropic in particular 500s intermittently on the first
# request.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_S = 8

# The notebook agent's opencode subprocess gets a CURATED env, not the full host
# environment: leaking unrelated host vars into opencode makes its provider
# request fail with an opaque server error (same class of bug as the #56 env
# leak). Only base vars + provider API keys are forwarded.
_BASE_ENV_VARS = frozenset({
    "PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR",
})
_PROVIDER_KEY_VARS = frozenset({
    "ANTHROPIC_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GOOGLE_API_KEY",
    "GEMINI_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY",
    "XAI_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY",
})


def _as_text(s: str | bytes | None) -> str:
    """Coerce a subprocess stream to text (``TimeoutExpired`` carries bytes even
    under ``text=True``)."""
    if s is None:
        return ""
    return s.decode("utf-8", errors="replace") if isinstance(s, bytes) else s


def _notebook_env(provided: dict[str, str]) -> dict[str, str]:
    """A minimal, curated environment for the notebook agent's opencode subprocess:
    base vars + provider API keys only (the caller's --env-file wins over any
    inherited value). Nothing else from the host env is forwarded."""
    env = {k: os.environ[k] for k in _BASE_ENV_VARS if k in os.environ}
    for k in _PROVIDER_KEY_VARS:
        if k in provided:
            env[k] = provided[k]
        elif k in os.environ:
            env[k] = os.environ[k]
    return env

_LAUNCH_PROMPT = (
    "The deterministic skeleton notebooks for this finished run are already built "
    "in ./notebooks/ (the adopted path as numbered phase notebooks, plus "
    "./notebooks/attempts/). Every code cell is REAL code the run executed, with "
    "its REAL output attached — do not write or alter code. Your job is to CURATE "
    "and NARRATE them following your instructions: survey with nb-list/nb-read, "
    "weave in markdown that explains the why (grounded via digest-get on each "
    "cell's hints), deduplicate and reorder, and author ./notebooks/00_overview.ipynb "
    "arguing the alternatives. When done, finalize every notebook and state which "
    "attempt was adopted and why."
)


def _seed_notebooks_from_skeleton(work_dir: Path) -> None:
    """Copy the deterministic skeleton into ``notebooks/`` — the curated output the
    composer edits in place, leaving ``skeleton/`` as the pristine artifact."""
    src = work_dir / SKELETON_DIR
    dst = work_dir / "notebooks"
    dst.mkdir(exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)


@dataclass
class NotebooksResult:
    """Outcome of a notebook agent run."""
    returncode: int
    notebooks: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    log: str = ""


def _notebook_agent_md() -> str:
    return files("dlab.agents").joinpath("notebooks.md").read_text(encoding="utf-8")


def _nb_tool_source(name: str) -> str:
    return files("dlab.js").joinpath(f"{name}.ts").read_text(encoding="utf-8")


def materialize_notebook_env(work_dir: Path) -> list[Path]:
    """Add the notebook agent's own files to ``work_dir/.opencode`` (agent + tools),
    without clobbering any dpack agents/tools already there. Returns the paths
    added, so ``cleanup_notebook_env`` can restore the work dir to a state that
    still resumes cleanly (``--continue-dir`` must not see notebook agent artefacts)."""
    oc = work_dir / ".opencode"
    tools = oc / "tools"
    agents = oc / "agents"
    tools.mkdir(parents=True, exist_ok=True)
    agents.mkdir(parents=True, exist_ok=True)

    added: list[Path] = []
    dg = tools / "digest-get.ts"
    dg.write_text(DIGEST_GET_SOURCE, encoding="utf-8")
    added.append(dg)
    for name in NB_TOOLS:
        p = tools / f"{name}.ts"
        p.write_text(_nb_tool_source(name), encoding="utf-8")
        added.append(p)
    comp = agents / "notebooks.md"
    comp.write_text(_notebook_agent_md(), encoding="utf-8")
    added.append(comp)
    return added


def cleanup_notebook_env(added: list[Path]) -> None:
    for p in added:
        try:
            p.unlink()
        except OSError:
            pass


def _isolate_notebook_tools(work_dir: Path) -> list[tuple[Path, Path]]:
    """Move every non-notebook agent ``.opencode/tools/*.ts`` out of the way for the
    run: opencode loads ALL tools in that dir and sends their schemas to the
    model, and a strict provider (Anthropic) rejects the dpack's unrelated tool
    schemas outright. The notebook agent never calls those tools — it reads their code
    from ``_digest/tool_sources/`` (via digest-get). Returns (original, stash)
    pairs to restore afterwards."""
    tools = work_dir / ".opencode" / "tools"
    keep = {"digest-get.ts", *(f"{n}.ts" for n in NB_TOOLS)}
    moved: list[tuple[Path, Path]] = []
    if not tools.is_dir():
        return moved
    stash = work_dir / ".opencode" / "_tools_stash"
    for f in sorted(tools.glob("*.ts")):
        if f.name not in keep:
            stash.mkdir(exist_ok=True)
            dest = stash / f.name
            shutil.move(str(f), str(dest))
            moved.append((f, dest))
    return moved


def _restore_tools(moved: list[tuple[Path, Path]]) -> None:
    for original, dest in moved:
        try:
            shutil.move(str(dest), str(original))
        except OSError:
            pass
    if moved:
        stash = moved[0][1].parent
        try:
            stash.rmdir()
        except OSError:
            pass


def generate_notebooks(
    work_dir: str | Path,
    *,
    model: str,
    dpack: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 3600,
) -> NotebooksResult:
    """
    Assemble notebooks for a finished work directory.

    Parameters
    ----------
    work_dir : str | Path
        A completed session work directory (must contain ``_opencode_logs``).
    model : str
        The notebook agent model, ``provider/model`` (e.g. ``google/gemini-3-flash-preview``).
    dpack : str | Path | None
        The decision-pack. Only used to signal that the pack's environment is
        available; absence produces a fidelity warning (see module docstring).
    env : dict | None
        Extra environment for the opencode subprocess (e.g. provider API keys).
    timeout : int
        Seconds before the notebook agent run is aborted.

    Returns
    -------
    NotebooksResult
    """
    work_dir = Path(work_dir).resolve()
    warnings: list[str] = []
    if not (work_dir / "_opencode_logs").is_dir():
        return NotebooksResult(
            returncode=1,
            warnings=[f"No _opencode_logs in {work_dir} — not a dlab work directory."],
        )
    if dpack is None:
        warnings.append(
            "No decision-pack given: the digest cannot resolve the real code a "
            "custom tool ran (its code map needs the pack's library source), so "
            "tool-generated outputs reproduce only at the CLI-invocation level. "
            "Pass --dpack for full fidelity."
        )

    # Digest first — with the dpack it resolves each custom tool to the REAL
    # library code (via the pack's code map) into _digest/tool_sources/.
    generate_digest(work_dir, dpack=dpack)
    # Then build the DETERMINISTIC skeleton (real code + real outputs, adopted path
    # + attempts, context hints) and seed notebooks/ from it — the composer curates
    # this copy in place; skeleton/ stays as the pristine deterministic artifact.
    write_skeletons(work_dir, dpack=dpack)
    _seed_notebooks_from_skeleton(work_dir)
    added = materialize_notebook_env(work_dir)
    moved = _isolate_notebook_tools(work_dir)

    run_env = _notebook_env(env or {})
    returncode, log = 1, ""
    try:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                proc = subprocess.run(
                    ["opencode", "run", "--agent", "notebooks", "--model", model,
                     "--format", "json", _LAUNCH_PROMPT],
                    cwd=str(work_dir), capture_output=True, text=True,
                    timeout=timeout, env=run_env,
                )
                returncode = proc.returncode
                log = proc.stdout + proc.stderr
            except subprocess.TimeoutExpired as exc:
                returncode = 124
                # On timeout, exc.stdout/stderr come back as bytes even under
                # text=True — decode defensively so a slow run degrades to a
                # warning (keeping any notebooks already written) instead of
                # crashing the command.
                log = _as_text(exc.stdout) + _as_text(exc.stderr)
                warnings.append(f"Notebook agent run timed out after {timeout}s.")
                break
            # A transient provider error (opencode emits an error event and
            # exits before any tool call) leaves no notebooks — retry it.
            produced = any((work_dir / "notebooks").glob("*.ipynb"))
            if returncode == 0 and produced:
                break
            if attempt < _MAX_ATTEMPTS:
                warnings.append(
                    f"Notebook agent attempt {attempt} produced nothing (likely a "
                    f"transient provider error) — retrying."
                )
                # Back off so retries span a provider instability window rather
                # than all landing inside the same few-second bad spell.
                time.sleep(_RETRY_BACKOFF_S * attempt)
    finally:
        _restore_tools(moved)
        cleanup_notebook_env(added)

    # Persist the notebook agent's opencode log so a failed/empty run is diagnosable.
    log_path = work_dir / "_notebooks.log"
    try:
        log_path.write_text(log, encoding="utf-8")
    except OSError:
        log_path = None

    notebooks = sorted((work_dir / "notebooks").glob("*.ipynb"))
    if not notebooks:
        where = f" (see {log_path})" if log_path else ""
        warnings.append(f"Notebook agent produced no notebooks{where}.")
    for nb in notebooks:
        try:
            json.loads(nb.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"{nb.name}: not valid JSON ({exc}).")

    return NotebooksResult(
        returncode=returncode, notebooks=notebooks, warnings=warnings, log=log,
    )
