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
    get_step_tokens,
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
    ARTIFACT_EXTENSIONS,
    EXCLUDE_DIRS,
    discover_artifacts,
    get_agent_directory,
    is_parallel_run_dir,
)


def _aggregate_events(events: list[LogEvent]) -> dict[str, Any]:
    """
    Compute aggregate stats from a list of log events.

    Parameters
    ----------
    events : list[LogEvent]
        Parsed log events.

    Returns
    -------
    dict[str, Any]
        Dict with cost, tool_counts, step_count, has_error, etc.
    """
    total_cost: float = 0.0
    tool_counts: dict[str, int] = {}
    step_count: int = 0
    has_error: bool = False
    error_message: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    timestamps: list[int] = []

    for event in events:
        if event.timestamp is not None:
            timestamps.append(event.timestamp)

        if event.event_type == "step_start":
            step_count += 1

        elif event.event_type == "step_finish":
            cost: float | None = get_step_cost(event)
            if cost:
                total_cost += cost
            tokens: dict[str, Any] | None = get_step_tokens(event)
            if tokens:
                total_input_tokens += tokens.get("input", 0)
                total_output_tokens += tokens.get("output", 0)

        elif event.event_type == "tool_use":
            status: str | None = get_tool_status(event)
            if status == "completed" or status == "error":
                name: str | None = get_tool_name(event)
                if name:
                    tool_counts[name] = tool_counts.get(name, 0) + 1

        elif event.event_type == "error":
            has_error = True
            if error_message is None:
                err_data: dict[str, Any] = event.part.get("error", event.raw.get("error", {}))
                if isinstance(err_data, dict):
                    error_message = err_data.get("data", {}).get("message", str(err_data.get("name", "")))
                else:
                    error_message = str(err_data)

    start_ms: int | None = min(timestamps) if timestamps else None
    end_ms: int | None = max(timestamps) if timestamps else None
    duration_ms: int | None = (end_ms - start_ms) if start_ms is not None and end_ms is not None else None

    return {
        "total_cost": round(total_cost, 6),
        "tool_counts": tool_counts,
        "total_tool_count": sum(tool_counts.values()),
        "step_count": step_count,
        "has_error": has_error,
        "error_message": error_message,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": duration_ms,
    }


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

        # Try to match to a spawn point
        parent_idx: int | None = None
        for sp in spawn_points:
            # Match by agent name substring (popo-poet matches poet)
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


