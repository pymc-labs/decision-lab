"""
Textual TUI wizard for creating a parallel agent configuration.

Single-screen wizard that collects configuration and writes a YAML file
to opencode/parallel_agents/{name}.yaml.
"""

import json
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    OptionList,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from textual import work

from dlab.config import load_dpack_config
from dlab.create_dpack import filter_models, get_model_list
from dlab.create_dpack_wizard import DpackCheckbox, FormScroll


# ---------------------------------------------------------------------------
# Default prompt templates
# ---------------------------------------------------------------------------

DEFAULT_SUFFIX_PROMPT: str = """\
When you complete your task, write a summary.md file with:

## Approach
Describe your approach and key decisions.

## Results
Present your findings and outputs.

## Recommendations
Provide actionable recommendations based on your analysis."""

DEFAULT_SUMMARIZER_PROMPT: str = """\
Read all summary.md files from the parallel instances.
Create a consolidated comparison highlighting:
- Key differences in approaches
- Agreement and disagreement across instances
- Overall recommendations based on all results"""

WORKER_AGENT_MD: str = """---
description: {description}
mode: subagent
tools:
  read: true
  edit: true
  bash: true
  parallel-agents: false
---

You are a worker agent. Complete the task described in the prompt.
"""

_NEW_AGENT_ID: str = "_new_agent"


# ---------------------------------------------------------------------------
# Main screen
# ---------------------------------------------------------------------------

