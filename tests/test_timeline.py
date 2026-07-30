"""Tests for dlab.timeline module."""

from pathlib import Path

import pytest

from dlab.timeline import build_timeline


class TestBuildTimeline:
    """Tests for build_timeline."""

    def test_empty_log_dir(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return empty dict when no log files exist."""
        result = build_timeline(tmp_path, is_running=False)
        assert result == {}
        captured = capsys.readouterr()
        assert "No .log files found" in captured.err

    def test_all_empty_log_files(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return empty dict when all log files are empty (#1)."""
        (tmp_path / "agent1.log").write_text("")
        (tmp_path / "agent2.log").write_text("")
        result = build_timeline(tmp_path, is_running=False)
        assert result == {}
        captured = capsys.readouterr()
        assert "All .log files" in captured.err
        assert "are empty" in captured.err
