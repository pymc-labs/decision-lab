"""
Tests for opening artifacts externally (issues #57, #62).

Artifact filenames are agent-controlled; opening them must never route
through a shell. These tests guard the fix without actually launching
system viewers.
"""

from pathlib import Path

from dlab.tui.widgets.artifacts_pane import open_file_externally

TUI_DIR = Path(__file__).parent.parent / "dlab" / "tui"


class TestOpenFileExternally:
    def test_none_path_returns_false(self) -> None:
        assert open_file_externally(None) is False

    def test_missing_path_returns_false(self, tmp_path: Path) -> None:
        assert open_file_externally(tmp_path / "does-not-exist.md") is False

    def test_missing_path_with_shell_metacharacters_returns_false(
        self, tmp_path: Path
    ) -> None:
        # A hostile artifact name must be treated as a plain path — here it
        # doesn't exist, so no opener may be spawned at all.
        hostile = tmp_path / "report & echo pwned.md"
        assert open_file_externally(hostile) is False


class TestNoShellInTui:
    def test_no_shell_true_anywhere_in_tui(self) -> None:
        """Regression guard for #57: no subprocess call in the TUI may use
        shell=True — artifact names are agent-controlled input."""
        offenders: list[str] = []
        for py in TUI_DIR.rglob("*.py"):
            if "shell=True" in py.read_text():
                offenders.append(str(py))
        assert not offenders, f"shell=True found in: {offenders}"

    def test_windows_path_uses_startfile(self) -> None:
        """Windows must use os.startfile (no cmd.exe), not `start`."""
        source: str = (TUI_DIR / "widgets" / "artifacts_pane.py").read_text()
        assert "os.startfile" in source
        assert '"start"' not in source

    def test_single_open_helper_is_used(self) -> None:
        """Regression guard for #62: exactly one place spawns openers."""
        source: str = (TUI_DIR / "widgets" / "artifacts_pane.py").read_text()
        assert source.count('subprocess.Popen(["open"') == 1
        assert source.count('subprocess.Popen(["xdg-open"') == 1
