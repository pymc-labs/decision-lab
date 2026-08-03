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
    def test_edit_then_rerun_shows_both_versions(self, tmp_path: Path) -> None:
        # write (buggy) -> run (error) -> edit (fix) -> run: two cells, v1 then v2.
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
        assert len(runs) == 2
        assert "wrong_name" in runs[0].source and "NameError" in runs[0].stream
        assert "x = 42" in runs[1].source and "42" in runs[1].stream
        assert "wrong_name" not in runs[1].source  # the edit was applied


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
        assert "def do_work" in cell.source            # resolved library code
        assert "REAL" in cell.source
        assert "do-thing(x='hello')" in cell.source     # the invocation header
        assert "did the thing" in cell.stream
