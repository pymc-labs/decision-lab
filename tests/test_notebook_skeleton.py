"""Tests for the deterministic notebook skeleton (issue #68).

The skeleton is correct-by-construction: real code paired with the real output it
produced, no LLM. These cover the deterministic pairing — script code + stdout +
window-attributed figures, custom-tool code resolution, dropping figures made
outside any execution window, skipping plumbing bash, and valid ipynb.
"""
import json
import os
from pathlib import Path

from dlab.notebook_skeleton import build_skeleton, write_skeletons


def _line(event_type: str, ts, **body) -> str:
    return json.dumps({"type": event_type, "timestamp": ts, **body})


def _tool(name: str, ts: int, *, inp: dict, start: int, end: int,
          output: str = "", error: str = "") -> str:
    return _line("tool_use", ts, part={"tool": name, "state": {
        "status": "completed", "input": inp, "output": output, "error": error,
        "time": {"start": start, "end": end}}})


def _set_mtime(path: Path, ms: int) -> None:
    os.utime(path, (ms / 1000, ms / 1000))


class TestScriptCell:
    def _workdir(self, tmp_path: Path) -> Path:
        wd = tmp_path / "w"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        (wd / "fig.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 40)
        _set_mtime(wd / "fig.png", 1500)          # inside [1000, 2000]
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 500, part={"model": "m"}),
            _tool("write", 900, inp={"filePath": "plot.py",
                  "content": "import matplotlib.pyplot as plt\nplt.savefig('fig.png')\n"},
                  start=900, end=910),
            _tool("bash", 1000, inp={"command": "python plot.py"},
                  start=1000, end=2000, output="made a figure\n"),
            "extra stdout line",   # bare stdout → raw_text, attached to the cell
        ]) + "\n")
        return wd

    def test_code_stream_and_figure_paired(self, tmp_path: Path) -> None:
        nbs = build_skeleton(self._workdir(tmp_path))
        assert len(nbs) == 1
        cells = nbs[0].cells
        # the write is not its own cell; the bash-run is, carrying the script code
        assert len(cells) == 1
        cell = cells[0]
        assert "plt.savefig" in cell.source        # the real script content
        assert "made a figure" in cell.stream       # tool output
        assert "extra stdout line" in cell.stream   # trailing raw_text captured
        assert [f.name for f in cell.figures] == ["fig.png"]  # window-attributed

    def test_figure_outside_window_is_dropped(self, tmp_path: Path) -> None:
        wd = self._workdir(tmp_path)
        _set_mtime(wd / "fig.png", 5000)            # after the run window + slack
        cell = build_skeleton(wd)[0].cells[0]
        assert cell.figures == []                   # not produced by a shown cell

    def test_valid_ipynb_with_embedded_outputs(self, tmp_path: Path) -> None:
        wd = self._workdir(tmp_path)
        paths = write_skeletons(wd)
        assert paths and paths[0].parent.name == "skeleton"
        nb = json.loads(paths[0].read_text())
        code = [c for c in nb["cells"] if c["cell_type"] == "code"]
        assert code and code[0]["outputs"]          # not empty-output
        kinds = {o["output_type"] for o in code[0]["outputs"]}
        assert kinds == {"stream", "display_data"}


