"""
Tests for dlab.create_dpack module.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from dlab.create_dpack import (
    filter_models,
    generate_dpack,
    validate_dpack_name,
)


class TestValidateDpackName:
    """Tests for validate_dpack_name."""

    def test_valid_names(self) -> None:
        """Should accept valid alphanumeric names with hyphens/underscores."""
        assert validate_dpack_name("my-dpack") is None
        assert validate_dpack_name("my_dpack") is None
        assert validate_dpack_name("dpack123") is None
        assert validate_dpack_name("MyDpack") is None
        assert validate_dpack_name("a") is None

    def test_empty_name(self) -> None:
        """Should reject empty name."""
        assert validate_dpack_name("") is not None

    def test_invalid_characters(self) -> None:
        """Should reject names with spaces or special characters."""
        assert validate_dpack_name("my dpack") is not None
        assert validate_dpack_name("my.dpack") is not None
        assert validate_dpack_name("my/dpack") is not None
        assert validate_dpack_name("my@dpack") is not None

    def test_cannot_start_with_hyphen_or_underscore(self) -> None:
        """Should reject names starting with - or _."""
        assert validate_dpack_name("-bad") is not None
        assert validate_dpack_name("_bad") is not None


class TestFilterModels:
    """Tests for filter_models."""

    def test_empty_query_returns_all(self) -> None:
        """Empty query should return all known models."""
        result: list[str] = filter_models("")
        assert len(result) > 0
        assert "opencode/big-pickle" in result

    def test_filter_by_provider(self) -> None:
        """Should filter by provider prefix."""
        result: list[str] = filter_models("anthropic")
        assert all("anthropic" in m for m in result)
        assert len(result) >= 2

    def test_filter_by_model_name(self) -> None:
        """Should filter by model name substring."""
        result: list[str] = filter_models("opus")
        assert all("opus" in m for m in result)

    def test_case_insensitive(self) -> None:
        """Should be case insensitive."""
        result: list[str] = filter_models("CLAUDE")
        assert len(result) > 0

    def test_no_match(self) -> None:
        """Should return empty list for no match."""
        result: list[str] = filter_models("nonexistent-model-xyz")
        assert result == []


class TestGenerateDpack:
    """Tests for generate_dpack."""

    def _minimal_config(self, name: str = "test-dpack") -> dict[str, Any]:
        """Return a minimal config dict."""
        return {"name": name}

    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        """Should create the expected directory structure."""
        result: Path = generate_dpack(tmp_path, self._minimal_config())

        assert result == tmp_path / "test-dpack"
        assert result.is_dir()
        assert (result / "config.yaml").is_file()
        assert (result / "docker" / "Dockerfile").is_file()
        assert (result / "opencode" / "opencode.json").is_file()
        assert (result / "opencode" / "agents" / "orchestrator.md").is_file()

    def test_config_yaml_content(self, tmp_path: Path) -> None:
        """config.yaml should have correct values and commented hooks."""
        config: dict[str, Any] = {
            "name": "my-project",
            "description": "My project description",
            "docker_image_name": "my-img",
            "default_model": "anthropic/claude-opus-4",
        }
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "my-project" / "config.yaml").read_text()
        parsed: dict[str, Any] = yaml.safe_load(content.split("\n# hooks:")[0])

        assert parsed["name"] == "my-project"
        assert parsed["description"] == "My project description"
        assert parsed["docker_image_name"] == "my-img"
        assert parsed["default_model"] == "anthropic/claude-opus-4"
        assert "# hooks:" in content
        assert "#   pre-run: setup.sh" in content
        assert "#   post-run: cleanup.sh" in content

    def test_dockerfile_uses_base_image(self, tmp_path: Path) -> None:
        """Dockerfile should use the specified base image."""
        config: dict[str, Any] = {
            "name": "custom",
            "base_image": "ubuntu:22.04",
        }
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "custom" / "docker" / "Dockerfile").read_text()
        assert "FROM ubuntu:22.04" in content
        assert "WORKDIR /workspace" in content

    def test_dockerfile_default_base_image(self, tmp_path: Path) -> None:
        """Dockerfile should default to python:3.11-slim."""
        generate_dpack(tmp_path, self._minimal_config())

        content: str = (tmp_path / "test-dpack" / "docker" / "Dockerfile").read_text()
        assert "FROM python:3.11-slim" in content

    def test_opencode_json_content(self, tmp_path: Path) -> None:
        """opencode.json should reference the correct default agent."""
        config: dict[str, Any] = {
            "name": "proj",
            "agent_name": "my-agent",
        }
        generate_dpack(tmp_path, config)

        data: dict[str, Any] = json.loads(
            (tmp_path / "proj" / "opencode" / "opencode.json").read_text()
        )
        assert data["default_agent"] == "my-agent"

    def test_agent_md_content(self, tmp_path: Path) -> None:
        """Agent .md should have frontmatter and default prompt."""
        config: dict[str, Any] = {
            "name": "proj",
            "agent_name": "proj-agent",
            "agent_description": "My agent",
        }
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "proj" / "opencode" / "agents" / "proj-agent.md").read_text()
        assert "description: My agent" in content
        assert "mode: primary" in content
        assert "read: true" in content
        assert "You are an AI assistant" in content

    def test_agent_md_subagents_only(self, tmp_path: Path) -> None:
        """Subagents-only should have task: true in tools."""
        config: dict[str, Any] = {
            "name": "proj",
            "skeletons": {"subagents": True, "parallel_agents": False},
        }
        generate_dpack(tmp_path, config)
        content: str = (tmp_path / "proj" / "opencode" / "agents" / "orchestrator.md").read_text()
        assert "task: true" in content
        assert "read: true" in content
        assert "parallel-agents" not in content

    def test_agent_md_parallel_only(self, tmp_path: Path) -> None:
        """Parallel agents should have only parallel-agents: true."""
        config: dict[str, Any] = {
            "name": "proj",
            "skeletons": {"parallel_agents": True, "subagents": True},
        }
        generate_dpack(tmp_path, config)
        content: str = (tmp_path / "proj" / "opencode" / "agents" / "orchestrator.md").read_text()
        assert "parallel-agents: true" in content
        assert "task:" not in content

    def test_agent_md_no_parallel_by_default(self, tmp_path: Path) -> None:
        """Agent .md should NOT have parallel-agents tool by default."""
        generate_dpack(tmp_path, self._minimal_config())

        content: str = (tmp_path / "test-dpack" / "opencode" / "agents" / "orchestrator.md").read_text()
        assert "parallel-agents" not in content

    def test_rejects_invalid_name(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid names."""
        with pytest.raises(ValueError, match="alphanumeric"):
            generate_dpack(tmp_path, {"name": "bad name!"})

    def test_rejects_empty_name(self, tmp_path: Path) -> None:
        """Should raise ValueError for empty name."""
        with pytest.raises(ValueError, match="required"):
            generate_dpack(tmp_path, {"name": ""})

    def test_rejects_existing_directory(self, tmp_path: Path) -> None:
        """Should raise ValueError if directory already exists."""
        (tmp_path / "existing").mkdir()
        with pytest.raises(ValueError, match="already exists"):
            generate_dpack(tmp_path, {"name": "existing"})

    def test_defaults_applied(self, tmp_path: Path) -> None:
        """Should apply sensible defaults when config is minimal."""
        generate_dpack(tmp_path, self._minimal_config())

        config_content: str = (tmp_path / "test-dpack" / "config.yaml").read_text()
        assert "dlab-test-dpack" in config_content
        assert "opencode/big-pickle" in config_content

        oc_json: dict[str, Any] = json.loads(
            (tmp_path / "test-dpack" / "opencode" / "opencode.json").read_text()
        )
        assert oc_json["default_agent"] == "orchestrator"


