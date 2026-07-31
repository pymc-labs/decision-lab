"""Tests for the cell-level notebook tools (issue #86).

Source-level guards in the style of test_parallel_tool.py, plus a real node
build: the tools import @opencode-ai/plugin (not installed), so we extract their
pure helper functions and run them under node (v22+ strips TS types) to compose
an actual .ipynb, then validate its structure.
"""

import json
import subprocess
from pathlib import Path

import pytest

JS_DIR = Path(__file__).parent.parent / "dlab" / "js"
NB_TOOLS = [
    "nb-add-markdown-cell", "nb-add-code-cell", "nb-edit-cell",
    "nb-read", "nb-finalize",
]


def _src(name: str) -> str:
    return (JS_DIR / f"{name}.ts").read_text()


def _have_node() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _helpers(name: str) -> str:
    """The helper block of a tool file: everything before `export default
    tool(`, minus the import lines (we supply our own fs import)."""
    src = _src(name)
    head = src.split("export default tool(")[0]
    return "\n".join(l for l in head.splitlines()
                     if not l.strip().startswith("import "))


def _run_node(ts_body: str, args: list[str], tmp_path: Path) -> str:
    driver = tmp_path / "driver.ts"
    driver.write_text('import { readFileSync, writeFileSync, existsSync } from "node:fs"\n' + ts_body)
    r = subprocess.run(["node", str(driver), *args],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


class TestNbToolSources:
    def test_all_five_tools_exist_and_export_tool(self) -> None:
        for name in NB_TOOLS:
            src = _src(name)
            assert "export default tool(" in src
            assert 'from "@opencode-ai/plugin"' in src

    def test_code_cell_passes_paths_not_base64(self) -> None:
        src = _src("nb-add-code-cell")
        # the model passes image PATHS; the TOOL does the base64
        assert '"base64"' in src
        assert "output_type" in src and "display_data" in src
        assert "nextExecCount" in src  # execution_count auto-assigned

    def test_markdown_escapes_dollar_by_default(self) -> None:
        src = _src("nb-add-markdown-cell")
        assert "escapeDollar" in src and "replace(/\\$/g" in src
        assert "math" in src  # per-cell opt-in to MathJax

    def test_read_strips_base64(self) -> None:
        src = _src("nb-read")
        assert "dlab_source" in src           # names the figure by path
        assert "image/png" not in src         # never touches the encoded bytes
        assert ".data" not in src             # doesn't read the payload at all

    def test_finalize_injects_idempotent_provenance_header(self) -> None:
        src = _src("nb-finalize")
        assert "Auto-composed from session artifacts" in src
        assert "not executed" in src.lower() or "not re-executed" in src.lower()
        assert "includes(HEADER_MARK)" in src  # idempotency guard


class TestNbToolsRuntime:
    def test_builds_valid_notebook_with_embedded_outputs(self, tmp_path: Path) -> None:
        if not _have_node():
            pytest.skip("node not available")
        png = tmp_path / "fig.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        out = tmp_path / "nb.ipynb"
        driver = _helpers("nb-add-code-cell") + """
const nb = emptyNb()
const outs = buildOutputs([{ image: process.argv[2] }, { stream: "line1\\nline2\\n" }])
nb.cells.push({ cell_type: "code", execution_count: nextExecCount(nb),
  metadata: { tags: ["long-running"] }, outputs: outs, source: "print(1)" })
nb.cells.push({ cell_type: "code", execution_count: nextExecCount(nb),
  metadata: {}, outputs: [], source: "print(2)" })
saveNb(process.argv[3], nb)
"""
        _run_node(driver, [str(png), str(out)], tmp_path)

        nb = json.loads(out.read_text())
        assert nb["nbformat"] == 4
        cells = nb["cells"]
        assert len(cells) == 2
        # execution counts are sequential and auto-assigned
        assert cells[0]["execution_count"] == 1
        assert cells[1]["execution_count"] == 2
        assert cells[0]["metadata"]["tags"] == ["long-running"]
        # the image output is a real display_data with base64, path in metadata
        img = next(o for o in cells[0]["outputs"] if o["output_type"] == "display_data")
        assert len(img["data"]["image/png"]) > 0
        assert img["metadata"]["dlab_source"].endswith("fig.png")
        # the stream output is preserved verbatim
        strm = next(o for o in cells[0]["outputs"] if o["output_type"] == "stream")
        text = strm["text"] if isinstance(strm["text"], str) else "".join(strm["text"])
        assert "line1" in text and "line2" in text

    def test_markdown_dollar_escaping(self, tmp_path: Path) -> None:
        if not _have_node():
            pytest.skip("node not available")
        driver = _helpers("nb-add-markdown-cell") + """
console.log(JSON.stringify([
  escapeDollar("$1,240 spend", false),
  escapeDollar("$x + y$", true),
]))
"""
        out = json.loads(_run_node(driver, [], tmp_path).strip())
        assert out[0] == "\\$1,240 spend"  # currency escaped
        assert out[1] == "$x + y$"          # math:true kept literal

    def test_finalize_header_is_idempotent(self, tmp_path: Path) -> None:
        if not _have_node():
            pytest.skip("node not available")
        out = tmp_path / "nb.ipynb"
        driver = _helpers("nb-finalize") + """
function finalize(p) {
  const nb = loadNb(p)
  if (!nb.cells) nb.cells = []
  const firstSrc = nb.cells[0] ? srcText(nb.cells[0].source) : ""
  if (!firstSrc.includes(HEADER_MARK))
    nb.cells.unshift({ cell_type: "markdown", metadata: {},
      source: `> **${HEADER_MARK}.** Outputs are embedded from the original run.` })
  saveNb(p, nb)
}
const p = process.argv[2]
saveNb(p, { ...emptyNb(), cells: [{ cell_type: "markdown", metadata: {}, source: "body" }] })
finalize(p); finalize(p)  // twice — must not double the header
"""
        _run_node(driver, [str(out)], tmp_path)
        nb = json.loads(out.read_text())
        headers = [c for c in nb["cells"]
                   if "Auto-composed from session artifacts" in
                   (c["source"] if isinstance(c["source"], str) else "".join(c["source"]))]
        assert len(headers) == 1  # exactly one, despite two finalize calls
        assert nb["cells"][0] is headers[0] or nb["cells"].index(headers[0]) == 0
