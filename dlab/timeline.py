"""
Timeline parsing and visualization for dlab sessions.

This module parses OpenCode log files and constructs execution timelines
with Gantt chart visualization showing parallel agent execution.

Supports both completed and running jobs - running jobs show agents
with "RUNNING" status and extend to current time in the Gantt chart.
"""

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dlab.opencode_logparser import (
    LogEvent as ParsedEvent,
    is_log_file_complete as is_log_complete,
    ms_to_datetime,
    parse_log_file as parse_log_events,
)


def natural_sort_key(name: str) -> tuple:
    """
    Sort key for natural ordering.

    Orders: main first, task subagents, instance-1..N, consolidator last.

    Parameters
    ----------
    name : str
        Log source name to sort.

    Returns
    -------
    tuple
        Sort key tuple.
    """
    if name == "main":
        return (0, 0, "")
    if name == "consolidator":
        return (4, 0, "")

    # Check for task subagent pattern (e.g., "popo-poet (task)")
    if name.endswith(" (task)"):
        return (1, 0, name)

    # Check for instance-N pattern
    match = re.match(r"instance-(\d+)", name)
    if match:
        return (2, int(match.group(1)), "")

    # Check for parallel run directories (e.g., modeler-parallel-run-123456)
    match = re.match(r"(.+)-parallel-run-(\d+)", name)
    if match:
        return (3, int(match.group(2)), match.group(1))

    # Default: alphabetical
    return (3, 0, name)


def discover_agents(opencode_dir: Path) -> set[str]:
    """
    Discover agent names from .opencode/agents/*.md files.

    Parameters
    ----------
    opencode_dir : Path
        Path to .opencode directory.

    Returns
    -------
    set[str]
        Set of agent names (filenames without .md).
    """
    agents_dir = opencode_dir / "agents"
    if not agents_dir.exists():
        return set()

    return {f.stem for f in agents_dir.glob("*.md")}


def format_duration(ms: int) -> str:
    """
    Format milliseconds as human-readable duration.

    Parameters
    ----------
    ms : int
        Duration in milliseconds.

    Returns
    -------
    str
        Human-readable duration string (e.g., "5.2s", "3.1m", "1.5h").
    """
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


def parse_log_file(log_path: Path) -> list[dict[str, Any]]:
    """
    Parse a single log file and extract timeline events.

    Uses opencode_logparser for JSON parsing, then builds timeline-specific
    event dicts with descriptions, idle periods, and task subagent info.

    Parameters
    ----------
    log_path : Path
        Path to the log file.

    Returns
    -------
    list[dict[str, Any]]
        List of parsed events with timestamp, type, and description.
    """
    parsed: list[ParsedEvent] = parse_log_events(log_path)
    events: list[dict[str, Any]] = []

    for pe in parsed:
        # Skip non-timestamped events (raw_text, additional_output)
        if pe.timestamp is None:
            continue

        event: dict[str, Any] = {
            "timestamp": pe.timestamp,
            "datetime": ms_to_datetime(pe.timestamp),
            "type": pe.event_type,
            "source": log_path.stem,
        }

        part: dict[str, Any] = pe.part

        if pe.event_type == "step_start":
            event["description"] = "Step started"

        elif pe.event_type == "step_finish":
            event["description"] = f"Step finished ({part.get('reason', 'unknown')})"
            cost = part.get("cost", 0)
            tokens = part.get("tokens", {})
            if cost:
                event["cost"] = cost
            if tokens:
                event["tokens"] = tokens

        elif pe.event_type == "text":
            text = part.get("text", "")
            if len(text) > 100:
                text = text[:100] + "..."
            event["description"] = f"Text: {text}"

        elif pe.event_type == "tool_use":
            tool = part.get("tool", "unknown")
            state = part.get("state", {})
            status = state.get("status", "unknown")
            input_data = state.get("input", {})

            if tool == "bash":
                cmd = input_data.get("command", "")
                desc = input_data.get("description", "")
                if len(cmd) > 50:
                    cmd = cmd[:50] + "..."
                event["description"] = f"Tool: {tool} ({status}) - {desc or cmd}"
            elif tool == "read":
                filepath = input_data.get("filePath", "")
                event["description"] = f"Tool: {tool} ({status}) - {Path(filepath).name}"
            elif tool == "write":
                filepath = input_data.get("filePath", "")
                event["description"] = f"Tool: {tool} ({status}) - {Path(filepath).name}"
            elif tool == "task":
                subagent = input_data.get("subagent_type", "")
                desc = input_data.get("description", "")
                event["description"] = f"Tool: {tool} ({status}) - {subagent}: {desc}"
                if subagent and status == "completed":
                    event["task_subagent"] = subagent
                    event["task_output"] = state.get("output", "")
                    task_time = state.get("time", {})
                    if task_time:
                        event["task_start_ts"] = task_time.get("start")
                        event["task_end_ts"] = task_time.get("end")
                        event["idle_period"] = (task_time.get("start"), task_time.get("end"))
            elif tool == "parallel-agents":
                agent = input_data.get("agent", "")
                prompts = input_data.get("prompts", [])
                event["description"] = f"Tool: {tool} ({status}) - {agent} x{len(prompts)}"
                tool_time = state.get("time", {})
                if tool_time and status == "completed":
                    event["idle_period"] = (tool_time.get("start"), tool_time.get("end"))
            else:
                event["description"] = f"Tool: {tool} ({status})"

            time_data = state.get("time", {})
            if time_data:
                start = time_data.get("start")
                end = time_data.get("end")
                if start and end:
                    event["duration_ms"] = end - start

        else:
            event["description"] = f"{pe.event_type}"

        events.append(event)

    return events


