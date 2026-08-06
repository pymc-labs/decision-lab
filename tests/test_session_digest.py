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
        cmd_row = next(l for l in md.splitlines()
                       if "prepare_data.py" in l and "bash" in l)
        assert "…" not in cmd_row  # command not truncated

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


class TestRawTextAndToolCalls:
    def test_raw_text_gets_rid_range_and_maps_to_call(self, tmp_path: Path) -> None:
        wd = tmp_path / "r"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 1000, model="m", agent="main"),
            _line("tool_use", 1100, part={"tool": "bash", "state": {
                "status": "completed", "input": {"command": "python fit.py"},
                "time": {"start": 1100, "end": 5100}}}),
            "sampling chain 1 complete",
            "sampling chain 2 complete",
            "[STDERR] Traceback (most recent call last):",
            "[STDERR] ValueError: boom",
        ]) + "\n")
        md, index = build_digest(wd)
        # the raw_text block is one r-id, indexed as a line RANGE
        rids = [k for k in index if k.startswith("main/r")]
        assert len(rids) == 1
        entry = index[rids[0]]
        assert entry["event_type"] == "raw_text"
        assert entry["line_end"] > entry["line_no"]
        # the bash call row points at it, and a [STDERR] line marks it stderr
        call_row = next(l for l in md.splitlines() if "python fit.py" in l)
        assert "→ r" in call_row
        assert "stderr" in call_row

    def test_shared_counter_includes_raw_text(self, tmp_path: Path) -> None:
        # r-ids share the per-agent counter with t/x (the numbering is time).
        wd = tmp_path / "r"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 1000, model="m", agent="main"),
            _line("tool_use", 1100, part={"tool": "bash", "state": {
                "status": "completed", "input": {"command": "x"},
                "time": {"start": 1100, "end": 1200}}}),
            "some stdout",
            _line("text", 1300, part={"type": "text", "text": "done"}),
        ]) + "\n")
        _, index = build_digest(wd)
        ids = {k.split("/")[1] for k in index if k != "main/p0"}
        # bash=t1, its raw_text=r2, the text=x3 — consecutive on one counter
        assert {"t1", "r2", "x3"} <= ids

    def test_from_tool_call_provenance_via_mtime(self, tmp_path: Path) -> None:
        import os
        wd = tmp_path / "m"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 1000, model="m", agent="main"),
            _line("tool_use", 2000, part={"tool": "fit-model-modal", "state": {
                "status": "completed", "input": {},
                "time": {"start": 2000, "end": 8000}}}),
        ]) + "\n")
        f = wd / "fitted_model.nc"
        f.write_text("x" * 100)
        os.utime(f, (5.0, 5.0))  # mtime 5000ms, inside the call's [2000,8000]
        md, _ = build_digest(wd)
        row = next(l for l in md.splitlines()
                   if "fitted_model.nc" in l and l.strip().startswith("- [a"))
        assert "← from t1 (fit-model-modal)" in row

    def test_custom_tools_labeled_not_just_bash(self, tmp_path: Path) -> None:
        wd = _rich_workdir(tmp_path)  # bash + write + edit exist here
        md, _ = build_digest(wd)
        section = next(s for s in md.split("### ") if s.startswith("modeler.r1.i1"))
        assert "**Tool calls**" in section
        assert "write fit_model.py" in section  # write is a labeled row now
        assert "**Navigational**" not in section or "read" in section


class TestComposerFeedbackFixes:
    """Digest tweaks from the composer experiment: input signatures, error
    tails, LSP-noise stripping, and consolidator failure flagging."""

    def test_custom_tool_shows_input_signature(self, tmp_path: Path) -> None:
        wd = tmp_path / "c"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 1000, model="m", agent="main"),
            _line("tool_use", 2000, part={"tool": "fit-model-modal", "state": {
                "status": "completed",
                "input": {"model_bundle_path": "model_to_fit.pkl",
                          "output_path": "fitted_model.nc"},
                "time": {"start": 2000, "end": 3000}}}),
        ]) + "\n")
        md, _ = build_digest(wd)
        row = next(l for l in md.splitlines()
                   if "fit-model-modal" in l and l.strip().startswith("- [t"))
        assert "model_bundle_path=model_to_fit.pkl" in row
        assert "output_path=fitted_model.nc" in row

    def test_error_line_keeps_its_tail(self, tmp_path: Path) -> None:
        wd = tmp_path / "e"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        errline = ("TypeError: MMMPlotSuite.prior_predictive() got an "
                   "unexpected keyword argument 'original_scale'")
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 1000, model="m", agent="main"),
            _line("tool_use", 2000, part={"tool": "bash", "state": {
                "status": "completed", "input": {"command": "python x.py"},
                "output": errline, "time": {"start": 2000, "end": 2100}}}),
        ]) + "\n")
        md, _ = build_digest(wd)
        row = next(l for l in md.splitlines() if "python x.py" in l)
        assert "original_scale" in row  # the offending key (line end) survives

    def test_strip_lsp_removes_diagnostics(self) -> None:
        from dlab.session_digest import _strip_lsp
        t = ("Edit applied successfully.\n\nLSP errors detected in this file, "
             "please fix:\n<diagnostics file=\"x.py\">\nERROR [1:2] bad\n</diagnostics>")
        out = _strip_lsp(t)
        assert "Edit applied successfully." in out
        assert "LSP errors" not in out and "diagnostics" not in out
        assert "ERROR [1:2]" not in out

    def test_digest_get_source_strips_lsp(self) -> None:
        assert "function stripLsp" in DIGEST_GET_SOURCE
        assert "diagnostics" in DIGEST_GET_SOURCE

    def test_consolidator_without_output_is_flagged(self, tmp_path: Path) -> None:
        wd = tmp_path / "c"
        run = wd / "_opencode_logs" / "poet-parallel-run-500"
        run.mkdir(parents=True)
        (run / "instance-1.log").write_text(
            _line("dlab_start", 500, model="m", agent="poet") + "\n")
        (run / "consolidator.log").write_text(
            _line("dlab_start", 900, model="m", agent="consolidator") + "\n")
        (wd / "parallel" / "run-500" / "instance-1").mkdir(parents=True)
        md, _ = build_digest(wd)  # no consolidated_summary.md
        assert "NO consolidated_summary.md (treat as failed)" in md
        (wd / "parallel" / "run-500" / "consolidated_summary.md").write_text("cmp")
        md2, _ = build_digest(wd)
        assert "NO consolidated_summary.md" not in md2


