"""
Tests for opening artifacts externally (issues #57, #62).

Artifact filenames are agent-controlled; opening them must never route
through a shell. The behavioral tests below spawn a REAL fake opener (a
recording shim placed on PATH) rather than mocking subprocess, per the
project's no-mocks policy — so they exercise the actual spawn path and
prove the filename arrives as one intact argument with no shell parsing.
"""

import os
import sys

import pytest

from pathlib import Path

from dlab.tui.widgets.artifacts_pane import open_file_externally

TUI_DIR = Path(__file__).parent.parent / "dlab" / "tui"


@pytest.fixture
def fake_opener(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a recording `xdg-open` (and `open`) shim first on PATH.

    monkeypatch here only edits the PATH env var and argv-recording target
    — no library call is patched; the helper really execs the shim.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "argv.txt"
    shim = "#!/bin/sh\n" f'printf "%s\\n" "$@" > "{record}"\n'
    for name in ("xdg-open", "open"):
        p = bindir / name
        p.write_text(shim)
        p.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return record


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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX opener shim; Windows uses os.startfile (no argv to record)",
)
class TestSpawnPassesFilenameSafely:
    """Behavioral tests: the real spawn path receives the filename as one
    intact argument, with shell metacharacters inert (issue #57)."""

    def test_plain_file_passed_as_single_arg(
        self, tmp_path: Path, fake_opener: Path
    ) -> None:
        f = tmp_path / "report.md"
        f.write_text("x")
        assert open_file_externally(f) is True
        # Wait for the detached shim to write its record.
        import time
        for _ in range(50):
            if fake_opener.exists():
                break
            time.sleep(0.02)
        recorded = fake_opener.read_text().splitlines()
        assert recorded == [str(f)]

    def test_hostile_filename_is_inert_single_arg(
        self, tmp_path: Path, fake_opener: Path
    ) -> None:
        # The classic injection payload as a real, existing filename.
        f = tmp_path / "report & touch PWNED.md"
        f.write_text("x")
        assert open_file_externally(f) is True
        import time
        for _ in range(50):
            if fake_opener.exists():
                break
            time.sleep(0.02)
        recorded = fake_opener.read_text().splitlines()
        # Exactly one argument — the whole name — not split on the shell '&'.
        assert recorded == [str(f)]
        # And the injected side effect never happened.
        assert not (tmp_path / "PWNED").exists()


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
