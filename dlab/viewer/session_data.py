"""
Extract structured session data from a work directory for the viewer.

Converts the SessionNode tree (from opencode_logparser) into flat
JSON-serializable node and edge dicts suitable for DAG rendering.
Handles main-node splitting at parallel-agents boundaries and
fallback discovery of parallel run directories.
"""

import json
from pathlib import Path
from typing import Any

from dlab.opencode_logparser import (
    LogEvent,
    SessionNode,
    build_session_graph,
    get_step_cost,
    get_text,
    get_tool_error,
    get_tool_input,
    get_tool_name,
    get_tool_output,
    get_tool_status,
    get_tool_time,
    is_log_complete,
    parse_log_file,
)
from dlab.tui.widgets.artifacts_pane import (
    discover_artifacts,
)


def _find_parallel_spawn_points(events: list[LogEvent]) -> list[dict[str, Any]]:
    """
    Find tool calls that spawned parallel work.

    Only parallel-agents calls are "blocking" (main waits for them),
    so only those are used as split points. Task calls are non-blocking
    (fire-and-forget) and are recorded for child linking but don't
    split main.

    Parameters
    ----------
    events : list[LogEvent]
        Events from a parent node.

    Returns
    -------
    list[dict[str, Any]]
        List of spawn point dicts with event_index, tool, agent_name, time, blocking.
    """
    spawn_points: list[dict[str, Any]] = []
    for i, event in enumerate(events):
        if event.event_type != "tool_use":
            continue
        tool: str | None = get_tool_name(event)
        status: str | None = get_tool_status(event)
        if tool not in ("parallel-agents", "task"):
            continue
        if status not in ("completed", "error"):
            continue

        state: dict[str, Any] = event.part.get("state", {})
        input_data: dict[str, Any] = state.get("input", {})
        time_start, time_end = get_tool_time(event)

        agent_name: str = ""
        if tool == "parallel-agents":
            agent_name = input_data.get("agent", "")
        elif tool == "task":
            agent_name = input_data.get("subagent_type", "")

        spawn_points.append({
            "event_index": i,
            "tool": tool,
            "agent_name": agent_name,
            "time_start": time_start,
            "time_end": time_end,
            "blocking": tool == "parallel-agents",
        })

    return spawn_points


def _discover_parallel_dirs(logs_dir: Path) -> list[Path]:
    """
    Find all parallel run directories in the logs dir.

    Parameters
    ----------
    logs_dir : Path
        Path to _opencode_logs directory.

    Returns
    -------
    list[Path]
        Sorted list of parallel run directory paths.
    """
    dirs: list[Path] = []
    if not logs_dir.exists():
        return dirs
    for item in sorted(logs_dir.iterdir()):
        if item.is_dir() and "-parallel-run-" in item.name:
            dirs.append(item)
    return dirs


