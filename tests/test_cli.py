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

from dlab.cli import (
    cmd_connect,
    cmd_install,
    cmd_run,
    create_parser,
)


class TestCreateParser:
    """Tests for create_parser function."""

    def test_parser_creation(self) -> None:
        """Parser should be created without errors."""
        parser = create_parser()
        assert parser is not None
        assert parser.prog == "dlab"

    def test_run_mode_args(self) -> None:
        """Parser should accept run mode arguments."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", "/path/to/dpack",
            "--data", "/path/to/data",
            "--prompt", "test prompt",
        ])
        assert args.dpack == "/path/to/dpack"
        assert args.data == ["/path/to/data"]
        assert args.prompt == "test prompt"

    def test_data_multiple_paths(self) -> None:
        """Parser should accept multiple --data paths."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", "/path/to/dpack",
            "--data", "/path/a", "/path/b", "/path/c",
            "--prompt", "test",
        ])
        assert args.data == ["/path/a", "/path/b", "/path/c"]

    def test_run_mode_with_model(self) -> None:
        """Parser should accept --model argument."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", "/path/to/dpack",
            "--data", "/path/to/data",
            "--prompt", "test",
            "--model", "anthropic/claude-opus-4-0",
        ])
        assert args.model == "anthropic/claude-opus-4-0"

    def test_run_mode_with_prompt_file(self) -> None:
        """Parser should accept --prompt-file argument."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", "/path/to/dpack",
            "--data", "/path/to/data",
            "--prompt-file", "/path/to/prompt.md",
        ])
        assert args.prompt_file == "/path/to/prompt.md"

    def test_run_mode_with_work_dir(self) -> None:
        """Parser should accept --work-dir argument."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", "/path/to/dpack",
            "--data", "/path/to/data",
            "--prompt", "test",
            "--work-dir", "/path/to/work",
        ])
        assert args.work_dir == "/path/to/work"

    def test_run_mode_with_env_file(self) -> None:
        """Parser should accept --env-file argument."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", "/path/to/dpack",
            "--data", "/path/to/data",
            "--prompt", "test",
            "--env-file", "/path/to/env/file",
        ])
        assert args.env_file == "/path/to/env/file"

    def test_install_subcommand(self) -> None:
        """Parser should handle install subcommand."""
        parser = create_parser()
        args = parser.parse_args(["install", "/path/to/dpack"])
        assert args.command == "install"
        assert args.dpack_path == "/path/to/dpack"

    def test_install_with_bin_dir(self) -> None:
        """Parser should accept --bin-dir for install."""
        parser = create_parser()
        args = parser.parse_args([
            "install", "/path/to/dpack",
            "--bin-dir", "/custom/bin",
        ])
        assert args.bin_dir == "/custom/bin"

    def test_connect_subcommand(self) -> None:
        """Parser should handle connect subcommand."""
        parser = create_parser()
        args = parser.parse_args(["connect", "/path/to/work"])
        assert args.command == "connect"
        assert args.work_dir == "/path/to/work"

    def test_connect_with_log(self) -> None:
        """Parser should accept --log for connect."""
        parser = create_parser()
        args = parser.parse_args(["connect", "/path/to/work", "--log"])
        assert args.log is True

    def test_connect_with_log_json(self) -> None:
        """Parser should accept --log-json for connect."""
        parser = create_parser()
        args = parser.parse_args(["connect", "/path/to/work", "--log-json"])
        assert args.log_json is True

    def test_create_parallel_agent_subcommand(self) -> None:
        """Parser should handle create-parallel-agent subcommand."""
        parser = create_parser()
        args = parser.parse_args(["create-parallel-agent", "/path/to/dpack"])
        assert args.command == "create-parallel-agent"
        assert args.dpack == "/path/to/dpack"

    def test_create_parallel_agent_default_dir(self) -> None:
        """Parser should default to current directory for create-parallel-agent."""
        parser = create_parser()
        args = parser.parse_args(["create-parallel-agent"])
        assert args.dpack == "."

    def test_create_dpack_help(self) -> None:
        """Create-dpack subcommand should show help."""
        result = subprocess.run(
            [sys.executable, "-m", "dlab.cli", "create-dpack", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "OUTPUT_DIR" in result.stdout


class TestCmdRun:
    """Tests for cmd_run function."""

    def test_missing_dpack(self) -> None:
        """Should fail if --dpack is missing."""
        parser = create_parser()
        args = parser.parse_args(["--data", "/path", "--prompt", "test"])
        result: int = cmd_run(args)
        assert result == 1

    def test_missing_data(self, dpack_config_dir: Path) -> None:
        """Should fail if --data is missing."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--prompt", "test",
        ])
        result: int = cmd_run(args)
        assert result == 1

    def test_missing_prompt(self, dpack_config_dir: Path, data_dir: Path) -> None:
        """Should fail if neither --prompt nor --prompt-file is provided."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
        ])
        result: int = cmd_run(args)
        assert result == 1

    def test_missing_prompt_ok_when_not_required(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should not fail on missing prompt when requires_prompt is false."""
        config_path: Path = dpack_config_dir / "config.yaml"
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config["requires_prompt"] = False
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
            "--work-dir", str(tmp_path / "work"),
        ])
        result: int = cmd_run(args)
        captured = capsys.readouterr()
        assert "--prompt" not in captured.err

    def test_both_prompt_args(self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path) -> None:
        """Should fail if both --prompt and --prompt-file are provided."""
        prompt_file: Path = tmp_path / "prompt.md"
        prompt_file.write_text("file prompt")

        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
            "--prompt", "inline prompt",
            "--prompt-file", str(prompt_file),
        ])
        result: int = cmd_run(args)
        assert result == 1

    def test_nonexistent_prompt_file(self, dpack_config_dir: Path, data_dir: Path) -> None:
        """Should fail if --prompt-file does not exist."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
            "--prompt-file", "/nonexistent/prompt.md",
        ])
        result: int = cmd_run(args)
        assert result == 1

    def test_invalid_dpack(self, data_dir: Path, tmp_path: Path) -> None:
        """Should fail if decision-pack directory is invalid."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(tmp_path / "nonexistent"),
            "--data", str(data_dir),
            "--prompt", "test",
        ])
        result: int = cmd_run(args)
        assert result == 1

    def test_invalid_data_dir(self, dpack_config_dir: Path, tmp_path: Path) -> None:
        """Should fail if data directory does not exist."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(tmp_path / "nonexistent"),
            "--prompt", "test",
            "--work-dir", str(tmp_path / "work"),
        ])
        result: int = cmd_run(args)
        assert result == 1

    def test_successful_run(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Run should create session, start container, and run opencode."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
            "--prompt", "test prompt",
            "--work-dir", str(tmp_path / "work"),
        ])
        result: int = cmd_run(args)
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
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should read prompt from file and run the full flow."""
        prompt_file: Path = tmp_path / "prompt.md"
        prompt_file.write_text("prompt from file")

        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
            "--prompt-file", str(prompt_file),
            "--work-dir", str(tmp_path / "work"),
        ])
        result: int = cmd_run(args)
        # opencode runs but fails (no API key) — exit code 0
        assert result == 0

    def test_run_uses_default_model(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should use default_model from config if --model not provided."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
            "--prompt", "test",
            "--work-dir", str(tmp_path / "work"),
        ])
        result: int = cmd_run(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "anthropic/claude-sonnet-4-0" in captured.out

    def test_run_uses_override_model(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should use --model if provided."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
            "--prompt", "test",
            "--model", "anthropic/claude-opus-4-0",
            "--work-dir", str(tmp_path / "work"),
        ])
        result: int = cmd_run(args)
        assert result == 0

    def test_no_env_file_warning(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should error when no --env-file and no .env in decision-pack."""
        # Remove .env so preflight catches missing orchestrator key
        env_path: Path = dpack_config_dir / ".env"
        if env_path.exists():
            env_path.unlink()
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
            "--prompt", "test",
            "--work-dir", str(tmp_path / "work"),
        ])
        result: int = cmd_run(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "requires an API key" in captured.out

    def test_env_file_autodetect_no_warning(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should not warn when .env exists in decision-pack (auto-detected)."""
        (dpack_config_dir / ".env").write_text("SOME_KEY=value\n")

        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
            "--prompt", "test",
            "--work-dir", str(tmp_path / "work"),
        ])
        cmd_run(args)
        captured = capsys.readouterr()
        assert "No --env-file provided" not in captured.out


class TestErrorMessages:
    """Tests for user-friendly error messages."""

    def test_docker_not_available_message(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should show friendly Docker error with --no-sandboxing hint."""
        import unittest.mock
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
            "--prompt", "test",
            "--work-dir", str(tmp_path / "work"),
        ])
        with unittest.mock.patch("dlab.local.is_docker_available", return_value=False):
            result: int = cmd_run(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "Docker daemon" in captured.err
        assert "--no-sandboxing" in captured.err
        assert "Warning" in captured.err

    def test_work_dir_exists_message(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should show friendly work-dir-exists error with rm hint."""
        existing: Path = tmp_path / "work"
        existing.mkdir()
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--data", str(data_dir),
            "--prompt", "test",
            "--work-dir", str(existing),
        ])
        result: int = cmd_run(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.out
        assert "rm -rf" in captured.out


class TestContinueDir:
    """Tests for --continue-dir functionality in both Docker and local modes."""

    @pytest.fixture
    def previous_session(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path,
    ) -> Path:
        """Create a completed session to continue from."""
        from dlab.config import load_dpack_config
        from dlab.session import create_session

        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        state: dict[str, Any] = create_session(
            config, str(data_dir), work_dir=str(tmp_path / "prev-session"),
        )
        return Path(state["work_dir"])

    def _run_continue(
        self,
        dpack_dir: Path,
        continue_dir: Path,
        work_dir: Path | None = None,
        prompt: str = "continue",
        no_sandboxing: bool = False,
        extra_args: list[str] | None = None,
    ) -> int:
        """Helper to run cmd_run in continue mode, mocking agent execution."""
        parser = create_parser()
        cmd: list[str] = [
            "--dpack", str(dpack_dir),
            "--continue-dir", str(continue_dir),
            "--prompt", prompt,
        ]
        if work_dir:
            cmd.extend(["--work-dir", str(work_dir)])
        if no_sandboxing:
            cmd.append("--no-sandboxing")
        if extra_args:
            cmd.extend(extra_args)
        args = parser.parse_args(cmd)

        # Mock agent execution so tests don't hang on real LLM calls
        mock_return = (0, "", "")
        with patch("dlab.cli.run_opencode", return_value=mock_return), \
             patch("dlab.local.run_opencode_local", return_value=mock_return):
            return cmd_run(args)

    # --- Error handling (no mode needed, errors before execution) ---

    def test_continue_nonexistent_dir(
        self, dpack_config_dir: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should error cleanly when continue-dir doesn't exist."""
        result: int = self._run_continue(
            dpack_config_dir, Path("/nonexistent/dir"),
        )
        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_continue_with_data_rejected(
        self, dpack_config_dir: Path, data_dir: Path, previous_session: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should reject --data combined with --continue-dir."""
        parser = create_parser()
        args = parser.parse_args([
            "--dpack", str(dpack_config_dir),
            "--continue-dir", str(previous_session),
            "--data", str(data_dir),
            "--prompt", "continue",
        ])
        result: int = cmd_run(args)
        assert result == 1

    def test_continue_workdir_exists_error(
        self, dpack_config_dir: Path, previous_session: Path, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should error when --work-dir already exists in continue mode."""
        existing: Path = tmp_path / "already-here"
        existing.mkdir()
        result: int = self._run_continue(
            dpack_config_dir, previous_session,
            work_dir=existing, no_sandboxing=True,
        )
        assert result == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.out

    # --- Local mode (--no-sandboxing) ---

    def test_local_continue_to_new_workdir(
        self, dpack_config_dir: Path, previous_session: Path, tmp_path: Path,
    ) -> None:
        """Local: --continue-dir + --work-dir should copy session."""
        new_dir: Path = tmp_path / "local-continued"
        self._run_continue(
            dpack_config_dir, previous_session,
            work_dir=new_dir, no_sandboxing=True,
        )
        assert new_dir.exists()
        assert (new_dir / "data").exists()
        assert (new_dir / ".opencode").exists()
        assert (new_dir / "_opencode_logs").exists()

    def test_local_continue_refreshes_opencode(
        self, dpack_config_dir: Path, previous_session: Path, tmp_path: Path,
    ) -> None:
        """Local: continue should refresh .opencode/ from decision-pack."""
        new_dir: Path = tmp_path / "local-refreshed"
        marker: Path = previous_session / ".opencode" / "STALE_MARKER"
        marker.write_text("this should be gone after continue")

        self._run_continue(
            dpack_config_dir, previous_session,
            work_dir=new_dir, no_sandboxing=True,
        )
        assert not (new_dir / ".opencode" / "STALE_MARKER").exists()
        assert (new_dir / ".opencode").exists()

    def test_local_continue_refreshes_hooks(
        self, dpack_config_dir: Path, previous_session: Path, tmp_path: Path,
    ) -> None:
        """Local: continue should refresh hook scripts."""
        new_dir: Path = tmp_path / "local-hooks"
        hooks_dir: Path = previous_session / "_hooks"
        hooks_dir.mkdir(exist_ok=True)
        (hooks_dir / "old_hook.sh").write_text("stale")

        self._run_continue(
            dpack_config_dir, previous_session,
            work_dir=new_dir, no_sandboxing=True,
        )
        assert not (new_dir / "_hooks" / "old_hook.sh").exists()

    def test_local_continue_preserves_data(
        self, dpack_config_dir: Path, previous_session: Path, tmp_path: Path,
    ) -> None:
        """Local: continue should preserve data from original session."""
        new_dir: Path = tmp_path / "local-preserved"
        self._run_continue(
            dpack_config_dir, previous_session,
            work_dir=new_dir, no_sandboxing=True,
        )
        assert (new_dir / "data" / "sample.csv").exists()
        assert (new_dir / "data" / "subdir" / "nested.txt").exists()

    # --- Docker mode ---

    def test_docker_continue_to_new_workdir(
        self, dpack_config_dir: Path, previous_session: Path, tmp_path: Path,
    ) -> None:
        """Docker: --continue-dir + --work-dir should copy session."""
        new_dir: Path = tmp_path / "docker-continued"
        self._run_continue(
            dpack_config_dir, previous_session, work_dir=new_dir,
        )
        assert new_dir.exists()
        assert (new_dir / "data").exists()
        assert (new_dir / ".opencode").exists()
        assert (new_dir / "_opencode_logs").exists()

    def test_docker_continue_refreshes_opencode(
        self, dpack_config_dir: Path, previous_session: Path, tmp_path: Path,
    ) -> None:
        """Docker: continue should refresh .opencode/ from decision-pack."""
        new_dir: Path = tmp_path / "docker-refreshed"
        marker: Path = previous_session / ".opencode" / "STALE_MARKER"
        marker.write_text("this should be gone after continue")

        self._run_continue(
            dpack_config_dir, previous_session, work_dir=new_dir,
        )
        assert not (new_dir / ".opencode" / "STALE_MARKER").exists()
        assert (new_dir / ".opencode").exists()

    def test_docker_continue_preserves_data(
        self, dpack_config_dir: Path, previous_session: Path, tmp_path: Path,
    ) -> None:
        """Docker: continue should preserve data from original session."""
        new_dir: Path = tmp_path / "docker-preserved"
        self._run_continue(
            dpack_config_dir, previous_session, work_dir=new_dir,
        )
        assert (new_dir / "data" / "sample.csv").exists()
        assert (new_dir / "data" / "subdir" / "nested.txt").exists()


class TestCmdInstall:
    """Tests for cmd_install function."""

    def test_invalid_dpack_path(self, tmp_path: Path) -> None:
        """Should fail if decision-pack path is invalid."""
        parser = create_parser()
        args = parser.parse_args(["install", str(tmp_path / "nonexistent")])
        result: int = cmd_install(args)
        assert result == 1

    def test_creates_wrapper_script(
        self, dpack_config_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should create executable wrapper script."""
        bin_dir: Path = tmp_path / "bin"

        parser = create_parser()
        args = parser.parse_args([
            "install", str(dpack_config_dir),
            "--bin-dir", str(bin_dir),
        ])
        result: int = cmd_install(args)
        assert result == 0

        wrapper_path: Path = bin_dir / "test-dpack"
        assert wrapper_path.exists()

        mode: int = wrapper_path.stat().st_mode
        assert mode & stat.S_IXUSR

        content: str = wrapper_path.read_text()
        assert "dlab" in content
        assert "--dpack" in content
        assert str(dpack_config_dir.resolve()) in content

    def test_creates_bin_dir_if_missing(self, dpack_config_dir: Path, tmp_path: Path) -> None:
        """Should create bin directory if it doesn't exist."""
        bin_dir: Path = tmp_path / "new" / "bin" / "path"

        parser = create_parser()
        args = parser.parse_args([
            "install", str(dpack_config_dir),
            "--bin-dir", str(bin_dir),
        ])
        result: int = cmd_install(args)
        assert result == 0

        assert bin_dir.exists()
        assert (bin_dir / "test-dpack").exists()

    def test_prints_path_warning(
        self, dpack_config_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn if bin_dir not in PATH."""
        bin_dir: Path = tmp_path / "not_in_path"

        parser = create_parser()
        args = parser.parse_args([
            "install", str(dpack_config_dir),
            "--bin-dir", str(bin_dir),
        ])
        result: int = cmd_install(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "may not be in your PATH" in captured.out


class TestCmdConnect:
    """Tests for cmd_connect function."""

    def test_invalid_session_dir(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Connect should fail if directory has no _opencode_logs."""
        parser = create_parser()
        args = parser.parse_args(["connect", str(tmp_path)])
        result: int = cmd_connect(args)
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
        assert "Did you mean --dpack?" in result.stderr

    def test_unknown_subcommand_suggests_close_match(self) -> None:
        """Misspelled subcommand should suggest the correct one."""
        result = subprocess.run(
            [sys.executable, "-m", "dlab.cli", "instal", "/tmp"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "Did you mean install?" in result.stderr

    def test_unknown_flag_exit_code(self) -> None:
        """Unknown arguments should exit with code 2."""
        result = subprocess.run(
            [sys.executable, "-m", "dlab.cli", "--zzzzzzz"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "Unknown argument: --zzzzzzz" in result.stderr

    def test_one_bad_flag_only_reports_that_flag(self) -> None:
        """A single misspelled flag should not cause all other flags to be reported as unknown."""
        result = subprocess.run(
            [sys.executable, "-m", "dlab.cli",
             "--dpack", "foo", "--data", "bar", "--prompt", "hello", "--workdir", "out"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "Did you mean --work-dir?" in result.stderr
        # The valid flags should NOT appear as unknown
        assert "Unknown argument: --dpack" not in result.stderr
        assert "Unknown argument: --data" not in result.stderr
        assert "Unknown argument: --prompt" not in result.stderr