def build_timeline(
    logs_dir: Path,
    known_agents: set[str] | None = None,
    is_running: bool = False,
) -> dict[str, Any]:
    """
    Build a complete timeline from all log files in a directory.

    Parameters
    ----------
    logs_dir : Path
        Directory containing log files (searched recursively).
    known_agents : set[str] | None
        Optional set of known agent names for task subagent detection.
    is_running : bool
        If True, the job is still running and some agents may not have finished.

    Returns
    -------
    dict[str, Any]
        Timeline data with events, file_summaries, total_events, and is_running.
    """
    all_events: list[dict[str, Any]] = []
    file_summaries: dict[str, dict[str, Any]] = {}
    task_subagents: list[dict[str, Any]] = []  # Collect task subagent info
    running_sources: set[str] = set()  # Track which sources are still running
    idle_periods_by_source: dict[str, list[tuple[int, int]]] = {}  # Track idle periods

    # Current time for running agents (in ms)
    now_ms: int = int(datetime.now().timestamp() * 1000)

    # Find all log files recursively
    log_files = sorted(logs_dir.rglob("*.log"))

    if not log_files:
        print(f"No .log files found in {logs_dir}", file=sys.stderr)
        return {}

    # Parse each log file
    for log_file in log_files:
        events = parse_log_file(log_file)

        # Use relative path from logs_dir as source name
        rel_path = log_file.relative_to(logs_dir)
        # For nested files like "modeler-parallel-run-123/instance-1.log", use full path
        # For top-level files like "main.log", use "main"
        if len(rel_path.parts) > 1:
            # Nested: prepend parent dir name for context
            source_name = f"{rel_path.parent.name}/{rel_path.stem}"
        else:
            source_name = rel_path.stem

        # Check if this log file is complete (only relevant if job is running)
        log_complete: bool = True
        if is_running:
            log_complete = is_log_complete(log_file)
            if not log_complete:
                running_sources.add(source_name)

        # Update source in all events and collect idle periods
        for e in events:
            e["source"] = source_name
            # Collect idle periods (when waiting on task/parallel-agents)
            if "idle_period" in e:
                if source_name not in idle_periods_by_source:
                    idle_periods_by_source[source_name] = []
                idle_periods_by_source[source_name].append(e["idle_period"])

        all_events.extend(events)

        if events:
            start_time = min(e["timestamp"] for e in events)
            end_time = max(e["timestamp"] for e in events)

            # For running logs, use current time as end
            if not log_complete:
                end_time = now_ms

            duration = end_time - start_time

            # Count events by type
            type_counts: dict[str, int] = {}
            for e in events:
                t = e["type"]
                type_counts[t] = type_counts.get(t, 0) + 1

            # Sum costs
            total_cost = sum(e.get("cost", 0) for e in events)

            file_summaries[source_name] = {
                "start": ms_to_datetime(start_time),
                "end": ms_to_datetime(end_time),
                "start_ms": start_time,
                "end_ms": end_time,
                "duration_ms": duration,
                "event_count": len(events),
                "type_counts": type_counts,
                "total_cost": total_cost,
                "is_running": not log_complete,
                "idle_periods": idle_periods_by_source.get(source_name, []),
            }

    # Sort all events by timestamp
    all_events.sort(key=lambda e: e["timestamp"])

    # Collect task subagent info from events
    if known_agents:
        for e in all_events:
            if "task_subagent" in e:
                subagent_name = e["task_subagent"]
                if subagent_name in known_agents:
                    task_subagents.append({
                        "name": subagent_name,
                        "caller": e["source"],
                        "start_ts": e.get("task_start_ts"),
                        "end_ts": e.get("task_end_ts"),
                        "output": e.get("task_output", ""),
                    })

    # Create virtual agent entries for task subagents
    for task in task_subagents:
        if not task["start_ts"] or not task["end_ts"]:
            continue

        source_name = f"{task['name']} (task)"
        start_ts = task["start_ts"]
        end_ts = task["end_ts"]
        duration = end_ts - start_ts

        # Create synthetic events for this task subagent
        output_preview = task["output"]
        if len(output_preview) > 100:
            output_preview = output_preview[:100] + "..."
        # Clean up newlines for display
        output_preview = output_preview.replace("\n", " ").strip()

        start_event: dict[str, Any] = {
            "timestamp": start_ts,
            "datetime": ms_to_datetime(start_ts),
            "type": "task_start",
            "source": source_name,
            "description": f"Spawned by {task['caller']}",
        }

        end_event: dict[str, Any] = {
            "timestamp": end_ts,
            "datetime": ms_to_datetime(end_ts),
            "type": "task_finish",
            "source": source_name,
            "description": f"Output: {output_preview}" if output_preview else "Completed",
            "duration_ms": duration,
        }

        all_events.extend([start_event, end_event])

        # Add file summary for task subagent
        file_summaries[source_name] = {
            "start": ms_to_datetime(start_ts),
            "end": ms_to_datetime(end_ts),
            "duration_ms": duration,
            "event_count": 2,
            "type_counts": {"task_start": 1, "task_finish": 1},
            "total_cost": 0,  # Cost is tracked in the calling agent
        }

    # Re-sort events after adding task subagent events
    all_events.sort(key=lambda e: e["timestamp"])

    return {
        "events": all_events,
        "file_summaries": file_summaries,
        "total_events": len(all_events),
        "is_running": is_running,
        "running_sources": running_sources,
    }


