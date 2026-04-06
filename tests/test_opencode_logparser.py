"""Tests for dlab.opencode_logparser module."""

import json
from pathlib import Path
from typing import Any

import pytest

from dlab.opencode_logparser import (
    LogEvent,
    SessionNode,
    build_session_graph,
    get_dlab_start_model,
    get_step_cost,
    get_step_reason,
    get_step_tokens,
    get_text,
    get_tool_error,
    get_tool_name,
    get_tool_output,
    get_tool_status,
    get_tool_time,
    is_log_complete,
    is_log_file_complete,
    iter_log_events,
    ms_to_datetime,
    parse_line,
    parse_log_file,
)


# ---------------------------------------------------------------------------
# Realistic log line fixtures
# ---------------------------------------------------------------------------

STEP_START_LINE: str = json.dumps({
    "type": "step_start",
    "timestamp": 1700000000000,
    "sessionID": "ses_abc123",
    "part": {"id": "prt_001", "sessionID": "ses_abc123", "type": "step-start"},
})

STEP_FINISH_LINE: str = json.dumps({
    "type": "step_finish",
    "timestamp": 1700000005000,
    "sessionID": "ses_abc123",
    "part": {
        "id": "prt_002",
        "sessionID": "ses_abc123",
        "type": "step-finish",
        "reason": "stop",
        "cost": 0.0042,
        "tokens": {
            "total": 1500,
            "input": 200,
            "output": 100,
            "reasoning": 0,
            "cache": {"read": 1200, "write": 0},
        },
    },
})

STEP_FINISH_TOOL_CALLS_LINE: str = json.dumps({
    "type": "step_finish",
    "timestamp": 1700000003000,
    "sessionID": "ses_abc123",
    "part": {
        "reason": "tool-calls",
        "cost": 0.001,
        "tokens": {"input": 100, "output": 50, "reasoning": 0, "cache": {"read": 0, "write": 0}},
    },
})

TEXT_LINE: str = json.dumps({
    "type": "text",
    "timestamp": 1700000001000,
    "sessionID": "ses_abc123",
    "part": {
        "id": "prt_003",
        "sessionID": "ses_abc123",
        "type": "text",
        "text": "Hello! I'll analyze your data now.",
        "time": {"start": 1700000001000, "end": 1700000001500},
    },
})

TOOL_COMPLETED_LINE: str = json.dumps({
    "type": "tool_use",
    "timestamp": 1700000002000,
    "sessionID": "ses_abc123",
    "part": {
        "id": "prt_004",
        "type": "tool",
        "tool": "bash",
        "callID": "call_xyz",
        "state": {
            "status": "completed",
            "input": {"command": "ls -la", "description": "List files"},
            "output": "total 8\ndrwxr-xr-x 3 user staff 96 Jan 1 00:00 .",
            "title": "List files",
            "metadata": {},
            "time": {"start": 1700000002000, "end": 1700000002500},
        },
    },
})

TOOL_ERROR_LINE: str = json.dumps({
    "type": "tool_use",
    "timestamp": 1700000002000,
    "sessionID": "ses_abc123",
    "part": {
        "type": "tool",
        "tool": "bash",
        "callID": "call_err",
        "state": {
            "status": "error",
            "input": {"command": "nonexistent_command"},
            "error": "command not found: nonexistent_command",
            "time": {"start": 1700000002000, "end": 1700000002100},
        },
    },
})

TOOL_PENDING_LINE: str = json.dumps({
    "type": "tool_use",
    "timestamp": 1700000002000,
    "sessionID": "ses_abc123",
    "part": {
        "type": "tool",
        "tool": "read",
        "callID": "call_read",
        "state": {
            "status": "pending",
            "input": {"filePath": "/workspace/data.csv"},
            "raw": '{"filePath": "/workspace/data.csv"}',
        },
    },
})

ERROR_LINE: str = json.dumps({
    "type": "error",
    "timestamp": 1700000010000,
    "sessionID": "ses_abc123",
    "error": {
        "name": "APIError",
        "data": {"message": "Rate limit exceeded", "statusCode": 429},
    },
})