class TestPermissions:
    """Tests for opencode.json permission configuration."""

    def test_all_permissions_written(self, tmp_path: Path) -> None:
        """All permissions should be explicitly written (no 'ask' defaults)."""
        generate_dpack(tmp_path, {"name": "perm-all"})

        data: dict[str, Any] = json.loads(
            (tmp_path / "perm-all" / "opencode" / "opencode.json").read_text()
        )
        perm: dict[str, Any] = data["permission"]
        # Hardcoded permissions
        assert perm["read"] == "allow"
        assert perm["glob"] == "allow"
        assert perm["grep"] == "allow"
        assert perm["list"] == "allow"
        assert perm["question"] == "deny"
        assert "doom_loop" not in perm  # left to OpenCode default (see TODO)
        # Configurable defaults (all allow)
        assert perm["edit"] == "allow"
        assert perm["bash"] == "allow"
        assert perm["external_directory"] == "allow"
        assert perm["webfetch"] == "allow"
        assert perm["websearch"] == "allow"
        assert perm["task"] == "allow"
        assert perm["skill"] == "allow"

    def test_deny_specific_permission(self, tmp_path: Path) -> None:
        """Should deny specific permissions when configured."""
        config: dict[str, Any] = {
            "name": "perm-deny",
            "permissions": {"bash": "deny", "webfetch": "deny", "websearch": "deny"},
        }
        generate_dpack(tmp_path, config)

        data: dict[str, Any] = json.loads(
            (tmp_path / "perm-deny" / "opencode" / "opencode.json").read_text()
        )
        perm: dict[str, Any] = data["permission"]
        assert perm["bash"] == "deny"
        assert perm["webfetch"] == "deny"
        assert perm["websearch"] == "deny"
        # Others still allowed
        assert perm["edit"] == "allow"
        assert perm["external_directory"] == "allow"

    def test_deny_external_directory(self, tmp_path: Path) -> None:
        """Should deny external_directory when configured."""
        config: dict[str, Any] = {
            "name": "perm-noext",
            "permissions": {"external_directory": "deny"},
        }
        generate_dpack(tmp_path, config)

        data: dict[str, Any] = json.loads(
            (tmp_path / "perm-noext" / "opencode" / "opencode.json").read_text()
        )
        assert data["permission"]["external_directory"] == "deny"

    def test_hardcoded_permissions_not_overridable(self, tmp_path: Path) -> None:
        """Hardcoded permissions should not be affected by user config."""
        config: dict[str, Any] = {
            "name": "perm-hard",
            "permissions": {"question": "allow"},
        }
        generate_dpack(tmp_path, config)

        data: dict[str, Any] = json.loads(
            (tmp_path / "perm-hard" / "opencode" / "opencode.json").read_text()
        )
        # question is hardcoded to deny, not configurable
        assert data["permission"]["question"] == "deny"