def _artifacts_workdir(tmp_path: Path) -> Path:
    wd = tmp_path / "art"
    logs = wd / "_opencode_logs"
    logs.mkdir(parents=True)
    (logs / "main.log").write_text("\n".join([
        _line("dlab_start", 1000, model="m", agent="main"),
        _line("tool_use", 1100, part={"tool": "bash", "state": {
            "status": "completed", "input": {"command": "python run.py"},
            "output": "done", "time": {"start": 1100, "end": 3000}}}),
    ]) + "\n")
    (wd / "metrics.json").write_text(json.dumps({"r2": 0.84, "mape": 9.3, "ess": 965}))
    (wd / "roas.csv").write_text("channel,roas\nEmail,25.5\nSearch,11.0\n")
    (wd / "report.md").write_text("# Big Title\n\nsome text\nmore\n")
    (wd / "model.nc").write_bytes(b"\x00" * 100)      # binary ext → not indexed
    (wd / "huge.txt").write_text("x\n" * 40000)        # >32KB text → not indexed
    return wd


class TestArtifactRetrieval:
    def test_shapes_rendered(self, tmp_path: Path) -> None:
        md, _ = build_digest(_artifacts_workdir(tmp_path))
        rows = {l.split("]")[1].split("(")[0].strip(): l
                for l in md.splitlines() if l.strip().startswith("- [a")}
        assert "keys: r2, mape, ess" in rows["metrics.json"]
        assert "cols: channel, roas; 2 rows" in rows["roas.csv"]
        assert "lines — Big Title" in rows["report.md"]

    def test_small_text_indexed_big_and_binary_excluded(self, tmp_path: Path) -> None:
        _, index = build_digest(_artifacts_workdir(tmp_path))
        paths = {v["log_file"] for v in index.values()
                 if v["event_type"] == "artifact"}
        assert {"metrics.json", "roas.csv", "report.md"} <= paths
        assert "model.nc" not in paths   # binary extension
        assert "huge.txt" not in paths   # over the 32KB cap

    def test_artifact_index_points_to_readable_file(self, tmp_path: Path) -> None:
        wd = _artifacts_workdir(tmp_path)
        _, index = build_digest(wd)
        entry = next(v for v in index.values()
                     if v["event_type"] == "artifact" and v["log_file"] == "roas.csv")
        assert "channel,roas" in (wd / entry["log_file"]).read_text()

    def test_digest_get_source_handles_artifacts(self) -> None:
        assert 'event_type === "artifact"' in DIGEST_GET_SOURCE