def _split_main_node(
    root: SessionNode,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Split main node into segments around parallel spawn points.

    If no children, returns a single "solo" node. Otherwise splits
    into pre-parallel, post-parallel segments with edges to children.

    Parameters
    ----------
    root : SessionNode
        Root session node.

    Returns
    -------
    tuple[list[dict], list[dict]]
        (nodes, edges) for the main node and its children.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    if not root.children:
        # Solo session — single node
        stats: dict[str, Any] = _aggregate_events(root.events)
        nodes.append({
            "id": "main",
            "name": "main",
            "agent_name": root.agent_name or "main",
            "phase": "solo",
            "model": root.model,
            "is_complete": is_log_complete(root.events),
            "is_consolidator": False,
            **stats,
        })
        return nodes, edges

    # Classify spawn points: only parallel-agents calls are blocking
    # (main waits). Task calls are fire-and-forget.
    spawn_points: list[dict[str, Any]] = _find_parallel_spawn_points(root.events)
    blocking_spawns: list[dict[str, Any]] = [sp for sp in spawn_points if sp["blocking"]]

    # Group children by parent_event_index
    spawn_groups: dict[int | None, list[SessionNode]] = {}
    for child in root.children:
        idx: int | None = child.parent_event_index
        if idx not in spawn_groups:
            spawn_groups[idx] = []
        spawn_groups[idx].append(child)

    # Helper to add child nodes and edges
    def _add_children(
        children: list[SessionNode],
        source_id: str,
        add_resume_to: str | None = None,
    ) -> None:
        instances: list[SessionNode] = [c for c in children if not c.is_consolidator]
        consols: list[SessionNode] = [c for c in children if c.is_consolidator]

        for child in instances:
            cid: str = f"{child.agent_name}/{child.name}"
            cstats: dict[str, Any] = _aggregate_events(child.events)
            nodes.append({
                "id": cid,
                "name": child.name,
                "agent_name": child.agent_name,
                "phase": "parallel",
                "model": child.model,
                "is_complete": is_log_complete(child.events),
                "is_consolidator": False,
                **cstats,
            })
            edges.append({"source": source_id, "target": cid, "type": "spawn"})

        for child in consols:
            cid = f"{child.agent_name}/consolidator"
            cstats = _aggregate_events(child.events)
            nodes.append({
                "id": cid,
                "name": "consolidator",
                "agent_name": child.agent_name,
                "phase": "consolidator",
                "model": child.model,
                "is_complete": is_log_complete(child.events),
                "is_consolidator": True,
                **cstats,
            })
            for inst in instances:
                iid: str = f"{inst.agent_name}/{inst.name}"
                edges.append({"source": iid, "target": cid, "type": "consolidate"})

        # Resume edges (only for blocking spawns)
        if add_resume_to is not None:
            last_nodes: list[SessionNode] = consols if consols else instances
            for child in last_nodes:
                cid = f"{child.agent_name}/consolidator" if child.is_consolidator else f"{child.agent_name}/{child.name}"
                edges.append({"source": cid, "target": add_resume_to, "type": "resume"})

    # No blocking spawns: main stays as single node, children get one-way spawn edges
    if not blocking_spawns:
        stats = _aggregate_events(root.events)
        main_phase: str = "solo" if not root.children else "pre-parallel"
        nodes.append({
            "id": "main",
            "name": "main",
            "agent_name": root.agent_name or "main",
            "phase": main_phase,
            "model": root.model,
            "is_complete": is_log_complete(root.events),
            "is_consolidator": False,
            **stats,
        })
        for idx_key, children in spawn_groups.items():
            _add_children(children, "main")
        return nodes, edges

    # Has blocking spawns: split main at each parallel-agents call
    blocking_indices: list[int] = [sp["event_index"] for sp in blocking_spawns]

    for seg_idx, spawn_idx in enumerate(blocking_indices):
        sp: dict[str, Any] = blocking_spawns[seg_idx]
        time_end: int | None = sp["time_end"]

        # Pre-parallel segment
        if seg_idx == 0:
            pre_events: list[LogEvent] = root.events[:spawn_idx]
            pre_stats: dict[str, Any] = _aggregate_events(pre_events)
            pre_id: str = f"main-pre-{seg_idx}" if len(blocking_indices) > 1 else "main-pre"
            nodes.append({
                "id": pre_id,
                "name": "main",
                "agent_name": root.agent_name or "main",
                "phase": "pre-parallel",
                "model": root.model,
                "is_complete": True,
                "is_consolidator": False,
                **pre_stats,
            })

        # Add children for this spawn group
        children: list[SessionNode] = spawn_groups.get(spawn_idx, [])

        # Post-parallel segment — start_ms is the tool's time.end
        # (when parallel-agents returned and main resumed)
        next_spawn: int = blocking_indices[seg_idx + 1] if seg_idx + 1 < len(blocking_indices) else len(root.events)
        post_events: list[LogEvent] = root.events[spawn_idx + 1:next_spawn]
        post_stats: dict[str, Any] = _aggregate_events(post_events)
        post_id: str = f"main-post-{seg_idx}" if len(blocking_indices) > 1 else "main-post"

        # Use tool's time.end as authoritative start for post segment
        if time_end is not None:
            post_stats["start_ms"] = time_end
            post_end: int | None = post_stats["end_ms"]
            if post_end is not None:
                if post_end < time_end:
                    post_end = time_end
                post_stats["end_ms"] = post_end
                post_stats["duration_ms"] = post_end - time_end
            else:
                post_stats["duration_ms"] = 0

        post_node: dict[str, Any] = {
            "id": post_id,
            "name": "main",
            "agent_name": root.agent_name or "main",
            "phase": "post-parallel",
            "model": root.model,
            "is_complete": seg_idx == len(blocking_indices) - 1 and is_log_complete(root.events),
            "is_consolidator": False,
            **post_stats,
        }
        nodes.append(post_node)

        _add_children(children, pre_id, add_resume_to=post_id)

        # If there's a next blocking spawn, post becomes the next pre
        if seg_idx + 1 < len(blocking_indices):
            new_id: str = f"main-pre-{seg_idx + 1}" if len(blocking_indices) > 1 else "main-pre"
            # Update edge targets that reference the old post_id
            for edge in edges:
                if edge["target"] == post_id:
                    edge["target"] = new_id
                if edge["source"] == post_id:
                    edge["source"] = new_id
            post_node["id"] = new_id
            post_node["phase"] = "pre-parallel"
            pre_id = new_id

    # Add children from non-blocking spawns (task calls) with
    # one-way edges from nearest main segment
    for idx_key, children in spawn_groups.items():
        if idx_key in blocking_indices:
            continue
        # Find nearest main segment that precedes this spawn
        source_id: str = nodes[0]["id"]  # fallback to first main node
        for n in nodes:
            if n["agent_name"] == (root.agent_name or "main") and n.get("start_ms") is not None:
                if idx_key is None or (n["start_ms"] <= root.events[idx_key].timestamp if root.events[idx_key].timestamp else True):
                    source_id = n["id"]
        _add_children(children, source_id)

    return nodes, edges


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


def _discover_node_artifacts(
    work_dir: Path,
    node_id: str,
    agent_name: str,
    phase: str,
) -> list[dict[str, Any]]:
    """
    Discover artifacts for a node.

    Parameters
    ----------
    work_dir : Path
        Session work directory.
    node_id : str
        Node ID (e.g. "main", "poet/instance-1").
    agent_name : str
        Agent name for directory mapping.
    phase : str
        Node phase (solo, pre-parallel, parallel, etc.).

    Returns
    -------
    list[dict[str, Any]]
        List of artifact dicts with path, type, size_bytes.
    """
    is_main: bool = phase in ("solo", "pre-parallel", "post-parallel")

    agent_dir: Path | None = None
    if not is_main:
        # Extract instance name from node_id: "poet/instance-1" → "instance-1"
        parts: list[str] = node_id.split("/", 1)
        instance_name: str = parts[1] if len(parts) > 1 else parts[0]
        agent_dir = _find_parallel_artifact_dir(work_dir, agent_name, instance_name)

    artifacts: list[Path] = discover_artifacts(work_dir, agent_dir, is_main=is_main)

    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for path in artifacts:
        try:
            rel_path: str = str(path.relative_to(work_dir))
        except ValueError:
            rel_path = str(path)

        # Deduplicate
        if rel_path in seen:
            continue
        seen.add(rel_path)

        # Skip hidden files like .prompt.txt
        if path.name.startswith("."):
            continue

        ext: str = path.suffix.lower()
        file_type: str = "image" if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"} else ext.lstrip(".")
        try:
            size: int = path.stat().st_size
        except OSError:
            size = 0
        result.append({
            "path": rel_path,
            "name": path.name,
            "type": file_type,
            "size_bytes": size,
        })
    return result


def extract_session_data(work_dir: Path) -> dict[str, Any]:
    """
    Extract complete session data for the viewer.

    Parameters
    ----------
    work_dir : Path
        Path to the session work directory.

    Returns
    -------
    dict[str, Any]
        {
            "nodes": list of node dicts,
            "edges": list of edge dicts,
            "meta": session metadata dict,
            "artifacts": {node_id: [artifact dicts]},
        }
    """
    root: SessionNode | None = _build_enhanced_graph(work_dir)
    if root is None:
        return {"nodes": [], "edges": [], "meta": {}, "artifacts": {}}

    nodes, edges = _split_main_node(root)

    # Session metadata
    state_meta: dict[str, Any] = _load_state_meta(work_dir)
    all_timestamps: list[int] = [n["start_ms"] for n in nodes if n["start_ms"] is not None]
    all_timestamps += [n["end_ms"] for n in nodes if n["end_ms"] is not None]
    global_start: int | None = min(all_timestamps) if all_timestamps else None
    global_end: int | None = max(all_timestamps) if all_timestamps else None
    total_cost: float = sum(n["total_cost"] for n in nodes)

    meta: dict[str, Any] = {
        "work_dir": str(work_dir),
        "dpack_name": state_meta.get("dpack_name", work_dir.name),
        "status": state_meta.get("status", "unknown"),
        "global_start_ms": global_start,
        "global_end_ms": global_end,
        "total_duration_ms": (global_end - global_start) if global_start and global_end else None,
        "total_cost": round(total_cost, 6),
        "node_count": len(nodes),
    }

    # Discover artifacts per node
    artifacts: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        node_artifacts: list[dict[str, Any]] = _discover_node_artifacts(
            work_dir, node["id"], node["agent_name"], node["phase"],
        )
        if node_artifacts:
            artifacts[node["id"]] = node_artifacts

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": meta,
        "artifacts": artifacts,
    }


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
        first_line: str = text.strip().split("\n")[0][:120]
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
            "summary": msg[:120],
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
            "summary": summary[:120],
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

    # Build phase segments
    phases: list[dict[str, Any]] = []
    boundaries: list[int] = [0] + todo_indices + [len(events)]

    for seg_idx in range(len(boundaries) - 1):
        start: int = boundaries[seg_idx]
        end: int = boundaries[seg_idx + 1]

        if seg_idx == 0:
            label = "Free-form working"
            status = None
        else:
            label = todo_labels[seg_idx - 1]
            status = todo_statuses[seg_idx - 1]

        # Clean up label: remove "Step N: " prefix if redundant
        # Keep it as-is for clarity

        phases.append({
            "id": f"phase-{seg_idx}",
            "label": label,
            "status": status,
            "event_start": start,
            "event_end": end,
        })

    # If no todowrite at all, single free-form phase
    if not phases:
        phases.append({
            "id": "phase-0",
            "label": "Free-form working",
            "status": None,
            "event_start": 0,
            "event_end": len(events),
        })

    return phases