class TestSkeletonSubagents:
    """Tests for subagents skeleton (without parallel)."""

    def test_subagent_creates_worker_md(self, tmp_path: Path) -> None:
        """Should create example-worker.md when subagents skeleton selected."""
        config: dict[str, Any] = {
            "name": "sub-test",
            "skeletons": {"subagents": True},
        }
        generate_dpack(tmp_path, config)

        worker: Path = tmp_path / "sub-test" / "opencode" / "agents" / "example-worker.md"
        assert worker.is_file()
        content: str = worker.read_text()
        assert "mode: subagent" in content
        assert "parallel-agents: false" in content

    def test_subagent_no_parallel_yaml(self, tmp_path: Path) -> None:
        """Subagents alone should NOT create parallel_agents/ dir."""
        config: dict[str, Any] = {
            "name": "sub-no-pa",
            "skeletons": {"subagents": True},
        }
        generate_dpack(tmp_path, config)

        assert not (tmp_path / "sub-no-pa" / "opencode" / "parallel_agents").exists()

    def test_subagent_no_parallel_tool(self, tmp_path: Path) -> None:
        """Subagents alone should NOT add parallel-agents tool to main agent."""
        config: dict[str, Any] = {
            "name": "sub-no-tool",
            "skeletons": {"subagents": True},
        }
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "sub-no-tool" / "opencode" / "agents" / "orchestrator.md").read_text()
        assert "parallel-agents" not in content

    def test_no_subagent_dir_without_skeleton(self, tmp_path: Path) -> None:
        """Should not create example-worker.md when no subagent skeleton."""
        generate_dpack(tmp_path, {"name": "no-sub"})
        assert not (tmp_path / "no-sub" / "opencode" / "agents" / "example-worker.md").exists()


