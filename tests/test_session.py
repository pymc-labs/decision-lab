"""
Tests for dlab.session module.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from dlab.config import load_dpack_config
from dlab.parallel_tool import PARALLEL_AGENTS_SOURCE
from dlab.session import (
    copy_data_to_workdir,
    copy_data_paths_to_workdir,
    copy_hook_scripts,
    copy_opencode_config,
    create_session,
    get_next_sequence_number,
    load_state,
    save_state,
    setup_opencode_config,
)


class TestGetNextSequenceNumber:
    """Tests for get_next_sequence_number function."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory should return 1."""
        seq: int = get_next_sequence_number(str(tmp_path), "mmm")
        assert seq == 1

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        """Non-existent directory should return 1."""
        seq: int = get_next_sequence_number(str(tmp_path / "nonexistent"), "mmm")
        assert seq == 1

    def test_with_existing_sessions(self, tmp_path: Path) -> None:
        """Should return next number after existing sessions."""
        (tmp_path / "dlab-mmm-workdir-001").mkdir()
        (tmp_path / "dlab-mmm-workdir-002").mkdir()
        (tmp_path / "dlab-mmm-workdir-005").mkdir()

        seq: int = get_next_sequence_number(str(tmp_path), "mmm")
        assert seq == 6

    def test_ignores_other_directories(self, tmp_path: Path) -> None:
        """Should ignore directories not matching the pattern."""
        (tmp_path / "dlab-mmm-workdir-003").mkdir()
        (tmp_path / "other-directory").mkdir()
        (tmp_path / "dlab-mmm-workdir-notanumber").mkdir()

        seq: int = get_next_sequence_number(str(tmp_path), "mmm")
        assert seq == 4

    def test_different_dpacks_independent(self, tmp_path: Path) -> None:
        """Different dpack names should have independent sequence numbers."""
        (tmp_path / "dlab-mmm-workdir-001").mkdir()
        (tmp_path / "dlab-mmm-workdir-002").mkdir()
        (tmp_path / "dlab-poem-workdir-001").mkdir()

        assert get_next_sequence_number(str(tmp_path), "mmm") == 3
        assert get_next_sequence_number(str(tmp_path), "poem") == 2


class TestCopyDataToWorkdir:
    """Tests for copy_data_to_workdir function."""

    def test_copies_data(self, data_dir: Path, work_dir: Path) -> None:
        """Data should be copied to work_dir/data/."""
        work_dir.mkdir()
        copy_data_to_workdir(str(data_dir), str(work_dir))

        dest: Path = work_dir / "data"
        assert dest.exists()
        assert (dest / "sample.csv").read_text() == "a,b,c\n1,2,3\n"
        assert (dest / "subdir" / "nested.txt").read_text() == "nested content"

    def test_nonexistent_data_dir(self, tmp_path: Path, work_dir: Path) -> None:
        """Non-existent data directory should raise ValueError."""
        work_dir.mkdir()

        with pytest.raises(ValueError, match="does not exist"):
            copy_data_to_workdir(str(tmp_path / "nonexistent"), str(work_dir))

    def test_data_dir_is_file(self, tmp_path: Path, work_dir: Path) -> None:
        """File instead of directory should raise ValueError."""
        work_dir.mkdir()
        file_path: Path = tmp_path / "file"
        file_path.write_text("content")

        with pytest.raises(ValueError, match="not a directory"):
            copy_data_to_workdir(str(file_path), str(work_dir))


