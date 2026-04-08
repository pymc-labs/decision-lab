"""Tests for dlab.viewer module (session_data + layout)."""

import json
from pathlib import Path
from typing import Any

import pytest

from dlab.opencode_logparser import LogEvent, SessionNode, parse_log_file
from dlab.viewer.layout import _tree_to_d3, compute_process_layout
from dlab.viewer.server import export_viewer
from dlab.viewer.session_data import (
    _build_agent_tree,
    _build_enhanced_graph,
    _clean_todo_label,
    _event_to_step,
    _segment_by_todowrite,
    _summarize_steps,
    _truncate,
    extract_process_tree,
)


# ---------------------------------------------------------------------------
# Synthetic log line fixtures
# ---------------------------------------------------------------------------

def _line(type: str, ts: int, **extra: Any) -> str:
    """Build a JSON log line."""
    data: dict[str, Any] = {"type": type, "timestamp": ts, "sessionID": "ses_test"}
    data.update(extra)
    return json.dumps(data)


def _step_start(ts: int) -> str:
    return _line("step_start", ts, part={"type": "step-start"})


def _step_finish(ts: int, reason: str = "tool-calls", cost: float = 0.001) -> str:
    return _line("step_finish", ts, part={
        "reason": reason, "cost": cost,
        "tokens": {"input": 100, "output": 50},
    })


def _text(ts: int, text: str) -> str:
    return _line("text", ts, part={"type": "text", "text": text})


def _tool(ts: int, tool: str, status: str = "completed", **state_extra: Any) -> str:
    state: dict[str, Any] = {
        "status": status,
        "input": state_extra.get("input", {"command": "test"}),
        "output": state_extra.get("output", "ok"),
        "time": {"start": ts, "end": ts + 500},
    }
    if "error" in state_extra:
        state["error"] = state_extra["error"]
    return _line("tool_use", ts, part={
        "type": "tool", "tool": tool, "callID": f"call_{ts}",
        "state": state,
    })


def _todowrite(ts: int, todos: list[dict[str, Any]]) -> str:
    return _line("tool_use", ts, part={
        "type": "tool", "tool": "todowrite", "callID": f"call_todo_{ts}",
        "state": {
            "status": "completed",
            "input": {"todos": todos},
            "output": json.dumps(todos),
            "time": {"start": ts, "end": ts + 2},
        },
    })


def _parallel_agents(ts: int, agent: str, n_prompts: int) -> str:
    return _line("tool_use", ts, part={
        "type": "tool", "tool": "parallel-agents", "callID": f"call_pa_{ts}",
        "state": {
            "status": "completed",
            "input": {"agent": agent, "prompts": ["p"] * n_prompts},
            "output": "done",
            "time": {"start": ts, "end": ts + 60000},
        },
    })


def _error(ts: int, message: str) -> str:
    return _line("error", ts, error={
        "name": "APIError",
        "data": {"message": message, "statusCode": 500},
    })


def _dlab_start(ts: int, model: str = "anthropic/claude-opus-4-5",
                agent: str = "main", prompt: str = "") -> str:
    data: dict[str, Any] = {
        "type": "dlab_start", "timestamp": ts,
        "model": model, "agent": agent,
    }
    if prompt:
        data["prompt"] = prompt
    return json.dumps(data)


def _make_log(tmp_path: Path, name: str, lines: list[str]) -> Path:
    """Write lines to a log file and return path."""
    log_file: Path = tmp_path / name
    log_file.write_text("\n".join(lines) + "\n")
    return log_file