REALISTIC_LOG: str = """\
Performing one time database migration, may take a few minutes...
sqlite-migration:done
Database migration complete.
{step_start}
{text}
{tool_completed}
{step_finish_tool_calls}
{step_start2}
{step_finish}
""".format(
    step_start=STEP_START_LINE,
    text=TEXT_LINE,
    tool_completed=TOOL_COMPLETED_LINE,
    step_finish_tool_calls=STEP_FINISH_TOOL_CALLS_LINE,
    step_start2=json.dumps({
        "type": "step_start", "timestamp": 1700000004000,
        "sessionID": "ses_abc123", "part": {"type": "step-start"},
    }),
    step_finish=STEP_FINISH_LINE,
)


# ---------------------------------------------------------------------------
# TestParseLine
# ---------------------------------------------------------------------------


class TestParseLine:
    """Tests for parse_line()."""

    def test_empty_line(self) -> None:
        assert parse_line("") is None
        assert parse_line("   ") is None
        assert parse_line("\n") is None

    def test_step_start(self) -> None:
        event: LogEvent | None = parse_line(STEP_START_LINE)
        assert event is not None
        assert event.event_type == "step_start"
        assert event.timestamp == 1700000000000
        assert event.session_id == "ses_abc123"

    def test_step_finish(self) -> None:
        event: LogEvent | None = parse_line(STEP_FINISH_LINE)
        assert event is not None
        assert event.event_type == "step_finish"
        assert event.part["reason"] == "stop"
        assert event.part["cost"] == 0.0042

    def test_text(self) -> None:
        event: LogEvent | None = parse_line(TEXT_LINE)
        assert event is not None
        assert event.event_type == "text"
        assert "analyze your data" in event.part["text"]

    def test_tool_use(self) -> None:
        event: LogEvent | None = parse_line(TOOL_COMPLETED_LINE)
        assert event is not None
        assert event.event_type == "tool_use"
        assert event.part["tool"] == "bash"
        assert event.part["state"]["status"] == "completed"

    def test_error_event(self) -> None:
        event: LogEvent | None = parse_line(ERROR_LINE)
        assert event is not None
        assert event.event_type == "error"

    def test_stderr_prefix(self) -> None:
        event: LogEvent | None = parse_line("[STDERR] some warning message")
        assert event is not None
        assert event.event_type == "raw_text"
        assert event.timestamp is None
        assert "[STDERR]" in event.part["text"]

    def test_plain_text(self) -> None:
        event: LogEvent | None = parse_line("Database migration complete.")
        assert event is not None
        assert event.event_type == "raw_text"
        assert "Database migration" in event.part["text"]

    def test_malformed_json(self) -> None:
        event: LogEvent | None = parse_line('{"broken json: }}}')
        assert event is not None
        assert event.event_type == "raw_text"

    def test_json_without_type(self) -> None:
        event: LogEvent | None = parse_line('{"key": "value", "number": 42}')
        assert event is not None
        assert event.event_type == "additional_output"
        assert event.part["raw_data"]["key"] == "value"

    def test_json_with_type_but_no_timestamp(self) -> None:
        event: LogEvent | None = parse_line('{"type": "text"}')
        assert event is not None
        assert event.event_type == "additional_output"

    def test_raw_preserves_full_json(self) -> None:
        event: LogEvent | None = parse_line(STEP_FINISH_LINE)
        assert event is not None
        assert event.raw["type"] == "step_finish"
        assert "part" in event.raw


# ---------------------------------------------------------------------------
# TestParseLogFile
# ---------------------------------------------------------------------------


