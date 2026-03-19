"""
Textual TUI wizard for creating a new decision-pack directory.

Multi-screen wizard that collects configuration and calls generate_dpack().
"""

import shutil
from pathlib import Path
from typing import Any

from textual import work
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import Screen


class FormScroll(VerticalScroll, can_focus=False):
    """VerticalScroll that doesn't consume arrow keys.

    Overrides scroll actions to raise SkipAction, so arrow keys pass through
    to app-level focus navigation. Still scrolls into view automatically
    when children receive focus.
    """

    def action_scroll_up(self) -> None:
        raise SkipAction()

    def action_scroll_down(self) -> None:
        raise SkipAction()

    def action_scroll_left(self) -> None:
        raise SkipAction()

    def action_scroll_right(self) -> None:
        raise SkipAction()
from textual.style import Style
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    ListItem,
    ListView,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option

class BackButton(Button, can_focus=False):
    """Back button that is clickable but skipped in focus/Tab navigation."""


from dlab.create_dpack import (
    CONFIGURABLE_PERMISSIONS,
    HIGH_IMPACT_PERMISSION_COUNT,
    KNOWN_BASE_IMAGES,
    PACKAGE_MANAGER_BASE_IMAGES,
    ask_skills,
    filter_models,
    generate_dpack,
    get_model_list,
    validate_dpack_name,
)


# ---------------------------------------------------------------------------
# Custom checkbox with ▢/▣ glyphs
# ---------------------------------------------------------------------------

class DpackCheckbox(Checkbox):
    """Checkbox with ▢ (unchecked) and ▣ (checked) glyphs."""

    BUTTON_LEFT: str = ""
    BUTTON_RIGHT: str = ""

    BINDINGS = [
        Binding("tab", "tab_out", show=False),
    ]

    @property
    def _button(self) -> Content:
        button_style = self.get_visual_style("toggle--button")
        glyph: str = "▣" if self.value else "▢"
        return Content.assemble((glyph, button_style))

    def action_tab_out(self) -> None:
        """Tab jumps out of cb-group container to next element outside."""
        # Walk up to find cb-group parent
        cb_group = self.parent
        while cb_group and not cb_group.has_class("cb-group"):
            cb_group = cb_group.parent
        if cb_group:
            # Find first focusable widget after self that is NOT inside this cb-group
            found_self: bool = False
            for widget in self.screen.focus_chain:
                if widget is self:
                    found_self = True
                    continue
                if found_self and cb_group not in widget.ancestors:
                    widget.focus()
                    return
        # Fallback: default focus_next
        self.screen.focus_next()


# ---------------------------------------------------------------------------
# Screen 1: Basics
# ---------------------------------------------------------------------------

