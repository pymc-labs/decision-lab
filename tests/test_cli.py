"""
Tests for dlab.cli module.
"""

import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from dlab.cli import app, cmd_connect, cmd_install, cmd_run

runner = CliRunner()


class TestTyperApp:
    """Replaces TestCreateParser — tests the Typer app object."""

    def test_app_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "dlab" in result.output

    def test_run_mode_options_appear_in_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert "--dpack" in result.output
        assert "--data" in result.output
        assert "--prompt" in result.output
        assert "--no-sandboxing" in result.output

    def test_install_help(self) -> None:
        result = runner.invoke(app, ["install", "--help"])
        assert result.exit_code == 0
        assert "--bin-dir" in result.output

    def test_connect_help(self) -> None:
        result = runner.invoke(app, ["connect", "--help"])
        assert result.exit_code == 0
        assert "WORK_DIR" in result.output
        assert "--log" in result.output
        assert "--log-json" in result.output

    def test_create_parallel_agent_help(self) -> None:
        result = runner.invoke(app, ["create-parallel-agent", "--help"])
        assert result.exit_code == 0

    def test_create_dpack_help(self) -> None:
        result = runner.invoke(app, ["create-dpack", "--help"])
        assert result.exit_code == 0
        assert "OUTPUT_DIR" in result.output

    def test_no_args_prints_help(self) -> None:
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "dlab" in result.output

    def test_data_repeated_flag(self) -> None:
        # exit 1 (invalid dpack) is fine; exit 2 means a parse error
        result = runner.invoke(
            app,
            [
                "--dpack",
                "/nonexistent",
                "--data",
                "/path/a",
                "--data",
                "/path/b",
                "--prompt",
                "test",
            ],
        )
        assert result.exit_code != 2