class TestSkeletonParallelAgents:
    """Tests for parallel agents skeleton."""

    def _config_with_parallel(self) -> dict[str, Any]:
        return {
            "name": "pa-test",
            "skeletons": {"parallel_agents": True},
        }

    def test_main_agent_has_parallel_tool(self, tmp_path: Path) -> None:
        """Main agent should have parallel-agents: true in tools."""
        generate_dpack(tmp_path, self._config_with_parallel())

        content: str = (tmp_path / "pa-test" / "opencode" / "agents" / "orchestrator.md").read_text()
        assert "parallel-agents: true" in content

    def test_main_agent_has_spawn_instructions(self, tmp_path: Path) -> None:
        """Main agent should explain how to spawn parallel agents."""
        generate_dpack(tmp_path, self._config_with_parallel())

        content: str = (tmp_path / "pa-test" / "opencode" / "agents" / "orchestrator.md").read_text()
        assert "example-worker" in content
        assert '"agent":' in content
        assert '"prompts":' in content

    def test_example_worker_md_created(self, tmp_path: Path) -> None:
        """Should create example-worker.md subagent file."""
        generate_dpack(tmp_path, self._config_with_parallel())

        worker: Path = tmp_path / "pa-test" / "opencode" / "agents" / "example-worker.md"
        assert worker.is_file()
        content: str = worker.read_text()
        assert "mode: subagent" in content
        assert "parallel-agents: false" in content

    def test_example_worker_yaml_created(self, tmp_path: Path) -> None:
        """Should create example-worker.yaml parallel agent config."""
        generate_dpack(tmp_path, self._config_with_parallel())

        yaml_file: Path = tmp_path / "pa-test" / "opencode" / "parallel_agents" / "example-worker.yaml"
        assert yaml_file.is_file()
        content: str = yaml_file.read_text()
        assert "name: example-worker" in content
        assert "subagent_suffix_prompt:" in content
        assert "summarizer_prompt:" in content
        assert "summarizer_model:" in content

    def test_parallel_implies_subagent_worker(self, tmp_path: Path) -> None:
        """parallel_agents should auto-create example-worker.md (implies subagents)."""
        generate_dpack(tmp_path, self._config_with_parallel())

        worker: Path = tmp_path / "pa-test" / "opencode" / "agents" / "example-worker.md"
        assert worker.is_file()


class TestSkeletonTools:
    """Tests for tools skeleton."""

    def test_example_tool_created(self, tmp_path: Path) -> None:
        """Should create example-tool.ts when tools skeleton selected."""
        config: dict[str, Any] = {
            "name": "tools-test",
            "skeletons": {"tools": True},
        }
        generate_dpack(tmp_path, config)

        tool_file: Path = tmp_path / "tools-test" / "opencode" / "tools" / "example-tool.ts"
        assert tool_file.is_file()
        content: str = tool_file.read_text()
        assert "@opencode-ai/plugin" in content
        assert "tool(" in content

    def test_no_tools_dir_without_skeleton(self, tmp_path: Path) -> None:
        """Should not create tools/ dir when skeleton not selected."""
        generate_dpack(tmp_path, {"name": "no-tools"})
        assert not (tmp_path / "no-tools" / "opencode" / "tools").exists()

    def test_run_on_modal_tool_has_nothrow(self, tmp_path: Path) -> None:
        """run-on-modal.ts should use .nothrow() to capture stderr."""
        config: dict[str, Any] = {
            "name": "modal-nothrow",
            "modal_integration": True,
            "skeletons": {"tools": True},
        }
        generate_dpack(tmp_path, config)
        tool_file: Path = tmp_path / "modal-nothrow" / "opencode" / "tools" / "run-on-modal.ts"
        assert tool_file.is_file()
        content: str = tool_file.read_text()
        assert ".nothrow()" in content
        assert "exitCode" in content


class TestSkeletonSkills:
    """Tests for skills skeleton."""

    def test_example_skill_created(self, tmp_path: Path) -> None:
        """Should create example-skill/SKILL.md when skills skeleton selected."""
        config: dict[str, Any] = {
            "name": "skills-test",
            "skeletons": {"skills": True},
        }
        generate_dpack(tmp_path, config)

        skill_file: Path = tmp_path / "skills-test" / "opencode" / "skills" / "example-skill" / "SKILL.md"
        assert skill_file.is_file()
        content: str = skill_file.read_text()
        assert "Example Skill" in content

    def test_no_skills_dir_without_skeleton(self, tmp_path: Path) -> None:
        """Should not create skills/ dir when skeleton not selected."""
        generate_dpack(tmp_path, {"name": "no-skills"})
        assert not (tmp_path / "no-skills" / "opencode" / "skills").exists()


class TestSkeletonCombinations:
    """Tests for combining multiple skeletons."""

    def test_all_skeletons(self, tmp_path: Path) -> None:
        """Should create all skeleton dirs when all selected."""
        config: dict[str, Any] = {
            "name": "all-skeletons",
            "skeletons": {
                "skills": True,
                "tools": True,
                "parallel_agents": True,
            },
        }
        generate_dpack(tmp_path, config)

        base: Path = tmp_path / "all-skeletons" / "opencode"
        assert (base / "tools" / "example-tool.ts").is_file()
        assert (base / "skills" / "example-skill" / "SKILL.md").is_file()
        assert (base / "parallel_agents" / "example-worker.yaml").is_file()
        assert (base / "agents" / "example-worker.md").is_file()

    def test_no_skeletons(self, tmp_path: Path) -> None:
        """Should create only base structure when no skeletons selected."""
        generate_dpack(tmp_path, {"name": "bare"})

        base: Path = tmp_path / "bare" / "opencode"
        assert (base / "agents").is_dir()
        assert (base / "opencode.json").is_file()
        assert not (base / "tools").exists()
        assert not (base / "skills").exists()
        assert not (base / "parallel_agents").exists()


