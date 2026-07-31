"""Tests for the composer step (issue #68).

The full opencode composer run needs a model + provider key (a manual
integration, like the docker tests). Here we cover the deterministic pieces:
environment materialization/cleanup, the composer model role, env parsing, and
the compose guard.
"""
from pathlib import Path

from dlab.composer import (
    NB_TOOLS,
    _isolate_composer_tools,
    _restore_tools,
    cleanup_composer_env,
    compose,
    materialize_composer_env,
)
from dlab.config import resolve_model_roles
from dlab.cli import _load_env_file, cmd_notebooks


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


class TestToolIsolation:
    def test_isolate_moves_dpack_tools_keeps_composer(self, tmp_path: Path) -> None:
        wd = tmp_path / "w"
        tools = wd / ".opencode" / "tools"
        tools.mkdir(parents=True)
        (tools / "analyze-model.ts").write_text("DPACK")   # a strict provider
        (tools / "fit-model-modal.ts").write_text("DPACK") # rejects these schemas
        materialize_composer_env(wd)
        moved = _isolate_composer_tools(wd)
        # during the run: only the composer's own tools remain loadable
        remaining = {p.name for p in tools.glob("*.ts")}
        assert "digest-get.ts" in remaining
        assert all(f"{n}.ts" in remaining for n in NB_TOOLS)
        assert "analyze-model.ts" not in remaining
        assert "fit-model-modal.ts" not in remaining
        # restore puts the dpack tools back and clears the stash
        _restore_tools(moved)
        after = {p.name for p in tools.glob("*.ts")}
        assert "analyze-model.ts" in after and "fit-model-modal.ts" in after
        assert not (wd / ".opencode" / "_tools_stash").exists()


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
    def test_composer_env_is_curated(self, monkeypatch) -> None:
        # host env must NOT leak into opencode (it breaks the provider request);
        # only base vars + provider keys are forwarded.
        from dlab.composer import _composer_env
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("SOME_HOST_JUNK", "leak")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from_host")
        env = _composer_env({"GOOGLE_GENERATIVE_AI_API_KEY": "g", "opencode_zen": "z"})
        assert env["PATH"] == "/usr/bin"
        assert "SOME_HOST_JUNK" not in env          # host junk dropped
        assert "opencode_zen" not in env            # non-provider --env-file key dropped
        assert env["ANTHROPIC_API_KEY"] == "from_host"        # provider key from host
        assert env["GOOGLE_GENERATIVE_AI_API_KEY"] == "g"     # provider key from --env-file

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

    def test_cmd_notebooks_needs_model_or_dpack(self, tmp_path: Path) -> None:
        (tmp_path / "_opencode_logs").mkdir()
        assert cmd_notebooks(str(tmp_path)) == 1  # neither --model nor --dpack

    def test_cmd_notebooks_rejects_non_workdir(self, tmp_path: Path) -> None:
        assert cmd_notebooks(str(tmp_path), model="x/y") == 1  # no _opencode_logs
