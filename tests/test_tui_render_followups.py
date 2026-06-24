"""Regression tests for the TUI render/perf fixes in the connect-tui-render-faster PR.

Covers the pure-ish helpers that back the performance and correctness fixes:
- ``AgentState.add_event`` O(1) timestamp dedup
- ``discover_artifacts`` directory pruning (notably ``.venv``)
- ``ConnectApp._is_agent_complete_in_memory`` matching ``is_log_complete`` semantics
"""

from pathlib import Path

from dlab.tui.app import ConnectApp
from dlab.tui.models import AgentState, LogEvent
from dlab.tui.widgets.artifacts_pane import discover_artifacts


def _event(timestamp: int, event_type: str, **part: object) -> LogEvent:
    """Build a TUI LogEvent from a raw dict the way the watcher does."""
    raw: dict[str, object] = {"timestamp": timestamp, "type": event_type}
    if part:
        raw["part"] = part
    return LogEvent.from_raw(raw, source="agent")


class TestAddEventDedup:
    """AgentState.add_event deduplicates by timestamp via the _seen set."""

    def test_duplicate_timestamp_rejected(self) -> None:
        state = AgentState(name="agent")
        assert state.add_event(_event(100, "text", text="a")) is True
        # Same timestamp -> treated as a duplicate, not added again.
        assert state.add_event(_event(100, "text", text="b")) is False
        assert len(state.events) == 1

    def test_distinct_timestamps_kept(self) -> None:
        state = AgentState(name="agent")
        assert state.add_event(_event(100, "text", text="a")) is True
        assert state.add_event(_event(200, "text", text="b")) is True
        assert len(state.events) == 2

    def test_zero_timestamp_never_deduped(self) -> None:
        # timestamp=0 events (raw_text / additional_output) must always be added.
        state = AgentState(name="agent")
        assert state.add_event(_event(0, "raw_text", text="x")) is True
        assert state.add_event(_event(0, "raw_text", text="y")) is True
        assert len(state.events) == 2


class TestDiscoverArtifactsPruning:
    """discover_artifacts excludes heavy/irrelevant directories."""

    def test_venv_is_pruned(self, tmp_path: Path) -> None:
        (tmp_path / "report.md").write_text("real artifact")
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "buried.py").write_text("should be ignored")

        found = discover_artifacts(tmp_path, agent_dir=None)

        assert Path("report.md") in found
        assert all(".venv" not in p.parts for p in found)

    def test_other_excluded_dirs_pruned(self, tmp_path: Path) -> None:
        (tmp_path / "keep.csv").write_text("a,b")
        for excluded in ("node_modules", "__pycache__", "build", ".git"):
            d = tmp_path / excluded
            d.mkdir()
            (d / "junk.py").write_text("x")

        found = discover_artifacts(tmp_path, agent_dir=None)

        assert Path("keep.csv") in found
        assert found == [Path("keep.csv")]


class TestInMemoryCompletion:
    """_is_agent_complete_in_memory mirrors is_log_complete semantics."""

    @staticmethod
    def _complete(events: list[LogEvent]) -> bool:
        # The method does not touch self, so an unbound call with None is safe.
        state = AgentState(name="agent", events=events)
        return ConnectApp._is_agent_complete_in_memory(None, state)  # type: ignore[arg-type]

    def test_stop_step_finish_is_complete(self) -> None:
        assert self._complete([_event(100, "step_finish", reason="stop")]) is True

    def test_running_step_finish_not_complete(self) -> None:
        assert self._complete([_event(100, "step_finish", reason="tool_use")]) is False

    def test_error_takes_priority_over_later_step_finish(self) -> None:
        # An error earlier in the list must still mark the agent complete even if
        # the final step_finish has a non-terminal reason (matches is_log_complete,
        # which gives any error event priority).
        events = [
            _event(100, "error"),
            _event(200, "step_finish", reason="tool_use"),
        ]
        assert self._complete(events) is True

    def test_no_terminal_events_not_complete(self) -> None:
        assert self._complete([_event(100, "text", text="hi")]) is False