class TestDockerfilePerPackageManager:
    """Tests for Dockerfile generation based on package manager."""

    def test_pip_dockerfile(self, tmp_path: Path) -> None:
        """pip should generate a python-slim Dockerfile with pip install."""
        config: dict[str, Any] = {"name": "pip-test", "package_manager": "pip"}
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "pip-test" / "docker" / "Dockerfile").read_text()
        assert "FROM python:3.11-slim" in content
        assert "COPY requirements.txt" in content
        assert "pip install --no-cache-dir" in content
        assert 'CMD ["/bin/bash"]' in content

    def test_conda_dockerfile(self, tmp_path: Path) -> None:
        """conda should generate a miniconda Dockerfile with conda env create."""
        config: dict[str, Any] = {"name": "conda-test", "package_manager": "conda"}
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "conda-test" / "docker" / "Dockerfile").read_text()
        assert "FROM continuumio/miniconda3:latest" in content
        assert "COPY environment.yml" in content
        assert "conda env create" in content
        assert "conda clean -afy" in content
        # Env name should use docker_image_name (dlab-{name})
        assert "dlab-conda-test" in content
        assert 'CMD ["conda", "run", "-n", "dlab-conda-test", "/bin/bash"]' in content

    def test_uv_dockerfile(self, tmp_path: Path) -> None:
        """uv should generate a Dockerfile with uv binary copied."""
        config: dict[str, Any] = {"name": "uv-test", "package_manager": "uv"}
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "uv-test" / "docker" / "Dockerfile").read_text()
        assert "FROM python:3.11-slim" in content
        assert "COPY --from=ghcr.io/astral-sh/uv:latest" in content
        assert "uv pip install --system --no-cache" in content
        assert 'CMD ["/bin/bash"]' in content

    def test_pixi_dockerfile(self, tmp_path: Path) -> None:
        """pixi should generate a debian Dockerfile with pixi install."""
        config: dict[str, Any] = {"name": "pixi-test", "package_manager": "pixi"}
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "pixi-test" / "docker" / "Dockerfile").read_text()
        assert "FROM debian:bookworm-slim" in content
        assert "pixi.sh/install.sh" in content
        assert "COPY pixi.toml" in content
        assert "pixi install" in content
        assert 'CMD ["/bin/bash"]' in content

    def test_default_package_manager_is_pip(self, tmp_path: Path) -> None:
        """Default package manager should be pip."""
        generate_dpack(tmp_path, {"name": "default-pkg"})

        content: str = (tmp_path / "default-pkg" / "docker" / "Dockerfile").read_text()
        assert "FROM python:3.11-slim" in content
        assert "COPY requirements.txt" in content


class TestEnvironmentFiles:
    """Tests for environment file generation per package manager."""

    def test_pip_creates_requirements_txt(self, tmp_path: Path) -> None:
        """pip should create requirements.txt."""
        config: dict[str, Any] = {"name": "env-pip", "package_manager": "pip"}
        generate_dpack(tmp_path, config)

        req: Path = tmp_path / "env-pip" / "docker" / "requirements.txt"
        assert req.is_file()
        content: str = req.read_text()
        assert "pip packages" in content

    def test_uv_creates_requirements_txt(self, tmp_path: Path) -> None:
        """uv should also create requirements.txt."""
        config: dict[str, Any] = {"name": "env-uv", "package_manager": "uv"}
        generate_dpack(tmp_path, config)

        req: Path = tmp_path / "env-uv" / "docker" / "requirements.txt"
        assert req.is_file()

    def test_conda_creates_environment_yml(self, tmp_path: Path) -> None:
        """conda should create environment.yml with docker_image_name."""
        config: dict[str, Any] = {"name": "env-conda", "package_manager": "conda"}
        generate_dpack(tmp_path, config)

        env: Path = tmp_path / "env-conda" / "docker" / "environment.yml"
        assert env.is_file()
        content: str = env.read_text()
        assert "conda-forge" in content
        assert "python=3.11" in content
        assert "name: dlab-env-conda" in content

    def test_pixi_creates_pixi_toml(self, tmp_path: Path) -> None:
        """pixi should create pixi.toml."""
        config: dict[str, Any] = {"name": "env-pixi", "package_manager": "pixi"}
        generate_dpack(tmp_path, config)

        pixi: Path = tmp_path / "env-pixi" / "docker" / "pixi.toml"
        assert pixi.is_file()
        content: str = pixi.read_text()
        assert "conda-forge" in content
        assert "dlab-env-pixi" in content


