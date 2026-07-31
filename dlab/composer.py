"""
Notebook composer step (issue #68).

Turns a finished work directory into Jupyter notebooks: generate the session
digest (host-side, deterministic), materialize the composer environment (the
`composer.md` agent + the `nb-*` tools + `digest-get`) into the work dir's
`.opencode/`, launch a composer `opencode run`, then collect and lightly
validate the notebooks. The composer reads the run ONLY through the digest and
`digest-get`, and writes exclusively through the `nb-*` tools.

Exposed standalone as ``dlab compose <work-dir>`` so it can be driven from the
CLI for testing; wiring it into the run lifecycle (a config flag, running inside
the dpack container) is a follow-up.

Note on environment (see ``dlab compose`` warning): a run's tool-generated
figures were produced by the dpack's library (e.g. what its custom tools shell
out to). If the composer runs **without that library importable** — a local run
with no dpack environment — it can still write the notebooks, but it cannot read
the library to reach the most granular reproduction level, and imports cannot be
validated. Pass a dpack for full fidelity.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from dlab.session_digest import DIGEST_GET_SOURCE, generate_digest

# The composer's authoring tools, shipped as package data (dlab/js/*.ts).
NB_TOOLS: list[str] = [
    "nb-add-markdown-cell", "nb-add-code-cell", "nb-edit-cell",
    "nb-note", "nb-read", "nb-finalize",
]

_LAUNCH_PROMPT = (
    "Compose the Jupyter notebooks for this finished run into the ./notebooks/ "
    "directory, following your instructions. Start by reading _digest/digest.md. "
    "When done, finalize every notebook and state which attempt you adopted and why."
)


@dataclass
class ComposeResult:
    """Outcome of a composer run."""
    returncode: int
    notebooks: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    log: str = ""


def _composer_agent_md() -> str:
    return files("dlab.agents").joinpath("composer.md").read_text(encoding="utf-8")


def _nb_tool_source(name: str) -> str:
    return files("dlab.js").joinpath(f"{name}.ts").read_text(encoding="utf-8")


def materialize_composer_env(work_dir: Path) -> list[Path]:
    """Add the composer's own files to ``work_dir/.opencode`` (agent + tools),
    without clobbering any dpack agents/tools already there. Returns the paths
    added, so ``cleanup_composer_env`` can restore the work dir to a state that
    still resumes cleanly (``--continue-dir`` must not see composer artefacts)."""
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
    comp = agents / "composer.md"
    comp.write_text(_composer_agent_md(), encoding="utf-8")
    added.append(comp)
    return added


def cleanup_composer_env(added: list[Path]) -> None:
    for p in added:
        try:
            p.unlink()
        except OSError:
            pass


def compose(
    work_dir: str | Path,
    *,
    model: str,
    dpack: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 1800,
) -> ComposeResult:
    """
    Compose notebooks for a finished work directory.

    Parameters
    ----------
    work_dir : str | Path
        A completed session work directory (must contain ``_opencode_logs``).
    model : str
        The composer model, ``provider/model`` (e.g. ``google/gemini-3-flash-preview``).
    dpack : str | Path | None
        The decision-pack. Only used to signal that the pack's environment is
        available; absence produces a fidelity warning (see module docstring).
    env : dict | None
        Extra environment for the opencode subprocess (e.g. provider API keys).
    timeout : int
        Seconds before the composer run is aborted.

    Returns
    -------
    ComposeResult
    """
    work_dir = Path(work_dir).resolve()
    warnings: list[str] = []
    if not (work_dir / "_opencode_logs").is_dir():
        return ComposeResult(
            returncode=1,
            warnings=[f"No _opencode_logs in {work_dir} — not a dlab work directory."],
        )
    if dpack is None:
        warnings.append(
            "No decision-pack given: the composer runs without the pack's "
            "environment. The library its tools call (e.g. what produces the "
            "figures) will not be importable, so figures can only be reproduced "
            "at a coarse level and imports cannot be validated. Pass --dpack for "
            "full fidelity."
        )

    generate_digest(work_dir)
    (work_dir / "notebooks").mkdir(exist_ok=True)
    added = materialize_composer_env(work_dir)

    run_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(
            ["opencode", "run", "--agent", "composer", "--model", model,
             "--format", "json", _LAUNCH_PROMPT],
            cwd=str(work_dir), capture_output=True, text=True,
            timeout=timeout, env=run_env,
        )
        returncode = proc.returncode
        log = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        log = (exc.stdout or "") + (exc.stderr or "")
        warnings.append(f"Composer run timed out after {timeout}s.")
    finally:
        cleanup_composer_env(added)

    # Persist the composer's opencode log so a failed/empty run is diagnosable.
    log_path = work_dir / "_compose.log"
    try:
        log_path.write_text(log, encoding="utf-8")
    except OSError:
        log_path = None

    notebooks = sorted((work_dir / "notebooks").glob("*.ipynb"))
    if not notebooks:
        where = f" (see {log_path})" if log_path else ""
        warnings.append(f"Composer produced no notebooks{where}.")
    for nb in notebooks:
        try:
            json.loads(nb.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"{nb.name}: not valid JSON ({exc}).")

    return ComposeResult(
        returncode=returncode, notebooks=notebooks, warnings=warnings, log=log,
    )