class TestParseLogFile:
    """Tests for parse_log_file()."""

    def test_realistic_log(self, tmp_path: Path) -> None:
        """Parse a realistic log with stderr + JSON events."""
        log_file: Path = tmp_path / "main.log"
        log_file.write_text(REALISTIC_LOG)

        events: list[LogEvent] = parse_log_file(log_file)

        # Should have: raw_text (grouped startup), step_start, text, tool, step_finish(tool-calls), step_start, step_finish(stop)
        event_types: list[str] = [e.event_type for e in events]
        assert event_types[0] == "raw_text"  # grouped startup lines
        assert "step_start" in event_types
        assert "text" in event_types
        assert "tool_use" in event_types
        assert "step_finish" in event_types

    def test_groups_consecutive_raw_text(self, tmp_path: Path) -> None:
        """Consecutive raw text lines should be grouped into one event."""
        log_file: Path = tmp_path / "test.log"
        log_file.write_text("line one\nline two\nline three\n")

        events: list[LogEvent] = parse_log_file(log_file)
        assert len(events) == 1
        assert events[0].event_type == "raw_text"
        assert "line one" in events[0].part["text"]
        assert "line three" in events[0].part["text"]

    def test_raw_text_between_json(self, tmp_path: Path) -> None:
        """Raw text between JSON events should create separate groups."""
        log_file: Path = tmp_path / "test.log"
        log_file.write_text(f"startup message\n{STEP_START_LINE}\nstderr noise\n{TEXT_LINE}\n")

        events: list[LogEvent] = parse_log_file(log_file)
        types: list[str] = [e.event_type for e in events]
        assert types == ["raw_text", "step_start", "raw_text", "text"]

    def test_empty_file(self, tmp_path: Path) -> None:
        log_file: Path = tmp_path / "empty.log"
        log_file.write_text("")
        assert parse_log_file(log_file) == []

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        assert parse_log_file(tmp_path / "nope.log") == []

    def test_only_json_events(self, tmp_path: Path) -> None:
        """File with only JSON events should have no raw_text."""
        log_file: Path = tmp_path / "clean.log"
        log_file.write_text(f"{STEP_START_LINE}\n{TEXT_LINE}\n{STEP_FINISH_LINE}\n")

        events: list[LogEvent] = parse_log_file(log_file)
        assert all(e.event_type != "raw_text" for e in events)
        assert len(events) == 3


# ---------------------------------------------------------------------------
# TestIterLogEvents
# ---------------------------------------------------------------------------


class TestIterLogEvents:
    """Tests for iter_log_events()."""

    def test_yields_events(self, tmp_path: Path) -> None:
        log_file: Path = tmp_path / "test.log"
        log_file.write_text(f"{STEP_START_LINE}\n{TEXT_LINE}\n")

        events: list[LogEvent] = list(iter_log_events(log_file))
        assert len(events) == 2

    def test_no_grouping(self, tmp_path: Path) -> None:
        """iter_log_events does NOT group raw_text (unlike parse_log_file)."""
        log_file: Path = tmp_path / "test.log"
        log_file.write_text("line one\nline two\n")

        events: list[LogEvent] = list(iter_log_events(log_file))
        assert len(events) == 2  # Not grouped


# ---------------------------------------------------------------------------
# TestIsLogComplete
# ---------------------------------------------------------------------------


class TestIsLogComplete:
    """Tests for is_log_complete() and is_log_file_complete()."""

    def test_complete_stop(self) -> None:
        events: list[LogEvent] = [
            LogEvent("step_start", 1000, "", {}, {}),
            LogEvent("step_finish", 2000, "", {"reason": "stop", "cost": 0.01}, {}),
        ]
        assert is_log_complete(events) is True

    def test_complete_error_reason(self) -> None:
        events: list[LogEvent] = [
            LogEvent("step_start", 1000, "", {}, {}),
            LogEvent("step_finish", 2000, "", {"reason": "error"}, {}),
        ]
        assert is_log_complete(events) is True

    def test_running_tool_calls(self) -> None:
        events: list[LogEvent] = [
            LogEvent("step_start", 1000, "", {}, {}),
            LogEvent("step_finish", 2000, "", {"reason": "tool-calls"}, {}),
        ]
        assert is_log_complete(events) is False

    def test_error_event(self) -> None:
        events: list[LogEvent] = [
            LogEvent("step_start", 1000, "", {}, {}),
            LogEvent("error", 2000, "", {}, {}),
        ]
        assert is_log_complete(events) is True

    def test_empty(self) -> None:
        assert is_log_complete([]) is False

    def test_no_step_finish(self) -> None:
        events: list[LogEvent] = [
            LogEvent("step_start", 1000, "", {}, {}),
            LogEvent("text", 1500, "", {"text": "hello"}, {}),
        ]
        assert is_log_complete(events) is False

    def test_file_complete(self, tmp_path: Path) -> None:
        log_file: Path = tmp_path / "done.log"
        log_file.write_text(f"{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")
        assert is_log_file_complete(log_file) is True

    def test_file_running(self, tmp_path: Path) -> None:
        log_file: Path = tmp_path / "running.log"
        log_file.write_text(f"{STEP_START_LINE}\n{STEP_FINISH_TOOL_CALLS_LINE}\n")
        assert is_log_file_complete(log_file) is False


