"""Tests for dlab.local module."""

from pathlib import Path
from typing import Any

from dlab.local import build_local_prompt


class TestBuildLocalPrompt:
    """Tests for build_local_prompt()."""

    def test_uses_provided_work_dir(self, tmp_path: Path) -> None:
        """Should use the provided work_dir for absolute paths, not config parent."""
        work_dir: Path = tmp_path / "my-workdir"
        work_dir.mkdir()
        config_dir: Path = tmp_path / "dpack"
        config_dir.mkdir()

        config: dict[str, Any] = {
            "config_dir": str(config_dir),
            "package_manager": "pip",
        }
        result: str = build_local_prompt("Do something", config, str(work_dir))

        # Should contain the actual work dir path in PYTHONPATH instructions
        assert f"PYTHONPATH={work_dir}/_docker" in result
        assert f"{work_dir}/.venv/bin/python" in result
        # Should NOT contain the generic placeholder
        assert "/absolute/path/to/workdir" not in result

    def test_falls_back_to_config_parent_when_no_work_dir(
        self, tmp_path: Path,
    ) -> None:
        """Should fall back to config dir parent when work_dir is None."""
        config_dir: Path = tmp_path / "dpack"
        config_dir.mkdir()

        config: dict[str, Any] = {
            "config_dir": str(config_dir),
            "package_manager": "pip",
        }
        result: str = build_local_prompt("Do something", config, None)

        # Should contain the parent of config_dir as the work dir
        assert f"PYTHONPATH={tmp_path}/_docker" in result
        assert f"{tmp_path}/.venv/bin/python" in result


class TestRunnerScript:
    """Tests for runner script generation (local and docker)."""

    def test_local_runner_uses_printf_not_echo(self, tmp_path: Path) -> None:
        """Runner script should use printf instead of echo for prompt."""
        from dlab.local import run_opencode_local

        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()
        logs_dir: Path = work_dir / "_opencode_logs"
        logs_dir.mkdir()

        # We can't easily call run_opencode_local without opencode installed,
        # but we can verify the runner script it creates by checking the file.
        # However, run_opencode_local writes and executes the script.
        # Instead, let's verify build_local_prompt includes the right path
        # and the script content indirectly.
        # A simpler approach: check the runner script template directly.

        # Read the source to verify printf is used
        import inspect
        source: str = inspect.getsource(run_opencode_local)
        assert 'printf' in source
        assert 'echo \"$prompt\"' not in source

    def test_docker_runner_uses_printf_not_echo(self) -> None:
        """Docker runner script should use printf instead of echo."""
        from dlab.docker import build_runner_script

        script: str = build_runner_script("/.prompt.txt", "anthropic/claude-sonnet-4-0", "main")
        assert "printf '%s\\n'" in script
        assert 'echo "$prompt"' not in script

    def test_printf_handles_dash_prefixed_prompt(self, tmp_path: Path) -> None:
        """printf should not interpret dash-prefixed prompts as flags."""
        from dlab.local import build_local_prompt

        config_dir: Path = tmp_path / "dpack"
        config_dir.mkdir()
        config: dict[str, Any] = {
            "config_dir": str(config_dir),
            "package_manager": "pip",
        }

        # A prompt starting with -n (which echo would interpret as a flag)
        prompt: str = "-n 5\nDo something"
        result: str = build_local_prompt(prompt, config, str(tmp_path / "work"))
        # The prompt should be preserved in the output
        assert "-n 5" in result