class TestPythonLib:
    """Tests for python library generation."""

    def test_creates_lib_dir(self, tmp_path: Path) -> None:
        """Should create python lib directory with __init__.py."""
        config: dict[str, Any] = {
            "name": "lib-test",
            "python_lib": True,
            "python_lib_name": "lib_test_lib",
        }
        generate_dpack(tmp_path, config)

        init: Path = tmp_path / "lib-test" / "docker" / "lib_test_lib" / "__init__.py"
        assert init.is_file()
        assert "lib_test_lib" in init.read_text()

    def test_dockerfile_copies_lib(self, tmp_path: Path) -> None:
        """Dockerfile should COPY the python lib and set PYTHONPATH."""
        config: dict[str, Any] = {
            "name": "lib-df",
            "python_lib": True,
            "python_lib_name": "lib_df_lib",
            "package_manager": "pip",
        }
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "lib-df" / "docker" / "Dockerfile").read_text()
        assert "COPY lib_df_lib/ /opt/lib_df_lib/" in content
        assert "PYTHONPATH" in content

    def test_no_lib_by_default(self, tmp_path: Path) -> None:
        """Should not create lib dir by default."""
        generate_dpack(tmp_path, {"name": "no-lib"})

        docker: Path = tmp_path / "no-lib" / "docker"
        # Only Dockerfile and env file should exist
        entries: list[str] = [e.name for e in docker.iterdir()]
        assert "Dockerfile" in entries
        assert "requirements.txt" in entries
        assert len(entries) == 2


