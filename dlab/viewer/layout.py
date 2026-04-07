"""
DAG layout algorithm for the session viewer.

Assigns x/y/width/height positions to session nodes on a time axis.
X-axis represents time, parallel instances stack vertically.
Pure geometry — no file I/O, fully testable with synthetic data.
"""

from typing import Any


# Layout constants
MARGIN_LEFT: int = 60
MARGIN_RIGHT: int = 60
MARGIN_TOP: int = 60
MARGIN_BOTTOM: int = 80  # space for time axis
NODE_HEIGHT: int = 60
NODE_MIN_WIDTH: int = 120
NODE_PADDING_Y: int = 20
LANE_GAP: int = NODE_HEIGHT + NODE_PADDING_Y


def _assign_lanes(nodes: list[dict[str, Any]]) -> dict[str, int]:
    """
    Assign vertical lane numbers to nodes.

    Lane 0 = main (top). Parallel instances stack below.
    Consolidator gets its own lane below instances.

    Parameters
    ----------
    nodes : list[dict[str, Any]]
        Node dicts with id, phase fields.

    Returns
    -------
    dict[str, int]
        Map of node_id → lane number.
    """
    lanes: dict[str, int] = {}
    instance_counter: int = 0

    # Sort: main phases first, then parallel instances, then consolidators
    phase_order: dict[str, int] = {
        "solo": 0,
        "pre-parallel": 0,
        "post-parallel": 0,
        "parallel": 1,
        "consolidator": 2,
    }

    sorted_nodes: list[dict[str, Any]] = sorted(
        nodes,
        key=lambda n: (phase_order.get(n["phase"], 1), n.get("start_ms") or 0),
    )

    for node in sorted_nodes:
        phase: str = node["phase"]
        if phase in ("solo", "pre-parallel", "post-parallel"):
            lanes[node["id"]] = 0
        elif phase == "parallel":
            instance_counter += 1
            lanes[node["id"]] = instance_counter
        elif phase == "consolidator":
            # Place consolidator below all instances
            lanes[node["id"]] = instance_counter + 1

    return lanes


def _compute_time_positions(
    nodes: list[dict[str, Any]],
    available_width: int,
) -> dict[str, tuple[float, float]]:
    """
    Compute x position and width for each node based on timestamps.

    Parameters
    ----------
    nodes : list[dict[str, Any]]
        Node dicts with start_ms, end_ms, duration_ms.
    available_width : int
        Pixel width available for the time axis.

    Returns
    -------
    dict[str, tuple[float, float]]
        Map of node_id → (x, width).
    """
    all_starts: list[int] = [n["start_ms"] for n in nodes if n["start_ms"] is not None]
    all_ends: list[int] = [n["end_ms"] for n in nodes if n["end_ms"] is not None]

    if not all_starts or not all_ends:
        # No timing data — stack horizontally
        positions: dict[str, tuple[float, float]] = {}
        x: float = 0.0
        for node in nodes:
            positions[node["id"]] = (x, NODE_MIN_WIDTH)
            x += NODE_MIN_WIDTH + 40
        return positions

    global_start: int = min(all_starts)
    global_end: int = max(all_ends)
    total_ms: int = global_end - global_start

    if total_ms == 0:
        # All events at same timestamp — single centered node
        positions = {}
        cx: float = available_width / 2
        for node in nodes:
            positions[node["id"]] = (cx - NODE_MIN_WIDTH / 2, NODE_MIN_WIDTH)
        return positions

    positions = {}
    for node in nodes:
        start_ms: int | None = node["start_ms"]
        end_ms: int | None = node["end_ms"]
        dur_ms: int | None = node["duration_ms"]

        if start_ms is None:
            start_ms = global_start
        if end_ms is None:
            end_ms = start_ms + (dur_ms or 1000)

        # Normalize to [0, 1]
        t_start: float = (start_ms - global_start) / total_ms
        t_end: float = (end_ms - global_start) / total_ms

        x = t_start * available_width
        w: float = max(NODE_MIN_WIDTH, (t_end - t_start) * available_width)

        positions[node["id"]] = (x, w)

    return positions


