"""Tests for the create-parallel-agent TUI wizard."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from textual.widgets import Checkbox, Input, OptionList

from dlab.create_parallel_agent_wizard import (
    CreateParallelAgentApp,
    ParallelAgentScreen,
    _NEW_AGENT_ID,
)

PAUSE: float = 0.3


@pytest.fixture
def dpack(tmp_path: Path) -> Path:
    """Create a minimal decision-pack directory for testing."""
    (tmp_path / "config.yaml").write_text(
        "name: test-dpack\n"
        "description: Test\n"
        "docker_image_name: test-img\n"
        "default_model: anthropic/claude-sonnet-4-0\n"
    )
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "Dockerfile").write_text("FROM python:3.11-slim\n")
    opencode: Path = tmp_path / "opencode"
    opencode.mkdir()
    (opencode / "opencode.json").write_text(json.dumps({
        "default_agent": "orchestrator",
        "permission": {"read": "allow"},
    }))
    agents: Path = opencode / "agents"
    agents.mkdir()
    (agents / "orchestrator.md").write_text("---\nmode: primary\n---\nMain.\n")
    (agents / "worker-a.md").write_text("---\nmode: subagent\n---\nA.\n")
    (agents / "worker-b.md").write_text("---\nmode: subagent\n---\nB.\n")
    return tmp_path


class TestParallelAgentScreen:
    """Tests for the parallel agent wizard screen."""

    @pytest.mark.asyncio
    async def test_renders(self, dpack: Path) -> None:
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            assert isinstance(app.screen, ParallelAgentScreen)
            app.screen.query_one("#pa-name-input")
            app.screen.query_one("#suffix-textarea")
            app.screen.query_one("#summarizer-textarea")

    @pytest.mark.asyncio
    async def test_existing_agents_listed(self, dpack: Path) -> None:
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            ol = app.screen.query_one("#agent-select")
            option_ids: list[str] = [
                str(ol.get_option_at_index(i).id) for i in range(ol.option_count)
            ]
            assert "worker-a" in option_ids
            assert "worker-b" in option_ids
            assert "orchestrator" not in option_ids
            assert _NEW_AGENT_ID in option_ids

    @pytest.mark.asyncio
    async def test_new_agent_fields_hidden_when_existing(self, dpack: Path) -> None:
        """When existing agents are available, new agent fields are hidden."""
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            assert app.screen.query_one("#pa-name-input").display is False

    @pytest.mark.asyncio
    async def test_new_agent_fields_shown_when_no_agents(self, tmp_path: Path) -> None:
        """When no existing agents (besides default), new agent fields shown."""
        (tmp_path / "config.yaml").write_text(
            "name: t\ndescription: t\ndocker_image_name: t\ndefault_model: m\n"
        )
        (tmp_path / "docker").mkdir()
        (tmp_path / "docker" / "Dockerfile").write_text("FROM python:3.11-slim\n")
        oc: Path = tmp_path / "opencode"
        oc.mkdir()
        (oc / "opencode.json").write_text('{"default_agent":"main","permission":{}}')
        (oc / "agents").mkdir()
        (oc / "agents" / "main.md").write_text("---\n---\n")

        app = CreateParallelAgentApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            assert app.screen.query_one("#pa-name-input").display is True

    @pytest.mark.asyncio
    async def test_empty_name_blocked_for_new_agent(self, tmp_path: Path) -> None:
        """When 'New agent...' is selected and name is empty, creation is blocked."""
        (tmp_path / "config.yaml").write_text(
            "name: t\ndescription: t\ndocker_image_name: t\ndefault_model: m\n"
        )
        (tmp_path / "docker").mkdir()
        (tmp_path / "docker" / "Dockerfile").write_text("FROM python:3.11-slim\n")
        oc: Path = tmp_path / "opencode"
        oc.mkdir()
        (oc / "opencode.json").write_text('{"default_agent":"main","permission":{}}')
        (oc / "agents").mkdir()
        (oc / "agents" / "main.md").write_text("---\n---\n")
        # No other agents — "New agent..." is auto-selected, name field is visible
        app = CreateParallelAgentApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            # Name input is empty, click create
            await pilot.click("#create-btn")
            await pilot.pause(delay=PAUSE)
            # Should NOT have created anything
            assert not (tmp_path / "opencode" / "parallel_agents").exists()

    @pytest.mark.asyncio
    async def test_radio_group(self, dpack: Path) -> None:
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            assert app.screen.query_one("#fail-continue", Checkbox).value is True
            assert app.screen.query_one("#fail-fast", Checkbox).value is False
            app.screen.query_one("#fail-fast", Checkbox).value = True
            await pilot.pause(delay=PAUSE)
            assert app.screen.query_one("#fail-continue", Checkbox).value is False

    @pytest.mark.asyncio
    async def test_retries_hidden_by_default(self, dpack: Path) -> None:
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            assert app.screen.query_one("#retries-input").display is False

    @pytest.mark.asyncio
    async def test_retries_shown_on_retry(self, dpack: Path) -> None:
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            app.screen.query_one("#fail-retry", Checkbox).value = True
            await pilot.pause(delay=PAUSE)
            assert app.screen.query_one("#retries-input").display is True

    @pytest.mark.asyncio
    async def test_creates_yaml_existing_agent(self, dpack: Path) -> None:
        """Selecting an existing agent creates a YAML with that agent's name."""
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            # Default selection is first existing agent (worker-a)
            await pilot.click("#create-btn")
            await pilot.pause(delay=PAUSE)
            yaml_file: Path = dpack / "opencode" / "parallel_agents" / "worker-a.yaml"
            assert yaml_file.exists()
            content: dict[str, Any] = yaml.safe_load(yaml_file.read_text())
            assert content["name"] == "worker-a"
            assert content["failure_behavior"] == "continue"

    @pytest.mark.asyncio
    async def test_creates_yaml_new_agent(self, dpack: Path) -> None:
        """Selecting 'New agent...' and entering a name creates YAML + .md."""
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            # Select "New agent..." (last option)
            ol = app.screen.query_one("#agent-select")
            ol.highlighted = ol.option_count - 1
            await pilot.pause(delay=PAUSE)
            app.screen.query_one("#pa-name-input").value = "new-worker"
            await pilot.click("#create-btn")
            await pilot.pause(delay=PAUSE)
            yaml_file: Path = dpack / "opencode" / "parallel_agents" / "new-worker.yaml"
            assert yaml_file.exists()
            agent_file: Path = dpack / "opencode" / "agents" / "new-worker.md"
            assert agent_file.exists()

    @pytest.mark.asyncio
    async def test_model_prefilled(self, dpack: Path) -> None:
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            model_val: str = app.screen.query_one("#summarizer-model-input").value
            assert model_val == "anthropic/claude-sonnet-4-0"

    @pytest.mark.asyncio
    async def test_model_search_hidden_by_default(self, dpack: Path) -> None:
        """Model results dropdown should be hidden initially."""
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            group = app.screen.query_one("#model-selection-group")
            assert group.display is False

    @pytest.mark.asyncio
    async def test_model_search_shows_on_typing(self, dpack: Path) -> None:
        """Typing in the model input should show filtered results."""
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            model_input: Input = app.screen.query_one("#summarizer-model-input", Input)
            model_input.value = ""
            await pilot.pause(delay=PAUSE)
            model_input.value = "gemini"
            await pilot.pause(delay=PAUSE)
            group = app.screen.query_one("#model-selection-group")
            assert group.display is True
            ol: OptionList = app.screen.query_one("#summarizer-model-results", OptionList)
            assert ol.option_count > 0

    @pytest.mark.asyncio
    async def test_model_search_filters(self, dpack: Path) -> None:
        """Search should filter the model list."""
        app = CreateParallelAgentApp(str(dpack))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            model_input: Input = app.screen.query_one("#summarizer-model-input", Input)
            model_input.value = ""
            await pilot.pause(delay=PAUSE)
            model_input.value = "claude-opus"
            await pilot.pause(delay=PAUSE)
            ol: OptionList = app.screen.query_one("#summarizer-model-results", OptionList)
            # All results should contain "claude-opus"
            for i in range(ol.option_count):
                option_text: str = str(ol.get_option_at_index(i).prompt)
                assert "claude-opus" in option_text.lower()