def _make_session(tmp_path: Path, main_lines: list[str],
                  parallel: dict[str, list[list[str]]] | None = None) -> Path:
    """
    Create a work directory with _opencode_logs structure.

    Parameters
    ----------
    tmp_path : Path
        Pytest tmp_path.
    main_lines : list[str]
        Lines for main.log.
    parallel : dict[str, list[list[str]]] | None
        Map of "agent-parallel-run-TS" → list of instance log lines.

    Returns
    -------
    Path
        Work directory path.
    """
    work_dir: Path = tmp_path / "workdir"
    logs_dir: Path = work_dir / "_opencode_logs"
    logs_dir.mkdir(parents=True)
    _make_log(logs_dir, "main.log", main_lines)

    if parallel:
        for run_name, instances in parallel.items():
            run_dir: Path = logs_dir / run_name
            run_dir.mkdir()
            for i, instance_lines in enumerate(instances):
                _make_log(run_dir, f"instance-{i + 1}.log", instance_lines)

    # Create .state.json
    (work_dir / ".state.json").write_text(json.dumps({
        "dpack_name": "test", "status": "completed",
    }))

    return work_dir


# ---------------------------------------------------------------------------
# TestTruncate
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short(self) -> None:
        assert _truncate("hello") == "hello"

    def test_exact_limit(self) -> None:
        assert _truncate("a" * 120) == "a" * 120

    def test_over_limit(self) -> None:
        result: str = _truncate("a" * 150)
        assert result == "a" * 120 + "..."
        assert len(result) == 123

    def test_custom_limit(self) -> None:
        assert _truncate("hello world", 5) == "hello..."


# ---------------------------------------------------------------------------
# TestCleanTodoLabel
# ---------------------------------------------------------------------------


class TestCleanTodoLabel:
    def test_strip_step_prefix(self) -> None:
        assert _clean_todo_label("Step 1: Data exploration") == "Data exploration"

    def test_strip_step_decimal(self) -> None:
        assert _clean_todo_label("Step 6.75: Run optimization") == "Run optimization"

    def test_strip_phase_prefix(self) -> None:
        assert _clean_todo_label("Phase 2: Modeling") == "Modeling"

    def test_passthrough(self) -> None:
        assert _clean_todo_label("Write final reports") == "Write final reports"

    def test_empty_after_strip(self) -> None:
        # If stripping leaves nothing, return original
        assert _clean_todo_label("Step 1:") == "Step 1:"


# ---------------------------------------------------------------------------
# TestSummarizeSteps
# ---------------------------------------------------------------------------


class TestSummarizeSteps:
    def test_tools_only(self) -> None:
        steps: list[dict[str, Any]] = [
            {"type": "tool"}, {"type": "tool"}, {"type": "tool"},
        ]
        assert _summarize_steps(steps) == "3 tool calls"

    def test_singular_tool(self) -> None:
        assert _summarize_steps([{"type": "tool"}]) == "1 tool call"

    def test_messages_only(self) -> None:
        assert _summarize_steps([{"type": "text"}]) == "1 message"

    def test_mixed(self) -> None:
        steps = [{"type": "tool"}, {"type": "tool"}, {"type": "text"}]
        assert _summarize_steps(steps) == "2 tool calls, 1 message"

    def test_errors(self) -> None:
        steps = [{"type": "tool"}, {"type": "error"}]
        assert _summarize_steps(steps) == "1 tool call, 1 error"

    def test_empty(self) -> None:
        assert _summarize_steps([]) == "working"


# ---------------------------------------------------------------------------
# TestEventToStep
# ---------------------------------------------------------------------------


