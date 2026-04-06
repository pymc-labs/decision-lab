"""
Data models for TUI state management.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dlab.opencode_logparser import ms_to_datetime


@dataclass
class LogEvent:
    """
    Parsed log event with computed fields.

    Attributes
    ----------
    timestamp : int
        Timestamp in milliseconds.
    dt : datetime
        Datetime object.
    event_type : str
        Event type (step_start, step_finish, text, tool_use).
    source : str
        Source agent/log name.
    description : str
        Human-readable description (truncated for display).
    raw : dict[str, Any]
        Original raw JSON data.
    cost : float
        Cost for this event (from step_finish).
    duration_ms : int | None
        Duration in milliseconds if applicable.
    """

    timestamp: int
    dt: datetime
    event_type: str
    source: str
    description: str
    raw: dict[str, Any]
    cost: float = 0.0
    duration_ms: int | None = None
    hidden: bool = False    # True for step_start/step_finish (not rendered)

    @property
    def full_description(self) -> str:
        """
        Get full untruncated description from raw data.

        Returns
        -------
        str
            Full description without any truncation.
        """
        if self.event_type == "dlab_start":
            model = self.raw.get("model", "unknown")
            agent = self.raw.get("agent", "")
            prompt = self.raw.get("prompt", "")
            description = f"Session started · {model} · {agent}"
            if prompt:
                description += f"\n--- prompt ---\n{prompt}"
            return description

        if self.event_type == "step_start":
            return "Step started"

        if self.event_type == "step_finish":
            part = self.raw.get("part", {})
            reason = part.get("reason", "unknown")
            return f"Step finished ({reason})"

        if self.event_type == "text":
            part = self.raw.get("part", {})
            return part.get("text", "")

        if self.event_type == "raw_text":
            part = self.raw.get("part", {})
            return part.get("text", "")

        if self.event_type == "error":
            error_data = self.raw.get("error", {})
            error_name = error_data.get("name", "Error")
            data = error_data.get("data", {})
            message = data.get("message", "Unknown error")
            status_code = data.get("statusCode", "")
            response_body = data.get("responseBody", "")

            description = f"[{error_name}]"
            if status_code:
                description += f" (status: {status_code})"
            description += f"\n{message}"
            if response_body:
                description += f"\n--- response ---\n{response_body}"
            return description

        if self.event_type == "tool_use":
            part = self.raw.get("part", {})
            tool = part.get("tool", "unknown")
            state = part.get("state", {})
            status = state.get("status", "unknown")
            input_data = state.get("input", {})
            output = state.get("output", "")

            if tool == "bash":
                cmd = input_data.get("command", "")
                desc = input_data.get("description", "")
                description = f"bash: {desc or cmd}"
                if output:
                    description += f"\n--- output ---\n{output}"
                return description

            if tool == "read":
                filepath = input_data.get("filePath", "")
                return f"read: {Path(filepath).name}"

            if tool == "write":
                filepath = input_data.get("filePath", "")
                filename = Path(filepath).name
                content = input_data.get("content", "")
                description = f"write: {filename}"
                if content:
                    description += f"\n--- content ---\n{content}"
                return description

            if tool == "edit":
                filepath = input_data.get("filePath", "")
                old_string = input_data.get("oldString", "")
                new_string = input_data.get("newString", "")
                description = f"edit: {Path(filepath).name}"
                if old_string or new_string:
                    description += f"\n-{old_string}\n+{new_string}"
                return description

            if tool == "task":
                subagent = input_data.get("subagent_type", "")
                desc = input_data.get("description", "")
                description = f"task: {subagent} - {desc}"
                if output:
                    description += f"\n--- output ---\n{output}"
                return description

            if tool == "parallel-agents":
                agent = input_data.get("agent", "")
                prompts = input_data.get("prompts", [])
                description = f"parallel-agents: {agent} x{len(prompts)}"
                if output:
                    description += f"\n--- output ---\n{output}"
                return description

            # Generic tool - show everything for debugging
            description = f"{tool} ({status})"
            # Show input parameters
            if input_data:
                description += f"\n--- input ---\n"
                for k, v in input_data.items():
                    description += f"  {k}: {v}\n"
            # Show error if present
            error = state.get("error", "")
            if error:
                description += f"\n--- error ---\n{error}"
            # Show output if present
            if output:
                description += f"\n--- output ---\n{output}"
            return description

        return self.description

    @classmethod
    def from_raw(cls, raw: dict[str, Any], source: str) -> "LogEvent":
        """
        Create LogEvent from raw JSON event data.

        Parameters
        ----------
        raw : dict[str, Any]
            Raw JSON event from log file.
        source : str
            Source name for this event.

        Returns
        -------
        LogEvent
            Parsed event.
        """
        timestamp = raw.get("timestamp")
        # Handle None timestamp (for additional_output events)
        if timestamp is None:
            timestamp = 0  # Will be displayed specially
            dt = datetime.min  # Sentinel — no real timestamp, won't affect duration
        else:
            dt = ms_to_datetime(timestamp)
        event_type = raw.get("type", "unknown")
        part = raw.get("part", {})

        # Build description based on event type
        description = ""
        cost = 0.0
        duration_ms = None
        hidden = False

        if event_type == "dlab_start":
            model = raw.get("model", part.get("model", "unknown"))
            agent = raw.get("agent", part.get("agent", ""))
            description = f"Session started · {model} · {agent}"

        elif event_type == "additional_output":
            # Raw JSON output from tool/script (not a proper OpenCode event)
            raw_data = part.get("raw_data", {})
            description = f"[output] {json.dumps(raw_data)}"

        elif event_type == "raw_text":
            # Raw text output (non-JSON lines from log)
            description = part.get("text", "")

        elif event_type == "step_start":
            description = ""
            hidden = True

        elif event_type == "step_finish":
            description = ""
            hidden = True
            cost = part.get("cost", 0.0)

        elif event_type == "text":
            text = part.get("text", "")
            description = text

        elif event_type == "error":
            error_data = raw.get("error", {})
            error_name = error_data.get("name", "Error")
            data = error_data.get("data", {})
            message = data.get("message", "Unknown error")
            status_code = data.get("statusCode", "")
            response_body = data.get("responseBody", "")

            description = f"[{error_name}]"
            if status_code:
                description += f" (status: {status_code})"
            description += f"\n{message}"
            if response_body:
                description += f"\n--- response ---\n{response_body}"

        elif event_type == "tool_use":
            tool = part.get("tool", "unknown")
            state = part.get("state", {})
            status = state.get("status", "unknown")
            input_data = state.get("input", {})
            output = state.get("output", "")

            if tool == "bash":
                cmd = input_data.get("command", "")
                desc = input_data.get("description", "")
                description = f"bash: {desc or cmd}"
                if output:
                    description += f"\n--- output ---\n{output}"
            elif tool == "read":
                filepath = input_data.get("filePath", "")
                description = f"read: {Path(filepath).name}"
            elif tool == "write":
                filepath = input_data.get("filePath", "")
                filename = Path(filepath).name
                content = input_data.get("content", "")
                description = f"write: {filename}"
                if content:
                    description += f"\n--- content ---\n{content}"
            elif tool == "edit":
                filepath = input_data.get("filePath", "")
                old_string = input_data.get("oldString", "")
                new_string = input_data.get("newString", "")
                description = f"edit: {Path(filepath).name}"
                if old_string or new_string:
                    description += f"\n-{old_string}\n+{new_string}"
            elif tool == "task":
                subagent = input_data.get("subagent_type", "")
                desc = input_data.get("description", "")
                description = f"task: {subagent} - {desc}"
                if output:
                    description += f"\n--- output ---\n{output}"
            elif tool == "parallel-agents":
                agent = input_data.get("agent", "")
                prompts = input_data.get("prompts", [])
                description = f"parallel-agents: {agent} x{len(prompts)}"
                if output:
                    description += f"\n--- output ---\n{output}"
            else:
                # Generic tool handling - show tool name, status, and any output/error
                description = f"{tool} ({status})"
                # Show input parameters
                if input_data:
                    description += f"\n--- input ---\n"
                    for k, v in input_data.items():
                        description += f"  {k}: {v}\n"
                # Show error if present
                error = state.get("error", "")
                if error:
                    description += f"\n--- error ---\n{error}"
                # Show output if present
                if output:
                    description += f"\n--- output ---\n{output}"

            # Extract timing
            time_data = state.get("time", {})
            if time_data:
                start = time_data.get("start")
                end = time_data.get("end")
                if start and end:
                    duration_ms = end - start

        return cls(
            timestamp=timestamp,
            dt=dt,
            event_type=event_type,
            source=source,
            description=description,
            raw=raw,
            cost=cost,
            duration_ms=duration_ms,
            hidden=hidden,
        )


@dataclass
class AgentState:
    """
    State tracking for a single agent/source.

    Attributes
    ----------
    name : str
        Agent/source name.
    is_running : bool
        Whether the agent is still running.
    events : list[LogEvent]
        List of events for this agent.
    total_cost : float
        Accumulated cost.
    start_time : datetime | None
        Start time of first event.
    end_time : datetime | None
        End time of last event.
    """

    name: str
    is_running: bool = True
    events: list[LogEvent] = field(default_factory=list)
    total_cost: float = 0.0
    start_time: datetime | None = None
    end_time: datetime | None = None

    def add_event(self, event: LogEvent) -> bool:
        """
        Add event and update computed state.

        Deduplicates events based on timestamp to prevent duplicates
        from watchdog firing multiple events.

        Parameters
        ----------
        event : LogEvent
            Event to add.

        Returns
        -------
        bool
            True if event was added, False if it was a duplicate.
        """
        # Deduplicate based on timestamp (events with same timestamp are duplicates)
        # Skip deduplication for timestamp=0 events (raw_text, additional_output)
        if event.timestamp > 0 and any(e.timestamp == event.timestamp for e in self.events):
            return False

        self.events.append(event)
        self.total_cost += event.cost

        # Only update timing from events with real timestamps (not raw text / additional_output)
        if event.timestamp > 0:
            if self.start_time is None or event.dt < self.start_time:
                self.start_time = event.dt
            if self.end_time is None or event.dt > self.end_time:
                self.end_time = event.dt

        return True


@dataclass
class SessionState:
    """
    Overall session state.

    Attributes
    ----------
    work_dir : Path
        Path to work directory.
    agents : dict[str, AgentState]
        Agent states keyed by name.
    global_start_ts : int | None
        Earliest timestamp across all agents.
    is_job_running : bool
        Whether the job is still running.
    """

    work_dir: Path
    agents: dict[str, AgentState] = field(default_factory=dict)
    global_start_ts: int | None = None
    is_job_running: bool = True

    @property
    def total_cost(self) -> float:
        """Sum of all agent costs."""
        return sum(a.total_cost for a in self.agents.values())

    @property
    def duration_seconds(self) -> float:
        """
        Duration from first to last timestamp in logs.

        NEVER uses datetime.now() - duration is purely derived from
        log timestamps so the view is identical whether viewed live
        or a year later.
        """
        if self.global_start_ts is None:
            return 0.0

        start_dt = ms_to_datetime(self.global_start_ts)

        # Find latest end time from all agents (from log timestamps only)
        end_times = [
            a.end_time for a in self.agents.values() if a.end_time is not None
        ]
        if end_times:
            end_dt = max(end_times)
        else:
            # No events yet - duration is 0
            return 0.0

        return (end_dt - start_dt).total_seconds()

    def get_or_create_agent(self, name: str) -> AgentState:
        """
        Get existing agent state or create new one.

        Parameters
        ----------
        name : str
            Agent name.

        Returns
        -------
        AgentState
            Agent state.
        """
        if name not in self.agents:
            self.agents[name] = AgentState(name=name)
        return self.agents[name]
