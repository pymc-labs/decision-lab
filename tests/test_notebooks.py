"""Tests for the notebook agent step (issue #68).

The full opencode notebook agent run needs a model + provider key (a manual
integration, like the docker tests). Here we cover the deterministic pieces:
environment materialization/cleanup, the notebook agent model role, env parsing, and
the generate_notebooks guard.
"""
from pathlib import Path

from dlab.notebooks import (
    NB_TOOLS,
    _isolate_notebook_tools,
    _restore_tools,
    cleanup_notebook_env,
    generate_notebooks,
    materialize_notebook_env,
)
from dlab.config import resolve_model_roles
from dlab.cli import (
    _available_provider_keys,
    _load_env_file,
    _suggest_models,
    cmd_notebooks,
)


class TestMaterializeEnv:
    def test_writes_agent_and_all_tools(self, tmp_path: Path) -> None:
        wd = tmp_path / "w"
        (wd / ".opencode").mkdir(parents=True)
        added = materialize_notebook_env(wd)
        assert (wd / ".opencode" / "agents" / "notebooks.md").is_file()
        assert (wd / ".opencode" / "tools" / "digest-get.ts").is_file()
        for name in NB_TOOLS:
            assert (wd / ".opencode" / "tools" / f"{name}.ts").is_file()
        # the notebooks.md agent prompt carried through is the real one
        assert "never write or alter code" in (
            wd / ".opencode" / "agents" / "notebooks.md").read_text()

    def test_cleanup_removes_only_what_was_added(self, tmp_path: Path) -> None:
        wd = tmp_path / "w"
        tools = wd / ".opencode" / "tools"
        tools.mkdir(parents=True)
        # a pre-existing dpack tool must survive materialize + cleanup untouched
        (tools / "analyze-model.ts").write_text("DPACK TOOL")
        added = materialize_notebook_env(wd)
        assert (tools / "analyze-model.ts").read_text() == "DPACK TOOL"
        cleanup_notebook_env(added)
        assert (tools / "analyze-model.ts").read_text() == "DPACK TOOL"
        assert not (tools / "nb-note.ts").exists()
        assert not (wd / ".opencode" / "agents" / "notebooks.md").exists()


class TestToolIsolation:
    def test_isolate_moves_dpack_tools_keeps_notebook(self, tmp_path: Path) -> None:
        wd = tmp_path / "w"
        tools = wd / ".opencode" / "tools"
        tools.mkdir(parents=True)
        (tools / "analyze-model.ts").write_text("DPACK")   # a strict provider
        (tools / "fit-model-modal.ts").write_text("DPACK") # rejects these schemas
        materialize_notebook_env(wd)
        moved = _isolate_notebook_tools(wd)
        # during the run: only the notebook agent's own tools remain loadable
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


class TestComposerModelResolution:
    def _dpack(self, root: Path, default_model: str, notebooks: str | None = None) -> Path:
        (root / "docker").mkdir(parents=True)
        (root / "opencode").mkdir()
        lines = ["name: x", "description: x", "docker_image_name: x",
                 f"default_model: {default_model}"]
        if notebooks:
            lines += ["models:", f"  notebooks: {notebooks}"]
        (root / "config.yaml").write_text("\n".join(lines) + "\n")
        return root

    def test_precedence(self, tmp_path: Path, monkeypatch) -> None:
        from dlab.cli import _resolve_notebooks_model
        monkeypatch.delenv("DLAB_NOTEBOOKS_MODEL", raising=False)
        pinned = self._dpack(tmp_path / "p1", "anthropic/def", notebooks="anthropic/pinned")
        plain = self._dpack(tmp_path / "p2", "anthropic/def")

        # --model always wins
        assert _resolve_notebooks_model("x/flag", str(pinned)) == "x/flag"
        # a pack's explicit models.notebooks beats the global env
        monkeypatch.setenv("DLAB_NOTEBOOKS_MODEL", "env/global")
        assert _resolve_notebooks_model(None, str(pinned)) == "anthropic/pinned"
        # the global env beats a pack's default_model fallback
        assert _resolve_notebooks_model(None, str(plain)) == "env/global"
        # with no pin and no env, fall back to default_model
        monkeypatch.delenv("DLAB_NOTEBOOKS_MODEL", raising=False)
        assert _resolve_notebooks_model(None, str(plain)) == "anthropic/def"
        # no model, no dpack, no env → unresolved
        assert _resolve_notebooks_model(None, None) is None
        # global env alone resolves it (no dpack)
        monkeypatch.setenv("DLAB_NOTEBOOKS_MODEL", "env/only")
        assert _resolve_notebooks_model(None, None) == "env/only"


