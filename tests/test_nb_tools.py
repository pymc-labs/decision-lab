"""Tests for the cell-level notebook tools (issue #86).

Source-level guards in the style of test_parallel_tool.py, plus a real node
build: the tools import @opencode-ai/plugin (not installed), so we extract their
pure helper functions and run them under node (v22+ strips TS types) to compose
an actual .ipynb, then validate its structure.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

# A stub of @opencode-ai/plugin so the REAL tool files load and their execute()
# functions can be driven directly (the package isn't installed in the env).
_PLUGIN_STUB = """
function chainable() {
  const c = new Proxy(function () { return c }, { get() { return () => c }, apply() { return c } })
  return c
}
const tool = (config) => config
tool.schema = new Proxy({}, { get: () => () => chainable() })
export { tool }
"""

JS_DIR = Path(__file__).parent.parent / "dlab" / "js"
AGENTS_DIR = Path(__file__).parent.parent / "dlab" / "agents"
NB_TOOLS = [
    "nb-add-markdown-cell", "nb-add-code-cell", "nb-edit-cell",
    "nb-note", "nb-read", "nb-finalize",
]


def _src(name: str) -> str:
    return (JS_DIR / f"{name}.ts").read_text()


def _make_harness(tmp_path: Path) -> Path:
    """A temp dir where the real tool files run: stub plugin in node_modules,
    tool .ts files copied in unchanged."""
    plugin = tmp_path / "node_modules" / "@opencode-ai" / "plugin"
    plugin.mkdir(parents=True)
    (plugin / "package.json").write_text(json.dumps({
        "name": "@opencode-ai/plugin", "version": "0.0.0",
        "type": "module", "main": "index.js"}))
    (plugin / "index.js").write_text(_PLUGIN_STUB)
    for name in NB_TOOLS:
        shutil.copy(JS_DIR / f"{name}.ts", tmp_path / f"{name}.ts")
    return tmp_path


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


class TestNbToolsEndToEnd:
    """Drive ALL FIVE real tools (their actual execute() functions) in sequence
    on one notebook, then validate the composed .ipynb."""

    def test_full_compose_chain(self, tmp_path: Path) -> None:
        if not _have_node():
            pytest.skip("node not available")
        h = _make_harness(tmp_path)
        fig = h / "roas.png"
        fig.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x01\x02\x03" * 500)  # >1KB
        nb_path = h / "overview.ipynb"
        (h / "compose.ts").write_text('''
import md from "./nb-add-markdown-cell.ts"
import code from "./nb-add-code-cell.ts"
import edit from "./nb-edit-cell.ts"
import note from "./nb-note.ts"
import read from "./nb-read.ts"
import finalize from "./nb-finalize.ts"
const NB = process.argv[2], FIG = process.argv[3]
await md.execute({ notebook: NB, text: "# MMM\\n\\nTotal spend $6.77M." })
await code.execute({ notebook: NB, code: "import pandas as pd", outputs: [{ stream: "ready\\n" }] })
await code.execute({ notebook: NB, code: "idata = pm.sample()", tags: ["long-running"], outputs: [{ stream: "Sampling...\\nDone.\\n" }] })
await code.execute({ notebook: NB, code: "print(roas)", outputs: [{ stream: "Local-Ads 5.21\\n" }, { image: FIG }] })
await edit.execute({ notebook: NB, index: 1, code: "import pandas as pd, pymc as pm" })
// disclose a reconstruction (must land in the top preamble cell)
await note.execute({ notebook: NB, text: "The figure was regenerated by re-invoking analyze-model." })
const before = await read.execute({ notebook: NB, head: 40 })
await finalize.execute({ notebook: NB })
await finalize.execute({ notebook: NB })  // idempotent — must not double the header
console.log(JSON.stringify({ read: before }))
''')
        r = subprocess.run(["node", str(h / "compose.ts"), str(nb_path), str(fig)],
                           capture_output=True, text=True, timeout=60, cwd=h)
        assert r.returncode == 0, r.stderr

        nb = json.loads(nb_path.read_text())
        assert nb["nbformat"] == 4
        # exactly one provenance header, at the top, despite two finalize calls
        headers = [c for c in nb["cells"] if isinstance(c["source"], str)
                   and "Auto-composed from session artifacts" in c["source"]]
        assert len(headers) == 1
        assert nb["cells"][0] is headers[0]
        # the preamble is ONE markdown cell holding provenance AND the nb-note
        preamble = nb["cells"][0]
        assert preamble["cell_type"] == "markdown"
        assert "regenerated by re-invoking analyze-model" in preamble["source"]
        # currency escaped in the markdown body
        body = next(c for c in nb["cells"] if "Total spend" in
                    (c["source"] if isinstance(c["source"], str) else "".join(c["source"])))
        assert "\\$6.77M" in body["source"]
        # code cells: sequential execution counts, edit applied, tag kept
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
        assert [c["execution_count"] for c in code_cells] == [1, 2, 3]
        assert "pymc as pm" in code_cells[0]["source"]  # nb-edit-cell applied
        assert sum(c["metadata"].get("tags") == ["long-running"] for c in code_cells) == 1
        # the figure is embedded as base64 with its source path tracked
        imgs = [o for c in code_cells for o in c["outputs"]
                if o["output_type"] == "display_data"]
        assert len(imgs) == 1 and len(imgs[0]["data"]["image/png"]) > 1000
        assert imgs[0]["metadata"]["dlab_source"].endswith("roas.png")
        # nb-read gave a compact, base64-free view (figure named by PATH)
        read_out = json.loads(r.stdout.strip())["read"]
        assert "image: " in read_out and "roas.png" in read_out
        assert "iVBOR" not in read_out and "base64" not in read_out.lower()


class TestNbNoteAndPreamble:
    def test_note_source_targets_first_markdown_cell(self) -> None:
        src = _src("nb-note")
        assert "export default tool(" in src
        assert 'cell_type === "markdown"' in src   # appends to a markdown preamble
        assert "unshift" in src                     # creates it if missing

    def test_finalize_pins_provenance_into_first_markdown_cell(self) -> None:
        # finalize must keep provenance + notes in ONE cell, not stack cells
        src = _src("nb-finalize")
        assert "cell_type === \"markdown\"" in src or 'cell_type === "markdown"' in src

    def test_note_appends_and_creates_preamble(self, tmp_path: Path) -> None:
        if not _have_node():
            pytest.skip("node not available")
        h = _make_harness(tmp_path)
        nb = h / "nb.ipynb"
        (h / "d.ts").write_text('''
import code from "./nb-add-code-cell.ts"
import note from "./nb-note.ts"
import finalize from "./nb-finalize.ts"
const NB = process.argv[2]
await code.execute({ notebook: NB, code: "x = 1" })        // first cell is CODE
await note.execute({ notebook: NB, text: "first note $5" }) // must PREPEND a preamble
await note.execute({ notebook: NB, text: "second note" })   // must APPEND to it
await finalize.execute({ notebook: NB })
''')
        r = subprocess.run(["node", str(h / "d.ts"), str(nb)],
                           capture_output=True, text=True, timeout=30, cwd=h)
        assert r.returncode == 0, r.stderr
        cells = json.loads(nb.read_text())["cells"]
        pre = cells[0]
        assert pre["cell_type"] == "markdown"
        # one preamble cell holds provenance + both notes, currency escaped
        assert "Auto-composed from session artifacts" in pre["source"]
        assert "first note \\$5" in pre["source"]
        assert "second note" in pre["source"]
        assert sum("first note" in (c["source"] if isinstance(c["source"], str)
                   else "".join(c["source"])) for c in cells) == 1  # not duplicated


class TestComposerPrompt:
    def test_prompt_file_exists_and_wires_tools(self) -> None:
        p = AGENTS_DIR / "composer.md"
        assert p.exists(), "dlab/agents/composer.md must exist"
        text = p.read_text()
        # frontmatter wires the nb-* tools + digest-get and denies edit/bash
        for t in NB_TOOLS + ["digest-get"]:
            assert f"{t}: true" in text, f"composer prompt must enable {t}"
        assert "bash: false" in text and "edit: false" in text

    def test_prompt_encodes_the_agreed_rules(self) -> None:
        text = (AGENTS_DIR / "composer.md").read_text()
        # composed-not-executed, digest-only, fit-then-load, tool-output
        # reproduction (3->2->1), disclosure, preamble
        for needle in ["composed", "digest-get", "long-running",
                       "custom tool", "nb-note", "preamble", "attempts/"]:
            assert needle in text, f"composer prompt missing: {needle}"

    def test_prompt_is_dpack_agnostic(self) -> None:
        # generality is load-bearing: no hardcoded library/pack specifics
        text = (AGENTS_DIR / "composer.md").read_text().lower()
        for banned in ["mmm_lib", "pymc", "roas", "adstock", "sunrise"]:
            assert banned not in text, f"composer prompt must stay general (found '{banned}')"