class TestCopyOpencodeConfig:
    """Tests for copy_opencode_config function."""

    def test_copies_opencode(self, dpack_config_dir: Path, work_dir: Path) -> None:
        """Opencode config should be copied to work_dir/.opencode/."""
        work_dir.mkdir()

        opencode_src: Path = dpack_config_dir / "opencode"
        (opencode_src / "opencode.json").write_text('{"test": true}')

        copy_opencode_config(str(dpack_config_dir), str(work_dir))

        dest: Path = work_dir / ".opencode"
        assert dest.exists()
        assert (dest / "opencode.json").read_text() == '{"test": true}'

    def test_missing_opencode_dir(self, tmp_path: Path, work_dir: Path) -> None:
        """Missing opencode directory should raise ValueError."""
        work_dir.mkdir()
        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()

        with pytest.raises(ValueError, match="opencode directory not found"):
            copy_opencode_config(str(dpack), str(work_dir))


class TestSaveAndLoadState:
    """Tests for save_state and load_state functions."""

    def test_round_trip(self, work_dir: Path) -> None:
        """State should survive save/load round trip."""
        work_dir.mkdir()

        state: dict[str, Any] = {
            "work_dir": str(work_dir),
            "status": "running",
            "extra": {"nested": "data"},
        }

        save_state(str(work_dir), state)
        loaded: dict[str, Any] = load_state(str(work_dir))

        assert loaded == state

    def test_load_missing_state(self, work_dir: Path) -> None:
        """Loading from directory without .state.json should raise ValueError."""
        work_dir.mkdir()

        with pytest.raises(ValueError, match="No .state.json found"):
            load_state(str(work_dir))

    def test_load_invalid_json(self, work_dir: Path) -> None:
        """Invalid JSON in .state.json should raise ValueError."""
        work_dir.mkdir()
        (work_dir / ".state.json").write_text("not json")

        with pytest.raises(ValueError, match="Invalid JSON"):
            load_state(str(work_dir))


class TestCreateSession:
    """Tests for create_session function."""

    def test_generates_parallel_agents_tool(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path
    ) -> None:
        """Should generate parallel-agents.ts when parallel_agents/ configs exist."""
        # Add parallel_agents config to the decision-pack
        parallel_configs: Path = dpack_config_dir / "opencode" / "parallel_agents"
        parallel_configs.mkdir()
        (parallel_configs / "test-agent.yaml").write_text("name: test-agent\n")

        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        state: dict[str, Any] = create_session(config, str(data_dir), base_dir=str(tmp_path))

        work_path: Path = Path(state["work_dir"])
        tool_path: Path = work_path / ".opencode" / "tools" / "parallel-agents.ts"

        assert tool_path.exists()
        assert "Spawn parallel subagents" in tool_path.read_text()

    def test_no_parallel_agents_tool_without_config(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path
    ) -> None:
        """Should NOT generate parallel-agents.ts when no parallel_agents/ configs exist."""
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        state: dict[str, Any] = create_session(config, str(data_dir), base_dir=str(tmp_path))

        work_path: Path = Path(state["work_dir"])
        tool_path: Path = work_path / ".opencode" / "tools" / "parallel-agents.ts"

        assert not tool_path.exists()

    def test_creates_session(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path
    ) -> None:
        """Session creation should set up proper directory structure."""
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        state: dict[str, Any] = create_session(config, str(data_dir), base_dir=str(tmp_path))

        work_path: Path = Path(state["work_dir"])

        assert work_path.exists()
        assert (work_path / "data").exists()
        assert (work_path / ".opencode").exists()
        assert (work_path / "_opencode_logs").exists()
        assert (work_path / ".state.json").exists()

        assert state["status"] == "created"
        assert state["dpack_name"] == "test-dpack"

    def test_explicit_work_dir(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path
    ) -> None:
        """Explicit work_dir should be used."""
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        explicit_dir: str = str(tmp_path / "my-work-dir")

        state: dict[str, Any] = create_session(config, str(data_dir), work_dir=explicit_dir)

        assert state["work_dir"] == str(Path(explicit_dir).resolve())

    def test_existing_work_dir_fails(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path
    ) -> None:
        """Existing work_dir should raise ValueError."""
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        existing_dir: Path = tmp_path / "existing"
        existing_dir.mkdir()

        with pytest.raises(ValueError, match="already exists"):
            create_session(config, str(data_dir), work_dir=str(existing_dir))

    def test_cleanup_on_failure(
        self, dpack_config_dir: Path, tmp_path: Path
    ) -> None:
        """Work dir should be cleaned up if session setup fails after creation."""
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        work_dir: Path = tmp_path / "will-fail"

        # Pass a nonexistent data path to trigger failure after work_dir is created
        with pytest.raises(ValueError, match="does not exist"):
            create_session(config, "/nonexistent/data/path", work_dir=str(work_dir))

        # Work dir should have been cleaned up
        assert not work_dir.exists()

    def test_auto_sequence_numbering(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path
    ) -> None:
        """Auto-generated work dirs should use sequential numbering."""
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))

        state1: dict[str, Any] = create_session(config, str(data_dir), base_dir=str(tmp_path))
        state2: dict[str, Any] = create_session(config, str(data_dir), base_dir=str(tmp_path))

        assert "dlab-test-dpack-workdir-001" in state1["work_dir"]
        assert "dlab-test-dpack-workdir-002" in state2["work_dir"]