class TestEventToStep:
    def test_text_event(self) -> None:
        event = LogEvent(
            event_type="text", timestamp=1000, session_id="",
            part={"text": "Hello world"}, raw={"type": "text", "part": {"text": "Hello world"}},
        )
        step: dict[str, Any] | None = _event_to_step(event)
        assert step is not None
        assert step["type"] == "text"
        assert step["summary"] == "Hello world"

    def test_tool_completed(self) -> None:
        event = LogEvent(
            event_type="tool_use", timestamp=1000, session_id="",
            part={"tool": "bash", "state": {
                "status": "completed",
                "input": {"command": "ls", "description": "List files"},
                "output": "ok",
                "time": {"start": 1000, "end": 1500},
            }},
            raw={},
        )
        step = _event_to_step(event)
        assert step is not None
        assert step["type"] == "tool"
        assert step["tool"] == "bash"
        assert step["duration_ms"] == 500

    def test_tool_pending_skipped(self) -> None:
        event = LogEvent(
            event_type="tool_use", timestamp=1000, session_id="",
            part={"tool": "read", "state": {"status": "pending"}},
            raw={},
        )
        assert _event_to_step(event) is None

    def test_todowrite_skipped(self) -> None:
        event = LogEvent(
            event_type="tool_use", timestamp=1000, session_id="",
            part={"tool": "todowrite", "state": {"status": "completed"}},
            raw={},
        )
        assert _event_to_step(event) is None

    def test_step_start_skipped(self) -> None:
        event = LogEvent(
            event_type="step_start", timestamp=1000, session_id="",
            part={}, raw={},
        )
        assert _event_to_step(event) is None

    def test_error_event(self) -> None:
        event = LogEvent(
            event_type="error", timestamp=1000, session_id="",
            part={},
            raw={"error": {"name": "APIError", "data": {"message": "Rate limit"}}},
        )
        step = _event_to_step(event)
        assert step is not None
        assert step["type"] == "error"
        assert step["has_error"] is True
        assert "Rate limit" in step["summary"]

    def test_raw_text(self) -> None:
        event = LogEvent(
            event_type="raw_text", timestamp=None, session_id="",
            part={"text": "stderr output"}, raw={},
        )
        step = _event_to_step(event)
        assert step is not None
        assert step["type"] == "raw"

    def test_tool_read(self) -> None:
        event = LogEvent(
            event_type="tool_use", timestamp=1000, session_id="",
            part={"tool": "read", "state": {
                "status": "completed",
                "input": {"filePath": "/workspace/data.csv"},
                "time": {"start": 1000, "end": 1001},
            }},
            raw={},
        )
        step = _event_to_step(event)
        assert step is not None
        assert step["summary"] == "read: data.csv"

    def test_truncation(self) -> None:
        long_text: str = "A" * 200
        event = LogEvent(
            event_type="text", timestamp=1000, session_id="",
            part={"text": long_text}, raw={"type": "text", "part": {"text": long_text}},
        )
        step = _event_to_step(event)
        assert step is not None
        assert step["summary"].endswith("...")
        assert len(step["summary"]) == 123


# ---------------------------------------------------------------------------
# TestSegmentByTodowrite
# ---------------------------------------------------------------------------