def print_timeline(timeline: dict[str, Any]) -> None:
    """
    Print a formatted timeline to stdout.

    Parameters
    ----------
    timeline : dict[str, Any]
        Timeline data from build_timeline().
    """
    if not timeline:
        return

    events = timeline["events"]
    file_summaries = timeline["file_summaries"]
    is_running: bool = timeline.get("is_running", False)

    # Print header with status
    print("=" * 80)
    if is_running:
        print("LOG FILE SUMMARIES  [JOB RUNNING]")
    else:
        print("LOG FILE SUMMARIES")
    print("=" * 80)

    # Find global start time for relative timing
    global_start = min(s["start"] for s in file_summaries.values())

    # Sort by natural order (main first, instance-1, instance-2, ..., consolidator last)
    sorted_files = sorted(
        file_summaries.items(),
        key=lambda x: natural_sort_key(x[0].split("/")[-1] if "/" in x[0] else x[0])
    )

    for name, summary in sorted_files:
        rel_start = (summary["start"] - global_start).total_seconds()
        duration = format_duration(summary["duration_ms"])
        cost = summary["total_cost"]
        source_running: bool = summary.get("is_running", False)

        status_suffix = "  [RUNNING]" if source_running else ""
        print(f"\n{name}:{status_suffix}")
        print(f"  Started: +{rel_start:.1f}s from global start")
        print(f"  Duration: {duration}{'*' if source_running else ''}")
        print(f"  Events: {summary['event_count']}")
        print(f"  Cost: ${cost:.4f}")
        print(f"  Types: {summary['type_counts']}")

    # Print timeline
    print("\n" + "=" * 80)
    print("TIMELINE (first and last 20 events per source)")
    print("=" * 80)

    # Group events by source
    by_source: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        source = e["source"]
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(e)

    global_start_ts = min(e["timestamp"] for e in events)

    # Sort sources by natural order
    sorted_sources = sorted(
        by_source.keys(),
        key=lambda x: natural_sort_key(x.split("/")[-1] if "/" in x else x)
    )

    for source in sorted_sources:
        source_events = by_source[source]
        print(f"\n--- {source} ---")

        # Show first 20 and last 20 events
        if len(source_events) <= 40:
            display_events: list[dict[str, Any] | None] = source_events
        else:
            display_events = source_events[:20] + [None] + source_events[-20:]

        for e in display_events:
            if e is None:
                print(f"  ... ({len(source_events) - 40} events omitted) ...")
                continue

            rel_time = (e["timestamp"] - global_start_ts) / 1000
            time_str = f"+{rel_time:7.1f}s"

            duration_str = ""
            if "duration_ms" in e:
                duration_str = f" [{format_duration(e['duration_ms'])}]"

            print(f"  {time_str} | {e['type']:12} | {e.get('description', '')}{duration_str}")

    # Print overall summary
    print("\n" + "=" * 80)
    print("OVERALL SUMMARY")
    print("=" * 80)

    total_duration = max(e["timestamp"] for e in events) - min(e["timestamp"] for e in events)
    total_cost = sum(s["total_cost"] for s in file_summaries.values())

    print(f"Total duration: {format_duration(total_duration)}")
    print(f"Total events: {timeline['total_events']}")
    print(f"Total cost: ${total_cost:.4f}")
    print(f"Log files: {len(file_summaries)}")

    # Show parallel execution timeline
    print("\n" + "=" * 80)
    print("EXECUTION GANTT (visual)")
    print("=" * 80)

    # Normalize times to 0-50 character width
    all_starts = [s["start"] for s in file_summaries.values()]
    all_ends = [s["end"] for s in file_summaries.values()]
    min_time = min(all_starts)
    max_time = max(all_ends)
    total_span = (max_time - min_time).total_seconds()

    if total_span == 0:
        total_span = 1

    width = 50

    # Calculate max name length for alignment
    max_name_len = max(len(name) for name in file_summaries.keys())
    name_width = min(max(max_name_len, 20), 45)  # Between 20 and 45 chars

    # Get global time range in ms for idle period calculations
    min_time_ms = min(s["start_ms"] for s in file_summaries.values() if "start_ms" in s)
    max_time_ms = max(s["end_ms"] for s in file_summaries.values() if "end_ms" in s)
    total_span_ms = max_time_ms - min_time_ms
    if total_span_ms == 0:
        total_span_ms = 1

    for name, summary in sorted_files:
        rel_start = (summary["start"] - min_time).total_seconds()
        rel_end = (summary["end"] - min_time).total_seconds()
        source_running = summary.get("is_running", False)
        idle_periods: list[tuple[int, int]] = summary.get("idle_periods", [])

        start_pos = int((rel_start / total_span) * width)
        end_pos = int((rel_end / total_span) * width)

        # Build segmented bar with idle periods shown as grey
        bar_chars: list[str] = [" "] * width
        for i in range(start_pos, min(end_pos, width)):
            bar_chars[i] = "█"

        # Grey out idle periods
        for idle_start, idle_end in idle_periods:
            if idle_start is None or idle_end is None:
                continue
            # Convert idle period to bar positions
            idle_start_rel = (idle_start - min_time_ms) / total_span_ms
            idle_end_rel = (idle_end - min_time_ms) / total_span_ms
            idle_start_pos = int(idle_start_rel * width)
            idle_end_pos = int(idle_end_rel * width)
            # Mark idle positions with grey
            for i in range(max(idle_start_pos, start_pos), min(idle_end_pos + 1, end_pos, width)):
                bar_chars[i] = "░"

        # If source is still running, use different end character
        if source_running and end_pos > 0 and end_pos <= width:
            bar_chars[end_pos - 1] = "░"

        bar = "".join(bar_chars)
        duration = format_duration(summary["duration_ms"])
        duration_suffix = "..." if source_running else ""

        # Truncate long names
        display_name = name if len(name) <= name_width else "..." + name[-(name_width - 3):]
        print(f"{display_name:{name_width}} |{bar}| {duration}{duration_suffix}")

    print(f"{'':{name_width}} |{'─' * width}|")
    print(f"{'':{name_width}} 0s{' ' * (width - 10)}{format_duration(total_span * 1000):>8}")