class TestSetupOpencodeConfig:
    """Tests for setup_opencode_config function."""

    def _make_config_dir(self, tmp_path: Path, with_parallel: bool = False) -> Path:
        """Create a minimal decision-pack config dir with opencode/ structure."""
        config_dir: Path = tmp_path / "dpack"
        config_dir.mkdir()
        opencode_dir: Path = config_dir / "opencode"
        opencode_dir.mkdir()
        if with_parallel:
            parallel_dir: Path = opencode_dir / "parallel_agents"
            parallel_dir.mkdir()
            (parallel_dir / "test-agent.yaml").write_text("name: test-agent\n")
        return config_dir

    def test_parallel_tool_content_matches_source(self, tmp_path: Path) -> None:
        """Written parallel-agents.ts should exactly match PARALLEL_AGENTS_SOURCE."""
        config_dir: Path = self._make_config_dir(tmp_path, with_parallel=True)
        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()

        setup_opencode_config(str(config_dir), str(work_dir))

        tool_path: Path = work_dir / ".opencode" / "tools" / "parallel-agents.ts"
        assert tool_path.read_text() == PARALLEL_AGENTS_SOURCE

    def test_creates_package_json_when_missing(self, tmp_path: Path) -> None:
        """Should create package.json with yaml dependency when none exists."""
        config_dir: Path = self._make_config_dir(tmp_path, with_parallel=True)
        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()

        setup_opencode_config(str(config_dir), str(work_dir))

        pkg_path: Path = work_dir / ".opencode" / "package.json"
        pkg: dict[str, Any] = json.loads(pkg_path.read_text())
        assert pkg["dependencies"]["yaml"] == "^2.0.0"

    def test_adds_yaml_to_existing_package_json(self, tmp_path: Path) -> None:
        """Should add yaml dep without overwriting existing deps."""
        config_dir: Path = self._make_config_dir(tmp_path, with_parallel=True)
        # Pre-create package.json with an existing dependency
        opencode_dir: Path = config_dir / "opencode"
        (opencode_dir / "package.json").write_text(
            json.dumps({"dependencies": {"zod": "^3.0.0"}})
        )

        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()

        setup_opencode_config(str(config_dir), str(work_dir))

        pkg_path: Path = work_dir / ".opencode" / "package.json"
        pkg: dict[str, Any] = json.loads(pkg_path.read_text())
        assert pkg["dependencies"]["zod"] == "^3.0.0"
        assert pkg["dependencies"]["yaml"] == "^2.0.0"

    def test_preserves_yaml_if_already_present(self, tmp_path: Path) -> None:
        """Should not rewrite package.json if yaml dep already exists."""
        config_dir: Path = self._make_config_dir(tmp_path, with_parallel=True)
        opencode_dir: Path = config_dir / "opencode"
        original_content: str = json.dumps(
            {"dependencies": {"yaml": "^2.0.0"}}, indent=2
        )
        (opencode_dir / "package.json").write_text(original_content)

        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()

        setup_opencode_config(str(config_dir), str(work_dir))

        pkg_path: Path = work_dir / ".opencode" / "package.json"
        assert pkg_path.read_text() == original_content

    def test_no_tools_dir_without_parallel_configs(self, tmp_path: Path) -> None:
        """Without parallel_agents/ dir, no tools/ dir should be created."""
        config_dir: Path = self._make_config_dir(tmp_path, with_parallel=False)
        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()

        setup_opencode_config(str(config_dir), str(work_dir))

        assert not (work_dir / ".opencode" / "tools").exists()

    def test_ignores_non_yaml_files_in_parallel_configs(self, tmp_path: Path) -> None:
        """parallel_agents/ with only non-YAML files should not trigger tool generation."""
        config_dir: Path = self._make_config_dir(tmp_path, with_parallel=False)
        parallel_dir: Path = config_dir / "opencode" / "parallel_agents"
        parallel_dir.mkdir()
        (parallel_dir / "readme.txt").write_text("not a yaml file")

        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()

        setup_opencode_config(str(config_dir), str(work_dir))

        assert not (work_dir / ".opencode" / "tools").exists()