class TestModalIntegration:
    """Tests for Modal integration generation."""

    def test_creates_modal_app_dir(self, tmp_path: Path) -> None:
        """Should create modal_app directory with example script."""
        config: dict[str, Any] = {
            "name": "modal-test",
            "modal_integration": True,
        }
        generate_dpack(tmp_path, config)

        modal_dir: Path = tmp_path / "modal-test" / "docker" / "modal_app"
        assert modal_dir.is_dir()
        assert (modal_dir / "__init__.py").is_file()
        assert (modal_dir / "example.py").is_file()

        content: str = (modal_dir / "example.py").read_text()
        assert "modal" in content.lower()
        assert "modal-test" in content

    def test_dockerfile_copies_modal_app(self, tmp_path: Path) -> None:
        """Dockerfile should COPY modal_app and set PYTHONPATH."""
        config: dict[str, Any] = {
            "name": "modal-df",
            "modal_integration": True,
            "package_manager": "pip",
        }
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "modal-df" / "docker" / "Dockerfile").read_text()
        assert "COPY modal_app/ /opt/modal_app/" in content
        assert "PYTHONPATH" in content

    def test_modal_example_has_cache_buster(self, tmp_path: Path) -> None:
        """Modal example.py should include self-hashing cache buster."""
        config: dict[str, Any] = {
            "name": "modal-hash",
            "modal_integration": True,
        }
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "modal-hash" / "docker" / "modal_app" / "example.py").read_text()
        assert "hashlib" in content
        assert "_modal_app_hash" in content
        assert "Cache buster" in content

    def test_modal_conda_uses_micromamba(self, tmp_path: Path) -> None:
        """Modal example.py should use micromamba when package manager is conda."""
        config: dict[str, Any] = {
            "name": "modal-conda",
            "modal_integration": True,
            "package_manager": "conda",
        }
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "modal-conda" / "docker" / "modal_app" / "example.py").read_text()
        assert "micromamba" in content
        assert "micromamba_install" in content
        assert "conda-forge" in content
        assert "CONDA_PACKAGES" in content
        assert "PIP_PACKAGES" in content

    def test_modal_pip_uses_debian_slim(self, tmp_path: Path) -> None:
        """Modal example.py should use debian_slim when package manager is pip."""
        config: dict[str, Any] = {
            "name": "modal-pip",
            "modal_integration": True,
            "package_manager": "pip",
        }
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "modal-pip" / "docker" / "modal_app" / "example.py").read_text()
        assert "debian_slim" in content
        assert "pip_install" in content
        assert "micromamba" not in content

    def test_creates_deploy_modal_sh(self, tmp_path: Path) -> None:
        """Should create deploy_modal.sh at decision-pack root when modal enabled."""
        config: dict[str, Any] = {
            "name": "modal-hook",
            "modal_integration": True,
        }
        generate_dpack(tmp_path, config)

        hook: Path = tmp_path / "modal-hook" / "deploy_modal.sh"
        assert hook.is_file()
        content: str = hook.read_text()
        assert "modal deploy" in content
        assert "/opt/modal_app/" in content

    def test_modal_config_has_active_hooks(self, tmp_path: Path) -> None:
        """config.yaml should have active (uncommented) hooks when modal enabled."""
        config: dict[str, Any] = {
            "name": "modal-hooks",
            "modal_integration": True,
        }
        generate_dpack(tmp_path, config)

        content: str = (tmp_path / "modal-hooks" / "config.yaml").read_text()
        assert "hooks:" in content
        assert "pre-run: deploy_modal.sh" in content
        # Should NOT have commented-out hooks
        assert "# hooks:" not in content

    def test_deploy_modal_sh_has_local_check(self, tmp_path: Path) -> None:
        """deploy_modal.sh should check DLAB_RUN_MODAL_TOOL_LOCALLY."""
        generate_dpack(tmp_path, {"name": "modal-env", "modal_integration": True})
        content: str = (tmp_path / "modal-env" / "deploy_modal.sh").read_text()
        assert "DLAB_RUN_MODAL_TOOL_LOCALLY" in content

    def test_deploy_modal_sh_has_token_check(self, tmp_path: Path) -> None:
        """deploy_modal.sh should check for Modal tokens."""
        generate_dpack(tmp_path, {"name": "modal-tok", "modal_integration": True})
        content: str = (tmp_path / "modal-tok" / "deploy_modal.sh").read_text()
        assert "MODAL_TOKEN_ID" in content
        assert "MODAL_TOKEN_SECRET" in content

    def test_no_modal_by_default(self, tmp_path: Path) -> None:
        """Should not create modal_app dir or deploy script by default."""
        generate_dpack(tmp_path, {"name": "no-modal"})
        assert not (tmp_path / "no-modal" / "docker" / "modal_app").exists()
        assert not (tmp_path / "no-modal" / "deploy_modal.sh").exists()

    def test_both_lib_and_modal(self, tmp_path: Path) -> None:
        """Should handle both python lib and modal together."""
        config: dict[str, Any] = {
            "name": "both-test",
            "python_lib": True,
            "python_lib_name": "both_test_lib",
            "modal_integration": True,
            "package_manager": "conda",
        }
        generate_dpack(tmp_path, config)

        docker: Path = tmp_path / "both-test" / "docker"
        assert (docker / "both_test_lib" / "__init__.py").is_file()
        assert (docker / "modal_app" / "example.py").is_file()

        content: str = (docker / "Dockerfile").read_text()
        assert "COPY both_test_lib/ /opt/both_test_lib/" in content
        assert "COPY modal_app/ /opt/modal_app/" in content
        assert "PYTHONPATH" in content


class TestConfigYamlHooks:
    """Tests for config.yaml hooks."""

    def test_hooks_comment_includes_explanation(self, tmp_path: Path) -> None:
        """config.yaml hooks comment should explain what hooks do."""
        generate_dpack(tmp_path, {"name": "hooks-test"})

        content: str = (tmp_path / "hooks-test" / "config.yaml").read_text()
        assert "# Scripts listed here run inside the container" in content

    def test_no_modal_has_commented_hooks(self, tmp_path: Path) -> None:
        """Without modal, hooks should be commented out."""
        generate_dpack(tmp_path, {"name": "hooks-no-modal"})

        content: str = (tmp_path / "hooks-no-modal" / "config.yaml").read_text()
        assert "# hooks:" in content
        assert "#   pre-run: setup.sh" in content
        assert "#   post-run: cleanup.sh" in content


class TestLspDefaultDeny:
    """Tests for lsp permission default."""

    def test_lsp_defaults_to_deny(self, tmp_path: Path) -> None:
        """lsp should default to deny."""
        generate_dpack(tmp_path, {"name": "lsp-test"})

        data: dict[str, Any] = json.loads(
            (tmp_path / "lsp-test" / "opencode" / "opencode.json").read_text()
        )
        assert data["permission"]["lsp"] == "deny"


