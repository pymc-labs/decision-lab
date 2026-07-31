"""Tests for the composer step (issue #68).

The full opencode composer run needs a model + provider key (a manual
integration, like the docker tests). Here we cover the deterministic pieces:
environment materialization/cleanup, the composer model role, env parsing, and
the compose guard.
"""
from pathlib import Path

from dlab.composer import (
    NB_TOOLS,
    cleanup_composer_env,
    compose,
    materialize_composer_env,
)
from dlab.config import resolve_model_roles
from dlab.cli import _load_env_file, cmd_compose


class TestMaterializeEnv:
    def test_writes_agent_and_all_tools(self, tmp_path: Path) -> None:
        wd = tmp_path / "w"
        (wd / ".opencode").mkdir(parents=True)
        added = materialize_composer_env(wd)
        assert (wd / ".opencode" / "agents" / "composer.md").is_file()
        assert (wd / ".opencode" / "tools" / "digest-get.ts").is_file()
        for name in NB_TOOLS:
            assert (wd / ".opencode" / "tools" / f"{name}.ts").is_file()
        # the composer.md carried through is the real prompt
        assert "Notebook Composer" in (wd / ".opencode" / "agents" / "composer.md").read_text()

    def test_cleanup_removes_only_what_was_added(self, tmp_path: Path) -> None:
        wd = tmp_path / "w"
        tools = wd / ".opencode" / "tools"
        tools.mkdir(parents=True)
        # a pre-existing dpack tool must survive materialize + cleanup untouched
        (tools / "analyze-model.ts").write_text("DPACK TOOL")
        added = materialize_composer_env(wd)
        assert (tools / "analyze-model.ts").read_text() == "DPACK TOOL"
        cleanup_composer_env(added)
        assert (tools / "analyze-model.ts").read_text() == "DPACK TOOL"
        assert not (tools / "nb-note.ts").exists()
        assert not (wd / ".opencode" / "agents" / "composer.md").exists()


class TestComposerModelRole:
    def test_composer_falls_back_to_default(self) -> None:
        roles = resolve_model_roles({"default_model": "anthropic/opus"})
        assert roles["composer"] == "anthropic/opus"

    def test_composer_override(self) -> None:
        roles = resolve_model_roles({
            "default_model": "anthropic/opus",
            "models": {"composer": "google/gemini-3-flash-preview"},
        })
        assert roles["composer"] == "google/gemini-3-flash-preview"


class TestEnvAndGuards:
    def test_load_env_file(self, tmp_path: Path) -> None:
        f = tmp_path / ".env"
        f.write_text('# comment\nA=1\nB="two"\nGOOGLE_KEY=\'xyz\'\nbad line\n')
        env = _load_env_file(f)
        assert env == {"A": "1", "B": "two", "GOOGLE_KEY": "xyz"}

    def test_compose_rejects_non_workdir(self, tmp_path: Path) -> None:
        result = compose(tmp_path, model="x/y")  # no _opencode_logs → early return
        assert result.returncode == 1
        assert any("_opencode_logs" in w for w in result.warnings)
        assert result.notebooks == []

    def test_cmd_compose_needs_model_or_dpack(self, tmp_path: Path) -> None:
        (tmp_path / "_opencode_logs").mkdir()
        assert cmd_compose(str(tmp_path)) == 1  # neither --model nor --dpack

    def test_cmd_compose_rejects_non_workdir(self, tmp_path: Path) -> None:
        assert cmd_compose(str(tmp_path), model="x/y") == 1  # no _opencode_logs