class TestCopyHookScripts:
    """Tests for copy_hook_scripts function."""

    def test_no_hooks(self, tmp_path: Path) -> None:
        """Empty hooks should not create _hooks/ directory."""
        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()

        config: dict[str, Any] = {
            "config_dir": str(tmp_path),
            "hooks": {"pre-run": [], "post-run": []},
        }
        copy_hook_scripts(config, str(work_dir))

        assert not (work_dir / "_hooks").exists()

    def test_single_pre_run_hook(self, tmp_path: Path) -> None:
        """Single pre-run hook should be copied to _hooks/."""
        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()
        script: Path = dpack / "deploy.sh"
        script.write_text("#!/bin/bash\necho deploy\n")

        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()

        config: dict[str, Any] = {
            "config_dir": str(dpack),
            "hooks": {"pre-run": ["deploy.sh"], "post-run": []},
        }
        copy_hook_scripts(config, str(work_dir))

        copied: Path = work_dir / "_hooks" / "deploy.sh"
        assert copied.exists()
        assert "echo deploy" in copied.read_text()

    def test_multiple_hooks(self, tmp_path: Path) -> None:
        """Multiple pre-run and post-run hooks should all be copied."""
        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()
        (dpack / "pre1.sh").write_text("#!/bin/bash\n")
        (dpack / "pre2.sh").write_text("#!/bin/bash\n")
        (dpack / "post1.sh").write_text("#!/bin/bash\n")

        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()

        config: dict[str, Any] = {
            "config_dir": str(dpack),
            "hooks": {"pre-run": ["pre1.sh", "pre2.sh"], "post-run": ["post1.sh"]},
        }
        copy_hook_scripts(config, str(work_dir))

        hooks_dir: Path = work_dir / "_hooks"
        assert (hooks_dir / "pre1.sh").exists()
        assert (hooks_dir / "pre2.sh").exists()
        assert (hooks_dir / "post1.sh").exists()

    def test_missing_script_raises(self, tmp_path: Path) -> None:
        """Referencing a non-existent script should raise ValueError."""
        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()

        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()

        config: dict[str, Any] = {
            "config_dir": str(dpack),
            "hooks": {"pre-run": ["nonexistent.sh"], "post-run": []},
        }

        with pytest.raises(ValueError, match="Hook script not found"):
            copy_hook_scripts(config, str(work_dir))

    def test_preserves_permissions(self, tmp_path: Path) -> None:
        """Executable permission should be preserved via copy2."""
        import stat

        dpack: Path = tmp_path / "dpack"
        dpack.mkdir()
        script: Path = dpack / "run.sh"
        script.write_text("#!/bin/bash\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        work_dir: Path = tmp_path / "work"
        work_dir.mkdir()

        config: dict[str, Any] = {
            "config_dir": str(dpack),
            "hooks": {"pre-run": ["run.sh"], "post-run": []},
        }
        copy_hook_scripts(config, str(work_dir))

        copied: Path = work_dir / "_hooks" / "run.sh"
        assert copied.stat().st_mode & stat.S_IXUSR

    def test_create_session_copies_hooks(
        self, dpack_config_dir: Path, data_dir: Path, tmp_path: Path
    ) -> None:
        """create_session should copy hook scripts to work dir."""
        # Add a hook script and update config
        script: Path = dpack_config_dir / "setup.sh"
        script.write_text("#!/bin/bash\necho setup\n")

        config_yaml: Path = dpack_config_dir / "config.yaml"
        content: str = config_yaml.read_text()
        content += "hooks:\n  pre-run: setup.sh\n"
        config_yaml.write_text(content)

        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        state: dict[str, Any] = create_session(config, str(data_dir), base_dir=str(tmp_path))

        work_path: Path = Path(state["work_dir"])
        assert (work_path / "_hooks" / "setup.sh").exists()


class TestCopyDataPathsToWorkdir:
    """Tests for copy_data_paths_to_workdir function."""

    def test_single_file(self, tmp_path: Path) -> None:
        src: Path = tmp_path / "input.csv"
        src.write_text("a,b\n1,2\n")
        work: Path = tmp_path / "work"
        work.mkdir()
        copy_data_paths_to_workdir([str(src)], str(work))
        assert (work / "data" / "input.csv").read_text() == "a,b\n1,2\n"

    def test_multiple_files(self, tmp_path: Path) -> None:
        f1: Path = tmp_path / "a.csv"
        f2: Path = tmp_path / "b.csv"
        f1.write_text("a")
        f2.write_text("b")
        work: Path = tmp_path / "work"
        work.mkdir()
        copy_data_paths_to_workdir([str(f1), str(f2)], str(work))
        assert (work / "data" / "a.csv").exists()
        assert (work / "data" / "b.csv").exists()

    def test_mixed_files_and_dirs(self, tmp_path: Path) -> None:
        f: Path = tmp_path / "file.txt"
        f.write_text("content")
        d: Path = tmp_path / "subdir"
        d.mkdir()
        (d / "nested.txt").write_text("nested")
        work: Path = tmp_path / "work"
        work.mkdir()
        copy_data_paths_to_workdir([str(f), str(d)], str(work))
        assert (work / "data" / "file.txt").exists()
        assert (work / "data" / "subdir" / "nested.txt").exists()

    def test_nonexistent_path_raises(self, tmp_path: Path) -> None:
        work: Path = tmp_path / "work"
        work.mkdir()
        with pytest.raises(ValueError, match="does not exist"):
            copy_data_paths_to_workdir([str(tmp_path / "nope")], str(work))


class TestCreateSessionNoData:
    """Tests for create_session with no data."""

    def test_no_data(self, dpack_config_dir: Path, tmp_path: Path) -> None:
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        state: dict[str, Any] = create_session(config, None, base_dir=str(tmp_path))
        work_path: Path = Path(state["work_dir"])
        assert work_path.exists()
        assert not (work_path / "data").exists()
        assert state["data_dir"] == ""

    def test_file_list(self, dpack_config_dir: Path, tmp_path: Path) -> None:
        f: Path = tmp_path / "input.csv"
        f.write_text("x,y\n1,2\n")
        config: dict[str, Any] = load_dpack_config(str(dpack_config_dir))
        state: dict[str, Any] = create_session(config, [str(f)], base_dir=str(tmp_path))
        work_path: Path = Path(state["work_dir"])
        assert (work_path / "data" / "input.csv").exists()