class TestEditReplay:
    def test_edit_then_rerun_keeps_only_final(self, tmp_path: Path) -> None:
        # write (buggy) -> run (error) -> edit (fix) -> run: the buggy run collapses
        # into the FINAL version — the one that produced the output.
        wd = tmp_path / "w"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 500, part={"model": "m"}),
            _tool("write", 900, inp={"filePath": "/ws/m.py",
                  "content": "x = wrong_name\nprint(x)\n"}, start=900, end=910),
            _tool("bash", 1000, inp={"command": "python m.py"},
                  start=1000, end=1100, error="NameError: wrong_name\n"),
            _tool("edit", 1200, inp={"filePath": "/ws/m.py",
                  "oldString": "wrong_name", "newString": "42"}, start=1200, end=1210),
            _tool("bash", 1300, inp={"command": "python m.py"},
                  start=1300, end=1400, output="42\n"),
        ]) + "\n")
        cells = build_skeleton(wd)[0].cells
        runs = [c for c in cells if c.source.strip().startswith("x =")]
        assert len(runs) == 1                              # collapsed to the final run
        assert "x = 42" in runs[0].source and "42" in runs[0].stream
        assert "wrong_name" not in runs[0].source          # the buggy version is gone
        assert "NameError" not in runs[0].stream

    def test_shell_decorations_dont_prevent_collapse(self, tmp_path: Path) -> None:
        # same script + args; only redirects/pipes/timeout differ across re-runs —
        # still one fix-arc, must collapse to the final run.
        wd = tmp_path / "w"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 500, part={"model": "m"}),
            _tool("write", 900, inp={"filePath": "/ws/p.py", "content": "print('v1')\n"},
                  start=900, end=910),
            _tool("bash", 1000, inp={"command": "python p.py"},
                  start=1000, end=1100, error="boom\n"),
            _tool("edit", 1150, inp={"filePath": "/ws/p.py",
                  "oldString": "v1", "newString": "v2"}, start=1150, end=1160),
            _tool("bash", 1200, inp={"command": "timeout 180 python p.py 2>&1 | head -100"},
                  start=1200, end=1300, output="v2\n"),
        ]) + "\n")
        runs = [c for c in build_skeleton(wd)[0].cells if "print(" in c.source]
        assert len(runs) == 1 and "v2" in runs[0].source   # decorations stripped

    def test_sweep_with_different_args_is_kept(self, tmp_path: Path) -> None:
        # same script, DIFFERENT args (a sweep) → distinct commands → both kept.
        wd = tmp_path / "w"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 500, part={"model": "m"}),
            _tool("write", 900, inp={"filePath": "/ws/opt.py", "content": "run()\n"},
                  start=900, end=910),
            _tool("bash", 1000, inp={"command": "python opt.py --pct 5"},
                  start=1000, end=1100, output="5%\n"),
            _tool("bash", 1200, inp={"command": "python opt.py --pct 50"},
                  start=1200, end=1300, output="50%\n"),
        ]) + "\n")
        cells = build_skeleton(wd)[0].cells
        runs = [c for c in cells if "run()" in c.source]
        assert len(runs) == 2                              # a sweep is distinct, not a fix-arc
        assert {"5%\n", "50%\n"} == {r.stream for r in runs}


class TestSkeletonCommand:
    def test_rejects_non_workdir(self, tmp_path: Path) -> None:
        from dlab.cli import cmd_skeleton
        assert cmd_skeleton(str(tmp_path)) == 1          # no _opencode_logs

    def test_builds_and_writes_skeleton(self, tmp_path: Path) -> None:
        from dlab.cli import cmd_skeleton
        wd = tmp_path / "w"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 500, part={"model": "m"}),
            _tool("write", 900, inp={"filePath": "/ws/s.py", "content": "print(1)\n"},
                  start=900, end=910),
            _tool("bash", 1000, inp={"command": "python s.py"},
                  start=1000, end=1100, output="1\n"),
        ]) + "\n")
        assert cmd_skeleton(str(wd)) == 0
        nbs = list((wd / "skeleton").glob("*.ipynb"))
        assert nbs and json.loads(nbs[0].read_text())["nbformat"] == 4


class TestContextHints:
    def _workdir(self, tmp_path: Path) -> Path:
        wd = tmp_path / "w"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 500, part={"model": "m", "prompt": "do the task"}),
            _tool("write", 900, inp={"filePath": "/ws/m.py", "content": "print('hi')\n"},
                  start=900, end=910),
            _tool("bash", 1000, inp={"command": "python m.py"},
                  start=1000, end=1100, output="hi\n"),
            "hi from stdout",   # raw_text stream for the bash call
        ]) + "\n")
        return wd

    def test_hint_ids_align_with_digest_index(self, tmp_path: Path) -> None:
        # a cell's produced_by must be a real digest tool-call id the composer can
        # digest-get — this guards against drift between the two parses.
        from dlab.session_digest import generate_digest
        wd = self._workdir(tmp_path)
        generate_digest(wd)
        index = json.loads((wd / "_digest" / "index.json").read_text())
        nbs = build_skeleton(wd)
        seen = False
        for nb in nbs:
            for c in nb.cells:
                if not c.tid:
                    continue
                seen = True
                entry = index.get(f"{nb.qual}/{c.tid}")
                assert entry and entry["event_type"] == "tool_use"
        assert seen

    def test_metadata_dlab_hints_rendered(self, tmp_path: Path) -> None:
        from dlab.notebook_skeleton import write_skeletons
        wd = self._workdir(tmp_path)
        (wd / "_digest").mkdir()  # not required, but mirrors a real run
        paths = write_skeletons(wd)
        nb = json.loads(paths[0].read_text())
        assert nb["metadata"]["dlab"]["adopted"] is True
        code = [c for c in nb["cells"] if c["cell_type"] == "code"][0]
        hint = code["metadata"]["dlab"]
        assert hint["kind"] == "script"
        assert hint["produced_by"].endswith("/t2")  # the bash run is the 2nd tool call


