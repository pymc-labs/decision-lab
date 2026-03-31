"""
Tests for dlab.parallel_tool module.
"""

from pathlib import Path

from dlab.parallel_tool import PARALLEL_AGENTS_SOURCE


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