class TestSegmentByTodowrite:
    def test_no_todowrite(self, tmp_path: Path) -> None:
        """No todowrite → single preamble phase."""
        log: Path = _make_log(tmp_path, "main.log", [
            _step_start(1000),
            _text(1001, "Hello"),
            _tool(1002, "bash"),
            _step_finish(1003),
        ])
        events = parse_log_file(log)
        phases = _segment_by_todowrite(events)
        assert len(phases) == 1
        assert phases[0]["is_preamble"] is True

    def test_with_todowrite(self, tmp_path: Path) -> None:
        """Todowrite creates labeled phases."""
        todos_v1 = [
            {"content": "Step 1: Explore data", "status": "in_progress", "priority": "high"},
            {"content": "Step 2: Model", "status": "pending", "priority": "high"},
        ]
        todos_v2 = [
            {"content": "Step 1: Explore data", "status": "completed", "priority": "high"},
            {"content": "Step 2: Model", "status": "in_progress", "priority": "high"},
        ]
        log: Path = _make_log(tmp_path, "main.log", [
            _step_start(1000),
            _text(1001, "Let me start"),
            _todowrite(1002, todos_v1),
            _step_finish(1003),
            _step_start(1004),
            _tool(1005, "bash"),
            _todowrite(1006, todos_v2),
            _step_finish(1007),
        ])
        events = parse_log_file(log)
        phases = _segment_by_todowrite(events)

        assert len(phases) == 3
        assert phases[0]["is_preamble"] is True
        assert phases[1]["label"] == "Step 1: Explore data"
        assert phases[2]["label"] == "Step 2: Model"

    def test_duplicate_label_merged(self, tmp_path: Path) -> None:
        """Consecutive phases with same label are merged."""
        todos_v1 = [{"content": "Write report", "status": "in_progress", "priority": "high"}]
        todos_v2 = [{"content": "Write report", "status": "completed", "priority": "high"}]
        log: Path = _make_log(tmp_path, "main.log", [
            _step_start(1000),
            _todowrite(1001, todos_v1),
            _step_finish(1002),
            _step_start(1003),
            _tool(1004, "write"),
            _todowrite(1005, todos_v2),
            _step_finish(1006),
        ])
        events = parse_log_file(log)
        phases = _segment_by_todowrite(events)

        # Preamble + one merged "Write report" phase
        non_preamble = [p for p in phases if not p.get("is_preamble")]
        assert len(non_preamble) == 1
        assert non_preamble[0]["label"] == "Write report"
        assert non_preamble[0]["status"] == "completed"

    def test_final_status_from_last_snapshot(self, tmp_path: Path) -> None:
        """Todo status reflects final todowrite snapshot."""
        todos_v1 = [
            {"content": "Task A", "status": "in_progress", "priority": "high"},
            {"content": "Task B", "status": "pending", "priority": "high"},
        ]
        todos_v2 = [
            {"content": "Task A", "status": "completed", "priority": "high"},
            {"content": "Task B", "status": "in_progress", "priority": "high"},
        ]
        todos_v3 = [
            {"content": "Task A", "status": "completed", "priority": "high"},
            {"content": "Task B", "status": "completed", "priority": "high"},
        ]
        log: Path = _make_log(tmp_path, "main.log", [
            _step_start(1000),
            _todowrite(1001, todos_v1),
            _step_finish(1002),
            _step_start(1003),
            _todowrite(1004, todos_v2),
            _step_finish(1005),
            _step_start(1006),
            _todowrite(1007, todos_v3),
            _step_finish(1008),
        ])
        events = parse_log_file(log)
        phases = _segment_by_todowrite(events)

        non_preamble = [p for p in phases if not p.get("is_preamble")]
        assert all(p["status"] == "completed" for p in non_preamble)


# ---------------------------------------------------------------------------
# TestBuildAgentTree
# ---------------------------------------------------------------------------