class TestPhaseGroupingAndAdoption:
    def _run(self, tmp_path: Path) -> Path:
        wd = tmp_path / "w"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        # orchestrator adopts instance-1 (compound cp — instance-2 is not adopted)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 500, part={"model": "m"}),
            _tool("bash", 1000, inp={"command":
                  "cp /workspace/parallel/run-111/instance-1/m.nc /workspace/best.nc "
                  "&& cp -r /workspace/parallel/run-111/instance-1/out /workspace/out"},
                  start=1000, end=1010),
        ]) + "\n")
        rundir = logs / "modeler-parallel-run-111"
        rundir.mkdir()
        for inst in ("instance-1", "instance-2"):
            (rundir / f"{inst}.log").write_text("\n".join([
                _line("dlab_start", 600, part={"model": "m"}),
                _tool("write", 610, inp={"filePath": f"/ws/{inst}.py",
                      "content": f"print('{inst}')\n"}, start=610, end=615),
                _tool("bash", 620, inp={"command": f"python {inst}.py"},
                      start=620, end=700, output="ran\n"),
            ]) + "\n")
            (wd / "parallel" / "run-111" / inst).mkdir(parents=True)
        return wd

    def test_adopted_detected_from_cp(self, tmp_path: Path) -> None:
        from dlab.notebook_skeleton import _adopted_instances
        adopted = _adopted_instances(self._run(tmp_path))
        assert ("111", "instance-1") in adopted        # promoted to the root
        assert ("111", "instance-2") not in adopted     # a compound cp didn't confuse it

    def test_write_routes_adopted_vs_attempts(self, tmp_path: Path) -> None:
        from dlab.notebook_skeleton import write_skeletons
        paths = write_skeletons(self._run(tmp_path))
        rels = {str(p.relative_to((tmp_path / "w" / "skeleton"))) for p in paths}
        # adopted modeler instance in the main dir; the other under attempts/
        assert any("modeler" in r and "attempts" not in r for r in rels)
        assert "attempts/modeler_instance-2.ipynb" in rels
        assert not any("instance-1" in r and "attempts" in r for r in rels)


class TestPlumbingSkipped:
    def test_cp_and_ls_produce_no_cells(self, tmp_path: Path) -> None:
        wd = tmp_path / "w"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 500, part={"model": "m"}),
            _tool("bash", 1000, inp={"command": "cp a.nc b.nc"}, start=1000, end=1010),
            _tool("bash", 1100, inp={"command": "ls -la"}, start=1100, end=1110),
        ]) + "\n")
        assert build_skeleton(wd) == []             # nothing worth a cell