def _compute_edge_paths(
    edges: list[dict[str, Any]],
    node_bounds: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    """
    Compute SVG path data for edges between nodes.

    Parameters
    ----------
    edges : list[dict[str, Any]]
        Edge dicts with source, target, type.
    node_bounds : dict[str, dict[str, float]]
        Map of node_id → {x, y, width, height}.

    Returns
    -------
    list[dict[str, Any]]
        Edge dicts with added path_data (SVG cubic bezier string),
        source_point, target_point.
    """
    result: list[dict[str, Any]] = []

    for edge in edges:
        src: dict[str, float] | None = node_bounds.get(edge["source"])
        tgt: dict[str, float] | None = node_bounds.get(edge["target"])

        if src is None or tgt is None:
            continue

        # Source anchor: right edge center
        sx: float = src["x"] + src["width"]
        sy: float = src["y"] + src["height"] / 2

        # Target anchor: left edge center
        tx: float = tgt["x"]
        ty: float = tgt["y"] + tgt["height"] / 2

        # For spawn edges going down, use bottom of source
        if edge["type"] == "spawn" and ty > sy:
            sx = src["x"] + src["width"] / 2
            sy = src["y"] + src["height"]
            tx = tgt["x"]
            ty = tgt["y"] + tgt["height"] / 2

        # For resume edges going up, use top of target
        if edge["type"] == "resume" and sy > ty:
            sx = src["x"] + src["width"]
            sy = src["y"] + src["height"] / 2
            tx = tgt["x"] + tgt["width"] / 2
            ty = tgt["y"] + tgt["height"]

        # Bezier control points — horizontal offset for smooth curves
        dx: float = abs(tx - sx) * 0.4
        cx1: float = sx + dx
        cy1: float = sy
        cx2: float = tx - dx
        cy2: float = ty

        path: str = f"M {sx:.1f} {sy:.1f} C {cx1:.1f} {cy1:.1f} {cx2:.1f} {cy2:.1f} {tx:.1f} {ty:.1f}"

        result.append({
            **edge,
            "path_data": path,
            "source_point": {"x": sx, "y": sy},
            "target_point": {"x": tx, "y": ty},
        })

    return result


def compute_layout(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    canvas_width: int = 1200,
    canvas_height: int = 800,
) -> dict[str, Any]:
    """
    Compute x/y/width/height for all nodes and path data for edges.

    Parameters
    ----------
    nodes : list[dict[str, Any]]
        Node dicts from session_data.extract_session_data().
    edges : list[dict[str, Any]]
        Edge dicts from session_data.extract_session_data().
    canvas_width : int
        Total SVG canvas width in pixels.
    canvas_height : int
        Minimum canvas height (auto-expands for many lanes).

    Returns
    -------
    dict[str, Any]
        {
            "nodes": nodes with x, y, width, height added,
            "edges": edges with path_data added,
            "canvas_width": int,
            "canvas_height": int,
            "time_axis": {global_start_ms, global_end_ms, ticks: [{ms, x, label}]},
        }
    """
    if not nodes:
        return {
            "nodes": [],
            "edges": [],
            "canvas_width": canvas_width,
            "canvas_height": canvas_height,
            "time_axis": None,
        }

    # Step 1: Assign lanes
    lanes: dict[str, int] = _assign_lanes(nodes)
    max_lane: int = max(lanes.values()) if lanes else 0

    # Auto-size canvas height
    needed_height: int = MARGIN_TOP + (max_lane + 1) * LANE_GAP + MARGIN_BOTTOM
    canvas_height = max(canvas_height, needed_height)

    # Step 2: Compute time positions
    available_width: int = canvas_width - MARGIN_LEFT - MARGIN_RIGHT
    time_positions: dict[str, tuple[float, float]] = _compute_time_positions(nodes, available_width)

    # Step 3: Assign final x/y/width/height to each node
    node_bounds: dict[str, dict[str, float]] = {}
    for node in nodes:
        nid: str = node["id"]
        x_offset, width = time_positions.get(nid, (0, NODE_MIN_WIDTH))
        lane: int = lanes.get(nid, 0)

        node["x"] = MARGIN_LEFT + x_offset
        node["y"] = MARGIN_TOP + lane * LANE_GAP
        node["width"] = width
        node["height"] = NODE_HEIGHT

        node_bounds[nid] = {
            "x": node["x"],
            "y": node["y"],
            "width": node["width"],
            "height": node["height"],
        }

    # Step 4: Compute edge paths
    laid_out_edges: list[dict[str, Any]] = _compute_edge_paths(edges, node_bounds)

    # Step 5: Build time axis
    time_axis: dict[str, Any] | None = _build_time_axis(nodes, available_width)

    return {
        "nodes": nodes,
        "edges": laid_out_edges,
        "canvas_width": canvas_width,
        "canvas_height": canvas_height,
        "time_axis": time_axis,
    }


def _build_time_axis(
    nodes: list[dict[str, Any]],
    available_width: int,
) -> dict[str, Any] | None:
    """
    Build time axis tick marks and labels.

    Parameters
    ----------
    nodes : list[dict[str, Any]]
        Nodes with start_ms, end_ms.
    available_width : int
        Pixel width of the time axis.

    Returns
    -------
    dict[str, Any] | None
        Time axis data, or None if no timing data.
    """
    all_starts: list[int] = [n["start_ms"] for n in nodes if n["start_ms"] is not None]
    all_ends: list[int] = [n["end_ms"] for n in nodes if n["end_ms"] is not None]

    if not all_starts or not all_ends:
        return None

    global_start: int = min(all_starts)
    global_end: int = max(all_ends)
    total_ms: int = global_end - global_start

    if total_ms == 0:
        return {
            "global_start_ms": global_start,
            "global_end_ms": global_end,
            "ticks": [{"ms": 0, "x": MARGIN_LEFT + available_width / 2, "label": "+0s"}],
        }

    # Choose tick interval based on total duration
    tick_interval_ms: int
    if total_ms < 10_000:
        tick_interval_ms = 1_000         # 1s ticks for < 10s
    elif total_ms < 60_000:
        tick_interval_ms = 5_000         # 5s ticks for < 1min
    elif total_ms < 300_000:
        tick_interval_ms = 30_000        # 30s ticks for < 5min
    elif total_ms < 600_000:
        tick_interval_ms = 60_000        # 1min ticks for < 10min
    else:
        tick_interval_ms = 300_000       # 5min ticks for >= 10min

    ticks: list[dict[str, Any]] = []
    t: int = 0
    while t <= total_ms:
        x: float = MARGIN_LEFT + (t / total_ms) * available_width
        label: str = _format_time_label(t)
        ticks.append({"ms": t, "x": x, "label": label})
        t += tick_interval_ms

    # Always include the end tick
    if ticks and ticks[-1]["ms"] < total_ms:
        x = MARGIN_LEFT + available_width
        ticks.append({"ms": total_ms, "x": x, "label": _format_time_label(total_ms)})

    return {
        "global_start_ms": global_start,
        "global_end_ms": global_end,
        "ticks": ticks,
    }


def _format_time_label(ms: int) -> str:
    """
    Format milliseconds as a human-readable time label.

    Parameters
    ----------
    ms : int
        Milliseconds from session start.

    Returns
    -------
    str
        Formatted label (e.g. "+0s", "+30s", "+2m30s").
    """
    seconds: int = ms // 1000
    if seconds < 60:
        return f"+{seconds}s"
    minutes: int = seconds // 60
    remaining_seconds: int = seconds % 60
    if remaining_seconds == 0:
        return f"+{minutes}m"
    return f"+{minutes}m{remaining_seconds}s"
