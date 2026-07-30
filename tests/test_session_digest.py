"""Tests for the deterministic session digest + digest-get tool (issue #85)."""

import json
import subprocess
from pathlib import Path

import pytest

from dlab.session_digest import (
    DIGEST_GET_SOURCE,
    build_digest,
    generate_digest,
    _differentiating_prompt,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session"


def _line(event_type: str, ts: int, **body) -> str:
    return json.dumps({"type": event_type, "timestamp": ts, **body})


def _rich_workdir(tmp_path: Path) -> Path:
    """A synthetic run exercising Task, script runs (pass+fail), and writes."""
    wd = tmp_path / "rich"
    logs = wd / "_opencode_logs"
    run = logs / "modeler-parallel-run-1700000000000"
    run.mkdir(parents=True)
    inst_work = wd / "parallel" / "run-1700000000000" / "instance-1"
    inst_work.mkdir(parents=True)
    (inst_work / "summary.md").write_text("done")

    (logs / "main.log").write_text("\n".join([
        _line("dlab_start", 1700000000000, model="anthropic/claude-sonnet-4-5", agent="main"),
        _line("text", 1700000000100, part={"type": "text", "text": "Spawning modelers."}),
        _line("tool_use", 1700000000200, part={
            "tool": "parallel-agents", "state": {
                "status": "completed",
                "input": {"agent": "modeler", "prompts": ["fit"]},
                "time": {"start": 1700000000200, "end": 1700000005000},
            }}),
        _line("step_finish", 1700000006000, part={"type": "step-finish", "reason": "stop", "cost": 0.02}),
    ]) + "\n")

    # instance-1: dlab_start w/ injected-context prompt, a failing then passing
    # bash, a write, and reasoning text.
    injected = (
        "IMPORTANT CONTEXT: You are running as a parallel subagent.\n\n"
        "CRITICAL OUTPUT RULES:\n- write summary.md\n\n"
        "Fit a geometric-adstock MMM with saturating priors on /workspace/data."
    )
    (run / "instance-1.log").write_text("\n".join([
        _line("dlab_start", 1700000000300, model="anthropic/claude-sonnet-4-5",
              agent="modeler", prompt=injected),
        _line("text", 1700000000400, part={"type": "text", "text": "Writing fit_model.py."}),
        _line("tool_use", 1700000000500, part={
            "tool": "write", "state": {"status": "completed",
                                        "input": {"filePath": "/workspace/parallel/x/instance-1/fit_model.py"},
                                        "output": "Wrote file."}}),
        _line("tool_use", 1700000000600, part={
            "tool": "bash", "state": {"status": "completed",
                                      "input": {"command": "python fit_model.py"},
                                      "error": "Traceback...\nKeyError: 'is_valid'",
                                      "time": {"start": 1700000000600, "end": 1700000000900}}}),
        _line("text", 1700000001000, part={"type": "text", "text": "Fixing the key error, rerunning."}),
        _line("tool_use", 1700000001100, part={
            "tool": "bash", "state": {"status": "completed",
                                      "input": {"command": "python fit_model.py"},
                                      "output": "sampling...\ndone\nr-hat ok",
                                      "time": {"start": 1700000001100, "end": 1700000004100}}}),
        _line("step_finish", 1700000005000, part={"type": "step-finish", "reason": "stop", "cost": 0.05}),
    ]) + "\n")
    (wd / "report.md").write_text("# report")
    return wd


class TestDiffPrompt:
    def test_strips_injected_context(self) -> None:
        p = ("IMPORTANT CONTEXT: blah\n\nCRITICAL OUTPUT RULES:\n- x\n\n"
             "The real task here.")
        assert _differentiating_prompt(p) == "The real task here."

    def test_plain_prompt_untouched(self) -> None:
        assert _differentiating_prompt("just do X") == "just do X"


class TestDigestAgainstFixture:
    def test_structure(self) -> None:
        md, index = build_digest(FIXTURE)
        assert "# Session digest: sample_session" in md
        assert "## Workflow tree" in md
        # one section per agent: main + 2 instances + consolidator
        assert md.count("\n### ") == 4
        assert "### main — orchestrator" in md
        assert "poet.r1.i1" in md and "poet.r1.cons" in md

    def test_shared_event_counter_and_index(self) -> None:
        md, index = build_digest(FIXTURE)
        # main: text(x1), tool(t2), text(x3) — the counter is shared.
        assert index["main/x1"]["event_type"] == "text"
        assert index["main/t2"]["event_type"] == "tool_use"
        assert index["main/x3"]["event_type"] == "text"
        # the pointer's line actually contains that event
        entry = index["main/t2"]
        line = (FIXTURE / entry["log_file"]).read_text().splitlines()[entry["line_no"] - 1]
        assert '"tool": "parallel-agents"' in line


class TestDigestRichFeatures:
    def test_task_artifacts_scripts(self, tmp_path: Path) -> None:
        wd = _rich_workdir(tmp_path)
        md, index = build_digest(wd)
        # Task field (differentiating prompt) + its p0 index entry
        assert "geometric-adstock MMM" in md
        assert "modeler.r1.i1/p0" in index
        # write chain
        assert "fit_model.py (written t" in md
        # script runs: one failed, one ok
        assert "✗ error" in md
        assert md.count("bash `python fit_model.py`") == 2
        # failed bash surfaces the stderr tail
        assert "KeyError" in md

    def test_brief_collapses_tool_tables(self, tmp_path: Path) -> None:
        wd = _rich_workdir(tmp_path)
        full, _ = build_digest(wd)
        brief, _ = build_digest(wd, brief=True)
        assert "**Tool calls**:" in brief
        assert len(brief) < len(full)

    def test_generate_writes_files(self, tmp_path: Path) -> None:
        wd = _rich_workdir(tmp_path)
        out = generate_digest(wd)
        assert (out / "digest.md").exists()
        assert (out / "index.json").exists()
        idx = json.loads((out / "index.json").read_text())
        assert any(k.endswith("/p0") for k in idx)


def _have_node() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class TestDigestGetTool:
    def test_source_reads_index_and_slices(self) -> None:
        assert "_digest" in DIGEST_GET_SOURCE and "index.json" in DIGEST_GET_SOURCE
        assert "function renderPayload" in DIGEST_GET_SOURCE
        assert "function sliceText" in DIGEST_GET_SOURCE

    def test_runtime_render_and_slice(self, tmp_path: Path) -> None:
        if not _have_node():
            pytest.skip("node not available")
        # Extract the two pure helpers from the actual source, strip TS types.
        import re
        src = DIGEST_GET_SOURCE
        helpers = src[src.index("function renderPayload"):]
        helpers = re.sub(r"\?:\s*(string|number|any)", "", helpers)  # optional params
        helpers = re.sub(r":\s*(string|number|any)", "", helpers)    # params + returns
        tool_line = json.dumps({"type": "tool_use", "part": {"tool": "bash", "state": {
            "input": {"command": "python x.py"},
            "output": "l1\nl2\nl3\nl4\nl5"}}})
        driver = f"""
{helpers}
const obj = {tool_line};
const rendered = renderPayload(obj, "tool_use");
if (!rendered.includes("python x.py")) process.exit(1);
if (!rendered.includes("l5")) process.exit(1);
const tail = sliceText(rendered, undefined, 2, undefined);
if (tail.split("\\n").length !== 2 || !tail.includes("l5")) process.exit(2);
console.log("ok");
"""
        js = tmp_path / "d.js"
        js.write_text(driver)
        r = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=15)
        assert r.returncode == 0, r.stderr
