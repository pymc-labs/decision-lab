"""First-pass dataset description.

Called by the orchestrator before any modeling. The numbers it reports
(class balance, temporal range, missingness) drive downstream choices —
the agent reads this and decides which evaluation protocols are applicable.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .loader import GraphDataset, load_dataset


def inspect(ds: GraphDataset) -> dict:
    labels = ds.labels
    positives = int((labels == 1).sum())
    negatives = int((labels == 0).sum())
    unknown = int((labels == -1).sum())
    n_labeled = positives + negatives

    out = {
        "n_nodes": ds.n_nodes,
        "n_edges": ds.n_edges,
        "n_features": ds.n_features,
        "has_timestamps": ds.has_timestamps,
        "labeled": {
            "n_positive": positives,
            "n_negative": negatives,
            "n_unknown": unknown,
            "positive_rate_labeled": positives / n_labeled if n_labeled > 0 else None,
            "positive_rate_overall": positives / ds.n_nodes,
        },
        "feature_stats": {
            "n_features": ds.n_features,
            "any_nan": bool(np.isnan(ds.features).any()),
            "min": float(ds.features.min()) if ds.features.size else None,
            "max": float(ds.features.max()) if ds.features.size else None,
            "mean": float(ds.features.mean()) if ds.features.size else None,
        },
    }

    if ds.has_timestamps:
        ts = ds.timestamps[ds.timestamps >= 0]
        out["temporal"] = {
            "min_timestep": int(ts.min()),
            "max_timestep": int(ts.max()),
            "n_timesteps": int(len(np.unique(ts))),
            "labeled_per_timestep": _per_timestep_label_distribution(ds),
        }

    # Edge / degree summary
    if ds.n_edges > 0:
        from collections import Counter
        deg = Counter(int(u) for u, _ in ds.edges)
        for _, v in ds.edges:
            deg[int(v)] += 1
        degs = np.array(list(deg.values()))
        out["degree"] = {
            "mean": float(degs.mean()),
            "median": float(np.median(degs)),
            "max": int(degs.max()),
            "p95": float(np.percentile(degs, 95)),
            "n_isolated": int(ds.n_nodes - len(deg)),
        }
    return out


def _per_timestep_label_distribution(ds: GraphDataset, max_steps: int = 50) -> list[dict]:
    ts_unique = sorted(np.unique(ds.timestamps[ds.timestamps >= 0]))
    out = []
    for t in ts_unique[:max_steps]:
        mask = ds.timestamps == t
        out.append({
            "timestep": int(t),
            "n_nodes": int(mask.sum()),
            "n_positive": int(((ds.labels == 1) & mask).sum()),
            "n_negative": int(((ds.labels == 0) & mask).sum()),
            "n_unknown": int(((ds.labels == -1) & mask).sum()),
        })
    return out


def main_cli(data_dir: str) -> None:
    """CLI entry point: python -m netforensics_lib.inspect_graph <data_dir>"""
    ds = load_dataset(Path(data_dir))
    report = inspect(ds)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m netforensics_lib.inspect_graph <data_dir>")
        sys.exit(1)
    main_cli(sys.argv[1])