def _build_agent_tree(
    node: SessionNode,
    agent_prefix: str = "",
) -> dict[str, Any]:
    """
    Build a process tree for a single agent (main or parallel instance).

    Parameters
    ----------
    node : SessionNode
        Session node with events and children.
    agent_prefix : str
        Prefix for phase IDs (e.g. "inst1-").

    Returns
    -------
    dict[str, Any]
        Agent tree with phases and steps.
    """
    phases_meta: list[dict[str, Any]] = _segment_by_todowrite(node.events)

    # Map children by parent_event_index
    children_by_idx: dict[int | None, list[SessionNode]] = {}
    for child in node.children:
        idx: int | None = child.parent_event_index
        if idx not in children_by_idx:
            children_by_idx[idx] = []
        children_by_idx[idx].append(child)

    phases: list[dict[str, Any]] = []
    total_cost: float = 0.0

    for phase_meta in phases_meta:
        phase_events: list[LogEvent] = node.events[phase_meta["event_start"]:phase_meta["event_end"]]
        steps: list[dict[str, Any]] = []
        phase_cost: float = 0.0

        for evt_offset, event in enumerate(phase_events):
            evt_idx: int = phase_meta["event_start"] + evt_offset

            # Accumulate cost from step_finish
            if event.event_type == "step_finish":
                cost: float | None = get_step_cost(event)
                if cost:
                    phase_cost += cost
                continue

            step: dict[str, Any] | None = _event_to_step(event)
            if step is None:
                continue

            # Attach children for parallel-agents or task tool calls
            if evt_idx in children_by_idx and step["type"] in ("parallel-agents", "tool"):
                # Promote task tool to parallel-agents type for rendering
                if step["tool"] == "task":
                    step["type"] = "parallel-agents"
                child_trees: list[dict[str, Any]] = []
                consolidator_tree: dict[str, Any] | None = None

                for child in children_by_idx[evt_idx]:
                    child_tree: dict[str, Any] = _build_agent_tree(
                        child,
                        agent_prefix=f"{child.agent_name}-{child.name}-",
                    )
                    if child.is_consolidator:
                        consolidator_tree = child_tree
                    else:
                        child_trees.append(child_tree)

                step["children"] = child_trees
                step["consolidator"] = consolidator_tree

            steps.append(step)

        total_cost += phase_cost

        phases.append({
            "id": f"{agent_prefix}{phase_meta['id']}",
            "label": phase_meta["label"],
            "status": phase_meta["status"],
            "steps": steps,
            "cost": round(phase_cost, 6),
        })

    return {
        "agent": f"{node.agent_name}/{node.name}" if node.agent_name != node.name else node.name,
        "model": node.model,
        "is_complete": is_log_complete(node.events),
        "is_consolidator": node.is_consolidator,
        "total_cost": round(total_cost, 6),
        "phases": phases,
    }