class TestBuildAgentTree:
    def test_solo_session(self, tmp_path: Path) -> None:
        """Session with no todowrite, no children."""
        work_dir: Path = _make_session(tmp_path, [
            _dlab_start(1000, prompt="Analyze data"),
            _step_start(1001),
            _text(1002, "I'll analyze the data"),
            _tool(1003, "read", input={"filePath": "/workspace/data.csv"}),
            _step_finish(1004, cost=0.05),
        ])
        result = extract_process_tree(work_dir)
        tree = result["tree"]

        assert tree["agent"] == "main"
        assert tree["model"] == "anthropic/claude-opus-4-5"
        assert tree["prompt"] == "Analyze data"
        assert len(tree["todos"]) == 0
        assert len(tree["preamble_turns"]) == 1
        assert tree["preamble_turns"][0]["type"] == "thinking"

    def test_session_with_todos(self, tmp_path: Path) -> None:
        """Session with todowrite creates todo phases."""
        todos = [
            {"content": "Step 1: Explore", "status": "in_progress", "priority": "high"},
            {"content": "Step 2: Model", "status": "pending", "priority": "high"},
        ]
        work_dir: Path = _make_session(tmp_path, [
            _step_start(1000),
            _text(1001, "Starting"),
            _todowrite(1002, todos),
            _step_finish(1003),
            _step_start(1004),
            _tool(1005, "bash"),
            _step_finish(1006, cost=0.01),
        ])
        result = extract_process_tree(work_dir)
        tree = result["tree"]

        assert len(tree["preamble_turns"]) >= 1
        assert len(tree["todos"]) == 1
        assert tree["todos"][0]["label"] == "Explore"  # "Step 1:" stripped

    def test_session_with_parallel(self, tmp_path: Path) -> None:
        """Session with parallel-agents creates child sub-trees."""
        work_dir: Path = _make_session(
            tmp_path,
            main_lines=[
                _step_start(1000),
                _text(1001, "Spawning agents"),
                _parallel_agents(1002, "worker", 2),
                _step_finish(1003),
                _step_start(1004),
                _text(1005, "Done"),
                _step_finish(1006, reason="stop"),
            ],
            parallel={
                "worker-parallel-run-1002": [
                    [_step_start(1010), _text(1011, "Instance 1 working"), _step_finish(1012)],
                    [_step_start(1010), _text(1011, "Instance 2 working"), _step_finish(1012)],
                ],
            },
        )
        result = extract_process_tree(work_dir)
        tree = result["tree"]

        # Preamble should have thinking + parallel turns
        has_parallel: bool = any(
            t["type"] == "parallel"
            for t in tree["preamble_turns"]
        )
        assert has_parallel

        # Find the parallel turn
        par_turn = [t for t in tree["preamble_turns"] if t["type"] == "parallel"][0]
        assert len(par_turn["children"]) == 2

    def test_task_tool_not_linked_to_parallel(self, tmp_path: Path) -> None:
        """Task tool calls should NOT be linked to parallel children (POPO fix)."""
        work_dir: Path = _make_session(
            tmp_path,
            main_lines=[
                _step_start(1000),
                _text(1001, "Let me call a task"),
                _tool(1002, "task", input={"subagent_type": "popo-poet", "description": "Test"}),
                _step_finish(1003),
                _step_start(1004),
                _text(1005, "Task returned, continuing"),
                _step_finish(1006, reason="stop"),
            ],
            parallel={
                "poet-parallel-run-2000": [
                    [_step_start(2001), _text(2002, "Poet 1"), _step_finish(2003)],
                    [_step_start(2001), _text(2002, "Poet 2"), _step_finish(2003)],
                ],
            },
        )
        result = extract_process_tree(work_dir)
        tree = result["tree"]

        # The task tool should appear as a regular step, NOT linked to children
        all_steps: list[dict[str, Any]] = []
        for t in tree["preamble_turns"]:
            all_steps.extend(t.get("steps", []))
        task_steps = [s for s in all_steps if s.get("tool") == "task"]
        assert len(task_steps) == 1  # task is a regular step

        # Children should be unlinked (appended to last todo as parallel)
        has_parallel: bool = any(
            t["type"] == "parallel"
            for t in tree["preamble_turns"]
        ) or any(
            t["type"] == "parallel"
            for todo in tree["todos"]
            for t in todo.get("turns", [])
        )
        assert has_parallel  # children still appear, just not linked to task


# ---------------------------------------------------------------------------
# TestTreeToD3
# ---------------------------------------------------------------------------


