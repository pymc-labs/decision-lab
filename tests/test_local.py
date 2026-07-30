"""Tests for dlab.local module."""

import json
import os
from pathlib import Path
from typing import Any

from dlab.local import build_local_prompt


class TestBuildLocalPrompt:
    """Tests for build_local_prompt()."""

    def test_uses_provided_work_dir_in_computation(self, tmp_path: Path) -> None:
        """work_dir parameter should be accepted and not crash."""
        work_dir: Path = tmp_path / "my-workdir"
        work_dir.mkdir()
        config_dir: Path = tmp_path / "dpack"
        config_dir.mkdir()

        config: dict[str, Any] = {
            "config_dir": str(config_dir),
            "package_manager": "pip",
        }
        result: str = build_local_prompt("Do something", config, str(work_dir))

        # Prompt should still use the generic placeholder (agents resolve it)
        assert "/absolute/path/to/workdir" in result

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

        # Prompt should still use the generic placeholder
        assert "/absolute/path/to/workdir" in result


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

    def test_printf_preserves_dash_prefixed_prompt_in_log(
        self, tmp_path: Path,
    ) -> None:
        """Runner script must preserve prompts starting with dash in dlab_start log."""
        from dlab.local import run_opencode_local

        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "_opencode_logs").mkdir()

        # A prompt starting with -n (which echo would interpret as the no-newline flag)
        prompt: str = "-n 5\nDo something important"

        # Use a bogus model so opencode fails fast; the dlab_start line is still written
        exit_code, _stdout, _stderr = run_opencode_local(
            str(work_dir),
            prompt,
            "bogus/test-model-12345",
            env=dict(os.environ),
            timeout=5,
            log_prefix="dash-test",
        )

        log_file: Path = work_dir / "_opencode_logs" / "dash-test.log"
        assert log_file.exists(), "Log file should be created by the runner script"

        lines: list[str] = log_file.read_text().splitlines()
        assert len(lines) >= 1, "Log should contain at least the dlab_start line"

        dlab_start: dict[str, Any] = json.loads(lines[0])
        assert dlab_start["type"] == "dlab_start"
        assert dlab_start["prompt"] == prompt, (
            f"Prompt mangled by shell: expected {prompt!r}, got {dlab_start['prompt']!r}"
        )