class BasicsScreen(Screen):
    """Collect decision-pack name and description."""

    CSS = """
    BasicsScreen {
        align: left bottom;
    }
    #basics-container {
        width: 66%;
        height: auto;
        padding: 1 2;
    }
    .field-label {
        margin-top: 1;
        color: $text;
    }
    .field-hint {
        color: $text-muted;
        text-style: italic;
        margin-bottom: 0;
        text-wrap: wrap;
        width: 1fr;
    }
    .error-label {
        color: $error;
    }
    .nav-bar {
        margin-top: 1;
        height: 1;
        align: right middle;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="basics-container"):
            yield Label("[b]Step 1 of 8[/b] — Basics", classes="field-label")
            yield Label("Tab / Shift+Tab to navigate  |  Ctrl+Q to quit", classes="field-hint")
            yield Label("decision-pack name", classes="field-label")
            yield Label("Alphanumeric, hyphens, underscores", classes="field-hint")
            yield Input(id="name-input", placeholder="my-dpack")
            with Horizontal(id="collision-bar"):
                yield Label("", id="name-error", classes="error-label")
                yield Button("Delete & Overwrite", id="overwrite-btn", variant="error")

            yield Label("Description", classes="field-label")
            yield Input(id="desc-input", placeholder="(default: dlab decision-pack: {name})")

            yield Label("CLI name", classes="field-label")
            yield Label("Override command name when installed (default: decision-pack name)", classes="field-hint")
            yield Input(id="cli-name-input", placeholder="(same as decision-pack name)")

            with Horizontal(classes="nav-bar"):
                yield Button("Next →", id="next-btn")

    def on_mount(self) -> None:
        state: dict[str, Any] = self.app.wizard_state
        if state.get("name"):
            self.query_one("#name-input", Input).value = state["name"]
        if state.get("description"):
            self.query_one("#desc-input", Input).value = state["description"]
        if state.get("cli_name"):
            self.query_one("#cli-name-input", Input).value = state["cli_name"]
        self.query_one("#overwrite-btn", Button).display = False
        self.query_one("#name-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "name-input":
            self.query_one("#overwrite-btn", Button).display = False
            self.app.wizard_state.pop("overwrite_existing", None)
            self.query_one("#name-error", Label).update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "overwrite-btn":
            self.app.wizard_state["overwrite_existing"] = True
            self.query_one("#name-error", Label).update("[green]decision-pack will be overwritten[/green]")
            self.query_one("#overwrite-btn", Button).display = False
            return

        if event.button.id != "next-btn":
            return

        name: str = self.query_one("#name-input", Input).value.strip()
        error: str | None = validate_dpack_name(name)
        error_label: Label = self.query_one("#name-error", Label)
        if error:
            error_label.update(f"[red]{error}[/red]")
            return

        # Check for existing decision-pack
        dpack_dir: Path = Path(self.app.output_dir) / name
        if dpack_dir.exists() and not self.app.wizard_state.get("overwrite_existing"):
            error_label.update("[red]decision-pack already exists.[/red]")
            self.query_one("#overwrite-btn", Button).display = True
            return

        error_label.update("")

        desc: str = self.query_one("#desc-input", Input).value.strip()

        state: dict[str, Any] = self.app.wizard_state
        state["name"] = name
        state["description"] = desc or f"dlab decision-pack: {name}"
        state["cli_name"] = self.query_one("#cli-name-input", Input).value.strip()

        self.app.push_screen(ContainerScreen())


# ---------------------------------------------------------------------------
# Screen 2: Container setup
# ---------------------------------------------------------------------------

class ContainerScreen(Screen):
    """Choose package manager and base image."""

    BINDINGS = [Binding("escape", "go_back", "Back")]

    CSS = """
    ContainerScreen {
        align: left bottom;
    }
    #container-container {
        width: 66%;
        height: auto;
        max-height: 80%;
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
    .cb-desc {
        color: $text-muted;
        text-style: italic;
        padding-left: 4;
        margin-bottom: 0;
        text-wrap: wrap;
        width: 1fr;
    }
    .nav-bar {
        margin-top: 1;
        height: 1;
        align: right middle;
    }
    #base-image-list {
        height: auto;
        max-height: 8;
        margin-top: 1;
        scrollbar-size: 1 1;
    }
    """

    PKG_MGR_OPTIONS: list[tuple[str, str, str]] = [
        ("conda", "conda (Recommended)",
         "Miniconda base image. Creates environment.yml with conda-forge channel. "
         "Best for scientific Python (BLAS, PyMC, JAX, etc.)"),
        ("pip", "pip",
         "Python slim base image. Creates requirements.txt. "
         "Simplest option for most projects."),
        ("uv", "uv",
         "Python slim base image with uv. Creates requirements.txt. "
         "Fast dependency resolution, drop-in pip replacement."),
        ("pixi", "pixi",
         "Debian base with pixi. Creates pixi.toml. "
         "Modern conda-forge workflow with lockfile support."),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._programmatic_fill: bool = False

    def compose(self) -> ComposeResult:
        with FormScroll(id="container-container"):
            yield Label("[b]Step 2 of 8[/b] — Container Setup", classes="field-label")
            yield Label("Tab / Shift+Tab to navigate  |  Ctrl+Q to quit", classes="field-hint")

            yield Label("[b]Package Manager[/b]", classes="field-label")
            with Vertical(classes="cb-group"):
                for key, label, desc in self.PKG_MGR_OPTIONS:
                    yield DpackCheckbox(
                        label,
                        value=(key == "conda"),
                        id=f"pkg-{key}",
                    )
                    yield Label(desc, classes="cb-desc")

            yield Label("[b]Base Image[/b]", classes="field-label")
            yield Label("Select or enter a custom Docker base image", classes="field-hint")
            yield Input(id="base-image-input", placeholder="python:3.11-slim")
            with Vertical(classes="selection-group"):
                yield OptionList(
                    *[Option(img, id=img) for img in KNOWN_BASE_IMAGES],
                    id="base-image-list",
                )
                yield Label("Tab to continue", classes="option-hint")

            with Horizontal(classes="nav-bar nav-swap"):
                yield Button("Next →", id="next-btn")
                yield Button("← Back", id="back-btn")

    def on_mount(self) -> None:
        state: dict[str, Any] = self.app.wizard_state
        # Restore package manager selection
        pkg_mgr: str = state.get("package_manager", "conda")
        for key, _, _ in self.PKG_MGR_OPTIONS:
            self.query_one(f"#pkg-{key}", Checkbox).value = (key == pkg_mgr)

        # Set base image from state or default for package manager
        base_image: str = state.get("base_image", PACKAGE_MANAGER_BASE_IMAGES.get(pkg_mgr, "python:3.11-slim"))
        self._programmatic_fill = True
        self.query_one("#base-image-input", Input).value = base_image

        self.query_one(f"#pkg-{pkg_mgr}", Checkbox).focus()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        # Radio group for package manager
        pkg_ids: list[str] = [f"pkg-{k}" for k, _, _ in self.PKG_MGR_OPTIONS]
        if event.checkbox.id in pkg_ids and event.value:
            for pid in pkg_ids:
                if pid != event.checkbox.id:
                    self.query_one(f"#{pid}", Checkbox).value = False
            # Update base image to default for selected package manager
            pkg_mgr: str = event.checkbox.id.removeprefix("pkg-")
            default_image: str = PACKAGE_MANAGER_BASE_IMAGES.get(pkg_mgr, "python:3.11-slim")
            self._programmatic_fill = True
            self.query_one("#base-image-input", Input).value = default_image

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "base-image-list":
            self._programmatic_fill = True
            self.query_one("#base-image-input", Input).value = str(event.option.id)
            self.screen.focus_next()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "base-image-input":
            return
        if self._programmatic_fill:
            self._programmatic_fill = False
            return
        # Filter base image list
        query: str = event.value.strip().lower()
        ol: OptionList = self.query_one("#base-image-list", OptionList)
        ol.clear_options()
        for img in KNOWN_BASE_IMAGES:
            if not query or query in img.lower():
                ol.add_option(Option(img, id=img))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
            return
        if event.button.id != "next-btn":
            return

        state: dict[str, Any] = self.app.wizard_state

        # Get selected package manager from radio checkboxes
        pkg_mgr: str = "conda"
        for key, _, _ in self.PKG_MGR_OPTIONS:
            if self.query_one(f"#pkg-{key}", Checkbox).value:
                pkg_mgr = key
                break

        state["package_manager"] = pkg_mgr

        # Get base image (from input, not from package manager default)
        base_image: str = self.query_one("#base-image-input", Input).value.strip()
        if not base_image:
            base_image = PACKAGE_MANAGER_BASE_IMAGES.get(pkg_mgr, "python:3.11-slim")
        state["base_image"] = base_image

        self.app.push_screen(FeaturesScreen())

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Screen 3: Additional features
# ---------------------------------------------------------------------------

class FeaturesScreen(Screen):
    """Configure additional features: dhub, python lib, modal, requires_data."""

    BINDINGS = [Binding("escape", "go_back", "Back")]

    CSS = """
    FeaturesScreen {
        align: left bottom;
    }
    #features-container {
        width: 66%;
        height: auto;
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
    .cb-desc {
        color: $text-muted;
        text-style: italic;
        padding-left: 4;
        margin-bottom: 0;
        text-wrap: wrap;
        width: 1fr;
    }
    .nav-bar {
        margin-top: 1;
        height: 1;
        align: right middle;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="features-container"):
            yield Label("[b]Step 3 of 8[/b] — Additional Features", classes="field-label")
            yield Label("Tab / Shift+Tab to navigate  |  Ctrl+Q to quit", classes="field-hint")

            with Vertical(classes="cb-group"):
                yield DpackCheckbox(
                    "Decision Hub integration",
                    value=True,
                    id="dhub-cb",
                )
                yield Label(
                    "The agent can dynamically search hub.decision.ai for skills "
                    "and install them at runtime. Adds dhub-cli to container dependencies.",
                    classes="cb-desc",
                )
                yield DpackCheckbox(
                    "Python library — create a {name}_lib/ package in docker/",
                    value=False,
                    id="python-lib-cb",
                )
                yield Label(
                    "Adds {name}_lib/__init__.py, COPY + PYTHONPATH in Dockerfile.",
                    classes="cb-desc",
                )
                yield DpackCheckbox(
                    "Modal integration — create docker/modal_app/ with example script",
                    value=False,
                    id="modal-cb",
                )
                yield Label(
                    "For serverless cloud execution (e.g. heavy compute).",
                    classes="cb-desc",
                )
                yield DpackCheckbox(
                    "Requires data directory — agent needs --data to run",
                    value=True,
                    id="requires-data-cb",
                )
                yield Label(
                    "If unchecked, --data becomes optional when running this decision-pack.",
                    classes="cb-desc",
                )
                yield DpackCheckbox(
                    "Requires prompt — agent needs --prompt or --prompt-file to run",
                    value=True,
                    id="requires-prompt-cb",
                )
                yield Label(
                    "If unchecked, --prompt becomes optional (useful for fully automated decision-packs).",
                    classes="cb-desc",
                )

            with Horizontal(classes="nav-bar nav-swap"):
                yield Button("Next →", id="next-btn")
                yield Button("← Back", id="back-btn")

    def on_mount(self) -> None:
        state: dict[str, Any] = self.app.wizard_state
        if state.get("dhub_integration") is not None:
            self.query_one("#dhub-cb", Checkbox).value = state["dhub_integration"]
        if state.get("python_lib") is not None:
            self.query_one("#python-lib-cb", Checkbox).value = state["python_lib"]
        if state.get("modal_integration") is not None:
            self.query_one("#modal-cb", Checkbox).value = state["modal_integration"]
        if state.get("requires_data") is not None:
            self.query_one("#requires-data-cb", Checkbox).value = state["requires_data"]
        if state.get("requires_prompt") is not None:
            self.query_one("#requires-prompt-cb", Checkbox).value = state["requires_prompt"]
        self.query_one("#dhub-cb", Checkbox).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
            return
        if event.button.id != "next-btn":
            return

        state: dict[str, Any] = self.app.wizard_state
        name: str = state.get("name", "dpack")

        state["dhub_integration"] = self.query_one("#dhub-cb", Checkbox).value

        python_lib: bool = self.query_one("#python-lib-cb", Checkbox).value
        state["python_lib"] = python_lib
        state["python_lib_name"] = name.replace("-", "_") + "_lib" if python_lib else ""

        state["modal_integration"] = self.query_one("#modal-cb", Checkbox).value
        state["requires_data"] = self.query_one("#requires-data-cb", Checkbox).value
        state["requires_prompt"] = self.query_one("#requires-prompt-cb", Checkbox).value

        self.app.push_screen(ModelScreen())

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Screen 3: Model selection
# ---------------------------------------------------------------------------