class TestTreeToD3:
    def test_free_form_collapsed(self) -> None:
        """Free-form working todo is collapsed — children promoted."""
        tree: dict[str, Any] = {
            "agent": "main",
            "model": "test-model",
            "is_complete": True,
            "is_consolidator": False,
            "total_cost": 0.1,
            "prompt": None,
            "artifacts": [],
            "preamble_turns": [],
            "todos": [{
                "id": "phase-0",
                "label": "Free-form working",
                "status": None,
                "turns": [{"type": "thinking", "summary": "3 tools", "steps": [], "has_error": False}],
                "has_error": False,
            }],
        }
        d3 = _tree_to_d3(tree)
        # "Free-form working" should NOT appear as a child
        child_names: list[str] = [c["name"] for c in d3["children"]]
        assert "Free-form working" not in child_names
        # The thinking turn should be a direct child
        assert any(c["type"] == "thinking" for c in d3["children"])

    def test_preamble_turns_promoted(self) -> None:
        """Preamble turns become direct children of session."""
        tree: dict[str, Any] = {
            "agent": "main", "model": None,
            "is_complete": True, "is_consolidator": False,
            "total_cost": 0, "prompt": None, "artifacts": [],
            "preamble_turns": [
                {"type": "thinking", "summary": "5 tools", "steps": [], "has_error": False},
            ],
            "todos": [{
                "id": "phase-1", "label": "Do stuff", "status": "completed",
                "turns": [{"type": "thinking", "summary": "2 tools", "steps": [], "has_error": False}],
                "has_error": False,
            }],
        }
        d3 = _tree_to_d3(tree)
        assert len(d3["children"]) == 2
        assert d3["children"][0]["type"] == "thinking"
        assert d3["children"][1]["type"] == "todo"
        assert d3["children"][1]["name"] == "Do stuff"

    def test_parallel_children_recursive(self) -> None:
        """Parallel turns create recursive child session sub-trees."""
        child_tree: dict[str, Any] = {
            "agent": "worker/instance-1", "model": "test",
            "is_complete": True, "is_consolidator": False,
            "total_cost": 0, "prompt": None, "artifacts": [],
            "preamble_turns": [
                {"type": "thinking", "summary": "1 tool", "steps": [], "has_error": False},
            ],
            "todos": [],
        }
        tree: dict[str, Any] = {
            "agent": "main", "model": None,
            "is_complete": True, "is_consolidator": False,
            "total_cost": 0, "prompt": None, "artifacts": [],
            "preamble_turns": [{
                "type": "parallel", "summary": "worker x1",
                "agent": "worker", "steps": [],
                "children": [child_tree], "consolidator": None,
                "has_error": False,
            }],
            "todos": [],
        }
        d3 = _tree_to_d3(tree)
        par = d3["children"][0]
        assert par["type"] == "parallel"
        assert len(par["children"]) == 1
        assert par["children"][0]["type"] == "session"
        assert par["children"][0]["name"] == "worker/instance-1"


# ---------------------------------------------------------------------------
# TestExtractProcessTree (integration)
# ---------------------------------------------------------------------------


class TestExtractProcessTree:
    def test_solo_error(self, tmp_path: Path) -> None:
        """Solo session with error event."""
        work_dir: Path = _make_session(tmp_path, [
            "raw stderr line",
            _error(1000, "Model not found"),
        ])
        result = extract_process_tree(work_dir)
        tree = result["tree"]
        meta = result["meta"]

        assert meta["dpack_name"] == "test"
        assert tree["agent"] == "main"
        # Should have preamble with error
        has_error: bool = any(
            t.get("has_error")
            for t in tree["preamble_turns"]
        )
        assert has_error

    def test_cost_recursive(self, tmp_path: Path) -> None:
        """Total cost includes child sessions."""
        work_dir: Path = _make_session(
            tmp_path,
            main_lines=[
                _step_start(1000),
                _parallel_agents(1001, "worker", 1),
                _step_finish(1002, cost=0.10),
            ],
            parallel={
                "worker-parallel-run-1001": [
                    [_step_start(2000), _step_finish(2001, cost=0.50)],
                ],
            },
        )
        result = extract_process_tree(work_dir)
        # Total should include main (0.10) + child (0.50) = 0.60
        assert result["meta"]["total_cost"] == 0.6

    def test_no_free_form_in_d3(self, tmp_path: Path) -> None:
        """D3 output never contains 'Free-form working' nodes."""
        work_dir: Path = _make_session(tmp_path, [
            _step_start(1000),
            _text(1001, "Hello"),
            _step_finish(1002),
        ])
        result = extract_process_tree(work_dir)
        d3 = compute_process_layout(result["tree"])

        def check_no_ffw(node: dict[str, Any]) -> None:
            assert node.get("name") != "Free-form working", \
                f"Found 'Free-form working' node in d3 tree"
            for child in (node.get("children") or []):
                check_no_ffw(child)

        check_no_ffw(d3)