# ---------------------------------------------------------------------------
# TestToolHelpers
# ---------------------------------------------------------------------------


class TestToolHelpers:
    """Tests for tool accessor functions."""

    def _make_tool_event(self, status: str, **kwargs: Any) -> LogEvent:
        state: dict[str, Any] = {"status": status, "input": {}, **kwargs}
        return LogEvent("tool_use", 1000, "", {"tool": "bash", "state": state}, {})

    def test_get_tool_name(self) -> None:
        event: LogEvent = self._make_tool_event("completed")
        assert get_tool_name(event) == "bash"

    def test_get_tool_name_non_tool(self) -> None:
        event: LogEvent = LogEvent("text", 1000, "", {"text": "hi"}, {})
        assert get_tool_name(event) is None

    def test_get_tool_status_completed(self) -> None:
        assert get_tool_status(self._make_tool_event("completed")) == "completed"

    def test_get_tool_status_error(self) -> None:
        assert get_tool_status(self._make_tool_event("error")) == "error"

    def test_get_tool_status_pending(self) -> None:
        assert get_tool_status(self._make_tool_event("pending")) == "pending"

    def test_get_tool_status_running(self) -> None:
        assert get_tool_status(self._make_tool_event("running")) == "running"

    def test_get_tool_output(self) -> None:
        event: LogEvent = self._make_tool_event("completed", output="result text")
        assert get_tool_output(event) == "result text"

    def test_get_tool_error(self) -> None:
        event: LogEvent = self._make_tool_event("error", error="command not found")
        assert get_tool_error(event) == "command not found"

    def test_get_tool_time(self) -> None:
        event: LogEvent = self._make_tool_event(
            "completed", time={"start": 1000, "end": 2000},
        )
        start, end = get_tool_time(event)
        assert start == 1000
        assert end == 2000

    def test_get_tool_time_no_time(self) -> None:
        event: LogEvent = self._make_tool_event("pending")
        start, end = get_tool_time(event)
        assert start is None
        assert end is None


# ---------------------------------------------------------------------------
# TestStepHelpers
# ---------------------------------------------------------------------------


class TestStepHelpers:
    """Tests for step accessor functions."""

    def test_get_step_reason(self) -> None:
        event: LogEvent | None = parse_line(STEP_FINISH_LINE)
        assert event is not None
        assert get_step_reason(event) == "stop"

    def test_get_step_reason_non_step(self) -> None:
        event: LogEvent | None = parse_line(TEXT_LINE)
        assert event is not None
        assert get_step_reason(event) is None

    def test_get_step_cost(self) -> None:
        event: LogEvent | None = parse_line(STEP_FINISH_LINE)
        assert event is not None
        cost: float | None = get_step_cost(event)
        assert cost is not None
        assert cost == 0.0042

    def test_get_step_cost_zero(self) -> None:
        event: LogEvent = LogEvent("step_finish", 1000, "", {"reason": "stop", "cost": 0}, {})
        assert get_step_cost(event) is None  # 0 cost treated as None

    def test_get_step_tokens(self) -> None:
        event: LogEvent | None = parse_line(STEP_FINISH_LINE)
        assert event is not None
        tokens: dict[str, Any] | None = get_step_tokens(event)
        assert tokens is not None
        assert tokens["input"] == 200
        assert tokens["output"] == 100
        assert tokens["cache"]["read"] == 1200

    def test_get_step_tokens_non_step(self) -> None:
        event: LogEvent | None = parse_line(TEXT_LINE)
        assert event is not None
        assert get_step_tokens(event) is None


# ---------------------------------------------------------------------------
# TestTextHelpers
# ---------------------------------------------------------------------------