def run_timeline(work_dir: Path | None) -> int:
    """
    Run timeline analysis on a work directory.

    Parameters
    ----------
    work_dir : Path | None
        Path to work directory. If None, checks cwd for _opencode_logs.

    Returns
    -------
    int
        Exit code (0 success, 1 error).
    """
    # Resolve logs directory and base directory
    if work_dir is None:
        # Check if _opencode_logs exists in cwd
        cwd_logs = Path.cwd() / "_opencode_logs"
        if cwd_logs.exists() and cwd_logs.is_dir():
            logs_dir = cwd_logs
            base_dir = Path.cwd()
        else:
            print(
                "Error: No work directory specified and no _opencode_logs in current directory",
                file=sys.stderr
            )
            return 1
    else:
        logs_dir = work_dir / "_opencode_logs"
        base_dir = work_dir
        if not logs_dir.exists():
            print(f"Error: No _opencode_logs directory found in {work_dir}", file=sys.stderr)
            return 1

    # Try to find .opencode/agents for task subagent detection
    opencode_dir = base_dir / ".opencode"
    known_agents: set[str] = set()
    if opencode_dir.exists():
        known_agents = discover_agents(opencode_dir)

    # Check if the job is still running by examining main.log
    main_log = logs_dir / "main.log"
    is_running: bool = main_log.exists() and not is_log_complete(main_log)

    timeline = build_timeline(logs_dir, known_agents, is_running=is_running)
    if not timeline:
        return 1

    print_timeline(timeline)
    return 0
