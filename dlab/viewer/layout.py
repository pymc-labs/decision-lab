"""
Layout conversion for the session viewer.

Converts the Python process tree into d3-hierarchy JSON format.
All spatial layout is computed client-side by d3.tree().
"""

from typing import Any


def compute_process_layout(tree: dict[str, Any]) -> dict[str, Any]:
    """
    Convert process tree to d3-hierarchy JSON format.

    The actual layout is computed client-side using d3.tree().
    This function converts the Python tree to a nested
    {name, type, children, ...} structure that d3 can consume.

    Parameters
    ----------
    tree : dict[str, Any]
        Agent tree from extract_process_tree().

    Returns
    -------
    dict[str, Any]
        d3-compatible hierarchy with {name, children, data}.
    """
    return _tree_to_d3(tree)


def _tree_to_d3(agent_tree: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively convert an agent tree to d3 hierarchy format.

    Structure: session root → todo nodes → turn nodes.
    Parallel turns get child session sub-trees.
    "Free-form working" todos are collapsed — their children
    are promoted directly into the parent's children list.

    Parameters
    ----------
    agent_tree : dict[str, Any]
        Agent tree with "todos" list.

    Returns
    -------
    dict[str, Any]
        d3 hierarchy node.
    """
    children: list[dict[str, Any]] = []

    # Preamble turns (before first todowrite) become direct session children
    for turn in agent_tree.get("preamble_turns", []):
        children.append(_turn_to_d3(turn))

    for todo in agent_tree.get("todos", []):
        todo_children: list[dict[str, Any]] = [
            _turn_to_d3(turn) for turn in todo.get("turns", [])
        ]

        # Skip "Free-form working" as a todo node — promote its children
        if todo["label"] == "Free-form working":
            children.extend(todo_children)
        else:
            children.append({
                "name": todo["label"],
                "type": "todo",
                "status": todo.get("status"),
                "has_error": todo.get("has_error", False),
                "children": todo_children if todo_children else None,
            })

    return {
        "name": agent_tree.get("agent", "agent"),
        "type": "session",
        "model": agent_tree.get("model"),
        "is_complete": agent_tree.get("is_complete", False),
        "is_consolidator": agent_tree.get("is_consolidator", False),
        "total_cost": agent_tree.get("total_cost", 0),
        "prompt": agent_tree.get("prompt"),
        "artifacts": agent_tree.get("artifacts", []),
        "children": children if children else None,
    }


def _turn_to_d3(turn: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a single turn (thinking or parallel) to a d3 node.

    Parameters
    ----------
    turn : dict[str, Any]
        Turn dict with type, summary, steps, and optionally children.

    Returns
    -------
    dict[str, Any]
        d3 node.
    """
    if turn["type"] == "parallel":
        parallel_children: list[dict[str, Any]] = []
        for child_tree in turn.get("children", []):
            parallel_children.append(_tree_to_d3(child_tree))
        consolidator: dict[str, Any] | None = turn.get("consolidator")
        if consolidator:
            parallel_children.append(_tree_to_d3(consolidator))
        return {
            "name": turn.get("summary", "parallel"),
            "type": "parallel",
            "has_error": turn.get("has_error", False),
            "steps": turn.get("steps", []),
            "children": parallel_children,
        }

    return {
        "name": turn.get("summary", "working"),
        "type": "thinking",
        "has_error": turn.get("has_error", False),
        "steps": turn.get("steps", []),
    }
