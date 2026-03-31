"""
Search popup overlay widget for the TUI.

Provides a popup search interface that appears on '/' key
and searches the current view (logs or file content).
"""

from textual.containers import Horizontal
from textual.widgets import Input, Static
from textual.message import Message


class SearchPopup(Horizontal):
    """
    Search popup overlay that appears on '/' key.

    Shows a search input with match count indicator.
    Searches only the current active view (Logs or Files tab).
    """

    DEFAULT_CSS = """
    SearchPopup {
        layer: popup;
        width: 50;
        height: 3;
        align: center middle;
        background: $surface;
        border: hkey $accent;
        padding: 0 1;
        display: none;
    }

    SearchPopup.visible {
        display: block;
    }

    SearchPopup #search-input {
        width: 1fr;
        border: none;
    }

    SearchPopup #search-count {
        width: auto;
        min-width: 6;
        padding: 0 1;
        text-align: right;
    }
    """

    class SearchSubmitted(Message):
        """Message sent when search is submitted."""

        def __init__(self, query: str) -> None:
            self.query = query
            super().__init__()

    class SearchChanged(Message):
        """Message sent when search text changes."""

        def __init__(self, query: str) -> None:
            self.query = query
            super().__init__()

    class SearchClosed(Message):
        """Message sent when search popup is closed."""

        pass

    class NextMatch(Message):
        """Message sent to jump to next match."""

        pass

    class PrevMatch(Message):
        """Message sent to jump to previous match."""

        pass

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._match_index: int = 0
        self._match_count: int = 0

    def compose(self):
        """Compose the widget."""
        yield Input(placeholder="Search...", id="search-input")
        yield Static("", id="search-count")

    def show(self) -> None:
        """Show the popup and focus the input."""
        self.add_class("visible")
        search_input = self.query_one("#search-input", Input)
        search_input.focus()

    def hide(self) -> None:
        """Hide the popup and clear search."""
        self.remove_class("visible")
        search_input = self.query_one("#search-input", Input)
        search_input.value = ""
        self._match_index = 0
        self._match_count = 0
        self._update_count_display()
        self.post_message(self.SearchClosed())

    def is_visible(self) -> bool:
        """Check if popup is currently visible."""
        return self.has_class("visible")

    def update_match_count(self, current: int, total: int) -> None:
        """
        Update the match count display.

        Parameters
        ----------
        current : int
            Current match index (1-based).
        total : int
            Total number of matches.
        """
        self._match_index = current
        self._match_count = total
        self._update_count_display()

    def _update_count_display(self) -> None:
        """Update the count label."""
        count_label = self.query_one("#search-count", Static)
        if self._match_count > 0:
            count_label.update(f"{self._match_index}/{self._match_count}")
        elif self.query_one("#search-input", Input).value:
            count_label.update("0/0")
        else:
            count_label.update("")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input text changes."""
        if event.input.id == "search-input":
            self.post_message(self.SearchChanged(event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key - jump to next match."""
        if event.input.id == "search-input":
            self.post_message(self.NextMatch())

    def on_key(self, event) -> None:
        """Handle key events."""
        if event.key == "escape":
            self.hide()
            event.stop()
        elif event.key == "shift+enter":
            self.post_message(self.PrevMatch())
            event.stop()