class TestCmdRun:
    """Tests for cmd_run function."""

    def test_missing_dpack(self) -> None:
        """Should fail if --dpack is missing."""
        result: int = cmd_run(data=["/path"], prompt="test")
        assert result == 1

    def test_missing_data(self, dpack_config_dir: Path) -> None:
        """Should fail if --data is missing."""
        result: int = cmd_run(dpack=str(dpack_config_dir), prompt="test")
        assert result == 1

    def test_missing_prompt(self, dpack_config_dir: Path, data_dir: Path) -> None:
        """Should fail if neither --prompt nor --prompt-file is provided."""
        result: int = cmd_run(dpack=str(dpack_config_dir), data=[str(data_dir)])
        assert result == 1

    def test_missing_prompt_ok_when_not_required(
        self,
        dpack_config_dir: Path,
        data_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should not fail on missing prompt when requires_prompt is false."""
        config_path: Path = dpack_config_dir / "config.yaml"
        import yaml

        with open(config_path) as f:
            config = yaml.safe_load(f)
        config["requires_prompt"] = False
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        result: int = cmd_run(
            dpack=str(dpack_config_dir),
            data=[str(data_dir)],
            work_dir=str(tmp_path / "work"),
        )
        captured = capsys.readouterr()
        assert "--prompt" not in captured.err

    def test_both_prompt_args(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path
    ) -> None:
        """Should fail if both --prompt and --prompt-file are provided."""
        prompt_file: Path = tmp_path / "prompt.md"
        prompt_file.write_text("file prompt")

        result: int = cmd_run(
            dpack=str(dpack_config_dir),
            data=[str(data_dir)],
            prompt="inline prompt",
            prompt_file=str(prompt_file),
        )
        assert result == 1

    def test_nonexistent_prompt_file(
        self, dpack_config_dir: Path, data_dir: Path
    ) -> None:
        """Should fail if --prompt-file does not exist."""
        result: int = cmd_run(
            dpack=str(dpack_config_dir),
            data=[str(data_dir)],
            prompt_file="/nonexistent/prompt.md",
        )
        assert result == 1

    def test_invalid_dpack(self, data_dir: Path, tmp_path: Path) -> None:
        """Should fail if decision-pack directory is invalid."""
        result: int = cmd_run(
            dpack=str(tmp_path / "nonexistent"),
            data=[str(data_dir)],
            prompt="test",
        )
        assert result == 1

    def test_invalid_data_dir(self, dpack_config_dir: Path, tmp_path: Path) -> None:
        """Should fail if data directory does not exist."""
        result: int = cmd_run(
            dpack=str(dpack_config_dir),
            data=[str(tmp_path / "nonexistent")],
            prompt="test",
            work_dir=str(tmp_path / "work"),
        )
        assert result == 1

    def test_successful_run(
        self,
        dpack_config_dir: Path,
        data_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Run should create session, start container, and run opencode."""
        result: int = cmd_run(
            dpack=str(dpack_config_dir),
            data=[str(data_dir)],
            prompt="test prompt",
            work_dir=str(tmp_path / "work"),
        )
        # opencode runs but fails (no API key / invalid model) — exit code 0
        assert result == 0

        captured = capsys.readouterr()
        assert "Session:" in captured.out
        assert "test-dpack" in captured.out
        assert "Container started:" in captured.out
        assert "dlab connect" in captured.out
        assert "dlab timeline" in captured.out
        assert "Stopping container" in captured.out

    def test_run_with_prompt_file(
        self,
        dpack_config_dir: Path,
        data_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should read prompt from file and run the full flow."""
        prompt_file: Path = tmp_path / "prompt.md"
        prompt_file.write_text("prompt from file")

        result: int = cmd_run(
            dpack=str(dpack_config_dir),
            data=[str(data_dir)],
            prompt_file=str(prompt_file),
            work_dir=str(tmp_path / "work"),
        )
        # opencode runs but fails (no API key) — exit code 0
        assert result == 0

    def test_run_uses_default_model(
        self,
        dpack_config_dir: Path,
        data_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should use default_model from config if --model not provided."""
        result: int = cmd_run(
            dpack=str(dpack_config_dir),
            data=[str(data_dir)],
            prompt="test",
            work_dir=str(tmp_path / "work"),
        )
        assert result == 0

        captured = capsys.readouterr()
        assert "anthropic/claude-sonnet-4-0" in captured.out

    def test_run_uses_override_model(
        self,
        dpack_config_dir: Path,
        data_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should use --model if provided."""
        result: int = cmd_run(
            dpack=str(dpack_config_dir),
            data=[str(data_dir)],
            prompt="test",
            model="anthropic/claude-opus-4-0",
            work_dir=str(tmp_path / "work"),
        )
        assert result == 0

    def test_no_env_file_warning(
        self,
        dpack_config_dir: Path,
        data_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should error when no --env-file and no .env in decision-pack."""
        # Remove .env so preflight catches missing orchestrator key
        env_path: Path = dpack_config_dir / ".env"
        if env_path.exists():
            env_path.unlink()
        result: int = cmd_run(
            dpack=str(dpack_config_dir),
            data=[str(data_dir)],
            prompt="test",
            work_dir=str(tmp_path / "work"),
        )
        assert result == 1
        captured = capsys.readouterr()
        assert "requires an API key" in captured.out

    def test_env_file_autodetect_no_warning(
        self,
        dpack_config_dir: Path,
        data_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should not warn when .env exists in decision-pack (auto-detected)."""
        (dpack_config_dir / ".env").write_text("SOME_KEY=value\n")

        cmd_run(
            dpack=str(dpack_config_dir),
            data=[str(data_dir)],
            prompt="test",
            work_dir=str(tmp_path / "work"),
        )
        captured = capsys.readouterr()
        assert "No --env-file provided" not in captured.out


class TestErrorMessages:
    """Tests for user-friendly error messages."""

    def test_docker_not_available_message(
        self,
        dpack_config_dir: Path,
        data_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should show friendly Docker error with --no-sandboxing hint."""
        import unittest.mock

        with unittest.mock.patch("dlab.local.is_docker_available", return_value=False):
            result: int = cmd_run(
                dpack=str(dpack_config_dir),
                data=[str(data_dir)],
                prompt="test",
                work_dir=str(tmp_path / "work"),
            )
        assert result == 1
        captured = capsys.readouterr()
        assert "Docker daemon" in captured.err
        assert "--no-sandboxing" in captured.err
        assert "Warning" in captured.err

    def test_work_dir_exists_message(
        self,
        dpack_config_dir: Path,
        data_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should show friendly work-dir-exists error with rm hint."""
        existing: Path = tmp_path / "work"
        existing.mkdir()
        result: int = cmd_run(
            dpack=str(dpack_config_dir),
            data=[str(data_dir)],
            prompt="test",
            work_dir=str(existing),
        )
        assert result == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.out
        assert "rm -rf" in captured.out


class TestContinueDir:
    """Tests for --continue-dir functionality in both Docker and local modes."""

    @pytest.fixture
    def previous_session(
        self,
        dpack_config_dir: Path,
        data_dir: Path,
        tmp_path: Path,
    ) -> Path:
        """Create a completed session to continue from."""
        from dlab.config import load_dpack_config
        from dlab.session import create_session

        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        state: dict[str, Any] = create_session(
            config,
            str(data_dir),
            work_dir=str(tmp_path / "prev-session"),
        )
        return Path(state["work_dir"])

    def _run_continue(
        self,
        dpack_dir: Path,
        continue_dir: Path,
        work_dir: Path | None = None,
        prompt: str = "continue",
        no_sandboxing: bool = False,
        data: list[str] | None = None,
    ) -> int:
        """Helper to run cmd_run in continue mode, mocking agent execution."""
        mock_return = (0, "", "")
        with (
            patch("dlab.cli.run_opencode", return_value=mock_return),
            patch("dlab.local.run_opencode_local", return_value=mock_return),
        ):
            return cmd_run(
                dpack=str(dpack_dir),
                continue_dir=str(continue_dir),
                prompt=prompt,
                work_dir=str(work_dir) if work_dir else None,
                no_sandboxing=no_sandboxing,
                data=data,
            )

    # --- Error handling (no mode needed, errors before execution) ---

    def test_continue_nonexistent_dir(
        self,
        dpack_config_dir: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should error cleanly when continue-dir doesn't exist."""
        result: int = self._run_continue(
            dpack_config_dir,
            Path("/nonexistent/dir"),
        )
        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_continue_with_data_rejected(
        self,
        dpack_config_dir: Path,
        data_dir: Path,
        previous_session: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should reject --data combined with --continue-dir."""
        result: int = cmd_run(
            dpack=str(dpack_config_dir),
            continue_dir=str(previous_session),
            data=[str(data_dir)],
            prompt="continue",
        )
        assert result == 1

    def test_continue_workdir_exists_error(
        self,
        dpack_config_dir: Path,
        previous_session: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should error when --work-dir already exists in continue mode."""
        existing: Path = tmp_path / "already-here"
        existing.mkdir()
        result: int = self._run_continue(
            dpack_config_dir,
            previous_session,
            work_dir=existing,
            no_sandboxing=True,
        )
        assert result == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.out

    # --- Local mode (--no-sandboxing) ---

    def test_local_continue_to_new_workdir(
        self,
        dpack_config_dir: Path,
        previous_session: Path,
        tmp_path: Path,
    ) -> None:
        """Local: --continue-dir + --work-dir should copy session."""
        new_dir: Path = tmp_path / "local-continued"
        self._run_continue(
            dpack_config_dir,
            previous_session,
            work_dir=new_dir,
            no_sandboxing=True,
        )
        assert new_dir.exists()
        assert (new_dir / "data").exists()
        assert (new_dir / ".opencode").exists()
        assert (new_dir / "_opencode_logs").exists()

    def test_local_continue_refreshes_opencode(
        self,
        dpack_config_dir: Path,
        previous_session: Path,
        tmp_path: Path,
    ) -> None:
        """Local: continue should refresh .opencode/ from decision-pack."""
        new_dir: Path = tmp_path / "local-refreshed"
        marker: Path = previous_session / ".opencode" / "STALE_MARKER"
        marker.write_text("this should be gone after continue")

        self._run_continue(
            dpack_config_dir,
            previous_session,
            work_dir=new_dir,
            no_sandboxing=True,
        )
        assert not (new_dir / ".opencode" / "STALE_MARKER").exists()
        assert (new_dir / ".opencode").exists()

    def test_local_continue_refreshes_hooks(
        self,
        dpack_config_dir: Path,
        previous_session: Path,
        tmp_path: Path,
    ) -> None:
        """Local: continue should refresh hook scripts."""
        new_dir: Path = tmp_path / "local-hooks"
        hooks_dir: Path = previous_session / "_hooks"
        hooks_dir.mkdir(exist_ok=True)
        (hooks_dir / "old_hook.sh").write_text("stale")

        self._run_continue(
            dpack_config_dir,
            previous_session,
            work_dir=new_dir,
            no_sandboxing=True,
        )
        assert not (new_dir / "_hooks" / "old_hook.sh").exists()

    def test_local_continue_preserves_data(
        self,
        dpack_config_dir: Path,
        previous_session: Path,
        tmp_path: Path,
    ) -> None:
        """Local: continue should preserve data from original session."""
        new_dir: Path = tmp_path / "local-preserved"
        self._run_continue(
            dpack_config_dir,
            previous_session,
            work_dir=new_dir,
            no_sandboxing=True,
        )
        assert (new_dir / "data" / "sample.csv").exists()
        assert (new_dir / "data" / "subdir" / "nested.txt").exists()

    # --- Docker mode ---

    def test_docker_continue_to_new_workdir(
        self,
        dpack_config_dir: Path,
        previous_session: Path,
        tmp_path: Path,
    ) -> None:
        """Docker: --continue-dir + --work-dir should copy session."""
        new_dir: Path = tmp_path / "docker-continued"
        self._run_continue(
            dpack_config_dir,
            previous_session,
            work_dir=new_dir,
        )
        assert new_dir.exists()
        assert (new_dir / "data").exists()
        assert (new_dir / ".opencode").exists()
        assert (new_dir / "_opencode_logs").exists()

    def test_docker_continue_refreshes_opencode(
        self,
        dpack_config_dir: Path,
        previous_session: Path,
        tmp_path: Path,
    ) -> None:
        """Docker: continue should refresh .opencode/ from decision-pack."""
        new_dir: Path = tmp_path / "docker-refreshed"
        marker: Path = previous_session / ".opencode" / "STALE_MARKER"
        marker.write_text("this should be gone after continue")

        self._run_continue(
            dpack_config_dir,
            previous_session,
            work_dir=new_dir,
        )
        assert not (new_dir / ".opencode" / "STALE_MARKER").exists()
        assert (new_dir / ".opencode").exists()

    def test_docker_continue_preserves_data(
        self,
        dpack_config_dir: Path,
        previous_session: Path,
        tmp_path: Path,
    ) -> None:
        """Docker: continue should preserve data from original session."""
        new_dir: Path = tmp_path / "docker-preserved"
        self._run_continue(
            dpack_config_dir,
            previous_session,
            work_dir=new_dir,
        )
        assert (new_dir / "data" / "sample.csv").exists()
        assert (new_dir / "data" / "subdir" / "nested.txt").exists()


class TestCmdInstall:
    """Tests for cmd_install function."""

    def test_invalid_dpack_path(self, tmp_path: Path) -> None:
        """Should fail if decision-pack path is invalid."""
        result: int = cmd_install(dpack_path=str(tmp_path / "nonexistent"))
        assert result == 1

    def test_creates_wrapper_script(
        self, dpack_config_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should create executable wrapper script."""
        bin_dir: Path = tmp_path / "bin"
        result: int = cmd_install(
            dpack_path=str(dpack_config_dir), bin_dir=str(bin_dir)
        )
        assert result == 0

        wrapper_path: Path = bin_dir / "test-dpack"
        assert wrapper_path.exists()

        mode: int = wrapper_path.stat().st_mode
        assert mode & stat.S_IXUSR

        content: str = wrapper_path.read_text()
        assert "dlab" in content
        assert "--dpack" in content
        assert str(dpack_config_dir.resolve()) in content

    def test_creates_bin_dir_if_missing(
        self, dpack_config_dir: Path, tmp_path: Path
    ) -> None:
        """Should create bin directory if it doesn't exist."""
        bin_dir: Path = tmp_path / "new" / "bin" / "path"
        result: int = cmd_install(
            dpack_path=str(dpack_config_dir), bin_dir=str(bin_dir)
        )
        assert result == 0

        assert bin_dir.exists()
        assert (bin_dir / "test-dpack").exists()

    def test_prints_path_warning(
        self, dpack_config_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn if bin_dir not in PATH."""
        bin_dir: Path = tmp_path / "not_in_path"
        result: int = cmd_install(
            dpack_path=str(dpack_config_dir), bin_dir=str(bin_dir)
        )
        assert result == 0

        captured = capsys.readouterr()
        assert "may not be in your PATH" in captured.out


class TestCmdConnect:
    """Tests for cmd_connect function."""

    def test_invalid_session_dir(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Connect should fail if directory has no _opencode_logs."""
        result: int = cmd_connect(work_dir=str(tmp_path))
        assert result == 1

        captured = capsys.readouterr()
        assert "No logs directory found" in captured.err


class TestCLIIntegration:
    """Integration tests for CLI entry point."""

    def test_help_output(self) -> None:
        """CLI should show help without error."""
        result = subprocess.run(
            [sys.executable, "-m", "dlab.cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "dlab" in result.stdout

    def test_install_help(self) -> None:
        """Install subcommand should show help."""
        result = subprocess.run(
            [sys.executable, "-m", "dlab.cli", "install", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "decision-pack" in result.stdout.lower()

    def test_connect_help(self) -> None:
        """Connect subcommand should show help."""
        result = subprocess.run(
            [sys.executable, "-m", "dlab.cli", "connect", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "WORK_DIR" in result.stdout

    def test_create_parallel_agent_help(self) -> None:
        """Create-parallel-agent subcommand should show help."""
        result = subprocess.run(
            [sys.executable, "-m", "dlab.cli", "create-parallel-agent", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "DPACK_DIR" in result.stdout

    def test_unknown_flag_suggests_close_match(self) -> None:
        """Misspelled flag should suggest the correct one."""
        result = subprocess.run(
            [sys.executable, "-m", "dlab.cli", "--dpak", "/tmp"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "--dpack" in result.stderr

    def test_unknown_subcommand_suggests_close_match(self) -> None:
        """Misspelled subcommand should suggest the correct one."""
        result = subprocess.run(
            [sys.executable, "-m", "dlab.cli", "instal", "/tmp"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "install" in result.stderr

    def test_unknown_flag_exit_code(self) -> None:
        """Unknown arguments should exit with code 2."""
        result = subprocess.run(
            [sys.executable, "-m", "dlab.cli", "--zzzzzzz"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "--zzzzzzz" in result.stderr

    def test_one_bad_flag_only_reports_that_flag(self) -> None:
        """A single misspelled flag should not cause all other flags to be reported as unknown."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "dlab.cli",
                "--dpack",
                "foo",
                "--data",
                "bar",
                "--prompt",
                "hello",
                "--workdir",
                "out",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "--work-dir" in result.stderr
        # The valid flags should NOT appear as unknown
        assert "No such option: --dpack" not in result.stderr
        assert "No such option: --data" not in result.stderr
        assert "No such option: --prompt" not in result.stderr
