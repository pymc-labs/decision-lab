"""Tests for the deterministic session digest + digest-get tool (issue #85)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlab.cli import app, cmd_digest
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
    # fit_model.py is tool-written (below); idata.nc + figures/ are produced by
    # the SCRIPT and never pass through a tool call — the digest must still list
    # them by walking the workdir on disk.
    (inst_work / "fit_model.py").write_text("import pymc as pm\n")
    (inst_work / "idata.nc").write_text("x" * 2048)
    (inst_work / "figures").mkdir()
    (inst_work / "figures" / "adstock.png").write_text("PNG" * 100)

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
        # tool-written file keeps its write chain (and now a size)
        fit_line = next(l for l in md.splitlines() if "fit_model.py" in l)
        assert "written t" in fit_line
        # script-produced outputs (no tool call) are listed by walking the disk
        assert "idata.nc" in md
        assert "figures/adstock.png" in md
        # script runs: one failed, one ok
        assert "✗ error" in md
        assert md.count("bash `python fit_model.py`") == 2
        # failed bash surfaces the stderr tail
        assert "KeyError" in md

    def test_script_produced_files_listed(self, tmp_path: Path) -> None:
        # A file created purely by a bash script (no write/edit tool) must
        # still appear, with a size and no write chain.
        wd = _rich_workdir(tmp_path)
        md, _ = build_digest(wd)
        nc_line = next(l for l in md.splitlines() if "idata.nc" in l)
        assert "KB" in nc_line  # has a size
        assert "written t" not in nc_line  # no fabricated provenance

    def test_script_command_shown_in_full(self, tmp_path: Path) -> None:
        # A long command must appear verbatim, not truncated to a preview.
        wd = tmp_path / "run"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        long_cmd = (
            "cd /workspace/parallel/run-1775647475873/instance-1 && "
            "python prepare_data.py --seed 0 --config full_pipeline.yaml"
        )
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 1700000000000, model="m", agent="main"),
            _line("tool_use", 1700000000100, part={
                "tool": "bash", "state": {"status": "completed",
                                          "input": {"command": long_cmd},
                                          "output": "ok",
                                          "time": {"start": 1700000000100,
                                                   "end": 1700000000300}}}),
        ]) + "\n")
        md, _ = build_digest(wd)
        assert f"`{long_cmd}`" in md
        assert "…" not in md.split("**Script runs**", 1)[1].split("\n")[1]

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


def _two_phase_workdir(tmp_path: Path) -> Path:
    """main → phase-1 'prep' (creates data.csv) → phase-2 'model'. Exercises
    inherited-copy dropping, creator retention, basename collision, and
    modified-from-inherited. Timestamps are the load-bearing part."""
    wd = tmp_path / "twophase"
    logs = wd / "_opencode_logs"
    logs.mkdir(parents=True)
    (logs / "main.log").write_text("\n".join([
        _line("dlab_start", 1000, model="m", agent="main"),
        _line("tool_use", 1100, part={"tool": "write", "state": {
            "status": "completed", "input": {"filePath": "/workspace/shared.txt"},
            "output": "ok"}}),
        _line("tool_use", 3000, part={"tool": "bash", "state": {
            "status": "completed", "input": {"command":
                "cp /workspace/parallel/run-2000/instance-1/data.csv /workspace/data.csv"},
            "output": "", "time": {"start": 3000, "end": 3001}}}),
        _line("step_finish", 5000, part={"type": "step-finish", "cost": 0.01}),
    ]) + "\n")
    r1 = logs / "prep-parallel-run-2000"
    r1.mkdir()
    (r1 / "instance-1.log").write_text("\n".join([
        _line("dlab_start", 2000, model="m", agent="prep", prompt="make data.csv"),
        _line("tool_use", 2100, part={"tool": "bash", "state": {
            "status": "completed", "input": {"command": "python prep.py"},
            "output": "wrote data.csv", "time": {"start": 2100, "end": 2200}}}),
        _line("tool_use", 2200, part={"tool": "write", "state": {
            "status": "completed", "input": {"filePath": "summary.md"}, "output": "ok"}}),
        _line("step_finish", 2300, part={"type": "step-finish", "cost": 0.01}),
    ]) + "\n")
    r2 = logs / "model-parallel-run-4000"
    r2.mkdir()
    (r2 / "instance-1.log").write_text("\n".join([
        _line("dlab_start", 4000, model="m", agent="model", prompt="fit the model"),
        _line("tool_use", 4100, part={"tool": "write", "state": {
            "status": "completed", "input": {"filePath": "shared.txt"}, "output": "ok"}}),
        _line("tool_use", 4200, part={"tool": "bash", "state": {
            "status": "completed", "input": {"command": "python fit.py"},
            "output": "wrote out.txt", "time": {"start": 4200, "end": 4300}}}),
        _line("tool_use", 4300, part={"tool": "write", "state": {
            "status": "completed", "input": {"filePath": "summary.md"}, "output": "ok"}}),
        _line("step_finish", 4400, part={"type": "step-finish", "cost": 0.01}),
    ]) + "\n")

    shared_v1, data = "shared v1\n", "a,b\n1,2\n"
    (wd / "shared.txt").write_text(shared_v1)
    (wd / "data.csv").write_text(data)
    i1 = wd / "parallel" / "run-2000" / "instance-1"
    i1.mkdir(parents=True)
    (i1 / "shared.txt").write_text(shared_v1)          # inherited, identical → drop
    (i1 / "data.csv").write_text(data)                 # prep CREATED it → keep
    (i1 / "summary.md").write_text("prep summary")     # keep
    i2 = wd / "parallel" / "run-4000" / "instance-1"
    i2.mkdir(parents=True)
    (i2 / "shared.txt").write_text("shared v2 EDITED\n")   # modified-from-inherited → keep+note
    (i2 / "data.csv").write_text(data)                 # inherited, identical → drop
    (i2 / "out.txt").write_text("result")              # produced → keep
    (i2 / "summary.md").write_text("model summary")    # collision, root lacks it → keep, no note
    return wd


def _section(md: str, qual: str) -> str:
    out, grab = [], False
    for line in md.splitlines():
        if line.startswith("### "):
            grab = line.startswith(f"### {qual} ")
        elif grab:
            out.append(line)
    return "\n".join(out)


class TestArtifactAttribution:
    def test_inherited_identical_copy_dropped(self, tmp_path: Path) -> None:
        md, _ = build_digest(_two_phase_workdir(tmp_path))
        prep, model = _section(md, "prep.r1.i1"), _section(md, "model.r1.i1")
        # prep inherited shared.txt unchanged from main → dropped
        assert "shared.txt" not in prep
        # model inherited data.csv unchanged from root seed → dropped
        assert "data.csv" not in model

    def test_creator_keeps_file_despite_identical_root_copy(self, tmp_path: Path) -> None:
        md, _ = build_digest(_two_phase_workdir(tmp_path))
        prep = _section(md, "prep.r1.i1")
        # root has an identical data.csv (main copied it up) but prep MADE it
        assert "data.csv" in prep

    def test_modified_inherited_kept_and_flagged(self, tmp_path: Path) -> None:
        md, _ = build_digest(_two_phase_workdir(tmp_path))
        model = _section(md, "model.r1.i1")
        sh = next(l for l in model.splitlines() if "shared.txt" in l)
        assert "modified from inherited" in sh

    def test_basename_collision_not_treated_as_inherited(self, tmp_path: Path) -> None:
        md, _ = build_digest(_two_phase_workdir(tmp_path))
        model = _section(md, "model.r1.i1")
        # both prep and model write their own summary.md; root has none →
        # model's is produced, NOT a false "modified from inherited"
        sm = next(l for l in model.splitlines() if "summary.md" in l)
        assert "modified from inherited" not in sm
        assert "out.txt" in model  # its own product

    def test_consolidator_workdir_does_not_swallow_instances(self, tmp_path: Path) -> None:
        # A consolidator whose base is the run root must not list instance files.
        wd = tmp_path / "cons"
        logs = wd / "_opencode_logs" / "poet-parallel-run-500"
        logs.mkdir(parents=True)
        (logs / "instance-1.log").write_text(
            _line("dlab_start", 500, model="m", agent="poet") + "\n")
        (logs / "consolidator.log").write_text(
            _line("dlab_start", 900, model="m", agent="consolidator") + "\n")
        inst = wd / "parallel" / "run-500" / "instance-1"
        inst.mkdir(parents=True)
        (inst / "poem.txt").write_text("a poem")
        (wd / "parallel" / "run-500" / "consolidated_summary.md").write_text("cmp")
        md, _ = build_digest(wd)
        cons = _section(md, "poet.r1.cons")
        assert "poem.txt" not in cons  # sibling's file, not the consolidator's


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


class TestDigestCommand:
    """The `dlab digest` CLI subcommand (thin wrapper over build/generate)."""

    def test_stdout_default(self, capsys: pytest.CaptureFixture) -> None:
        rc = cmd_digest(str(FIXTURE))
        assert rc == 0
        out = capsys.readouterr().out
        assert out.startswith("# Session digest: sample_session")
        assert "### main — orchestrator" in out

    def test_write_materializes_pair(self, tmp_path: Path,
                                     capsys: pytest.CaptureFixture) -> None:
        run = tmp_path / "run"
        shutil.copytree(FIXTURE, run)
        rc = cmd_digest(str(run), write=True)
        assert rc == 0
        digest_md = run / "_digest" / "digest.md"
        index_json = run / "_digest" / "index.json"
        assert digest_md.is_file() and index_json.is_file()
        # stdout reports the written paths, not the digest body.
        out = capsys.readouterr().out
        assert "digest.md" in out and "index.json" in out
        assert "# Session digest" not in out
        index = json.loads(index_json.read_text())
        assert any(k.startswith("main/") for k in index)

    def test_brief_is_shorter_than_full(self) -> None:
        full, _ = build_digest(FIXTURE, brief=False)
        brief, _ = build_digest(FIXTURE, brief=True)
        assert len(brief) <= len(full)

    def test_cwd_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                          capsys: pytest.CaptureFixture) -> None:
        run = tmp_path / "run"
        shutil.copytree(FIXTURE, run)
        monkeypatch.chdir(run)
        rc = cmd_digest(None)
        assert rc == 0
        assert "# Session digest" in capsys.readouterr().out

    def test_missing_logs_errors(self, tmp_path: Path,
                                 capsys: pytest.CaptureFixture) -> None:
        rc = cmd_digest(str(tmp_path))
        assert rc == 1
        assert "_opencode_logs" in capsys.readouterr().err

    def test_no_arg_without_logs_errors(self, tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch,
                                        capsys: pytest.CaptureFixture) -> None:
        monkeypatch.chdir(tmp_path)
        rc = cmd_digest(None)
        assert rc == 1
        assert "No work directory specified" in capsys.readouterr().err

    def test_command_is_registered(self) -> None:
        result = CliRunner().invoke(app, ["digest", "--help"])
        assert result.exit_code == 0
        assert "session digest" in result.output.lower()