class TestCustomToolResolution:
    def test_custom_tool_cell_carries_resolved_code(self, tmp_path: Path) -> None:
        # a minimal dpack whose tool shells out to a library function
        dpack = tmp_path / "pack"
        tools = dpack / "opencode" / "tools"
        tools.mkdir(parents=True)
        (tools / "do-thing.ts").write_text(
            'import { tool } from "@opencode-ai/plugin"\n'
            "export default tool({ args: { x: tool.schema.string() },\n"
            "  async execute(a){ await Bun.$`python -m lib.run ${a.x}` } })\n")
        pkg = dpack / "docker" / "lib"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "run.py").write_text(
            "import argparse\nfrom lib.core import do_work\n"
            "def main():\n    do_work('z')\n"
            "if __name__=='__main__':\n    main()\n")
        (pkg / "core.py").write_text("def do_work(z):\n    print('REAL', z)\n")

        wd = tmp_path / "w"
        logs = wd / "_opencode_logs"
        logs.mkdir(parents=True)
        wtools = wd / ".opencode" / "tools"
        wtools.mkdir(parents=True)
        (wtools / "do-thing.ts").write_text("stub")   # marks it a custom tool
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 500, part={"model": "m"}),
            _tool("do-thing", 1000, inp={"x": "hello"}, start=1000, end=1100,
                  output="did the thing\n"),
        ]) + "\n")

        cell = build_skeleton(wd, dpack=dpack)[0].cells[0]
        # a clean import + call, NOT a verbatim dump of the function body
        assert "from lib.core import do_work" in cell.source
        assert "do_work('hello')" in cell.source        # single input → positional
        assert "def do_work" not in cell.source         # no module dump
        assert "did the thing" in cell.stream

    def test_call_template_is_substituted(self, tmp_path: Path) -> None:
        # an LLM-authored template (committed in code_map.json) → the skeleton fills
        # its $placeholders with the run's input values, deterministically.
        dpack = tmp_path / "pack"
        (dpack / "opencode" / "tools").mkdir(parents=True)
        (dpack / "opencode" / "tools" / "do-thing.ts").write_text("stub")
        (dpack / "code_map.json").write_text(json.dumps({
            "dpack": "pack", "shape": "tool-backed", "sources": {},
            "tools": {"do-thing": {"kind": "python-module",
                      "call_template": "from lib.core import work\nwork($a, out=$b)"}},
        }))
        wd = tmp_path / "w"
        (wd / ".opencode" / "tools").mkdir(parents=True)
        (wd / ".opencode" / "tools" / "do-thing.ts").write_text("stub")
        logs = wd / "_opencode_logs"
        logs.mkdir()
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 500, part={"model": "m"}),
            _tool("do-thing", 1000, inp={"a": "x.nc", "b": "out"},
                  start=1000, end=1100, output="ok\n"),
        ]) + "\n")
        src = build_skeleton(wd, dpack=dpack)[0].cells[0].source
        assert "from lib.core import work" in src
        assert "work('x.nc', out='out')" in src   # $a, $b → repr of the inputs

    def test_signature_mismatch_falls_back_to_invocation(self, tmp_path: Path) -> None:
        # a CLI whose main() loads/transforms: the work fn's params are NOT the
        # tool inputs, so we import it and document the invocation rather than
        # emitting a wrong fn(**inputs) call.
        dpack = tmp_path / "pack"
        tools = dpack / "opencode" / "tools"
        tools.mkdir(parents=True)
        (tools / "do-thing.ts").write_text(
            'import { tool } from "@opencode-ai/plugin"\n'
            "export default tool({ args: { a: tool.schema.string(),"
            " b: tool.schema.string() },\n"
            "  async execute(x){ await Bun.$`python -m lib.run ${x.a} ${x.b}` } })\n")
        pkg = dpack / "docker" / "lib"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "run.py").write_text(
            "import argparse\nfrom lib.core import work\n"
            "def main():\n    obj = load()\n    work(obj, tuning=1)\n"
            "if __name__=='__main__':\n    main()\n")
        (pkg / "core.py").write_text("def work(model, tuning):\n    print('W')\n")

        wd = tmp_path / "w"
        (wd / ".opencode" / "tools").mkdir(parents=True)
        (wd / ".opencode" / "tools" / "do-thing.ts").write_text("stub")
        logs = wd / "_opencode_logs"
        logs.mkdir()
        (logs / "main.log").write_text("\n".join([
            _line("dlab_start", 500, part={"model": "m"}),
            _tool("do-thing", 1000, inp={"a": "x.nc", "b": "out"},
                  start=1000, end=1100, output="ok\n"),
        ]) + "\n")

        src = build_skeleton(wd, dpack=dpack)[0].cells[0].source
        assert "from lib.core import work" in src         # imports the real fn
        assert "work(a=" not in src and "work(b=" not in src  # no wrong call
        assert "a='x.nc'" in src and "b='out'" in src      # documents the invocation