class ModelScreen(Screen):
    """Select default model with live filtering."""

    BINDINGS = [Binding("escape", "go_back", "Back")]

    CSS = """
    ModelScreen {
        align: left bottom;
    }
    #model-container {
        width: 66%;
        height: auto;
        padding: 1 2;
    }
    #model-results {
        height: auto;
        max-height: 18;
    }
    .nav-bar {
        margin-top: 1;
        height: 1;
        align: right middle;
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
    """

    def __init__(self) -> None:
        super().__init__()
        self._models: list[str] = get_model_list()
        self._programmatic_fill: bool = False

    def compose(self) -> ComposeResult:
        with Vertical(id="model-container"):
            yield Label("[b]Step 4 of 8[/b] — Default Model", classes="field-label")
            yield Label("Tab / Shift+Tab to navigate  |  Ctrl+Q to quit", classes="field-hint")
            yield Label("Type to filter, or enter a custom model name", classes="field-hint")
            yield Input(id="model-input", placeholder="opencode/big-pickle")
            with Vertical(classes="selection-group"):
                yield OptionList(
                    *[Option(m, id=m) for m in self._models],
                    id="model-results",
                )
                yield Label("Tab to continue", classes="option-hint")
            with Horizontal(classes="nav-bar nav-swap"):
                yield Button("Next →", id="next-btn")
                yield Button("← Back", id="back-btn")

    def on_mount(self) -> None:
        state: dict[str, Any] = self.app.wizard_state
        if state.get("default_model"):
            self._programmatic_fill = True
            self.query_one("#model-input", Input).value = state["default_model"]
        self.query_one("#model-input", Input).focus()
        self._refresh_models()

    @work(thread=True)
    def _refresh_models(self) -> None:
        """Fetch models from API in background and refresh the list."""
        from dlab.create_dpack import fetch_models_from_api, save_model_cache
        try:
            data: dict[str, Any] = fetch_models_from_api()
            save_model_cache(data)
            from dlab.create_dpack import _model_sort_key
            new_models: list[str] = sorted(set(self._models) | set(data.get("models", [])), key=_model_sort_key)
            if new_models != self._models:
                self._models = new_models
                self.app.call_from_thread(self._rebuild_options, "")
        except Exception:
            pass  # Network failure is fine — we have cached/hardcoded models

    def _rebuild_options(self, query: str) -> None:
        """Rebuild the OptionList with current model list, filtered by query."""
        matches: list[str] = filter_models(query, self._models) if query else self._models
        ol: OptionList = self.query_one("#model-results", OptionList)
        ol.clear_options()
        for m in matches:
            ol.add_option(Option(m, id=m))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "model-input":
            return
        if self._programmatic_fill:
            self._programmatic_fill = False
            return
        self._rebuild_options(event.value.strip())

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "model-results":
            return
        self._programmatic_fill = True
        self.query_one("#model-input", Input).value = str(event.option.prompt)
        self.query_one("#next-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
            return
        if event.button.id != "next-btn":
            return

        model: str = self.query_one("#model-input", Input).value.strip()
        if not model:
            model = "opencode/big-pickle"

        self.app.wizard_state["default_model"] = model
        self.app.push_screen(PermissionsScreen())

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Screen 4: Permissions
# ---------------------------------------------------------------------------

class PermissionsScreen(Screen):
    """Configure opencode.json permissions."""

    BINDINGS = [Binding("escape", "go_back", "Back")]

    CSS = """
    PermissionsScreen {
        align: left bottom;
    }
    #perms-container {
        width: 66%;
        height: auto;
        max-height: 80%;
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
    .cb-desc {
        color: $text-muted;
        text-style: italic;
        padding-left: 4;
        margin-bottom: 0;
        text-wrap: wrap;
        width: 1fr;
    }
    .section-divider {
        margin-top: 1;
        color: $accent;
    }
    .cb-group {
        height: auto;
    }
    .nav-bar {
        margin-top: 1;
        height: 1;
        align: right middle;
    }
    """

    def compose(self) -> ComposeResult:
        with FormScroll(id="perms-container"):
            yield Label("[b]Step 5 of 8[/b] — Permissions", classes="field-label")
            yield Label("Tab / Shift+Tab to navigate  |  Ctrl+Q to quit", classes="field-hint")
            yield Label(
                "These permissions are written to opencode.json and apply project-wide. "
                "In automated mode (opencode run), every permission must be explicitly "
                "allow or deny — there is no interactive approval prompt.",
                classes="field-hint",
            )
            yield Label(
                "Each agent's .md frontmatter has a tools: section that can further "
                "restrict permissions per-agent (overrides opencode.json). "
                "Subagent permissions are controlled in their own .md frontmatter.",
                classes="field-hint",
            )

            yield Label("[b]High-impact[/b]", classes="section-divider")
            with Vertical(classes="cb-group"):
                for key, label, desc, default in CONFIGURABLE_PERMISSIONS[:HIGH_IMPACT_PERMISSION_COUNT]:
                    yield DpackCheckbox(label, value=(default == "allow"), id=f"perm-{key}")
                    yield Label(desc, classes="cb-desc")

            yield Label("[b]Internal/basic[/b]", classes="section-divider")
            with Vertical(classes="cb-group"):
                for key, label, desc, default in CONFIGURABLE_PERMISSIONS[HIGH_IMPACT_PERMISSION_COUNT:]:
                    yield DpackCheckbox(label, value=(default == "allow"), id=f"perm-{key}")
                    yield Label(desc, classes="cb-desc")

            with Horizontal(classes="nav-bar nav-swap"):
                yield Button("Next →", id="next-btn")
                yield Button("← Back", id="back-btn")

    def on_mount(self) -> None:
        state: dict[str, Any] = self.app.wizard_state
        perms: dict[str, str] = state.get("permissions", {})

        for key, _label, _desc, _default in CONFIGURABLE_PERMISSIONS:
            if key in perms:
                self.query_one(f"#perm-{key}", Checkbox).value = (perms[key] == "allow")

        first_key: str = CONFIGURABLE_PERMISSIONS[0][0]
        self.query_one(f"#perm-{first_key}", Checkbox).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
            return
        if event.button.id != "next-btn":
            return

        perms: dict[str, str] = {}
        for key, _label, _desc, _default in CONFIGURABLE_PERMISSIONS:
            checked: bool = self.query_one(f"#perm-{key}", Checkbox).value
            perms[key] = "allow" if checked else "deny"
        self.app.wizard_state["permissions"] = perms

        self.app.push_screen(SkeletonsScreen())

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Screen 5: Directory skeletons
# ---------------------------------------------------------------------------

class SkeletonsScreen(Screen):
    """Select which opencode directory skeletons to scaffold."""

    BINDINGS = [Binding("escape", "go_back", "Back")]

    CSS = """
    SkeletonsScreen {
        align: left bottom;
    }
    #skeletons-container {
        width: 66%;
        height: auto;
        max-height: 80%;
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
    .cb-desc {
        color: $text-muted;
        text-style: italic;
        padding-left: 4;
        margin-bottom: 0;
        text-wrap: wrap;
        width: 1fr;
    }
    .nav-bar {
        margin-top: 1;
        height: 1;
        align: right middle;
    }
    """

    def compose(self) -> ComposeResult:
        with FormScroll(id="skeletons-container"):
            yield Label("[b]Step 6 of 8[/b] — Directory Skeletons", classes="field-label")
            yield Label("Tab / Shift+Tab to navigate  |  Ctrl+Q to quit", classes="field-hint")
            yield Label(
                "Scaffold opencode directories with example files. "
                "All are enabled by default — disable the ones you don't need.",
                classes="field-hint",
            )

            with Vertical(classes="cb-group"):
                yield DpackCheckbox(
                    "Skills — knowledge files the agent can reference (opencode/skills/)",
                    value=True,
                    id="skel-skills",
                )
                yield Label(
                    "Add domain-specific knowledge, API references, or best practices.",
                    classes="cb-desc",
                )
                yield DpackCheckbox(
                    "Tools — custom TypeScript tools (opencode/tools/)",
                    value=True,
                    id="skel-tools",
                )
                yield Label(
                    "Extend the agent with custom tools written in TypeScript.",
                    classes="cb-desc",
                    id="skel-tools-desc",
                )
                yield DpackCheckbox(
                    "Subagents — additional agents the main agent can delegate to",
                    value=True,
                    id="skel-subagents",
                )
                yield Label(
                    "Create an example subagent .md file in opencode/agents/.",
                    classes="cb-desc",
                )
                yield DpackCheckbox(
                    "Parallel subagents — run multiple subagent instances simultaneously",
                    value=True,
                    id="skel-parallel",
                )
                yield Label(
                    "Adds parallel agent YAML config + parallel-agents tool to the main agent. "
                    "Requires subagents (auto-enabled).",
                    classes="cb-desc",
                )

            with Horizontal(classes="nav-bar nav-swap"):
                yield Button("Next →", id="next-btn")
                yield Button("← Back", id="back-btn")

    def on_mount(self) -> None:
        state: dict[str, Any] = self.app.wizard_state
        skels: dict[str, bool] = state.get("skeletons", {})

        # Restore from state if going back (skels may have False values)
        if skels:
            self.query_one("#skel-skills", Checkbox).value = skels.get("skills", True)
            self.query_one("#skel-tools", Checkbox).value = skels.get("tools", True)
            self.query_one("#skel-subagents", Checkbox).value = skels.get("subagents", True)
            self.query_one("#skel-parallel", Checkbox).value = skels.get("parallel_agents", True)

        # Modal integration requires tools
        if state.get("modal_integration"):
            tools_cb: Checkbox = self.query_one("#skel-tools", Checkbox)
            tools_cb.value = True
            tools_cb.disabled = True
            self.query_one("#skel-tools-desc", Label).update(
                "Required by Modal integration (includes run-on-modal tool)."
            )

        # Decision Hub integration requires skills
        if state.get("dhub_integration"):
            skills_cb: Checkbox = self.query_one("#skel-skills", Checkbox)
            skills_cb.value = True
            skills_cb.disabled = True

        self.query_one("#skel-skills", Checkbox).focus()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        # parallel implies subagents
        if event.checkbox.id == "skel-parallel" and event.value:
            self.query_one("#skel-subagents", Checkbox).value = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
            return
        if event.button.id != "next-btn":
            return

        self.app.wizard_state["skeletons"] = {
            "skills": self.query_one("#skel-skills", Checkbox).value,
            "tools": self.query_one("#skel-tools", Checkbox).value,
            "subagents": self.query_one("#skel-subagents", Checkbox).value,
            "parallel_agents": self.query_one("#skel-parallel", Checkbox).value,
        }

        # Skip skill search if skills not selected
        if self.app.wizard_state["skeletons"]["skills"]:
            self.app.push_screen(SkillSearchScreen())
        else:
            self.app.push_screen(SummaryScreen())

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Screen 6: Skill search (Decision Hub)
# ---------------------------------------------------------------------------

class SkillSearchScreen(Screen):
    """Search and select skills from Decision Hub.

    Two search mechanisms feed into the same results list:
    - Keyword search (Enter in the input) — via /v1/skills
    - Natural-language "ask" (automatic on mount from description) — via /v1/ask
    """

    BINDINGS = [Binding("escape", "go_back", "Back")]

    CSS = """
    SkillSearchScreen {
        align: left bottom;
    }
    #skill-container {
        width: 66%;
        height: auto;
        max-height: 80%;
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
    #skill-results {
        height: auto;
        max-height: 14;
        display: none;
    }
    #selected-skills {
        height: auto;
        max-height: 6;
        display: none;
    }
    .nav-bar {
        margin-top: 1;
        height: 1;
        align: right middle;
    }
    .status-label {
        color: $text-muted;
        margin-top: 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._results: list[dict[str, Any]] = []
        self._selected: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with FormScroll(id="skill-container"):
            yield Label("[b]Step 7 of 8[/b] — Decision Hub Skills", classes="field-label")
            yield Label("Tab / Shift+Tab to navigate  |  Ctrl+Q to quit", classes="field-hint")
            yield Label(
                "Search for skills to include in your decision-pack. "
                "Describe what you need and press Enter. "
                "You can skip this step.",
                classes="field-hint",
            )
            yield Label("")
            yield Input(id="skill-search-input", placeholder="Describe what skills you need...")
            yield Label("", id="search-status", classes="status-label")
            with Vertical(classes="selection-group"):
                yield OptionList(id="skill-results")
                yield Label("Tab to continue", classes="option-hint")

            yield Label("Selected skills:", classes="field-label")
            with Vertical(classes="selection-group"):
                yield OptionList(id="selected-skills")
                yield Label("Tab to continue", classes="option-hint")

            with Horizontal(classes="nav-bar nav-swap"):
                yield Button("Skip →", id="next-btn")
                yield Button("← Back", id="back-btn")

    def on_mount(self) -> None:
        state: dict[str, Any] = self.app.wizard_state
        self._selected = list(state.get("selected_skills", []))
        self._refresh_selected_display()

        search_input: Input = self.query_one("#skill-search-input", Input)

        # If the user wrote a custom description, use it for
        # automatic skill recommendations on mount.
        desc: str = state.get("description", "")
        name: str = state.get("name", "")
        auto_desc: str = f"dlab decision-pack: {name}"
        if desc and desc != auto_desc:
            search_input.value = desc
            self._do_search(desc)

        search_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "skill-search-input":
            return
        query: str = event.value.strip()
        if not query:
            return
        self._do_search(query)

    @work(thread=True)
    def _do_search(self, query: str) -> None:
        """Run natural-language skill search via Decision Hub."""
        status: Label = self.query_one("#search-status", Label)
        self.app.call_from_thread(status.update, "Searching...")

        try:
            results: list[dict[str, Any]] = ask_skills(query)
            self._results = results
            self.app.call_from_thread(self._display_results, results)
        except Exception as e:
            self.app.call_from_thread(status.update, f"[red]Error: {e}[/red]")

    def _display_results(self, results: list[dict[str, Any]]) -> None:
        status: Label = self.query_one("#search-status", Label)
        ol: OptionList = self.query_one("#skill-results", OptionList)
        ol.clear_options()

        if not results:
            status.update("No results found.")
            ol.display = False
            return

        ol.display = True
        status.update(f"{len(results)} result(s) — select to add")
        for skill in results:
            name: str = f"{skill.get('org_slug', '?')}/{skill.get('skill_name', '?')}"
            reason: str = skill.get("reason", skill.get("description", ""))
            line: str = f"  {name}  [dim]{reason}[/dim]"
            ol.add_option(Option(line, id=name))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "skill-results":
            self._add_skill(event.option.id)
        elif event.option_list.id == "selected-skills":
            self._remove_skill(event.option.id)

    def _add_skill(self, skill_id: str | None) -> None:
        if skill_id is None:
            return
        for skill in self._results:
            key: str = f"{skill.get('org_slug', '')}/{skill.get('skill_name', '')}"
            if key == skill_id:
                if not any(s.get("skill_name") == skill.get("skill_name") for s in self._selected):
                    self._selected.append(skill)
                    self._refresh_selected_display()
                return

    def _remove_skill(self, skill_id: str | None) -> None:
        if skill_id is None:
            return
        self._selected = [
            s for s in self._selected
            if f"{s.get('org_slug', '')}/{s.get('skill_name', '')}" != skill_id
        ]
        self._refresh_selected_display()

    def _refresh_selected_display(self) -> None:
        ol: OptionList = self.query_one("#selected-skills", OptionList)
        ol.clear_options()
        if self._selected:
            ol.display = True
            for skill in self._selected:
                name: str = f"{skill.get('org_slug', '')}/{skill.get('skill_name', '')}"
                ol.add_option(Option(f"✓ {name}  [dim](click to remove)[/dim]", id=name))
            self.query_one("#next-btn", Button).label = "Next →"
        else:
            ol.display = False
            self.query_one("#next-btn", Button).label = "Skip →"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
            return
        if event.button.id == "next-btn":
            self.app.wizard_state["selected_skills"] = self._selected
            self.app.push_screen(SummaryScreen())

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Screen 7: Summary & confirm
# ---------------------------------------------------------------------------

class SummaryScreen(Screen):
    """Show summary and confirm decision-pack creation."""

    BINDINGS = [Binding("escape", "go_back", "Back")]

    CSS = """
    SummaryScreen {
        align: left bottom;
    }
    #summary-container {
        width: 66%;
        height: auto;
        max-height: 80%;
        padding: 1 2;
    }
    .field-label {
        margin-top: 1;
    }
    .nav-bar {
        margin-top: 1;
        height: 1;
        align: right middle;
    }
    #create-btn {
        min-width: 16;
    }
    """

    def compose(self) -> ComposeResult:
        step: str = self._step_label()
        with FormScroll(id="summary-container"):
            yield Label(f"[b]{step}[/b] — Review & Create", classes="field-label")
            yield Label("Tab / Shift+Tab to navigate  |  Ctrl+Q to quit", classes="field-hint")
            yield Static(id="summary-content")
            yield Label("", id="result-label")
            yield Button("Delete & Overwrite", id="overwrite-btn", variant="error")
            with Horizontal(classes="nav-bar nav-swap-wide"):
                yield Button("Create decision-pack", id="create-btn", variant="success")
                yield Button("Done", id="done-btn", variant="primary")
                yield Button("Keep Partial", id="keep-btn")
                yield Button("← Back", id="back-btn")

    def _step_label(self) -> str:
        skills_enabled: bool = self.app.wizard_state.get("skeletons", {}).get("skills", True)
        total: int = 8 if skills_enabled else 7
        return f"Step {total} of {total}"

    def on_mount(self) -> None:
        self.query_one("#done-btn", Button).display = False
        self.query_one("#keep-btn", Button).display = False
        self.query_one("#overwrite-btn", Button).display = False
        self._show_review()
        self.query_one("#create-btn", Button).focus()

    def _show_review(self) -> None:
        state: dict[str, Any] = self.app.wizard_state
        skeletons: dict[str, bool] = state.get("skeletons", {})
        permissions: dict[str, str] = state.get("permissions", {})
        selected_skills: list[dict[str, Any]] = state.get("selected_skills", [])

        enabled_skels: list[str] = [k for k, v in skeletons.items() if v]
        skel_str: str = ", ".join(enabled_skels) if enabled_skels else "none"

        allowed: list[str] = [k for k, v in permissions.items() if v == "allow"]
        denied: list[str] = [k for k, v in permissions.items() if v == "deny"]
        allowed_str: str = ", ".join(allowed) if allowed else "none"
        denied_str: str = ", ".join(denied) if denied else "none"

        skill_names: list[str] = [
            f"{s.get('org_slug', '')}/{s.get('skill_name', '')}"
            for s in selected_skills
        ]
        skill_str: str = ", ".join(skill_names) if skill_names else "none"

        pkg_mgr: str = state.get("package_manager", "pip")
        python_lib_name: str = state.get("python_lib_name", "")
        modal: bool = state.get("modal_integration", False)
        extras: list[str] = []
        if python_lib_name:
            extras.append(f"python lib ({python_lib_name})")
        if modal:
            extras.append("modal integration")
        extras_str: str = ", ".join(extras) if extras else "none"

        summary: str = f"""