class ParallelAgentScreen(Screen):
    """Single-screen wizard for parallel agent configuration."""

    CSS = """
    ParallelAgentScreen {
        align: left bottom;
    }
    #pa-container {
        width: 66%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
    }
    .field-label {
        margin-top: 1;
    }
    .field-hint {
        color: $text-muted;
        text-style: italic;
        text-wrap: wrap;
        width: 1fr;
    }
    .section-divider {
        margin-top: 1;
        color: $accent;
    }
    .error-label {
        color: $error;
    }
    .success-label {
        color: $success;
    }
    .nav-bar {
        margin-top: 1;
        height: 1;
        align: right middle;
    }
    #suffix-textarea, #summarizer-textarea {
        height: 8;
        border-left: tall $accent;
    }
    #retries-input {
        margin-left: 4;
    }
    #new-agent-name-input {
        margin-left: 4;
    }
    #model-selection-group {
        display: none;
    }
    #summarizer-model-results {
        height: auto;
        max-height: 12;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._existing_agents: list[str] = []
        self._default_model: str = ""
        self._models: list[str] = get_model_list()
        self._programmatic_fill: bool = False

    def compose(self) -> ComposeResult:
        with FormScroll(id="pa-container"):
            yield Label("[b]Create Parallel Agent[/b]", classes="field-label")
            yield Label("Tab / Shift+Tab to navigate  |  Ctrl+Q to quit", classes="field-hint")

            # Agent selection or creation
            yield Label("[b]Agent[/b]", classes="section-divider")
            yield Label(
                "Select an existing agent to run in parallel, or create a new one. "
                "The parallel config YAML will share the agent's name.",
                classes="field-hint",
            )
            with Vertical(classes="selection-group"):
                yield OptionList(id="agent-select")
                yield Label("Tab to continue", classes="option-hint")

            # New agent name (only shown when "New agent..." selected)
            yield Label("New agent name", classes="field-label", id="new-agent-label")
            yield Label("Alphanumeric, hyphens, underscores", classes="field-hint")
            yield Input(id="pa-name-input", placeholder="my-worker")
            yield Label("", id="pa-name-error", classes="error-label")
            yield Label(
                "A worker agent .md will be created in opencode/agents/",
                classes="field-hint",
                id="new-agent-hint",
            )

            # Description
            yield Label("[b]Description[/b]", classes="section-divider")
            yield Label(
                "Optional. Used in the YAML config for documentation purposes.",
                classes="field-hint",
            )
            yield Input(id="pa-desc-input", placeholder="(default: Parallel agent: {name})")

            # Timeout
            yield Label("[b]Instance Timeout[/b]", classes="section-divider")
            yield Label(
                "Maximum time each parallel instance is allowed to run before being stopped.",
                classes="field-hint",
            )
            yield Input(id="timeout-input", value="60", placeholder="60")

            # Failure behavior
            yield Label("[b]Instance Failure Behavior[/b]", classes="section-divider")
            yield Label(
                "What happens when one of the parallel instances fails or times out.",
                classes="field-hint",
            )
            with Vertical(classes="cb-group"):
                yield DpackCheckbox(
                    "Continue — other instances keep running",
                    value=True,
                    id="fail-continue",
                )
                yield DpackCheckbox(
                    "Fail fast — stop all instances on first failure",
                    value=False,
                    id="fail-fast",
                )
                yield DpackCheckbox(
                    "Retry — re-run failed instances",
                    value=False,
                    id="fail-retry",
                )
            yield Label("Max retries", classes="field-label", id="retries-label")
            yield Input(id="retries-input", value="2", placeholder="2")

            # Suffix prompt
            yield Label("[b]Suffix Prompt[/b]", classes="section-divider")
            yield Label(
                "Appended to each worker's prompt. Typically instructs writing summary.md.",
                classes="field-hint",
            )
            yield TextArea(DEFAULT_SUFFIX_PROMPT, id="suffix-textarea")

            # Consolidator prompt
            yield Label("[b]Consolidator Prompt[/b]", classes="section-divider")
            yield Label(
                "Given to the consolidator agent that reads all summary.md files and "
                "produces a combined report. Only runs when 3 or more instances are spawned.",
                classes="field-hint",
            )
            yield TextArea(DEFAULT_SUMMARIZER_PROMPT, id="summarizer-textarea")

            # Consolidator model
            yield Label("[b]Consolidator Model[/b]", classes="section-divider")
            yield Label(
                "Model used by the consolidator agent. Defaults to the decision-pack's default model.",
                classes="field-hint",
            )
            yield Input(id="summarizer-model-input", placeholder="(uses decision-pack default)")
            with Vertical(classes="selection-group", id="model-selection-group"):
                yield OptionList(id="summarizer-model-results")
                yield Label("Tab to continue", classes="option-hint")

            # Errors + nav
            yield Label("", id="pa-error", classes="error-label")
            with Horizontal(classes="nav-bar"):
                yield Button("Create", id="create-btn", variant="success")

    def on_mount(self) -> None:
        app: CreateParallelAgentApp = self.app  # type: ignore[assignment]
        self._default_model = app.dpack_config.get("default_model", "")
        self._programmatic_fill = True
        self.query_one("#summarizer-model-input", Input).value = self._default_model
        self._refresh_models()

        # Discover existing agents (exclude default agent)
        config_dir: Path = Path(app.dpack_config["config_dir"])
        agents_dir: Path = config_dir / "opencode" / "agents"
        default_agent: str = ""

        opencode_json: Path = config_dir / "opencode" / "opencode.json"
        if opencode_json.exists():
            try:
                data: dict[str, Any] = json.loads(opencode_json.read_text())
                default_agent = data.get("default_agent", "")
            except (json.JSONDecodeError, OSError):
                pass

        # Find which agents already have a parallel config
        pa_dir: Path = config_dir / "opencode" / "parallel_agents"
        existing_yamls: set[str] = set()
        if pa_dir.exists():
            for yaml_file in pa_dir.glob("*.yaml"):
                existing_yamls.add(yaml_file.stem)

        if agents_dir.exists():
            for md_file in sorted(agents_dir.glob("*.md")):
                agent_name: str = md_file.stem
                if agent_name != default_agent:
                    self._existing_agents.append(agent_name)

        # Build agent selection list
        ol: OptionList = self.query_one("#agent-select", OptionList)
        first_available: int = -1
        if self._existing_agents:
            for i, agent in enumerate(self._existing_agents):
                already_configured: bool = agent in existing_yamls
                label: str = f"{agent} [dim](already configured)[/dim]" if already_configured else agent
                ol.add_option(Option(label, id=agent, disabled=already_configured))
                if not already_configured and first_available < 0:
                    first_available = i
        ol.add_option(Option("New agent...", id=_NEW_AGENT_ID))

        # Default: first available existing agent, or "New agent..."
        if first_available >= 0:
            ol.highlighted = first_available
            self._show_new_agent_fields(False)
        else:
            ol.highlighted = ol.option_count - 1
            self._show_new_agent_fields(True)

        # Hide retries by default (continue is selected)
        self._update_retries_visibility()

        self.query_one("#pa-name-input", Input).focus()

    def _show_new_agent_fields(self, show: bool) -> None:
        self.query_one("#new-agent-label", Label).display = show
        self.query_one("#pa-name-input", Input).display = show
        self.query_one("#new-agent-hint", Label).display = show
        # pa-error stays visible always (used for all validation errors)

    def _update_retries_visibility(self) -> None:
        retry: bool = self.query_one("#fail-retry", Checkbox).value
        self.query_one("#retries-input", Input).display = retry
        self.query_one("#retries-label", Label).display = retry

    @work(thread=True)
    def _refresh_models(self) -> None:
        """Fetch models from API in background and refresh the list."""
        from dlab.create_dpack import fetch_models_from_api, save_model_cache, _model_sort_key
        try:
            data: dict[str, Any] = fetch_models_from_api()
            save_model_cache(data)
            new_models: list[str] = sorted(
                set(self._models) | set(data.get("models", [])),
                key=_model_sort_key,
            )
            if new_models != self._models:
                self._models = new_models
                self.app.call_from_thread(self._rebuild_model_options, "")
        except Exception:
            pass

    def _rebuild_model_options(self, query: str) -> None:
        """Rebuild the model OptionList filtered by query."""
        matches: list[str] = filter_models(query, self._models) if query else self._models
        ol: OptionList = self.query_one("#summarizer-model-results", OptionList)
        ol.clear_options()
        for m in matches:
            ol.add_option(Option(m, id=m))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "summarizer-model-input":
            return
        if self._programmatic_fill:
            self._programmatic_fill = False
            return
        group: Vertical = self.query_one("#model-selection-group", Vertical)
        group.display = True
        self._rebuild_model_options(event.value.strip())

    def _get_selected_agent(self) -> str | None:
        """Return the currently highlighted agent ID, or None."""
        ol: OptionList = self.query_one("#agent-select", OptionList)
        idx: int | None = ol.highlighted
        if idx is None:
            return None
        return str(ol.get_option_at_index(idx).id)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id != "agent-select":
            return
        is_new: bool = str(event.option.id) == _NEW_AGENT_ID
        self._show_new_agent_fields(is_new)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "summarizer-model-results":
            return
        self._programmatic_fill = True
        self.query_one("#summarizer-model-input", Input).value = str(event.option.prompt)
        self.query_one("#model-selection-group", Vertical).display = False
        self.query_one("#create-btn", Button).focus()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        # Radio group for failure behavior
        radio_ids: list[str] = ["fail-continue", "fail-fast", "fail-retry"]
        if event.checkbox.id in radio_ids and event.value:
            for rid in radio_ids:
                if rid != event.checkbox.id:
                    self.query_one(f"#{rid}", Checkbox).value = False
            self._update_retries_visibility()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "create-btn":
            return

        error_label: Label = self.query_one("#pa-error", Label)
        name_error_label: Label = self.query_one("#pa-name-error", Label)
        name_error_label.update("")

        # Determine agent name
        selected_agent: str | None = self._get_selected_agent()
        create_new_agent: bool = selected_agent == _NEW_AGENT_ID
        agent_name: str

        if create_new_agent:
            agent_name = self.query_one("#pa-name-input", Input).value.strip()
            if not agent_name:
                name_error_label.update("[red]Agent name is required[/red]")
                return
            if not agent_name.replace("_", "").replace("-", "").isalnum():
                name_error_label.update("[red]Must be alphanumeric (with - or _)[/red]")
                return
        else:
            agent_name = selected_agent or ""
            if not agent_name:
                error_label.update("[red]Select an agent[/red]")
                return

        error_label.update("")

        # Validate timeout
        timeout_str: str = self.query_one("#timeout-input", Input).value.strip()
        try:
            timeout: int = int(timeout_str) if timeout_str else 60
            if timeout <= 0:
                raise ValueError
        except ValueError:
            error_label.update("[red]Timeout must be a positive number[/red]")
            return

        # Gather values
        description: str = self.query_one("#pa-desc-input", Input).value.strip()
        if not description:
            description = f"Parallel agent: {agent_name}"

        failure_behavior: str = "continue"
        if self.query_one("#fail-fast", Checkbox).value:
            failure_behavior = "fail_fast"
        elif self.query_one("#fail-retry", Checkbox).value:
            failure_behavior = "retry"

        max_retries: int = 2
        if failure_behavior == "retry":
            retries_str: str = self.query_one("#retries-input", Input).value.strip()
            try:
                max_retries = int(retries_str) if retries_str else 2
            except ValueError:
                max_retries = 2

        suffix_prompt: str = self.query_one("#suffix-textarea", TextArea).text
        summarizer_prompt: str = self.query_one("#summarizer-textarea", TextArea).text
        summarizer_model: str = self.query_one("#summarizer-model-input", Input).value.strip()
        if not summarizer_model:
            summarizer_model = self._default_model

        # Build YAML
        yaml_lines: list[str] = [
            f"name: {agent_name}",
            f'description: "{description}"',
            f"timeout_minutes: {timeout}",
            f"failure_behavior: {failure_behavior}",
        ]
        if failure_behavior == "retry":
            yaml_lines.append(f"max_retries: {max_retries}")

        yaml_lines.append("")
        yaml_lines.append("subagent_suffix_prompt: |")
        for line in suffix_prompt.split("\n"):
            yaml_lines.append(f"  {line}")

        yaml_lines.append("")
        yaml_lines.append("summarizer_prompt: |")
        for line in summarizer_prompt.split("\n"):
            yaml_lines.append(f"  {line}")

        yaml_lines.append("")
        yaml_lines.append(f'summarizer_model: "{summarizer_model}"')
        yaml_lines.append("")

        yaml_content: str = "\n".join(yaml_lines)

        # Write files
        app: CreateParallelAgentApp = self.app  # type: ignore[assignment]
        config_dir: Path = Path(app.dpack_config["config_dir"])
        pa_dir: Path = config_dir / "opencode" / "parallel_agents"
        pa_dir.mkdir(parents=True, exist_ok=True)

        yaml_file: Path = pa_dir / f"{agent_name}.yaml"
        if yaml_file.exists():
            error_label.update(f"[red]{agent_name}.yaml already exists[/red]")
            return

        yaml_file.write_text(yaml_content)
        created_files: list[str] = [str(yaml_file.relative_to(config_dir))]

        # Create agent .md if "New agent..." was selected
        if create_new_agent:
            agents_dir: Path = config_dir / "opencode" / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            agent_file: Path = agents_dir / f"{agent_name}.md"
            if not agent_file.exists():
                agent_file.write_text(
                    WORKER_AGENT_MD.format(description=description)
                )
                created_files.append(str(agent_file.relative_to(config_dir)))

        # Exit app with created files list
        app.created_files = created_files
        app.exit()


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class CreateParallelAgentApp(App):
    """TUI wizard for creating a parallel agent configuration."""

    TITLE = "dlab create-parallel-agent"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("down", "focus_next", show=False),
        Binding("up", "focus_previous", show=False),
    ]
    theme = "monokai"

    CSS = """
    /* --- Flat widget overrides ------------------------------------------ */
    Input {
        border: none;
        border-left: tall $accent;
        height: 1;
        padding: 0 1;
        background: $surface;
        &:focus {
            border: none;
            border-left: tall $accent;
        }
    }
    Button {
        min-width: 10;
        border: none;
        background: $surface;
        &:hover {
            background: $primary;
        }
        &.-success {
            background: $success-muted;
            border: none;
            &:hover { background: $success; border: none; }
        }
    }
    OptionList {
        border: none;
        border-left: tall $accent;
        background: $surface;
        scrollbar-size: 1 1;
    }
    Checkbox {
        border: none;
        background: transparent;
        height: 1;
        padding: 0;
    }
    Checkbox > .toggle--button {
        color: $text-muted;
    }
    Checkbox.-on > .toggle--button {
        color: $success;
    }
    .cb-group {
        border-left: tall $accent;
        background: $surface;
        padding: 0 1;
        height: auto;
    }
    .selection-group {
        height: auto;
    }
    .option-hint {
        display: none;
        color: $text-muted;
        text-style: italic;
        height: 1;
    }
    .selection-group:focus-within .option-hint {
        display: block;
    }
    """

    def __init__(self, dpack: str = ".") -> None:
        super().__init__()
        self.dpack: str = dpack
        self.dpack_config: dict[str, Any] = load_dpack_config(dpack)
        self.created_files: list[str] = []

    def on_mount(self) -> None:
        self.push_screen(ParallelAgentScreen())
