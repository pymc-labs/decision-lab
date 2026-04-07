"""
Main Textual application for dlab connect TUI.
"""

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, TabbedContent, TabPane
from textual.binding import Binding
from textual.timer import Timer

from dlab.tui.widgets.agent_list import AgentSelector
from dlab.tui.widgets.log_view import LogView
from dlab.tui.widgets.status_bar import StatusBar
from dlab.tui.widgets.artifacts_pane import ArtifactList, FileViewer
from dlab.tui.widgets.search_popup import SearchPopup
from dlab.tui.log_watcher import LogWatcher
from dlab.tui.models import SessionState, LogEvent
from dlab.timeline import (
    is_log_complete,
    discover_agents,
)


def load_default_agent(work_dir: Path) -> str | None:
    """
    Load default agent name from opencode.json.

    Parameters
    ----------
    work_dir : Path
        Work directory path.

    Returns
    -------
    str | None
        Default agent name or None if not found.
    """
    opencode_json = work_dir / ".opencode" / "opencode.json"
    if opencode_json.exists():
        try:
            data = json.loads(opencode_json.read_text())
            return data.get("default_agent")
        except (json.JSONDecodeError, IOError):
            pass
    return None


def get_global_start_ts(logs_dir: Path) -> int | None:
    """
    Get the global start timestamp from main.log.

    The global start is defined as the first timestamp in main.log.
    This is used as the reference point for ALL relative timestamps
    across all agents in the session.

    Parameters
    ----------
    logs_dir : Path
        Path to _opencode_logs directory.

    Returns
    -------
    int | None
        First timestamp from main.log in milliseconds, or None if not found.
    """
    main_log = logs_dir / "main.log"
    if not main_log.exists():
        return None

    try:
        with open(main_log, "r") as f:
            for line in f:
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    data = json.loads(line)
                    ts = data.get("timestamp")
                    if ts and isinstance(ts, int) and ts > 0:
                        return ts
                except json.JSONDecodeError:
                    continue
    except (IOError, OSError):
        pass

    return None