class TestTextHelpers:
    """Tests for get_text()."""

    def test_text_event(self) -> None:
        event: LogEvent | None = parse_line(TEXT_LINE)
        assert event is not None
        text: str | None = get_text(event)
        assert text is not None
        assert "analyze your data" in text

    def test_raw_text_event(self) -> None:
        event: LogEvent | None = parse_line("some raw output")
        assert event is not None
        assert get_text(event) == "some raw output"

    def test_non_text_event(self) -> None:
        event: LogEvent | None = parse_line(STEP_START_LINE)
        assert event is not None
        assert get_text(event) is None


# ---------------------------------------------------------------------------
# TestMsToDatetime
# ---------------------------------------------------------------------------


class TestMsToDatetime:
    """Tests for ms_to_datetime()."""

    def test_conversion(self) -> None:
        dt = ms_to_datetime(1700000000000)
        assert dt.year == 2023
        assert dt.month == 11


# ---------------------------------------------------------------------------
# TestDlabStart
# ---------------------------------------------------------------------------


DLAB_START_LINE: str = json.dumps({
    "type": "dlab_start",
    "timestamp": 1700000000000,
    "model": "anthropic/claude-sonnet-4-5",
    "agent": "main",
})


class TestDlabStart:
    """Tests for dlab_start event parsing."""

    def test_parse_dlab_start(self) -> None:
        event: LogEvent | None = parse_line(DLAB_START_LINE)
        assert event is not None
        assert event.event_type == "dlab_start"
        assert event.raw.get("model") == "anthropic/claude-sonnet-4-5"

    def test_get_model_from_dlab_start(self) -> None:
        events: list[LogEvent] = [
            LogEvent("dlab_start", 1000, "", {"model": "google/gemini-2.5-flash"}, {"model": "google/gemini-2.5-flash"}),
            LogEvent("step_start", 2000, "", {}, {}),
        ]
        assert get_dlab_start_model(events) == "google/gemini-2.5-flash"

    def test_no_dlab_start_returns_none(self) -> None:
        events: list[LogEvent] = [
            LogEvent("step_start", 1000, "", {}, {}),
            LogEvent("text", 2000, "", {"text": "hi"}, {}),
        ]
        assert get_dlab_start_model(events) is None

    def test_dlab_start_in_log_file(self, tmp_path: Path) -> None:
        """dlab_start as first line followed by normal events."""
        log_file: Path = tmp_path / "main.log"
        log_file.write_text(f"{DLAB_START_LINE}\n{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")

        events: list[LogEvent] = parse_log_file(log_file)
        assert events[0].event_type == "dlab_start"
        assert get_dlab_start_model(events) == "anthropic/claude-sonnet-4-5"
        # Other events still parsed normally
        assert events[1].event_type == "step_start"

    def test_backwards_compatible_no_dlab_start(self, tmp_path: Path) -> None:
        """Older logs without dlab_start still parse correctly."""
        log_file: Path = tmp_path / "main.log"
        log_file.write_text(f"Database migration...\n{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")

        events: list[LogEvent] = parse_log_file(log_file)
        assert events[0].event_type == "raw_text"
        assert get_dlab_start_model(events) is None


# ---------------------------------------------------------------------------
# TestBuildSessionGraph
# ---------------------------------------------------------------------------