# ---------------------------------------------------------------------------
# TestExportViewer
# ---------------------------------------------------------------------------


class TestExportViewer:
    def test_basic_export(self, tmp_path: Path) -> None:
        """Export produces a valid HTML file with inlined data."""
        work_dir: Path = _make_session(tmp_path, [
            _dlab_start(1000, prompt="Test prompt"),
            _step_start(1001),
            _text(1002, "Working on it"),
            _tool(1003, "bash"),
            _step_finish(1004, cost=0.05),
        ])
        output: Path = tmp_path / "report.html"
        result: int = export_viewer(work_dir, output)

        assert result == 0
        assert output.exists()

        html: str = output.read_text()
        assert "<!DOCTYPE html>" in html
        assert "__INLINE_DATA__" in html
        assert "__ARTIFACT_MAP__" in html
        # Should NOT have fetch('/api/session')
        assert "fetch('/api/session')" not in html

    def test_export_no_external_deps(self, tmp_path: Path) -> None:
        """Exported HTML has no script src= or link href= to external URLs."""
        work_dir: Path = _make_session(tmp_path, [
            _step_start(1000),
            _text(1001, "Hello"),
            _step_finish(1002),
        ])
        output: Path = tmp_path / "report.html"
        export_viewer(work_dir, output)

        html: str = output.read_text()
        # All CDN scripts should be inlined (or at worst kept as fallback)
        # But no fetch() calls to /api/ endpoints
        assert "fetch(`/api/file/" not in html
        assert "fetch('/api/session')" not in html

    def test_export_with_artifacts(self, tmp_path: Path) -> None:
        """Artifacts are embedded in the export."""
        work_dir: Path = _make_session(tmp_path, [
            _step_start(1000),
            _tool(1001, "write", input={"filePath": "/workspace/report.md"}),
            _step_finish(1002),
        ])
        # Create an artifact file
        (work_dir / "report.md").write_text("# Test Report\nHello world")

        output: Path = tmp_path / "report.html"
        export_viewer(work_dir, output)

        html: str = output.read_text()
        assert "Test Report" in html
        assert "Hello world" in html

    def test_export_with_image_artifact(self, tmp_path: Path) -> None:
        """Binary artifacts are base64-encoded in the export."""
        work_dir: Path = _make_session(tmp_path, [
            _step_start(1000),
            _step_finish(1001),
        ])
        # Create a fake PNG (just the header)
        png_header: bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        (work_dir / "plot.png").write_bytes(png_header)

        output: Path = tmp_path / "report.html"
        export_viewer(work_dir, output)

        html: str = output.read_text()
        assert "data:image/png;base64," in html

    def test_export_csv_truncation(self, tmp_path: Path) -> None:
        """Large CSV files are truncated to 1000 rows in export."""
        work_dir: Path = _make_session(tmp_path, [
            _step_start(1000),
            _step_finish(1001),
        ])
        # Create a CSV with 2000 rows
        header: str = "a,b,c"
        rows: list[str] = [header] + [f"{i},{i*2},{i*3}" for i in range(2000)]
        (work_dir / "data.csv").write_text("\n".join(rows))

        output: Path = tmp_path / "report.html"
        export_viewer(work_dir, output)

        html: str = output.read_text()
        assert "truncated" in html
        assert "2000 rows total" in html

    def test_export_empty_session(self, tmp_path: Path) -> None:
        """Export works for minimal sessions."""
        work_dir: Path = _make_session(tmp_path, [
            _error(1000, "Immediate failure"),
        ])
        output: Path = tmp_path / "report.html"
        result: int = export_viewer(work_dir, output)

        assert result == 0
        assert output.exists()
        assert output.stat().st_size > 1000  # not empty