def extract_process_tree(work_dir: Path) -> dict[str, Any]:
    """
    Extract a process tree for the viewer (v2 — todo-segmented).

    The tree is organized by todowrite phases, with steps within each
    phase and recursive children for parallel agent instances.

    Parameters
    ----------
    work_dir : Path
        Path to the session work directory.

    Returns
    -------
    dict[str, Any]
        {
            "tree": agent tree dict,
            "meta": session metadata dict,
            "artifacts": {agent_id: [artifact dicts]},
        }
    """
    root: SessionNode | None = _build_enhanced_graph(work_dir)
    if root is None:
        return {"tree": {"agent": "main", "phases": [], "total_cost": 0}, "meta": {}, "artifacts": {}}

    tree: dict[str, Any] = _build_agent_tree(root)

    # Metadata
    state_meta: dict[str, Any] = _load_state_meta(work_dir)
    all_ts: list[int] = [e.timestamp for e in root.events if e.timestamp]
    for child in root.children:
        all_ts += [e.timestamp for e in child.events if e.timestamp]
    global_start: int | None = min(all_ts) if all_ts else None
    global_end: int | None = max(all_ts) if all_ts else None

    meta: dict[str, Any] = {
        "work_dir": str(work_dir),
        "dpack_name": state_meta.get("dpack_name", work_dir.name),
        "status": state_meta.get("status", "unknown"),
        "global_start_ms": global_start,
        "global_end_ms": global_end,
        "total_duration_ms": (global_end - global_start) if global_start and global_end else None,
        "total_cost": tree["total_cost"],
    }

    return {
        "tree": tree,
        "meta": meta,
        "artifacts": {},  # TODO: wire up per-agent artifact discovery
    }