class TestComposerFlow:
    def test_seed_copies_skeleton_into_notebooks(self, tmp_path: Path) -> None:
        from dlab.notebooks import _seed_notebooks_from_skeleton
        wd = tmp_path / "w"
        (wd / "skeleton" / "attempts").mkdir(parents=True)
        (wd / "skeleton" / "00_orchestrator.ipynb").write_text("{}")
        (wd / "skeleton" / "attempts" / "a.ipynb").write_text("{}")
        _seed_notebooks_from_skeleton(wd)
        assert (wd / "notebooks" / "00_orchestrator.ipynb").is_file()
        assert (wd / "notebooks" / "attempts" / "a.ipynb").is_file()   # subdir preserved

    def test_launch_prompt_is_curate_not_assemble(self) -> None:
        from dlab.notebooks import _LAUNCH_PROMPT
        low = _LAUNCH_PROMPT.lower()
        assert "already built" in low and "curate" in low
        assert "do not write or alter code" in low   # immutability, up front


class TestMapDpackModelSuggestions:
    def test_suggest_one_model_per_available_provider(self) -> None:
        assert _suggest_models({"ANTHROPIC_API_KEY"}) == ["anthropic/claude-sonnet-4-5"]
        many = _suggest_models({"OPENAI_API_KEY", "GEMINI_API_KEY", "opencode_zen"})
        assert "openai/gpt-5" in many and "google/gemini-3-flash-preview" in many
        assert "opencode/deepseek-v4-pro" in many
        assert _suggest_models(set()) == []          # no keys → no suggestions

    def test_available_keys_from_host_env_and_file(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "x")   # host env
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        f = tmp_path / ".env"
        f.write_text("OPENAI_API_KEY=y\nGEMINI_API_KEY=\nJUNK=z\n")  # file (empty ignored)
        keys = _available_provider_keys(str(f), tmp_path)
        assert "ANTHROPIC_API_KEY" in keys            # from host env
        assert "OPENAI_API_KEY" in keys               # from the env file
        assert "GEMINI_API_KEY" not in keys           # empty value → not "available"
        assert "JUNK" not in keys


class TestNotebooksModelRole:
    def test_notebooks_falls_back_to_default(self) -> None:
        roles = resolve_model_roles({"default_model": "anthropic/opus"})
        assert roles["notebooks"] == "anthropic/opus"

    def test_notebooks_override(self) -> None:
        roles = resolve_model_roles({
            "default_model": "anthropic/opus",
            "models": {"notebooks": "google/gemini-3-flash-preview"},
        })
        assert roles["notebooks"] == "google/gemini-3-flash-preview"


class TestEnvAndGuards:
    def test_notebook_env_is_curated(self, monkeypatch) -> None:
        # host env must NOT leak into opencode (it breaks the provider request);
        # only base vars + provider keys are forwarded.
        from dlab.notebooks import _notebook_env
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("SOME_HOST_JUNK", "leak")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from_host")
        env = _notebook_env({"GOOGLE_GENERATIVE_AI_API_KEY": "g", "opencode_zen": "z"})
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

    def test_generate_notebooks_rejects_non_workdir(self, tmp_path: Path) -> None:
        result = generate_notebooks(tmp_path, model="x/y")  # no _opencode_logs → early return
        assert result.returncode == 1
        assert any("_opencode_logs" in w for w in result.warnings)
        assert result.notebooks == []

    def test_cmd_notebooks_needs_model_or_dpack(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("DLAB_NOTEBOOKS_MODEL", raising=False)
        (tmp_path / "_opencode_logs").mkdir()
        assert cmd_notebooks(str(tmp_path)) == 1  # no --model, --dpack, or env default

    def test_cmd_notebooks_rejects_non_workdir(self, tmp_path: Path) -> None:
        assert cmd_notebooks(str(tmp_path), model="x/y") == 1  # no _opencode_logs