class TestBuildSessionGraph:
    """Tests for build_session_graph()."""

    def test_missing_main_log(self, tmp_path: Path) -> None:
        assert build_session_graph(tmp_path) is None

    def test_main_only(self, tmp_path: Path) -> None:
        """Session with only main.log (no parallel agents)."""
        (tmp_path / "main.log").write_text(f"{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")

        root: SessionNode | None = build_session_graph(tmp_path)
        assert root is not None
        assert root.name == "main"
        assert root.agent_name == "main"
        assert len(root.events) == 2
        assert root.children == []

    def test_with_parallel_instances(self, tmp_path: Path) -> None:
        """Session with main + parallel agent instances."""
        # Main log with a parallel-agents tool call
        pa_tool_call: str = json.dumps({
            "type": "tool_use",
            "timestamp": 1700000010000,
            "sessionID": "ses_abc",
            "part": {
                "tool": "parallel-agents",
                "callID": "call_pa",
                "state": {
                    "status": "completed",
                    "input": {"agent": "worker", "prompts": ["p1", "p2"]},
                    "output": "results",
                    "time": {"start": 1700000005000, "end": 1700000010000},
                },
            },
        })
        (tmp_path / "main.log").write_text(
            f"{STEP_START_LINE}\n{pa_tool_call}\n{STEP_FINISH_LINE}\n"
        )

        # Create parallel run directory matching the agent name
        run_dir: Path = tmp_path / "worker-parallel-run-1700000005000"
        run_dir.mkdir()
        (run_dir / "instance-1.log").write_text(f"{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")
        (run_dir / "instance-2.log").write_text(f"{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")

        root: SessionNode | None = build_session_graph(tmp_path)
        assert root is not None
        assert len(root.children) == 2
        assert root.children[0].name == "instance-1"
        assert root.children[0].agent_name == "worker"
        assert root.children[1].name == "instance-2"
        # parent_event_index should point to the tool_use event
        assert root.children[0].parent_event_index == 1  # 0=step_start, 1=tool_use

    def test_with_consolidator(self, tmp_path: Path) -> None:
        """Session with instances + consolidator."""
        pa_tool_call: str = json.dumps({
            "type": "tool_use",
            "timestamp": 1700000010000,
            "sessionID": "ses_abc",
            "part": {
                "tool": "parallel-agents",
                "callID": "call_pa",
                "state": {
                    "status": "completed",
                    "input": {"agent": "modeler", "prompts": ["p1", "p2", "p3"]},
                    "output": "results",
                    "time": {"start": 1700000005000, "end": 1700000010000},
                },
            },
        })
        (tmp_path / "main.log").write_text(f"{STEP_START_LINE}\n{pa_tool_call}\n{STEP_FINISH_LINE}\n")

        run_dir: Path = tmp_path / "modeler-parallel-run-1700000005000"
        run_dir.mkdir()
        (run_dir / "instance-1.log").write_text(f"{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")
        (run_dir / "instance-2.log").write_text(f"{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")
        (run_dir / "instance-3.log").write_text(f"{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")
        (run_dir / "consolidator.log").write_text(f"{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")

        root: SessionNode | None = build_session_graph(tmp_path)
        assert root is not None
        assert len(root.children) == 4  # 3 instances + consolidator

        consolidators: list[SessionNode] = [c for c in root.children if c.is_consolidator]
        assert len(consolidators) == 1
        assert consolidators[0].name == "consolidator"
        assert consolidators[0].agent_name == "modeler"

    def test_model_from_dlab_start(self, tmp_path: Path) -> None:
        """Model should be extracted from dlab_start event."""
        dlab_start: str = json.dumps({
            "type": "dlab_start", "timestamp": 999,
            "model": "openai/gpt-5", "agent": "main",
        })
        (tmp_path / "main.log").write_text(f"{dlab_start}\n{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")

        root: SessionNode | None = build_session_graph(tmp_path)
        assert root is not None
        assert root.model == "openai/gpt-5"

    def test_model_none_for_old_logs(self, tmp_path: Path) -> None:
        """Older logs without dlab_start should have model=None."""
        (tmp_path / "main.log").write_text(f"{STEP_START_LINE}\n{STEP_FINISH_LINE}\n")

        root: SessionNode | None = build_session_graph(tmp_path)
        assert root is not None
        assert root.model is None

    def test_real_logs(self) -> None:
        """Test with real MMM session logs if available."""
        logs_dir: Path = Path.home() / "dlab-demo/dlab-mmm-agent-oc-workdir-003/_opencode_logs"
        if not logs_dir.exists():
            pytest.skip("Real log directory not available")

        root: SessionNode | None = build_session_graph(logs_dir)
        assert root is not None
        assert root.name == "main"
        assert len(root.events) > 0
        # Should have children from parallel agent calls
        assert len(root.children) > 0
        # Old logs won't have dlab_start
        assert root.model is None

        # Check children have agent names
        agent_names: set[str] = {c.agent_name for c in root.children}
        assert "data-preparer" in agent_names or "modeler" in agent_names