[b]decision-pack[/b]
  Name:         {state['name']}
  Description:  {state.get('description', '')}

[b]Container[/b]
  Package mgr:  {pkg_mgr}
  Base image:   {state.get('base_image', '')}
  Extras:       {extras_str}

[b]Model[/b]
  Default:      {state.get('default_model', '')}

[b]Permissions[/b]
  Allowed:      {allowed_str}
  Denied:       {denied_str}

[b]Skeletons[/b]
  Enabled:      {skel_str}

[b]Hub Skills[/b]
  Selected:     {skill_str}
"""
        self.query_one("#summary-content", Static).update(summary)

    def _show_walkthrough(self, dpack_path: Path) -> None:
        """Replace summary with a walkthrough of what was created."""
        state: dict[str, Any] = self.app.wizard_state
        skeletons: dict[str, bool] = state.get("skeletons", {})
        agent_name: str = state.get("agent_name", "orchestrator")
        pkg_mgr: str = state.get("package_manager", "pip")
        selected_skills: list[dict[str, Any]] = state.get("selected_skills", [])

        # Determine env file name
        env_files: dict[str, str] = {
            "conda": "environment.yml",
            "pixi": "pixi.toml",
        }
        env_file: str = env_files.get(pkg_mgr, "requirements.txt")

        lines: list[str] = [
            f"[green bold]decision-pack created: {dpack_path}[/green bold]",
            "",
            "[b]What was created:[/b]",
            f"  config.yaml            decision-pack configuration (name, model, docker image)",
            f"  docker/Dockerfile      Container setup ({pkg_mgr})",
            f"  docker/{env_file:<20s} Package dependencies",
            f"  opencode/opencode.json Points to your main agent: {agent_name}",
            f"  opencode/agents/{agent_name}.md",
            f"                         Your main agent's system prompt",
        ]

        python_lib_name: str = state.get("python_lib_name", "")
        if python_lib_name:
            lines.append(f"  docker/{python_lib_name}/")
            lines.append(f"                         Python library package")
        if state.get("modal_integration"):
            lines.append(f"  docker/modal_app/      Modal serverless compute")

        has_subagents: bool = skeletons.get("subagents", False) or skeletons.get("parallel_agents", False)
        if has_subagents:
            lines.append(f"  opencode/agents/example-worker.md")
            lines.append(f"                         Example subagent (rename & customize)")
        if skeletons.get("parallel_agents"):
            lines.append(f"  opencode/parallel_agents/example-worker.yaml")
            lines.append(f"                         Parallel agent config")
        if skeletons.get("tools"):
            lines.append(f"  opencode/tools/example-tool.ts")
            lines.append(f"                         Example custom tool")
        if skeletons.get("skills"):
            lines.append(f"  opencode/skills/example-skill/SKILL.md")
            lines.append(f"                         Example skill")
        for skill in selected_skills:
            sname: str = skill.get("skill_name", "?")
            lines.append(f"  opencode/skills/{sname}/")
            lines.append(f"                         Downloaded from Decision Hub")

        lines.extend([
            "",
            "[b]Next steps:[/b]",
            f"  1. Edit opencode/agents/{agent_name}.md to write your agent's system prompt",
            f"  2. Add your data files to a directory and run:",
            f"     dlab --dpack {dpack_path} --data ./your-data --prompt \"Your task\"",
            f"  3. Install as a shortcut:",
            f"     dlab install {dpack_path}",
        ])

        self.query_one("#summary-content", Static).update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
            return
        if event.button.id in ("done-btn", "keep-btn"):
            self.app.exit()
            return
        if event.button.id == "overwrite-btn":
            self.app.wizard_state["overwrite_existing"] = True
            self.query_one("#result-label", Label).update(
                "[green]decision-pack will be overwritten[/green]"
            )
            self.query_one("#overwrite-btn", Button).display = False
            return
        if event.button.id != "create-btn":
            return

        result_label: Label = self.query_one("#result-label", Label)
        state: dict[str, Any] = self.app.wizard_state
        output_dir: Path = Path(self.app.output_dir)
        dpack_dir: Path = output_dir / state["name"]

        # Pre-create collision check
        if dpack_dir.exists() and not state.get("overwrite_existing"):
            result_label.update("[red]decision-pack directory exists![/red]")
            self.query_one("#overwrite-btn", Button).display = True
            return

        self._run_create(output_dir, state)

    @work(thread=True)
    def _run_create(self, output_dir: Path, state: dict[str, Any]) -> None:
        """Run decision-pack creation in background with progress feedback."""
        def _on_progress(msg: str) -> None:
            self.app.call_from_thread(
                self.query_one("#result-label", Label).update, msg
            )

        try:
            dpack_path: Path = generate_dpack(output_dir, dict(state), on_progress=_on_progress)
            self.app.call_from_thread(self._on_create_success, dpack_path)
        except Exception as e:
            self.app.call_from_thread(self._on_create_error, str(e))

    def _on_create_success(self, dpack_path: Path) -> None:
        self.query_one("#result-label", Label).update("")
        self._show_walkthrough(dpack_path)
        self.query_one("#create-btn", Button).display = False
        self.query_one("#back-btn", Button).display = False
        self.query_one("#done-btn", Button).display = True

    def _on_create_error(self, error_msg: str) -> None:
        self.query_one("#result-label", Label).update(f"[red]Error: {error_msg}[/red]")
        self.query_one("#create-btn", Button).display = False
        self.query_one("#keep-btn", Button).display = True
        self.query_one("#back-btn", Button).label = "← Go Back (fix & retry)"

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class CreateDpackApp(App):
    """Multi-screen wizard for creating a new decision-pack directory."""

    TITLE = "dlab create-dpack"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("down", "focus_next", show=False),
        Binding("up", "focus_previous", show=False),
        Binding("left", "focus_previous", show=False),
        Binding("right", "focus_next", show=False),
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
        &.-primary {
            background: $primary-muted;
            border: none;
            &:hover { background: $primary; border: none; }
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
    #model-results, #skill-results, #selected-skills {
        margin-top: 1;
    }
    .cb-group {
        border-left: tall $accent;
        background: $surface;
        padding: 0 1;
        height: auto;
    }
    #overwrite-btn {
        color: $text;
    }
    #collision-bar {
        height: auto;
    }
    /* TODO: The nav-swap offset hack visually swaps button positions so that
       Next appears right and Back appears left, while keeping Next first in
       focus order. This is brittle (hardcoded pixel offsets). Replace with a
       proper solution when Textual adds CSS `order` or when we rename decision-packs. */
    .nav-swap > #next-btn {
        offset: 10 0;
    }
    .nav-swap > #back-btn {
        offset: -10 0;
    }
    .nav-swap-wide > #create-btn {
        offset: 12 0;
    }
    .nav-swap-wide > #back-btn {
        offset: -18 0;
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

    def __init__(self, output_dir: str = ".") -> None:
        super().__init__()
        self.output_dir: str = output_dir
        self.wizard_state: dict[str, Any] = {}

    def on_mount(self) -> None:
        self.push_screen(BasicsScreen())