def _build_enhanced_graph(work_dir: Path) -> SessionNode | None:
    """
    Build a session graph with fallback parallel directory discovery.

    If build_session_graph() finds no children but parallel run
    directories exist on disk, manually link them to the root.

    Parameters
    ----------
    work_dir : Path
        Session work directory.

    Returns
    -------
    SessionNode | None
        Enhanced session graph root, or None.
    """
    logs_dir: Path = work_dir / "_opencode_logs"
    root: SessionNode | None = build_session_graph(logs_dir)
    if root is None:
        return None

    # If build_session_graph already found children, use as-is
    if root.children:
        return root

    # Fallback: discover parallel run dirs and link manually
    parallel_dirs: list[Path] = _discover_parallel_dirs(logs_dir)
    if not parallel_dirs:
        return root

    # Find spawn points in main events to link children
    spawn_points: list[dict[str, Any]] = _find_parallel_spawn_points(root.events)

    for run_dir in parallel_dirs:
        # Extract agent name from dir: "poet-parallel-run-1234" → "poet"
        dir_name: str = run_dir.name
        parts: list[str] = dir_name.split("-parallel-run-")
        agent_name: str = parts[0] if len(parts) == 2 else dir_name

        # Try to match to a blocking spawn point (parallel-agents only).
        # Task tool calls are single subagents, not parallel spawns.
        parent_idx: int | None = None
        for sp in spawn_points:
            if not sp["blocking"]:
                continue
            if agent_name in sp["agent_name"] or sp["agent_name"] in agent_name:
                parent_idx = sp["event_index"]
                break

        # Parse instance logs
        instance_logs: list[Path] = sorted(run_dir.glob("instance-*.log"))
        for instance_log in instance_logs:
            instance_events: list[LogEvent] = parse_log_file(instance_log)
            child: SessionNode = SessionNode(
                name=instance_log.stem,
                log_path=instance_log,
                events=instance_events,
                parent_event_index=parent_idx,
                agent_name=agent_name,
                model=_get_model(instance_events),
            )
            root.children.append(child)

        # Parse consolidator if present
        consolidator_log: Path = run_dir / "consolidator.log"
        if consolidator_log.exists():
            cons_events: list[LogEvent] = parse_log_file(consolidator_log)
            cons_node: SessionNode = SessionNode(
                name="consolidator",
                log_path=consolidator_log,
                events=cons_events,
                parent_event_index=parent_idx,
                agent_name=agent_name,
                is_consolidator=True,
                model=_get_model(cons_events),
            )
            root.children.append(cons_node)

    return root


def _get_model(events: list[LogEvent]) -> str | None:
    """Extract model from dlab_start event if present."""
    for event in events:
        if event.event_type == "dlab_start":
            return event.part.get("model") or event.raw.get("model")
        if event.timestamp is not None:
            break
    return None


def _get_prompt(events: list[LogEvent]) -> str | None:
    """Extract prompt from dlab_start event if present."""
    for event in events:
        if event.event_type == "dlab_start":
            return event.part.get("prompt") or event.raw.get("prompt")
        if event.timestamp is not None:
            break
    return None