class TestCustomToolSource:
    """A custom tool (has a .opencode/tools/<name>.ts) gets its source bundled
    into its tN retrieval, so the composer can reproduce what it ran."""

    def _workdir(self, tmp_path: Path) -> Path:
        wd = tmp_path / "w"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        tools = wd / ".opencode" / "tools"
        tools.mkdir(parents=True)
        (tools / "analyze-thing.ts").write_text(
            "// runs: python -m mypkg.analyze\nexport default 1\n")
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 1000, model="m", agent="main"),
            _line("tool_use", 1100, part={"tool": "analyze-thing", "state": {
                "status": "completed", "input": {"model_path": "m.nc"},
                "time": {"start": 1100, "end": 1200}}}),
            _line("tool_use", 1300, part={"tool": "bash", "state": {
                "status": "completed", "input": {"command": "ls"},
                "time": {"start": 1300, "end": 1310}}}),
        ]) + "\n")
        return wd

    def test_custom_tool_indexed_with_source_builtin_not(self, tmp_path: Path) -> None:
        wd = self._workdir(tmp_path)
        _, index = build_digest(wd)
        custom = {k: v for k, v in index.items()
                  if v["event_type"] == "tool_use" and v.get("tool_source")}
        assert len(custom) == 1
        assert list(custom.values())[0]["tool_source"] == ".opencode/tools/analyze-thing.ts"
        # the bash call is built-in — no tool_source
        assert any(v["event_type"] == "tool_use" and "tool_source" not in v
                   for v in index.values())

    def test_custom_tool_row_flagged(self, tmp_path: Path) -> None:
        md, _ = build_digest(self._workdir(tmp_path))
        assert "analyze-thing (custom)" in md
        assert "bash (custom)" not in md

    def test_digest_get_appends_tool_source(self) -> None:
        assert "tool_source" in DIGEST_GET_SOURCE
        assert "the code this tool ran" in DIGEST_GET_SOURCE

    def test_generate_digest_copies_sources_and_rewrites_paths(self, tmp_path: Path) -> None:
        # so the composer can read a tool's code without that tool being loaded
        wd = self._workdir(tmp_path)
        out = generate_digest(wd)
        assert (out / "tool_sources" / "analyze-thing.ts").is_file()
        index = json.loads((out / "index.json").read_text())
        srcs = [v["tool_source"] for v in index.values() if v.get("tool_source")]
        assert srcs and all(s == "_digest/tool_sources/analyze-thing.ts" for s in srcs)


class TestCodeMapResolution:
    """With a --dpack, the digest resolves a custom tool to the REAL library code
    it ran (via the pack's code map) instead of the thin .ts wrapper."""

    def _pack_and_workdir(self, tmp_path: Path) -> tuple[Path, Path]:
        dpack = tmp_path / "pack"
        tools = dpack / "opencode" / "tools"
        tools.mkdir(parents=True)
        tool_ts = (
            'import { tool } from "@opencode-ai/plugin"\n'
            "export default tool({\n"
            "  args: { model_path: tool.schema.string() },\n"
            "  async execute(args) {\n"
            "    await Bun.$`python -m mypkg.analyze ${args.model_path}`.nothrow()\n"
            "  },\n})\n"
        )
        (tools / "analyze-thing.ts").write_text(tool_ts)
        pkg = dpack / "docker" / "mypkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "analyze.py").write_text(
            "import argparse\n"
            "from mypkg.core import do_the_analysis\n"
            "def main():\n"
            "    p = argparse.ArgumentParser(); p.add_argument('model_path')\n"
            "    a = p.parse_args(); do_the_analysis(a.model_path)\n"
            "if __name__ == '__main__':\n    main()\n"
        )
        (pkg / "core.py").write_text(
            "def do_the_analysis(path):\n"
            "    print('REAL ANALYSIS CODE for', path)\n"
        )

        wd = tmp_path / "w"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        wtools = wd / ".opencode" / "tools"
        wtools.mkdir(parents=True)
        (wtools / "analyze-thing.ts").write_text(tool_ts)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 1000, model="m", agent="main"),
            _line("tool_use", 1100, part={"tool": "analyze-thing", "state": {
                "status": "completed", "input": {"model_path": "m.nc"},
                "time": {"start": 1100, "end": 1200}}}),
        ]) + "\n")
        return dpack, wd

    def test_resolved_library_code_replaces_wrapper(self, tmp_path: Path) -> None:
        dpack, wd = self._pack_and_workdir(tmp_path)
        out = generate_digest(wd, dpack=dpack)
        resolved = out / "tool_sources" / "analyze-thing.py"
        assert resolved.is_file()
        body = resolved.read_text()
        assert "def do_the_analysis" in body            # the real work function
        assert "REAL ANALYSIS CODE" in body
        assert "resolved from the decision-pack library" in body  # the header
        # the .ts wrapper is NOT what the pointer resolves to anymore
        index = json.loads((out / "index.json").read_text())
        srcs = [v["tool_source"] for v in index.values() if v.get("tool_source")]
        assert srcs and all(s.endswith("analyze-thing.py") for s in srcs)

    def test_without_dpack_falls_back_to_wrapper(self, tmp_path: Path) -> None:
        _, wd = self._pack_and_workdir(tmp_path)
        out = generate_digest(wd)  # no dpack → no resolution
        assert (out / "tool_sources" / "analyze-thing.ts").is_file()
        assert not (out / "tool_sources" / "analyze-thing.py").exists()


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

    def test_source_handles_raw_text_and_line_ranges(self) -> None:
        # r-ids: reads a line range (line_no..line_end) and strips [STDERR].
        assert "line_end" in DIGEST_GET_SOURCE
        assert 'event_type === "raw_text"' in DIGEST_GET_SOURCE
        assert "[STDERR]" in DIGEST_GET_SOURCE

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
