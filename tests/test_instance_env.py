"""
Tests for the parallel-instance environment allowlist (issue #56).

Subagents must receive a curated environment, not the full host env.
dlab writes the authoritative allowlist; parallel-agents.ts filters
process.env against it. These tests cover the Python (writer/setup) side
and a Node runtime check of the TS filtering logic.
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from dlab.parallel_tool import PARALLEL_AGENTS_SOURCE
from dlab.session import (
    INSTANCE_ENV_EXACT,
    setup_opencode_config,
    write_instance_env_allowlist,
)

REPO = Path(__file__).parent.parent


class TestAllowlistWriter:
    def test_writer_includes_operational_and_provider_vars(
        self, tmp_path: Path
    ) -> None:
        opencode = tmp_path / ".opencode"
        opencode.mkdir()
        write_instance_env_allowlist(opencode)
        allow = json.loads(
            (opencode / "instance-env-allowlist.json").read_text()
        )
        # operational
        assert "PATH" in allow["exact"]
        assert "PYTHONPATH" in allow["exact"]
        # provider credentials (from bundled models.dev list) — several families
        assert "ANTHROPIC_API_KEY" in allow["exact"]
        assert "GEMINI_API_KEY" in allow["exact"]
        assert "OPENAI_API_KEY" in allow["exact"]
        assert "AWS_SECRET_ACCESS_KEY" in allow["exact"]  # non _API_KEY name
        # prefixes for dlab/opencode config + cloud families
        assert "DLAB_" in allow["prefixes"]
        assert "OPENCODE_" in allow["prefixes"]

    def test_writer_excludes_ambient_host_junk(self, tmp_path: Path) -> None:
        opencode = tmp_path / ".opencode"
        opencode.mkdir()
        write_instance_env_allowlist(opencode)
        allow = json.loads(
            (opencode / "instance-env-allowlist.json").read_text()
        )
        for junk in ("HISTFILE", "SSH_AUTH_SOCK", "MY_BANK_PASSWORD"):
            assert junk not in allow["exact"]
        # No prefix should match generic shell/secret junk either.
        assert not any("HIST".startswith(p) for p in allow["prefixes"])


class TestSetupWritesAllowlist:
    def test_setup_opencode_config_emits_allowlist_for_parallel_pack(
        self, tmp_path: Path
    ) -> None:
        """A pack with parallel_agents/ must get the allowlist during setup,
        next to the generated parallel-agents.ts."""
        poem = REPO / "decision-packs" / "poem"
        if not poem.exists():
            pytest.skip("poem decision-pack not present")
        wd = tmp_path / "work"
        wd.mkdir()
        setup_opencode_config(
            config_dir=str(poem),
            work_dir=str(wd),
            orchestrator_model="google/gemini-2.5-flash",
        )
        allow_file = wd / ".opencode" / "instance-env-allowlist.json"
        ts_file = wd / ".opencode" / "tools" / "parallel-agents.ts"
        assert ts_file.exists(), "parallel-agents.ts not generated"
        assert allow_file.exists(), "allowlist not written alongside the tool"


class TestSourceUsesCuratedEnv:
    def test_no_bare_process_env_passed_to_spawn(self) -> None:
        """Regression guard for #56: instances/consolidator must not be
        spawned with the full host environment."""
        assert "env: process.env" not in PARALLEL_AGENTS_SOURCE
        assert PARALLEL_AGENTS_SOURCE.count("env: buildInstanceEnv(cwd)") == 2

    def test_builder_reads_the_allowlist(self) -> None:
        assert "function buildInstanceEnv" in PARALLEL_AGENTS_SOURCE
        assert "instance-env-allowlist.json" in PARALLEL_AGENTS_SOURCE


class TestBuildInstanceEnvRuntime:
    """Run the ACTUAL buildInstanceEnv logic (sliced from source, TS types
    stripped) under Node against a hostile environment."""

    def _extract_js(self) -> str:
        src = PARALLEL_AGENTS_SOURCE
        start = src.index("const FALLBACK_ENV_EXACT")
        end = src.index("\n}", src.index("function buildInstanceEnv")) + 2
        block = src[start:end]
        # Strip the few TS annotations present in this block.
        block = block.replace(
            "function buildInstanceEnv(cwd: string): Record<string, string>",
            "function buildInstanceEnv(cwd)",
        )
        block = block.replace(
            "const out: Record<string, string> = {}", "const out = {}"
        )
        block = block.replace("(p: string)", "(p)")
        return block

    def test_filters_hostile_env(self, tmp_path: Path) -> None:
        if not _have_node():
            pytest.skip("node not available")
        opencode = tmp_path / ".opencode"
        opencode.mkdir()
        write_instance_env_allowlist(opencode)

        driver = f"""
const {{ readFileSync }} = require("fs");
const {{ join }} = require("path");
{self._extract_js()}
process.env.ANTHROPIC_API_KEY = "sk-real";
process.env.GEMINI_API_KEY = "g-real";
process.env.DLAB_FIT_MODEL_LOCALLY = "1";
process.env.PYTHONPATH = "/opt";
process.env.MY_BANK_PASSWORD = "leak-me";
process.env.HISTFILE = "/home/x/.zsh_history";
const env = buildInstanceEnv({json.dumps(str(tmp_path))});
const has = k => Object.prototype.hasOwnProperty.call(env, k);
const ok = has("ANTHROPIC_API_KEY") && has("GEMINI_API_KEY")
  && has("DLAB_FIT_MODEL_LOCALLY") && has("PYTHONPATH")
  && !has("MY_BANK_PASSWORD") && !has("HISTFILE");
process.exit(ok ? 0 : 1);
"""
        js = tmp_path / "driver.js"
        js.write_text(driver)
        result = subprocess.run(
            ["node", str(js)], capture_output=True, text=True, timeout=15
        )
        assert result.returncode == 0, (
            f"buildInstanceEnv did not filter correctly\n{result.stderr}"
        )


def _have_node() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
