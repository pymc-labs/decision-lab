"""
Bottom status bar showing session status, cost, duration.
"""

from textual.widgets import Static
from textual.reactive import reactive
from rich.text import Text


def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable string.

    Parameters
    ----------
    seconds : float
        Duration in seconds.

    Returns
    -------
    str
        Formatted duration (e.g., "2m 34s").
    """
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


class StatusBar(Static):
    """
    Status bar with session information.

    Displays:
    - Job status (RUNNING / COMPLETED)
    - Total cost so far
    - Duration since start
    - Selected agent name
    """

    status: reactive[str] = reactive("RUNNING")
    total_cost: reactive[float] = reactive(0.0)
    duration_seconds: reactive[float] = reactive(0.0)
    selected_agent: reactive[str | None] = reactive(None)

    def render(self) -> Text:
        """Render the status bar."""
        text = Text()

        # Status indicator
        if self.status == "RUNNING":
            text.append(" ● ", style="bold #A6E22E")
            text.append("RUNNING", style="#A6E22E")
        else:
            text.append(" ○ ", style="#75715E")
            text.append("COMPLETED", style="#75715E")

        text.append("  ", style="#75715E")

        # Cost
        text.append(f"${self.total_cost:.4f}", style="#66D9EF")

        text.append("  ", style="#75715E")

        # Duration
        duration_str = format_duration(self.duration_seconds)
        text.append(duration_str, style="#FD971F")

        # Selected agent
        if self.selected_agent:
            text.append("  ", style="#75715E")
            text.append(self.selected_agent, style="#AE81FF")

        return text

    def update_status(
        self,
        is_running: bool,
        cost: float,
        duration: float,
        agent: str | None = None,
    ) -> None:
        """
        Update all status values at once.

        Parameters
        ----------
        is_running : bool
            Whether job is still running.
        cost : float
            Total cost.
        duration : float
            Duration in seconds.
        agent : str | None
            Currently selected agent.
        """
        self.status = "RUNNING" if is_running else "COMPLETED"
        self.total_cost = cost
        self.duration_seconds = duration
        if agent is not None:
            self.selected_agent = agent
