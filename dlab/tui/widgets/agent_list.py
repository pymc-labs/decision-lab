"""
Agent selector sidebar widget.

Displays list of agents/sources with status indicators.
"""

import re

from textual.widgets import ListView, ListItem, Static
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text


def shorten_agent_name(name: str) -> str:
    """
    Shorten agent names for display.

    Converts "poet-parallel-run-1234567890/instance-1" to "⟝ poet (…90) / inst-1".
    Converts "poet-parallel-run-1234567890/consolidator" to "⟝ poet (…90) / cnsldtr".

    Parameters
    ----------
    name : str
        Full agent name.

    Returns
    -------
    str
        Shortened display name.
    """
    # Match pattern: agent-parallel-run-<number>/suffix
    match = re.match(r"^(.+)-parallel-run-(\d+)/(.+)$", name)
    if match:
        agent = match.group(1)
        number = match.group(2)
        suffix = match.group(3)

        # Shorten suffix
        if suffix.startswith("instance-"):
            suffix = "inst-" + suffix[9:]
        elif suffix == "consolidator":
            suffix = "cnsldtr"
        elif suffix.startswith("consolidator-"):
            suffix = "cnsldtr-" + suffix[13:]

        return f"⟝ {agent} …{number[-2:]}/ {suffix}"
    return name


class AgentListItem(ListItem):
    """
    List item for a single agent.

    Displays agent name with status indicator.
    """

    def __init__(self, name: str, agent_running: bool = True) -> None:
        """
        Initialize agent list item.

        Parameters
        ----------
        name : str
            Agent name.
        agent_running : bool
            Whether agent is still running.
        """
        super().__init__()
        self.agent_name = name
        self.agent_running = agent_running

    def compose(self):
        """Compose the widget."""
        self._display_name = shorten_agent_name(self.agent_name)
        yield Static(self._build_text(False), id="agent-label")

    def _build_text(self, highlighted: bool) -> Text:
        if self.agent_running:
            indicator = Text("● ", style="bold #A6E22E")
            name_style = "black" if highlighted else ""
        else:
            indicator = Text("○ ", style="#75715E")
            name_style = "black" if highlighted else "#75715E"
        return indicator + Text(self._display_name, style=name_style)

    def watch_highlighted(self, value: bool) -> None:
        super().watch_highlighted(value)
        try:
            self.query_one("#agent-label", Static).update(self._build_text(value))
        except Exception:
            pass


class AgentSelector(ListView):
    """
    Sidebar list widget for selecting log sources.

    Features:
    - Show running agents with green indicator
    - Grey out completed agents
    - Natural sort order (main first, instances, consolidator last)
    - Click/keyboard to select agent
    """

    class AgentSelected(Message):
        """Message sent when an agent is selected."""

        def __init__(self, agent_name: str) -> None:
            self.agent_name = agent_name
            super().__init__()

    selected_agent: reactive[str | None] = reactive(None)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._agents: dict[str, bool] = {}  # name -> is_running

    def update_agents(
        self,
        agents: list[str],
        running: set[str],
    ) -> None:
        """
        Update the agent list with current states.

        Parameters
        ----------
        agents : list[str]
            All agent names (should be pre-sorted).
        running : set[str]
            Names of currently running agents.
        """
        # Track what changed
        new_agents = {name: name in running for name in agents}

        if new_agents == self._agents:
            return

        self._agents = new_agents

        # Rebuild list
        self.clear()
        for name in agents:
            running_status = name in running
            item = AgentListItem(name, agent_running=running_status)
            self.append(item)

        # Re-select if needed
        if self.selected_agent and self.selected_agent in self._agents:
            self._select_by_name(self.selected_agent)

    def _select_by_name(self, name: str) -> None:
        """Select agent by name."""
        for i, item in enumerate(self.children):
            if isinstance(item, AgentListItem) and item.agent_name == name:
                self.index = i
                break

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle selection (Enter key or click)."""
        if isinstance(event.item, AgentListItem):
            self.selected_agent = event.item.agent_name
            self.post_message(self.AgentSelected(event.item.agent_name))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Handle highlight change (arrow key navigation)."""
        if isinstance(event.item, AgentListItem):
            self.selected_agent = event.item.agent_name
            self.post_message(self.AgentSelected(event.item.agent_name))

    def select_first(self) -> None:
        """Select the first agent."""
        if self._agents:
            first_name = next(iter(self._agents.keys()))
            self.selected_agent = first_name
            self._select_by_name(first_name)
            self.post_message(self.AgentSelected(first_name))
