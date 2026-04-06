"""
Main log display widget with collapsible events.

Displays formatted log events for the selected agent with
real-time updates and expand/collapse functionality.
"""

from textual.widgets import Static
from textual.containers import VerticalScroll, Horizontal
from textual.reactive import reactive
from textual import events
from rich.text import Text
from rich.markdown import Markdown
from rich.console import Group

from dlab.tui.models import LogEvent


# Monokai-native color palette
_CYAN: str = "#66D9EF"
_GREEN: str = "#A6E22E"
_ORANGE: str = "#FD971F"
_RED: str = "#F92672"
_PURPLE: str = "#AE81FF"
_COMMENT: str = "#75715E"
_FG: str = "#F8F8F2"

# Color styles by event type
EVENT_STYLES: dict[str, str] = {
    "dlab_start": f"bold {_CYAN}",
    "step_start": _CYAN,
    "step_finish": _GREEN,
    "text": _FG,
    "tool_use": _ORANGE,
    "task_start": _ORANGE,
    "task_finish": _GREEN,
    "additional_output": _COMMENT,
    "raw_text": _COMMENT,
    "error": f"bold {_RED}",
}


def format_relative_time(event_ts: int, global_start_ts: int | None) -> str:
    """
    Format timestamp relative to global start.

    Parameters
    ----------
    event_ts : int
        Event timestamp in ms, or 0 for events without timestamp.
    global_start_ts : int | None
        Global start timestamp in ms, or None if unknown.

    Returns
    -------
    str
        Formatted relative time (e.g., "+5.2s"), "---" for no timestamp,
        or "????.?s" if start unknown.
    """
    # Events with timestamp=0 have no time (additional_output events)
    # All returns must be exactly 10 chars for column alignment
    if event_ts == 0:
        return "  ---"
    if global_start_ts is None:
        return "  ---"
    rel_seconds: int = max(0, (event_ts - global_start_ts) // 1000)
    if rel_seconds < 60:
        return f"{rel_seconds:>3d}s"
    minutes: int = rel_seconds // 60
    s: int = rel_seconds % 60
    if minutes < 60:
        return f"{minutes}m{s:02d}s"
    hours: int = minutes // 60
    m: int = minutes % 60
    return f"{hours}h{m:02d}m{s:02d}s"


def format_duration(ms: int | None) -> str:
    """
    Format duration in milliseconds.

    Parameters
    ----------
    ms : int | None
        Duration in milliseconds.

    Returns
    -------
    str
        Formatted duration or empty string.
    """
    if ms is None:
        return ""
    seconds = ms / 1000
    if seconds < 60:
        return f"[{seconds:.1f}s]"
    minutes = seconds / 60
    return f"[{minutes:.1f}m]"


# Display labels for event types (shorter, cleaner)
_EVENT_TYPE_LABELS: dict[str, str] = {
    "tool_use": "tool",
    "raw_text": "raw",
    "text": "",
    "error": "err",
    "dlab_start": "init",
    "additional_output": "raw",
    "step_start": "",
    "step_finish": "",
}


class LogEventPrefix(Static):
    """Fixed-width prefix showing selection, time, and event type."""

    DEFAULT_CSS = """
    LogEventPrefix {
        width: 17;
        min-width: 17;
        max-width: 17;
    }
    """

    def __init__(
        self,
        time_str: str,
        event_type: str,
        style: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._time_str = time_str
        self._event_type = event_type
        self._style = style
        self._is_selected = False

    def set_selected(self, selected: bool) -> None:
        """Update selection state."""
        self._is_selected = selected
        self.refresh()

    def render(self) -> Text:
        """Render the prefix."""
        if self._is_selected:
            text = Text("► ", style=f"bold {_PURPLE}")
        else:
            text = Text("  ")

        text.append(f"{self._time_str:>8}", style="dim")
        text.append(" ", style="dim")
        label: str = _EVENT_TYPE_LABELS.get(self._event_type, self._event_type)
        text.append(f"{label:<5}", style=self._style)

        return text


class LogEventDescription(Static):
    """Flexible-width description that wraps properly."""

    DEFAULT_CSS = """
    LogEventDescription {
        width: 1fr;
    }
    """

    def __init__(
        self,
        description: str,
        full_description: str,
        event_type: str,
        style: str,
        duration_str: str,
        is_long: bool,
        start_expanded: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._description = description
        self._full_description = full_description
        self._event_type = event_type
        self._style = style
        self._duration_str = duration_str
        self._is_long = is_long
        self._is_collapsed = not start_expanded

    def set_collapsed(self, collapsed: bool) -> None:
        """Update collapsed state."""
        self._is_collapsed = collapsed
        self.refresh(layout=True)

    def render(self):
        """Render the description."""
        if self._is_long and self._is_collapsed:
            # Only take first line if multiline, then truncate
            first_line = self._description.split("\n")[0]
            if len(first_line) > 100:
                first_line = first_line[:100] + "..."
            text = Text(first_line, style=self._style)
            text.append(" [+]", style="dim italic")
            if self._duration_str:
                text.append(f" {self._duration_str}", style="dim")
            return text
        else:
            # Use full description when expanded
            desc = self._full_description

            # Check if this should be rendered as Markdown
            is_markdown = self._event_type == "text"
            # Also render "write: *.md" content as Markdown
            if desc.startswith("write:") and ".md" in desc.split("\n")[0]:
                is_markdown = True

            if is_markdown:
                md = Markdown(desc)
                if self._is_long or self._duration_str:
                    suffix = Text()
                    if self._is_long:
                        suffix.append(" [-]", style="dim italic")
                    if self._duration_str:
                        suffix.append(f" {self._duration_str}", style="dim")
                    return Group(md, suffix)
                return md
            else:
                # For multiline expanded text, only style the first line
                # (e.g. dlab_start: header is bold, prompt is dim)
                if not self._is_collapsed and "\n" in desc:
                    first_line, rest = desc.split("\n", 1)
                    text = Text(first_line, style=self._style)
                    text.append("\n")
                    text.append(rest, style="dim")
                else:
                    text = Text(desc, style=self._style)
                if self._is_long:
                    text.append(" [-]", style="dim italic")
                if self._duration_str:
                    text.append(f" {self._duration_str}", style="dim")
                return text


class LogEventWidget(Horizontal):
    """
    Single log event display using horizontal layout.

    Shows timestamp, event type, and description with appropriate styling.
    Long text content can be collapsed. Description wraps properly.
    """

    DEFAULT_CSS = """
    LogEventWidget {
        height: auto;
        width: 100%;
    }
    """

    is_collapsed: reactive[bool] = reactive(True)
    is_selected: reactive[bool] = reactive(False)

    def __init__(
        self,
        event: LogEvent,
        global_start_ts: int | None,
        start_expanded: bool = False,
        **kwargs,
    ) -> None:
        """
        Initialize event widget.

        Parameters
        ----------
        event : LogEvent
            The log event to display.
        global_start_ts : int | None
            Global start timestamp for relative time calculation, or None if unknown.
        """
        super().__init__(**kwargs)
        self.event = event
        self.global_start_ts = global_start_ts
        self._start_expanded = start_expanded
        # Check if description has multiple lines or is long
        self._is_long = (
            len(event.description) > 100
            or "\n" in event.description
            or "\n" in event.full_description
        )

        self._style = EVENT_STYLES.get(event.event_type, "white")
        self._time_str = format_relative_time(event.timestamp, global_start_ts)
        self._duration_str = format_duration(event.duration_ms)

    def compose(self):
        """Create child widgets."""
        yield LogEventPrefix(
            self._time_str,
            self.event.event_type,
            self._style,
        )
        yield LogEventDescription(
            self.event.description,
            self.event.full_description,
            self.event.event_type,
            self._style,
            self._duration_str,
            self._is_long,
            start_expanded=self._start_expanded,
        )

    def on_mount(self) -> None:
        """Apply initial expanded state after mounting."""
        if self._start_expanded:
            self.is_collapsed = False

    def watch_is_collapsed(self, value: bool) -> None:
        """Update description collapsed state."""
        try:
            desc = self.query_one(LogEventDescription)
            desc.set_collapsed(value)
        except Exception:
            pass

    def watch_is_selected(self, value: bool) -> None:
        """Update prefix selected state."""
        try:
            prefix = self.query_one(LogEventPrefix)
            prefix.set_selected(value)
        except Exception:
            pass

    def toggle_collapse(self) -> None:
        """Toggle collapsed state."""
        if self._is_long:
            self.is_collapsed = not self.is_collapsed

    def on_click(self) -> None:
        """Select this event when clicked."""
        try:
            log_view: LogView = self.screen.query_one("#log-view", LogView)
            idx: int = log_view._widgets.index(self)
            log_view.selected_index = idx
        except Exception:
            pass


class LogView(VerticalScroll, can_focus=True):
    """
    Scrollable container of log events for selected agent.

    Features:
    - Real-time event appending
    - Auto-scroll to bottom (toggleable)
    - Collapsible long events
    - Search highlighting
    - Keyboard navigation with selection
    """

    # Override scroll bindings to use for message navigation instead
    BINDINGS = [
        ("up", "select_prev", "Previous"),
        ("down", "select_next", "Next"),
        ("enter", "toggle_expand", "Expand"),
    ]

    auto_scroll: reactive[bool] = reactive(True)
    search_query: reactive[str] = reactive("")
    selected_index: reactive[int] = reactive(-1)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._events: list[LogEvent] = []
        self._global_start_ts: int | None = None
        self._widgets: list[LogEventWidget] = []
        self._expand_all_mode: bool = False
        self._suppress_scroll: bool = False

    def watch_selected_index(self, old_index: int, new_index: int) -> None:
        """Update selection visuals when index changes."""
        if 0 <= old_index < len(self._widgets):
            self._widgets[old_index].is_selected = False
        if 0 <= new_index < len(self._widgets):
            self._widgets[new_index].is_selected = True
            if not self._suppress_scroll:
                self._widgets[new_index].scroll_visible()

    def on_focus(self) -> None:
        """Auto-select first event when focusing if none selected."""
        if self.selected_index == -1 and self._widgets:
            self.selected_index = 0

    def set_events(
        self,
        events: list[LogEvent],
        global_start_ts: int | None,
    ) -> None:
        """
        Replace all events (when switching agents).

        Parameters
        ----------
        events : list[LogEvent]
            List of events to display.
        global_start_ts : int | None
            Global start timestamp for relative time (from main.log), or None if unknown.
        """
        self._events = list(events)  # Copy to avoid shared reference with AgentState
        self._global_start_ts = global_start_ts
        self.selected_index = -1  # Reset selection
        self._expand_all_mode = False  # Reset expand state
        self._rebuild_widgets()

    def _rebuild_widgets(self) -> None:
        """Rebuild all event widgets."""
        self.remove_children()
        self._widgets = []

        for event in self._events:
            if event.hidden:
                continue
            widget = LogEventWidget(event, self._global_start_ts)
            self._widgets.append(widget)
            self.mount(widget)

        if self.auto_scroll:
            self.scroll_end(animate=False)

    def append_event(self, event: LogEvent) -> None:
        """
        Add new event (real-time update).

        Parameters
        ----------
        event : LogEvent
            Event to append.
        """
        self._events.append(event)
        if event.hidden:
            return

        widget = LogEventWidget(
            event,
            self._global_start_ts,
            start_expanded=self._expand_all_mode,
        )
        self._widgets.append(widget)
        self.mount(widget)

        if self.auto_scroll:
            self.scroll_end(animate=False)

    def _snap_selection_to_visible(self) -> None:
        """If selected widget is off-screen, move selection to first visible."""
        if not self._widgets:
            return
        if 0 <= self.selected_index < len(self._widgets):
            w = self._widgets[self.selected_index]
            vp_top: int = self.scroll_offset.y
            vp_bottom: int = vp_top + self.size.height
            try:
                if w.virtual_region.y < vp_bottom and w.virtual_region.y + w.virtual_region.height > vp_top:
                    return
            except Exception:
                return
        # Snap — suppress scroll so we don't jump
        vp_top = self.scroll_offset.y
        self._suppress_scroll = True
        for i, widget in enumerate(self._widgets):
            try:
                if widget.virtual_region.y + widget.virtual_region.height > vp_top:
                    self.selected_index = i
                    break
            except Exception:
                pass
        self._suppress_scroll = False

    def expand_all(self) -> None:
        """Expand all collapsible events."""
        self._snap_selection_to_visible()
        self._expand_all_mode = True
        for widget in self._widgets:
            widget.is_collapsed = False
        self.refresh(layout=True)
        if 0 <= self.selected_index < len(self._widgets):
            self.call_after_refresh(
                self._widgets[self.selected_index].scroll_visible
            )

    def collapse_all(self) -> None:
        """Collapse all collapsible events."""
        self._snap_selection_to_visible()
        self._expand_all_mode = False
        for widget in self._widgets:
            widget.is_collapsed = True
        self.refresh(layout=True)
        if 0 <= self.selected_index < len(self._widgets):
            self.call_after_refresh(
                self._widgets[self.selected_index].scroll_visible
            )

    def highlight_search(self, query: str) -> list[int]:
        """
        Highlight search matches.

        Parameters
        ----------
        query : str
            Search query.

        Returns
        -------
        list[int]
            Indices of matching events.
        """
        self.search_query = query
        matches: list[int] = []

        if not query:
            return matches

        query_lower = query.lower()
        for i, event in enumerate(self._events):
            if query_lower in event.description.lower():
                matches.append(i)

        return matches

    def scroll_to_event(self, index: int) -> None:
        """
        Scroll to event at index.

        Parameters
        ----------
        index : int
            Event index.
        """
        if 0 <= index < len(self._widgets):
            self._widgets[index].scroll_visible()

    def select_next(self) -> None:
        """Select the next event."""
        if not self._widgets:
            return
        self._snap_selection_to_visible()
        if self.selected_index < len(self._widgets) - 1:
            self.selected_index += 1
        elif self.selected_index == -1:
            self.selected_index = 0

    def select_prev(self) -> None:
        """Select the previous event."""
        if not self._widgets:
            return
        self._snap_selection_to_visible()
        if self.selected_index > 0:
            self.selected_index -= 1
        elif self.selected_index == -1:
            self.selected_index = len(self._widgets) - 1

    def toggle_selected(self) -> None:
        """Toggle expand/collapse of selected event."""
        if 0 <= self.selected_index < len(self._widgets):
            self._widgets[self.selected_index].toggle_collapse()
            self.refresh(layout=True)

    def action_select_next(self) -> None:
        """Action handler for down key."""
        self.select_next()

    def action_select_prev(self) -> None:
        """Action handler for up key."""
        self.select_prev()

    def action_toggle_expand(self) -> None:
        """Action handler for enter key."""
        self.toggle_selected()

    def get_selected_content(self) -> str | None:
        """
        Get the full content of the selected event.

        Returns
        -------
        str | None
            Full description of selected event, or None if nothing selected.
        """
        if 0 <= self.selected_index < len(self._events):
            return self._events[self.selected_index].full_description
        return None
