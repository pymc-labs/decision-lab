"""Tests for the deterministic decision-pack code map (issue #68).

Two layers: synthetic fixtures for precise extractor assertions, and integration
against the real in-repo decision-packs (no mocks) covering every pack shape —
tool-backed + remote-dispatch (mmm), modal-inline (modal-example), script-only
(poem).
"""
import json
import shutil
from pathlib import Path

from dlab.dpack_codemap import (
    build_code_map,
    extract_py_module,
    extract_ts_tool,
    resolve_dispatch,
    resolve_entry_code,
    stale_sources,
    write_code_map,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DPACKS = REPO_ROOT / "decision-packs"


# --------------------------------------------------------------------------- #
# synthetic fixtures — exact extractor behaviour, decoupled from any real pack
# --------------------------------------------------------------------------- #

def _make_pack(root: Path, *, tool_ts: str, lib: dict[str, str] | None = None,
               modal: dict[str, str] | None = None) -> Path:
    (root / "opencode" / "tools").mkdir(parents=True)
    (root / "opencode" / "tools" / "do-thing.ts").write_text(tool_ts)
    docker = root / "docker"
    if lib:
        pkg = docker / "mylib"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        for name, body in lib.items():
            (pkg / name).write_text(body)
    if modal:
        app = docker / "modal_app"
        app.mkdir(parents=True)
        for name, body in modal.items():
            (app / name).write_text(body)
    return root


TS_MODULE = '''import { tool } from "@opencode-ai/plugin"
export default tool({
  args: {
    data_path: tool.schema.string().describe("the data"),
    seed: tool.schema.number().optional().describe("seed"),
  },
  async execute(args) {
    const cmdParts = [`python -m mylib.run_cli`, args.data_path, `--seed ${args.seed}`]
    await Bun.$`sh -c ${cmdParts.join(' ')}`.nothrow()
  },
})
'''

PY_CLI = '''import argparse
from mylib.core import do_the_work

def main():
    p = argparse.ArgumentParser()
    p.add_argument("data_path")
    p.add_argument("--seed", type=int)
    args = p.parse_args()
    do_the_work(args.data_path, seed=args.seed)

if __name__ == "__main__":
    main()
'''


class TestTsExtraction:
    def test_inputs_module_and_optional(self, tmp_path: Path) -> None:
        ts = tmp_path / "t.ts"
        ts.write_text(TS_MODULE)
        out = extract_ts_tool(ts)
        assert out["module"] == "mylib.run_cli"
        assert out["kind"] == "python-module"
        names = {i["name"]: i["optional"] for i in out["inputs"]}
        assert names == {"data_path": False, "seed": True}

    def test_pure_ts_when_no_python(self, tmp_path: Path) -> None:
        ts = tmp_path / "t.ts"
        ts.write_text('export default tool({ async execute() { return "hi" } })')
        assert extract_ts_tool(ts)["kind"] == "pure-ts"


class TestPyExtraction:
    def test_argparse_and_entry(self, tmp_path: Path) -> None:
        pack = _make_pack(tmp_path / "p", tool_ts=TS_MODULE,
                          lib={"run_cli.py": PY_CLI, "core.py": "def do_the_work(*a, **k): ..."})
        out = extract_py_module(pack, "mylib.run_cli")
        assert out["argparse"] == ["data_path", "--seed"]
        assert out["entry"] == {"function": "do_the_work", "defined_in": "mylib.core"}
        assert out["residue"] == []

    def test_inline_work_flags_module_body(self, tmp_path: Path) -> None:
        # a CLI that does the work itself (no first-party delegation) → the module
        # body is the entry, marked inline.
        body = ('import argparse\n'
                'def main():\n'
                '    p = argparse.ArgumentParser(); p.add_argument("x"); p.parse_args()\n'
                '    print("work done here")\n'
                'if __name__ == "__main__":\n    main()\n')
        pack = _make_pack(tmp_path / "p", tool_ts=TS_MODULE, lib={"run_cli.py": body})
        out = extract_py_module(pack, "mylib.run_cli")
        assert out["entry"]["inline"] is True


class TestDispatchResolution:
    def test_reaches_deployed_function(self, tmp_path: Path) -> None:
        modal_src = ('import modal\n'
                     'app = modal.App("my-app")\n'
                     '@app.function()\n'
                     'def crunch(payload):\n    return payload\n')
        cli = ('import modal\n'
               'def main():\n'
               '    fn = modal.Function.from_name("my-app", "crunch")\n'
               '    fn.remote(payload=1)\n'
               'if __name__ == "__main__":\n    main()\n')
        pack = _make_pack(tmp_path / "p", tool_ts=TS_MODULE,
                          lib={"run_cli.py": cli}, modal={"sampler.py": modal_src})
        d = resolve_dispatch(cli, pack)
        assert d is not None
        assert d["app"] == "my-app" and d["function"] == "crunch"
        assert d["defined_in"] == "docker/modal_app/sampler.py"
        assert d["resolved"] is True


# --------------------------------------------------------------------------- #
# integration — the real in-repo packs, one per shape
# --------------------------------------------------------------------------- #

class TestRealPacks:
    def test_mmm_is_mixed_with_local_and_remote(self) -> None:
        m = build_code_map(DPACKS / "mmm")
        assert m["shape"] == "mixed"
        tools = m["tools"]
        # a local module tool resolves to the library work function
        assert tools["analyze-model"]["entry"]["function"] == "analyze_mmm"
        assert tools["optimize-budget"]["entry"]["function"] == "budget_optimization"
        # the modal fit reaches THROUGH the dispatch to the deployed sampler body
        fit = tools["fit-model-modal"]
        assert fit["kind"] == "remote-dispatch"
        assert fit["entry"]["reached_through"] == "dispatch"
        assert fit["entry"]["defined_in"].endswith("modal_app/mmm_sampler.py")
        assert fit["dispatch"]["resolved"] is True
        assert "disclose" in fit
        # an inline python -c tool that calls a first-party function resolves it
        assert tools["inspect-data"]["entry"]["function"].startswith(
            "load_csv_or_parquet")

    def test_modal_example_is_modal_inline(self) -> None:
        m = build_code_map(DPACKS / "modal-example")
        assert m["shape"] == "modal-inline"
        rc = m["tools"]["run-on-modal"]
        assert rc["kind"] == "remote-dispatch"
        assert rc["entry"]["function"] == "run_compute"
        assert rc["entry"]["defined_in"].endswith("modal_app/example.py")

    def test_resolve_entry_code_returns_real_source(self) -> None:
        m = build_code_map(DPACKS / "mmm")
        # a local module tool -> the work function's verbatim source
        code = resolve_entry_code(DPACKS / "mmm", m["tools"]["analyze-model"]["entry"])
        assert code is not None and "def analyze_mmm" in code
        # the modal fit -> the DEPLOYED body, reached through the dispatch
        fit_code = resolve_entry_code(DPACKS / "mmm", m["tools"]["fit-model-modal"]["entry"])
        assert fit_code is not None and "def fit_mmm" in fit_code

    def test_resolve_entry_code_pulls_helper_functions(self) -> None:
        # the entry's figure/metric code lives in the helpers it calls, so those
        # must be resolved too — not just the level-2 entry body.
        m = build_code_map(DPACKS / "mmm")
        code = resolve_entry_code(DPACKS / "mmm", m["tools"]["analyze-model"]["entry"])
        assert "# helper:" in code                 # helpers were followed
        assert "savefig" in code                   # the real plotting code is present
        assert len(code) > len(                     # deeper than the entry alone
            (DPACKS / "mmm" / "docker" / "mmm_lib" / "analyze_model.py").read_text()
        ) / 4

    def test_poem_is_script_only(self) -> None:
        m = build_code_map(DPACKS / "poem")
        assert m["shape"] == "script-only"
        assert m["tools"] == {}

    def test_every_pack_builds_and_serializes(self) -> None:
        for pack in ("mmm", "modal-example", "poem", "event-forecaster"):
            m = build_code_map(DPACKS / pack)
            json.dumps(m)  # must be JSON-serializable
            assert set(m) == {"dpack", "shape", "tools", "sources"}


# --------------------------------------------------------------------------- #
# staleness via source checksums
# --------------------------------------------------------------------------- #

class TestStaleness:
    def _copy(self, tmp_path: Path, pack: str) -> Path:
        dst = tmp_path / pack
        shutil.copytree(DPACKS / pack, dst)
        return dst

    def test_no_map_yet(self, tmp_path: Path) -> None:
        dst = self._copy(tmp_path, "mmm")
        (dst / "code_map.json").unlink()  # a pack that was never mapped
        assert stale_sources(dst) == ["<no code_map.json>"]

    def test_committed_map_is_current(self, tmp_path: Path) -> None:
        # the in-repo map must match its sources (guards against a stale commit)
        dst = self._copy(tmp_path, "mmm")
        assert stale_sources(dst) == []

    def test_fresh_map_is_current(self, tmp_path: Path) -> None:
        dst = self._copy(tmp_path, "mmm")
        write_code_map(dst)
        assert stale_sources(dst) == []

    def test_mutated_source_is_flagged(self, tmp_path: Path) -> None:
        dst = self._copy(tmp_path, "mmm")
        write_code_map(dst)
        target = dst / "docker" / "mmm_lib" / "analyze_model.py"
        target.write_text(target.read_text() + "\n# changed\n")
        stale = stale_sources(dst)
        assert "docker/mmm_lib/analyze_model.py" in stale

    def test_write_code_map_roundtrips(self, tmp_path: Path) -> None:
        dst = self._copy(tmp_path, "modal-example")
        path = write_code_map(dst)
        assert path.name == "code_map.json"
        loaded = json.loads(path.read_text())
        assert loaded["shape"] == "modal-inline"
        assert loaded["sources"]  # non-empty checksum set