class TestGetProviderEnvVars:
    """Tests for get_provider_env_vars."""

    def test_known_provider(self) -> None:
        from dlab.create_dpack import get_provider_env_vars
        result: list[str] = get_provider_env_vars("anthropic/claude-sonnet-4")
        assert "ANTHROPIC_API_KEY" in result

    def test_opencode_provider(self) -> None:
        from dlab.create_dpack import get_provider_env_vars
        result: list[str] = get_provider_env_vars("opencode/big-pickle")
        assert "OPENCODE_API_KEY" in result

    def test_unknown_provider(self) -> None:
        from dlab.create_dpack import get_provider_env_vars
        result: list[str] = get_provider_env_vars("unknown/some-model")
        assert result == []


class TestFilterModelsCustomList:
    """Tests for filter_models with custom models parameter."""

    def test_filters_custom_list(self) -> None:
        custom: list[str] = ["foo/bar", "baz/qux", "foo/baz"]
        result: list[str] = filter_models("foo", custom)
        assert result == ["foo/bar", "foo/baz"]

    def test_empty_query_returns_custom_list(self) -> None:
        custom: list[str] = ["a/b", "c/d"]
        result: list[str] = filter_models("", custom)
        assert result == ["a/b", "c/d"]


class TestOverwriteExisting:
    """Tests for generate_dpack with overwrite_existing."""

    def test_overwrite_replaces_directory(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "ow-test"})
        assert (tmp_path / "ow-test" / "config.yaml").exists()
        # Overwrite
        generate_dpack(tmp_path, {"name": "ow-test", "overwrite_existing": True})
        assert (tmp_path / "ow-test" / "config.yaml").exists()

    def test_no_overwrite_raises(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "ow-test2"})
        with pytest.raises(ValueError, match="already exists"):
            generate_dpack(tmp_path, {"name": "ow-test2"})


class TestOnProgress:
    """Tests for generate_dpack on_progress callback."""

    def test_progress_callback_called(self, tmp_path: Path) -> None:
        messages: list[str] = []
        generate_dpack(tmp_path, {"name": "prog-test"}, on_progress=messages.append)
        assert len(messages) > 0
        assert any("directory" in m.lower() for m in messages)

    def test_none_callback_ok(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "prog-none"}, on_progress=None)
        assert (tmp_path / "prog-none" / "config.yaml").exists()


class TestEnvExample:
    """Tests for .env.example and .gitignore generation."""

    def test_env_example_generated(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "env-test", "default_model": "anthropic/claude-sonnet-4"})
        env_file: Path = tmp_path / "env-test" / ".env.example"
        assert env_file.exists()
        content: str = env_file.read_text()
        assert "ANTHROPIC_API_KEY" in content

    def test_env_example_modal_vars(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "env-modal", "modal_integration": True})
        content: str = (tmp_path / "env-modal" / ".env.example").read_text()
        assert "MODAL_TOKEN_ID" in content
        assert "MODAL_TOKEN_SECRET" in content

    def test_gitignore_generated(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "gi-test"})
        content: str = (tmp_path / "gi-test" / ".gitignore").read_text()
        assert ".env" in content
        assert "!.env.example" in content


class TestRequiresData:
    """Tests for requires_data in config.yaml."""

    def test_requires_data_default_true(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "rd-true"})
        content: str = (tmp_path / "rd-true" / "config.yaml").read_text()
        assert "requires_data: true" in content

    def test_requires_data_false(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "rd-false", "requires_data": False})
        content: str = (tmp_path / "rd-false" / "config.yaml").read_text()
        assert "requires_data: false" in content


class TestRequiresPrompt:
    """Tests for requires_prompt in config.yaml."""

    def test_requires_prompt_default_true(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "rp-true"})
        content: str = (tmp_path / "rp-true" / "config.yaml").read_text()
        assert "requires_prompt: true" in content

    def test_requires_prompt_false(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "rp-false", "requires_prompt": False})
        content: str = (tmp_path / "rp-false" / "config.yaml").read_text()
        assert "requires_prompt: false" in content


class TestModalInEnvFile:
    """Tests that modal is added to env files when modal_integration is on."""

    def test_modal_in_requirements(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "m-pip", "modal_integration": True, "package_manager": "pip"})
        content: str = (tmp_path / "m-pip" / "docker" / "requirements.txt").read_text()
        assert "modal" in content

    def test_modal_in_environment_yml(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "m-conda", "modal_integration": True, "package_manager": "conda"})
        content: str = (tmp_path / "m-conda" / "docker" / "environment.yml").read_text()
        assert "modal" in content

    def test_no_modal_without_flag(self, tmp_path: Path) -> None:
        generate_dpack(tmp_path, {"name": "m-none", "package_manager": "pip"})
        content: str = (tmp_path / "m-none" / "docker" / "requirements.txt").read_text()
        assert "modal" not in content