def _load_state_meta(work_dir: Path) -> dict[str, Any]:
    """
    Load session metadata from .state.json.

    Parameters
    ----------
    work_dir : Path
        Session work directory.

    Returns
    -------
    dict[str, Any]
        Session metadata (dpack_name, status, etc.).
    """
    state_file: Path = work_dir / ".state.json"
    if not state_file.exists():
        return {}
    try:
        with open(state_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _find_parallel_artifact_dir(
    work_dir: Path,
    agent_name: str,
    instance_name: str,
) -> Path | None:
    """
    Map agent_name + instance_name to the parallel work directory.

    Parallel artifacts live in: parallel/run-TIMESTAMP/instance-N/
    We match by finding run dirs whose parent log dir name contains agent_name.

    Parameters
    ----------
    work_dir : Path
        Session work directory.
    agent_name : str
        Agent name (e.g. "poet").
    instance_name : str
        Instance or consolidator name (e.g. "instance-1", "consolidator").

    Returns
    -------
    Path | None
        Artifact directory path, or None if not found.
    """
    parallel_dir: Path = work_dir / "parallel"
    if not parallel_dir.exists():
        return None

    # Find matching run directory
    for run_dir in sorted(parallel_dir.iterdir()):
        if not run_dir.is_dir() or not run_dir.name.startswith("run-"):
            continue
        # Check if corresponding log dir exists with agent name
        timestamp: str = run_dir.name[4:]  # strip "run-"
        logs_dir: Path = work_dir / "_opencode_logs"
        log_dir_name: str = f"{agent_name}-parallel-run-{timestamp}"
        if (logs_dir / log_dir_name).exists():
            candidate: Path = run_dir / instance_name
            if candidate.exists():
                return candidate

    # Fallback: if only one run dir, use it
    run_dirs: list[Path] = [d for d in parallel_dir.iterdir() if d.is_dir() and d.name.startswith("run-")]
    if len(run_dirs) == 1:
        candidate = run_dirs[0] / instance_name
        if candidate.exists():
            return candidate

    return None


def _truncate(text: str, max_len: int = 120) -> str:
    """Truncate text with ellipsis."""
    return text[:max_len] + "..." if len(text) > max_len else text


# ---------------------------------------------------------------------------
# Process tree extraction (v2 — todo-segmented vertical tree)
# ---------------------------------------------------------------------------


def _event_to_step(event: LogEvent) -> dict[str, Any] | None:
    """
    Convert a single LogEvent to a step dict for the process tree.

    Returns None for events that should be skipped (step_start,
    step_finish, intermediate tool states, todowrite).

    Parameters
    ----------
    event : LogEvent
        Parsed log event.

    Returns
    -------
    dict[str, Any] | None
        Step dict or None to skip.
    """
    etype: str = event.event_type

    # Skip structural events
    if etype in ("step_start", "step_finish", "dlab_start", "additional_output"):
        return None

    # Skip reasoning (extended thinking)
    if etype == "reasoning":
        return None

    if etype == "text":
        text: str | None = get_text(event)
        if not text or not text.strip():
            return None
        first_line: str = _truncate(text.strip().split("\n")[0])
        return {
            "type": "text",
            "tool": None,
            "status": None,
            "summary": first_line,
            "timestamp": event.timestamp,
            "duration_ms": None,
            "cost": 0.0,
            "has_error": False,
            "raw": event.raw,
        }

    if etype == "raw_text":
        text = get_text(event)
        if not text or not text.strip():
            return None
        first_line = text.strip().split("\n")[0][:120]
        return {
            "type": "raw",
            "tool": None,
            "status": None,
            "summary": first_line,
            "timestamp": event.timestamp,
            "duration_ms": None,
            "cost": 0.0,
            "has_error": False,
            "raw": event.raw,
        }

    if etype == "error":
        err_data: dict[str, Any] = event.raw.get("error", event.part.get("error", {}))
        if isinstance(err_data, dict):
            msg: str = err_data.get("data", {}).get("message", err_data.get("name", "Error"))
        else:
            msg = str(err_data)
        return {
            "type": "error",
            "tool": None,
            "status": "error",
            "summary": _truncate(msg),
            "timestamp": event.timestamp,
            "duration_ms": None,
            "cost": 0.0,
            "has_error": True,
            "raw": event.raw,
        }

    if etype == "tool_use":
        tool: str | None = get_tool_name(event)
        status: str | None = get_tool_status(event)

        # Skip intermediate states (pending, running) — only show final
        if status not in ("completed", "error"):
            return None

        # Skip todowrite from step list (it's a phase boundary)
        if tool == "todowrite":
            return None

        # Build summary
        input_data: dict[str, Any] | None = get_tool_input(event)
        summary: str = tool or "unknown"
        if tool == "bash":
            desc: str = (input_data or {}).get("description", "")
            cmd: str = (input_data or {}).get("command", "")
            summary = f"bash: {desc or cmd[:60]}"
        elif tool == "read":
            fp: str = (input_data or {}).get("filePath", "")
            summary = f"read: {Path(fp).name}" if fp else "read"
        elif tool == "write":
            fp = (input_data or {}).get("filePath", "")
            summary = f"write: {Path(fp).name}" if fp else "write"
        elif tool == "edit":
            fp = (input_data or {}).get("filePath", "")
            summary = f"edit: {Path(fp).name}" if fp else "edit"
        elif tool == "glob":
            pattern: str = (input_data or {}).get("pattern", "")
            summary = f"glob: {pattern}" if pattern else "glob"
        elif tool == "inspect-data":
            summary = "inspect-data"
        elif tool == "task":
            subagent: str = (input_data or {}).get("subagent_type", "")
            summary = f"task: {subagent}" if subagent else "task"
        elif tool == "parallel-agents":
            agent: str = (input_data or {}).get("agent", "")
            prompts: list = (input_data or {}).get("prompts", [])
            summary = f"parallel-agents: {agent} x{len(prompts)}"
        elif tool == "optimize-budget":
            summary = "optimize-budget"

        time_start, time_end = get_tool_time(event)
        dur: int | None = (time_end - time_start) if time_start and time_end else None

        return {
            "type": "parallel-agents" if tool == "parallel-agents" else "tool",
            "tool": tool,
            "status": status,
            "summary": _truncate(summary),
            "timestamp": event.timestamp,
            "duration_ms": dur,
            "cost": 0.0,
            "has_error": status == "error",
            "raw": event.raw,
        }

    return None


def _segment_by_todowrite(
    events: list[LogEvent],
) -> list[dict[str, Any]]:
    """
    Segment events into phases based on todowrite boundaries.

    Parameters
    ----------
    events : list[LogEvent]
        All events from a log file.

    Returns
    -------
    list[dict[str, Any]]
        List of phase dicts with id, label, status, event_range.
    """
    # Find todowrite indices and extract labels
    todo_indices: list[int] = []
    todo_labels: list[str] = []
    todo_statuses: list[str | None] = []

    prev_todos: list[dict[str, Any]] = []
    for i, event in enumerate(events):
        if event.event_type != "tool_use":
            continue
        if get_tool_name(event) != "todowrite":
            continue
        if get_tool_status(event) != "completed":
            continue

        state: dict[str, Any] = event.part.get("state", {})
        todos: list[dict[str, Any]] = state.get("input", {}).get("todos", [])

        # Find which todo transitioned to in_progress
        label: str = "Working"
        status: str | None = None
        for j, t in enumerate(todos):
            old_status: str = prev_todos[j]["status"] if j < len(prev_todos) else "new"
            if t.get("status") == "in_progress" and old_status != "in_progress":
                label = t.get("content", "Working")
                status = "in_progress"
                break

        # If nothing went to in_progress, find what completed
        if status is None:
            for j, t in enumerate(todos):
                old_status = prev_todos[j]["status"] if j < len(prev_todos) else "new"
                if t.get("status") == "completed" and old_status != "completed":
                    label = t.get("content", "Working")
                    status = "completed"

        todo_indices.append(i)
        todo_labels.append(label)
        todo_statuses.append(status)
        prev_todos = todos

    # Determine final status for each todo from the last todowrite snapshot.
    # A todo's status should reflect its FINAL state, not when it first appeared.
    final_status_by_label: dict[str, str] = {}
    if prev_todos:
        for t in prev_todos:
            content: str = t.get("content", "")
            final_status_by_label[content] = t.get("status", "pending")

    # Build phase segments
    phases: list[dict[str, Any]] = []
    boundaries: list[int] = [0] + todo_indices + [len(events)]

    for seg_idx in range(len(boundaries) - 1):
        start: int = boundaries[seg_idx]
        end: int = boundaries[seg_idx + 1]

        if seg_idx == 0:
            # Events before first todowrite — preamble, not a real todo
            phases.append({
                "id": f"phase-{seg_idx}",
                "label": "",
                "status": None,
                "is_preamble": True,
                "event_start": start,
                "event_end": end,
            })
            continue

        label = todo_labels[seg_idx - 1]
        status = final_status_by_label.get(label, todo_statuses[seg_idx - 1])

        # Merge duplicate labels (e.g. same todo appearing twice as
        # in_progress then completed in consecutive todowrite calls)
        if phases and not phases[-1].get("is_preamble") and phases[-1]["label"] == label:
            phases[-1]["event_end"] = end
            phases[-1]["status"] = status
        else:
            phases.append({
                "id": f"phase-{seg_idx}",
                "label": label,
                "status": status,
                "is_preamble": False,
                "event_start": start,
                "event_end": end,
            })

    # If no todowrite at all, single preamble phase
    if not phases:
        phases.append({
            "id": "phase-0",
            "label": "",
            "status": None,
            "is_preamble": True,
            "event_start": 0,
            "event_end": len(events),
        })

    return phases


def _clean_todo_label(label: str) -> str:
    """
    Strip 'Step N:' or 'Phase N:' prefixes from todo labels.

    Parameters
    ----------
    label : str
        Raw todo label.

    Returns
    -------
    str
        Cleaned label.
    """
    import re
    # Remove "Step N:" or "Step N.N:" or "Phase N:" prefix
    cleaned: str = re.sub(r"^(?:Step|Phase)\s+[\d.]+:\s*", "", label)
    return cleaned.strip() or label


def _summarize_steps(steps: list[dict[str, Any]]) -> str:
    """Build a consistent summary string for a list of steps."""
    n_tools: int = sum(1 for s in steps if s["type"] == "tool")
    n_text: int = sum(1 for s in steps if s["type"] == "text")
    n_errors: int = sum(1 for s in steps if s["type"] == "error")
    parts: list[str] = []
    if n_tools:
        parts.append(f"{n_tools} tool call{'s' if n_tools != 1 else ''}")
    if n_text:
        parts.append(f"{n_text} message{'s' if n_text != 1 else ''}")
    if n_errors:
        parts.append(f"{n_errors} error{'s' if n_errors != 1 else ''}")
    return ", ".join(parts) if parts else "working"


def _build_agent_tree(
    node: SessionNode,
    agent_prefix: str = "",
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Build a process tree: session → todos → turns.

    Each todo contains "turns" — segments of work separated by
    parallel-agents calls. Steps (individual events) are stored
    inside turns for the detail panel, not as tree nodes.

    Parameters
    ----------
    node : SessionNode
        Session node with events and children.
    agent_prefix : str
        Prefix for IDs.
    work_dir : Path | None
        Work directory for artifact discovery.

    Returns
    -------
    dict[str, Any]
        Agent tree with todos and turns.
    """
    phases_meta: list[dict[str, Any]] = _segment_by_todowrite(node.events)

    # Map children by parent_event_index
    children_by_idx: dict[int | None, list[SessionNode]] = {}
    for child in node.children:
        idx: int | None = child.parent_event_index
        if idx not in children_by_idx:
            children_by_idx[idx] = []
        children_by_idx[idx].append(child)

    todos: list[dict[str, Any]] = []
    preamble_turns: list[dict[str, Any]] = []
    total_cost: float = 0.0

    for phase_meta in phases_meta:
        phase_events: list[LogEvent] = node.events[phase_meta["event_start"]:phase_meta["event_end"]]

        # Split phase events into turns at parallel-agents/task spawn points
        turns: list[dict[str, Any]] = []
        current_steps: list[dict[str, Any]] = []
        has_error: bool = False

        for evt_offset, event in enumerate(phase_events):
            evt_idx: int = phase_meta["event_start"] + evt_offset

            # Accumulate cost from step_finish events
            if event.event_type == "step_finish":
                cost: float | None = get_step_cost(event)
                if cost:
                    total_cost += cost

            step: dict[str, Any] | None = _event_to_step(event)
            if step is None:
                continue

            # Only count actual error events (session-level), not tool retries
            if step["type"] == "error":
                has_error = True

            # Check if this event spawns parallel children
            is_spawn: bool = (
                evt_idx in children_by_idx
                and event.event_type == "tool_use"
                and get_tool_name(event) in ("parallel-agents", "task")
            )

            if is_spawn:
                # Flush current steps as a "thinking" turn
                if current_steps:
                    turns.append({
                        "type": "thinking",
                        "summary": _summarize_steps(current_steps),
                        "steps": current_steps,
                        "has_error": any(s["type"] == "error" for s in current_steps),
                    })
                    current_steps = []

                # Build child session trees
                child_sessions: list[dict[str, Any]] = []
                consolidator_session: dict[str, Any] | None = None
                agent_name: str = ""

                for child in children_by_idx[evt_idx]:
                    child_tree: dict[str, Any] = _build_agent_tree(
                        child,
                        agent_prefix=f"{child.agent_name}-{child.name}-",
                        work_dir=work_dir,
                    )
                    if child.is_consolidator:
                        consolidator_session = child_tree
                    else:
                        child_sessions.append(child_tree)
                    agent_name = child.agent_name

                turns.append({
                    "type": "parallel",
                    "summary": f"{agent_name} x{len(child_sessions)}",
                    "agent": agent_name,
                    "children": child_sessions,
                    "consolidator": consolidator_session,
                    "steps": [step],  # the spawn step itself
                    "has_error": step.get("has_error", False),
                })
            else:
                current_steps.append(step)

        # Flush remaining steps
        if current_steps:
            turns.append({
                "type": "thinking",
                "summary": _summarize_steps(current_steps),
                "steps": current_steps,
                "has_error": any(s["type"] == "error" for s in current_steps),
            })

        # Preamble turns (before first todowrite) go directly on session,
        # not wrapped in a fake todo
        if phase_meta.get("is_preamble"):
            preamble_turns.extend(turns)
        else:
            label_raw: str = phase_meta["label"]
            label: str = _clean_todo_label(label_raw)

            todos.append({
                "id": f"{agent_prefix}{phase_meta['id']}",
                "label": label,
                "status": phase_meta["status"],
                "turns": turns,
                "has_error": has_error,
            })

    # Handle unlinked children (parent_event_index=None) — parallel work
    # that wasn't triggered by a visible tool call in main.log.
    # Add as a parallel turn to the last existing todo (or create a
    # minimal wrapper if no todos exist).
    unlinked: list[SessionNode] = children_by_idx.get(None, [])
    if unlinked:
        child_sessions: list[dict[str, Any]] = []
        agent_name: str = ""
        for child in unlinked:
            child_tree: dict[str, Any] = _build_agent_tree(
                child,
                agent_prefix=f"{child.agent_name}-{child.name}-",
            )
            if not child.is_consolidator:
                child_sessions.append(child_tree)
            agent_name = child.agent_name

        if child_sessions:
            parallel_turn: dict[str, Any] = {
                "type": "parallel",
                "summary": f"{agent_name} x{len(child_sessions)}",
                "agent": agent_name,
                "children": child_sessions,
                "consolidator": None,
                "steps": [],
                "has_error": False,
            }
            if todos:
                # Append to the last todo's turns
                todos[-1]["turns"].append(parallel_turn)
            else:
                # No todos at all — create a minimal one
                todos.append({
                    "id": f"{agent_prefix}phase-0",
                    "label": "Free-form working",
                    "status": None,
                    "turns": [parallel_turn],
                    "has_error": False,
                })

    agent_label: str = node.name
    if node.agent_name and node.agent_name != node.name:
        agent_label = f"{node.agent_name}/{node.name}"

    # Discover artifacts for this agent's work directory
    agent_artifacts: list[dict[str, Any]] = []
    if work_dir is not None:
        is_main: bool = node.name == "main" or node.agent_name == "main"
        agent_dir: Path | None = None
        if not is_main:
            agent_dir = _find_parallel_artifact_dir(
                work_dir, node.agent_name, node.name,
            )
        from dlab.tui.widgets.artifacts_pane import _sort_artifacts
        raw: list[Path] = discover_artifacts(work_dir, agent_dir, is_main=is_main)
        # discover_artifacts returns paths relative to search_dir (agent_dir or work_dir).
        # We need paths relative to work_dir for the /api/file/ endpoint.
        base_dir: Path = agent_dir if agent_dir else work_dir
        for path in _sort_artifacts(raw):
            if path.name.startswith("."):
                continue
            abs_path: Path = path if path.is_absolute() else (base_dir / path)
            try:
                rel: str = str(abs_path.relative_to(work_dir))
            except ValueError:
                # If it can't be made relative, try resolving
                try:
                    rel = str(abs_path.resolve().relative_to(work_dir.resolve()))
                except ValueError:
                    rel = str(path)
            ext: str = path.suffix.lower()
            ftype: str = "image" if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"} else ext.lstrip(".")
            try:
                sz: int = abs_path.stat().st_size
            except OSError:
                sz = 0
            agent_artifacts.append({"path": rel, "name": path.name, "type": ftype, "size_bytes": sz})

    return {
        "agent": agent_label,
        "model": node.model,
        "prompt": _get_prompt(node.events),
        "is_complete": is_log_complete(node.events),
        "is_consolidator": node.is_consolidator,
        "total_cost": round(total_cost, 6),
        "artifacts": agent_artifacts,
        "todos": todos,
        "preamble_turns": preamble_turns,
    }


def extract_process_tree(work_dir: Path) -> dict[str, Any]:
    """
    Extract a process tree: session → todos → turns.

    Parameters
    ----------
    work_dir : Path
        Path to the session work directory.

    Returns
    -------
    dict[str, Any]
        {"tree": agent tree, "meta": session metadata}
    """
    root: SessionNode | None = _build_enhanced_graph(work_dir)
    if root is None:
        return {"tree": {"agent": "main", "todos": [], "model": None}, "meta": {}}

    tree: dict[str, Any] = _build_agent_tree(root, work_dir=work_dir)

    # Metadata
    state_meta: dict[str, Any] = _load_state_meta(work_dir)
    all_ts: list[int] = [e.timestamp for e in root.events if e.timestamp]
    for child in root.children:
        all_ts += [e.timestamp for e in child.events if e.timestamp]
    global_start: int | None = min(all_ts) if all_ts else None
    global_end: int | None = max(all_ts) if all_ts else None

    def _recursive_cost(t: dict[str, Any]) -> float:
        c: float = t.get("total_cost", 0)
        for todo in t.get("todos", []):
            for turn in todo.get("turns", []):
                if turn.get("type") == "parallel":
                    for child in turn.get("children", []):
                        c += _recursive_cost(child)
                    cons: dict[str, Any] | None = turn.get("consolidator")
                    if cons:
                        c += _recursive_cost(cons)
        for turn in t.get("preamble_turns", []):
            if turn.get("type") == "parallel":
                for child in turn.get("children", []):
                    c += _recursive_cost(child)
        return c

    meta: dict[str, Any] = {
        "work_dir": str(work_dir),
        "dpack_name": state_meta.get("dpack_name", work_dir.name),
        "status": state_meta.get("status", "unknown"),
        "global_start_ms": global_start,
        "global_end_ms": global_end,
        "total_duration_ms": (global_end - global_start) if global_start and global_end else None,
        "total_cost": round(_recursive_cost(tree), 2),
    }

    # Discover artifacts for the main session (sorted by relevance)
    from dlab.tui.widgets.artifacts_pane import _sort_artifacts
    raw_artifacts: list[Path] = discover_artifacts(work_dir, None, is_main=True)
    sorted_artifacts: list[Path] = _sort_artifacts(raw_artifacts)
    artifacts: list[dict[str, Any]] = []
    for path in sorted_artifacts:
        if path.name.startswith("."):
            continue
        try:
            rel_path: str = str(path.relative_to(work_dir))
        except ValueError:
            rel_path = str(path)
        ext: str = path.suffix.lower()
        file_type: str = "image" if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"} else ext.lstrip(".")
        try:
            size: int = path.stat().st_size
        except OSError:
            size = 0
        artifacts.append({"path": rel_path, "name": path.name, "type": file_type, "size_bytes": size})

    return {"tree": tree, "meta": meta, "artifacts": artifacts}
