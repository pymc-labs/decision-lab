"""
Tests for dlab.parallel_tool module.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from dlab.parallel_tool import PARALLEL_AGENTS_SOURCE

# Node built-in modules and OpenCode packages are safe for ESM named imports
_ALLOWED_ESM_NAMED_IMPORTS: set[str] = {
    "fs", "path", "os", "util", "url", "child_process", "crypto",
    "stream", "events", "http", "https", "net", "assert",
    "@opencode-ai/plugin",
}


class TestParallelAgentsSource:
    """Tests for PARALLEL_AGENTS_SOURCE loading."""

    def test_loads_successfully(self) -> None:
        """PARALLEL_AGENTS_SOURCE should be a non-empty string."""
        assert isinstance(PARALLEL_AGENTS_SOURCE, str)
        assert len(PARALLEL_AGENTS_SOURCE) > 0

    def test_contains_tool_export(self) -> None:
        """Should contain the tool description marker."""
        assert "Spawn parallel subagents" in PARALLEL_AGENTS_SOURCE

    def test_contains_key_functions(self) -> None:
        """Should contain key TypeScript functions from the source."""
        assert "copyWorkDir" in PARALLEL_AGENTS_SOURCE
        assert "setupConsolidator" in PARALLEL_AGENTS_SOURCE
        assert "buildPermissionsFromFrontmatter" in PARALLEL_AGENTS_SOURCE

    def test_matches_source_file(self) -> None:
        """Content should match the .ts file read directly from disk."""
        source_file: Path = Path(__file__).parent.parent / "dlab" / "js" / "parallel-agents.ts"
        expected: str = source_file.read_text()
        assert PARALLEL_AGENTS_SOURCE == expected

    def test_consolidator_can_write_its_summary(self) -> None:
        """The consolidator must be able to write consolidated_summary.md.

        opencode gates the write tool behind the "edit" permission key.
        Regression guard: with "edit" denied, the write tool silently
        disappears, the consolidator's output file is never created, and the
        orchestrator only ever sees the placeholder text — parallel runs then
        pay for a consolidator whose entire output is discarded.
        """
        consolidator_block: str = PARALLEL_AGENTS_SOURCE.split(
            "function setupConsolidator"
        )[1].split("function ")[0]
        assert '"edit": { "*": "allow" }' in consolidator_block
        assert '"edit": { "*": "deny" }' not in consolidator_block
        assert "write: true" in consolidator_block
        assert '"bash": { "*": "deny" }' in consolidator_block
        assert '"task": { "*": "deny" }' in consolidator_block

    def test_consolidator_opt_out_supported(self) -> None:
        """`consolidator: false` in a parallel agent YAML must skip the
        consolidation step (the orchestrator then reads per-instance
        summaries directly)."""
        assert "config.consolidator !== false" in PARALLEL_AGENTS_SOURCE

    def test_invalid_instance_models_fall_back(self) -> None:
        """Hallucinated model ids from the orchestrator (e.g. "gemini-pro"
        without a provider prefix) must fall back to the configured model
        instead of silently killing every instance — opencode dies with
        ProviderModelNotFoundError but still exits 0, so without this guard
        the whole fan-out fails invisibly."""
        assert 'ignored invalid model' in PARALLEL_AGENTS_SOURCE
        assert 'requestedModel.includes("/")' in PARALLEL_AGENTS_SOURCE
        # Missing summary.md must be surfaced as a failure signal
        assert "no summary.md produced" in PARALLEL_AGENTS_SOURCE

    def test_no_esm_named_imports_from_third_party(self) -> None:
        """Third-party packages must use default imports to avoid CJS/ESM issues.

        ESM named imports (import { x } from "pkg") break when the package
        is CommonJS. Node built-ins and @opencode-ai/* are safe.
        """
        pattern: re.Pattern[str] = re.compile(
            r'import\s*\{[^}]+\}\s*from\s*["\']([^"\']+)["\']'
        )
        for match in pattern.finditer(PARALLEL_AGENTS_SOURCE):
            pkg: str = match.group(1)
            assert pkg in _ALLOWED_ESM_NAMED_IMPORTS, (
                f"ESM named import from third-party package '{pkg}' — "
                f"use default import instead (import pkg from \"{pkg}\") "
                f"to avoid CJS/ESM interop issues"
            )


class TestYamlImportRuntime:
    """Verify that the yaml import in parallel-agents.ts works at runtime.

    Catches ESM/CJS interop issues that static analysis alone would miss.
    """

    @pytest.fixture
    def js_workspace(self, tmp_path: Path) -> Path:
        """Set up a temp workspace with yaml installed, mirroring session setup."""
        pkg: dict[str, object] = {"dependencies": {"yaml": "^2.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["npm", "install", "--silent"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            pytest.skip(f"npm install failed: {result.stderr}")
        return tmp_path

    def test_yaml_import_node(self, js_workspace: Path) -> None:
        """yaml import must resolve and parse() must work under Node."""
        # Extract just the yaml import line from our source
        import_lines: list[str] = [
            line for line in PARALLEL_AGENTS_SOURCE.splitlines()
            if "yaml" in line and ("import" in line or "require" in line)
        ]
        assert import_lines, "No yaml import found in parallel-agents.ts"

        # Build a minimal JS test that does what our .ts does
        test_js: str = (
            'const yaml = require("yaml");\n'
            'const result = yaml.parse("key: value");\n'
            'if (result.key !== "value") { process.exit(1); }\n'
            'console.log("ok");\n'
        )
        test_file: Path = js_workspace / "test_yaml.js"
        test_file.write_text(test_js)

        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["node", str(test_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"yaml require() failed under Node:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_yaml_import_docker(self, js_workspace: Path) -> None:
        """yaml import must work inside a Docker container (closer to production)."""
        test_js: str = (
            'const yaml = require("yaml");\n'
            'const result = yaml.parse("key: value");\n'
            'if (result.key !== "value") { process.exit(1); }\n'
            'console.log("ok");\n'
        )
        test_file: Path = js_workspace / "test_yaml.js"
        test_file.write_text(test_js)

        result: subprocess.CompletedProcess[str] = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{js_workspace}:/app",
                "-w", "/app",
                "node:20-slim",
                "node", "test_yaml.js",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"yaml require() failed inside Docker (node:20-slim):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_import_style_matches_source(self) -> None:
        """The yaml import in parallel-agents.ts must use require(), not ESM import."""
        assert 'require("yaml")' in PARALLEL_AGENTS_SOURCE, (
            "parallel-agents.ts must use require('yaml') for CJS/ESM compatibility"
        )