class ConnectApp(App):
    """
    TUI application for monitoring running dlab sessions.

    Layout:
    ┌─────────────────────────────────────────────────────────────┐
    │ Header: dlab connect - {work_dir}                       │
    ├──────────────┬──────────────────────────────────────────────┤
    │ Agents       │  [Logs] [Files]  ← TabbedContent             │
    │ ● main-poet  │ ─────────────────────────────────────────────│
    │ ○ inst-1     │ + 0.0s | step_start | Started                │
    │ ○ inst-2     │ + 1.2s | text       | I'll help...           │
    │──────────────│ + 5.0s | tool_use   | write: ...             │
    │ Files        │                                              │
    │ 📄 poem.md   │   (scrollable content)                       │
    │ 🐍 script.py │                                              │
    ├──────────────┴──────────────────────────────────────────────┤
    │ RUNNING | Cost: $0.05 | Duration: 45s | Agent: main-poet    │
    └─────────────────────────────────────────────────────────────┘
    """

    CSS = """
    #main-container {
        height: 1fr;
    }

    #left-sidebar {
        width: 28;
        min-width: 20;
        max-width: 36;
        border-right: vkey $surface-lighten-1;
    }

    .section-header {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        text-style: bold;
    }

    AgentSelector {
        height: 1fr;
        padding: 0 1;
    }


    ArtifactList {
        height: 1fr;
        padding: 0 1;
        border-top: hkey $surface-lighten-1;
    }

    #main-tabs {
        width: 1fr;
    }

    /* Flatten tab underline bar */
    Underline > .underline--bar {
        background: $foreground 5%;
    }

    LogView {
        padding: 0 1;
    }

    FileViewer {
        padding: 0 1;
    }

    StatusBar {
        height: 1;
        padding: 0 1;
    }

    /* Search popup overlay */
    SearchPopup {
        dock: bottom;
        margin-bottom: 2;
        margin-left: 28;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("/", "show_search", "Search"),
        Binding("escape", "hide_search", "Close", show=False),
        Binding("e", "expand_all", "Expand All"),
        Binding("c", "collapse_all", "Collapse All"),
        Binding("o", "open_file", "Open"),
        Binding("y", "yank_log", "Yank"),
        Binding("f", "flush_clip", "Flush"),
        Binding("j", "next_agent", "Next Agent", show=False),
        Binding("k", "prev_agent", "Prev Agent", show=False),
        Binding("left", "focus_sidebar", "Sidebar"),
        Binding("right", "focus_main", "Main"),
        Binding("tab", "cycle_sidebar_focus", "Cycle", show=False),
        Binding("up", "prev_item", "Up", show=False),
        Binding("down", "next_item", "Down", show=False),
        Binding("enter", "select_item", "Select", show=False),
        Binding("1", "show_logs_tab", "Logs", show=False),
        Binding("2", "show_files_tab", "Files", show=False),
        Binding("n", "next_match", "Next Match", show=False),
        Binding("N", "prev_match", "Prev Match", show=False),
    ]

    TITLE = "dlab connect"
    theme = "monokai"

    def __init__(self, work_dir: Path) -> None:
        super().__init__()
        self._work_dir = work_dir
        self._logs_dir = work_dir / "_opencode_logs"
        self._state = SessionState(work_dir=work_dir)
        self._watcher: LogWatcher | None = None
        self._selected_agent: str | None = None
        self._known_agents: set[str] = set()
        self._update_timer: Timer | None = None
        self._default_agent = load_default_agent(work_dir)
        self._search_matches: list[int] = []
        self._current_match_index: int = 0

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header(show_clock=False)

        with Horizontal(id="main-container"):
            with Vertical(id="left-sidebar"):
                yield Static("Agents", classes="section-header")
                yield AgentSelector(id="agent-selector")
                yield Static("Files", classes="section-header")
                yield ArtifactList(self._work_dir, id="artifact-list")

            with TabbedContent(id="main-tabs"):
                with TabPane("Logs", id="logs-tab"):
                    yield LogView(id="log-view")
                with TabPane("Files", id="files-tab"):
                    yield FileViewer(id="file-viewer")

        yield SearchPopup(id="search-popup")
        yield StatusBar(id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize on app mount."""
        self.title = f"dlab connect - {self._work_dir.name}"

        # Discover known agents
        opencode_dir = self._work_dir / ".opencode"
        if opencode_dir.exists():
            self._known_agents = discover_agents(opencode_dir)

        # Check if job is running
        main_log = self._logs_dir / "main.log"
        self._state.is_job_running = main_log.exists() and not is_log_complete(main_log)

        # Get global start timestamp from main.log FIRST
        # This is the authoritative reference for all relative timestamps
        self._state.global_start_ts = get_global_start_ts(self._logs_dir)

        # Start log watcher
        self._watcher = LogWatcher(self._logs_dir)
        self._watcher.start()

        # Poll for initial events (populates queue before processing)
        self._watcher.poll()

        # Process initial events
        self._process_pending_events()

        # Select first agent
        agent_selector = self.query_one("#agent-selector", AgentSelector)
        agent_selector.select_first()

        # Show placeholder in file viewer
        file_viewer = self.query_one("#file-viewer", FileViewer)
        file_viewer.show_placeholder()

        # Focus log view and select last event
        log_view = self.query_one("#log-view", LogView)
        log_view.focus()
        if log_view._widgets:
            log_view.selected_index = len(log_view._widgets) - 1

        # Start periodic update timer
        self._update_timer = self.set_interval(0.5, self._on_update_tick)

    async def on_unmount(self) -> None:
        """Cleanup on app unmount."""
        if self._watcher:
            self._watcher.stop()
        if self._update_timer:
            self._update_timer.stop()

    def _get_display_name(self, source: str) -> str:
        """
        Get display name for a source, renaming 'main' to 'main-{agent}'.

        Parameters
        ----------
        source : str
            Original source name from log file.

        Returns
        -------
        str
            Display name for the agent.
        """
        if source == "main" and self._default_agent:
            return f"main-{self._default_agent}"
        return source

    def _process_pending_events(self) -> None:
        """Process any pending events from the watcher."""
        if not self._watcher:
            return

        events = self._watcher.get_events()
        for source, raw_event in events:
            display_name = self._get_display_name(source)
            event = LogEvent.from_raw(raw_event, display_name)
            agent_state = self._state.get_or_create_agent(display_name)

            was_added = agent_state.add_event(event)

            if was_added:
                # Only update global_start_ts with valid timestamps (not 0)
                # raw_text and additional_output events have timestamp=0
                if event.timestamp > 0 and (
                    self._state.global_start_ts is None
                    or event.timestamp < self._state.global_start_ts
                ):
                    self._state.global_start_ts = event.timestamp

                if display_name == self._selected_agent:
                    log_view = self.query_one("#log-view", LogView)
                    log_view.append_event(event)

        if events:
            self._update_agent_list()
            self._update_status_bar()

    def _get_log_path(self, display_name: str) -> Path:
        """
        Get the log file path for a display name.

        Parameters
        ----------
        display_name : str
            Display name of the agent.

        Returns
        -------
        Path
            Path to the log file.
        """
        if display_name.startswith("main-"):
            return self._logs_dir / "main.log"

        log_path = self._logs_dir / f"{display_name}.log"
        if log_path.exists():
            return log_path

        parts = display_name.split("/")
        if len(parts) == 2:
            return self._logs_dir / parts[0] / f"{parts[1]}.log"

        return log_path

    def _update_agent_list(self) -> None:
        """Update the agent selector with current state."""
        agent_selector = self.query_one("#agent-selector", AgentSelector)

        def sort_by_start_time(name: str) -> int:
            agent_state = self._state.agents.get(name)
            if agent_state and agent_state.start_time:
                return int(agent_state.start_time.timestamp() * 1000)
            return 0

        agents = sorted(self._state.agents.keys(), key=sort_by_start_time)

        running: set[str] = set()
        main_display_name = self._get_display_name("main")

        # Check if main agent is complete — if so, all sub-agents are done
        # (sub-agents may lack a clean stop event if the container was killed)
        main_log = self._get_log_path("main")
        main_complete = main_log.exists() and is_log_complete(main_log)

        if not main_complete:
            for name in self._state.agents.keys():
                log_path = self._get_log_path(name)
                if log_path.exists() and not is_log_complete(log_path):
                    running.add(name)

        agent_selector.update_agents(agents, running)

        self._state.is_job_running = main_display_name in running

    def _update_status_bar(self) -> None:
        """Update the status bar."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_status(
            is_running=self._state.is_job_running,
            cost=self._state.total_cost,
            duration=self._state.duration_seconds,
            agent=self._selected_agent,
        )

    def _on_update_tick(self) -> None:
        """Periodic update tick."""
        # Poll log files directly as fallback for unreliable watchdog events
        # (especially on macOS where FSEvents can miss Docker/atomic writes)
        if self._watcher:
            self._watcher.poll()

        self._process_pending_events()
        self._update_status_bar()

        # Refresh artifacts periodically (detect new files created during execution)
        artifact_list = self.query_one("#artifact-list", ArtifactList)
        artifact_list.refresh_if_changed()

    def on_agent_selector_agent_selected(
        self, event: AgentSelector.AgentSelected
    ) -> None:
        """Handle agent selection."""
        self._selected_agent = event.agent_name

        log_view = self.query_one("#log-view", LogView)

        if event.agent_name in self._state.agents:
            agent_state = self._state.agents[event.agent_name]
            # Use global_start_ts from main.log - this is authoritative
            # NEVER use 0 - if global_start_ts is None, we have no valid reference
            start_ts = self._state.global_start_ts
            if start_ts is None:
                # Fallback: try to get it again from main.log
                start_ts = get_global_start_ts(self._logs_dir)
                if start_ts:
                    self._state.global_start_ts = start_ts
            log_view.set_events(
                agent_state.events,
                start_ts,  # Can be None - LogView must handle this
            )
        else:
            log_view.set_events([], self._state.global_start_ts)

        # Update artifact list for selected agent
        artifact_list = self.query_one("#artifact-list", ArtifactList)
        artifact_list.set_agent(event.agent_name)

        self._update_status_bar()

    def on_artifact_list_file_selected(self, event: ArtifactList.FileSelected) -> None:
        """Handle file selection from artifact list."""
        # Switch to Files tab
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = "files-tab"

        # Show file content
        file_viewer = self.query_one("#file-viewer", FileViewer)
        file_viewer.show_file(event.path)

    def on_search_popup_search_changed(self, event: SearchPopup.SearchChanged) -> None:
        """Handle search text changes."""
        self._perform_search(event.query)

    def on_search_popup_next_match(self, event: SearchPopup.NextMatch) -> None:
        """Jump to next search match."""
        if self._search_matches:
            self._current_match_index = (self._current_match_index + 1) % len(
                self._search_matches
            )
            self._jump_to_match()

    def on_search_popup_prev_match(self, event: SearchPopup.PrevMatch) -> None:
        """Jump to previous search match."""
        if self._search_matches:
            self._current_match_index = (self._current_match_index - 1) % len(
                self._search_matches
            )
            self._jump_to_match()

    def on_search_popup_search_closed(self, event: SearchPopup.SearchClosed) -> None:
        """Handle search popup closed."""
        log_view = self.query_one("#log-view", LogView)
        log_view.highlight_search("")
        self._search_matches = []
        self._current_match_index = 0

    def _perform_search(self, query: str) -> None:
        """Perform search on current view."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        search_popup = self.query_one("#search-popup", SearchPopup)

        if tabs.active == "logs-tab":
            log_view = self.query_one("#log-view", LogView)
            self._search_matches = log_view.highlight_search(query)
            self._current_match_index = 0

            if self._search_matches:
                search_popup.update_match_count(1, len(self._search_matches))
                log_view.scroll_to_event(self._search_matches[0])
            else:
                search_popup.update_match_count(0, 0)
        else:
            # TODO: Implement file content search
            self._search_matches = []
            search_popup.update_match_count(0, 0)

    def _jump_to_match(self) -> None:
        """Jump to current match index."""
        if not self._search_matches:
            return

        search_popup = self.query_one("#search-popup", SearchPopup)
        search_popup.update_match_count(
            self._current_match_index + 1, len(self._search_matches)
        )

        tabs = self.query_one("#main-tabs", TabbedContent)
        if tabs.active == "logs-tab":
            log_view = self.query_one("#log-view", LogView)
            log_view.scroll_to_event(self._search_matches[self._current_match_index])

    def action_show_search(self) -> None:
        """Show the search popup."""
        search_popup = self.query_one("#search-popup", SearchPopup)
        search_popup.show()

    def action_hide_search(self) -> None:
        """Hide the search popup."""
        search_popup = self.query_one("#search-popup", SearchPopup)
        if search_popup.is_visible():
            search_popup.hide()

    def action_expand_all(self) -> None:
        """Expand all log events."""
        log_view = self.query_one("#log-view", LogView)
        log_view.expand_all()

    def action_collapse_all(self) -> None:
        """Collapse all log events."""
        log_view = self.query_one("#log-view", LogView)
        log_view.collapse_all()

    def action_next_agent(self) -> None:
        """Select next agent."""
        agent_selector = self.query_one("#agent-selector", AgentSelector)
        agent_selector.action_cursor_down()

    def action_prev_agent(self) -> None:
        """Select previous agent."""
        agent_selector = self.query_one("#agent-selector", AgentSelector)
        agent_selector.action_cursor_up()

    def action_focus_sidebar(self) -> None:
        """Focus the left sidebar (agent selector)."""
        agent_selector = self.query_one("#agent-selector", AgentSelector)
        agent_selector.focus()

    def action_focus_main(self) -> None:
        """Focus the main area (current tab content)."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        if tabs.active == "logs-tab":
            log_view = self.query_one("#log-view", LogView)
            log_view.focus()
        else:
            file_viewer = self.query_one("#file-viewer", FileViewer)
            file_viewer.focus()

    def action_cycle_sidebar_focus(self) -> None:
        """Cycle focus between agent selector and artifact list."""
        focused = self.focused
        agent_selector = self.query_one("#agent-selector", AgentSelector)
        artifact_list = self.query_one("#artifact-list", ArtifactList)

        if focused == agent_selector:
            artifact_list.focus()
        elif focused == artifact_list:
            agent_selector.focus()
        else:
            agent_selector.focus()

    def action_prev_item(self) -> None:
        """Navigate to previous item in focused pane."""
        focused = self.focused
        if isinstance(focused, AgentSelector):
            focused.action_cursor_up()
        elif isinstance(focused, LogView):
            focused.select_prev()
        elif isinstance(focused, ArtifactList):
            focused.action_cursor_up()

    def action_next_item(self) -> None:
        """Navigate to next item in focused pane."""
        focused = self.focused
        if isinstance(focused, AgentSelector):
            focused.action_cursor_down()
        elif isinstance(focused, LogView):
            focused.select_next()
        elif isinstance(focused, ArtifactList):
            focused.action_cursor_down()

    def action_select_item(self) -> None:
        """Select/expand current item."""
        focused = self.focused
        if isinstance(focused, LogView):
            focused.toggle_selected()
        elif isinstance(focused, AgentSelector):
            log_view = self.query_one("#log-view", LogView)
            log_view.toggle_selected()
        elif isinstance(focused, ArtifactList):
            # Trigger file selection via ListView's built-in selection
            pass

    def action_show_logs_tab(self) -> None:
        """Switch to Logs tab."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = "logs-tab"

    def action_show_files_tab(self) -> None:
        """Switch to Files tab."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = "files-tab"

    def action_next_match(self) -> None:
        """Jump to next search match."""
        search_popup = self.query_one("#search-popup", SearchPopup)
        if search_popup.is_visible() and self._search_matches:
            self._current_match_index = (self._current_match_index + 1) % len(
                self._search_matches
            )
            self._jump_to_match()

    def action_prev_match(self) -> None:
        """Jump to previous search match."""
        search_popup = self.query_one("#search-popup", SearchPopup)
        if search_popup.is_visible() and self._search_matches:
            self._current_match_index = (self._current_match_index - 1) % len(
                self._search_matches
            )
            self._jump_to_match()

    def action_open_file(self) -> None:
        """Open the highlighted file in the system's default viewer."""
        artifact_list = self.query_one("#artifact-list", ArtifactList)
        artifact_list.open_highlighted()

    def action_yank_log(self) -> None:
        """Append selected log event content to /tmp/clip.txt."""
        log_view = self.query_one("#log-view", LogView)
        content = log_view.get_selected_content()

        if not content:
            self.notify("No event selected (use ↑↓ to select)", timeout=2)
            return

        # Append to clip file
        clip_file = "/tmp/clip.txt"
        with open(clip_file, "a") as f:
            f.write(content)
            f.write("\n\n---\n\n")  # Separator between entries

        # Count entries
        try:
            with open(clip_file, "r") as f:
                count = f.read().count("---")
        except Exception:
            count = 1

        preview = content[:40].replace("\n", " ") + "..."
        self.notify(f"Yanked ({count}): {preview}", timeout=2)

    def action_flush_clip(self) -> None:
        """Clear /tmp/clip.txt."""
        clip_file = "/tmp/clip.txt"
        with open(clip_file, "w") as f:
            pass  # Empty the file
        self.notify("Flushed /tmp/clip.txt", timeout=2)
