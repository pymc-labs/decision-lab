"""CLI bridge for the eval-edge-shuffle tool.

Trains the chosen model twice: once on the real graph, once on a
degree-preserving randomized version. If F1 is similar, the model is not
using graph structure — the "graph signal" claim collapses.

Critical: when the split is temporal or inductive, `strict_edges=true` is
forced for GNN training in BOTH the real-graph and the shuffled-graph runs.
Measuring the edge-shuffle gap under training-time leakage is meaningless —
the leaky regime mixes graph signal with leakage signal, so the
"real-minus-shuffled" comparison no longer isolates graph contribution.

Usage:
    python -m netforensics_lib.edge_shuffle_cli \\
        --data <dir> --model {xgboost,gcn,graphsage} \\
        --split {transductive,temporal,inductive} \\
        [--seed 0]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .eval import edge_shuffle_ablation
from .loader import load_dataset
from .models import train_gcn, train_graphsage, train_xgboost
from .splits import (
    inductive_subgraph_split,
    temporal_split,
    transductive_split,
)


SPLITS = {
    "transductive": transductive_split,
    "temporal": temporal_split,
    "inductive": inductive_subgraph_split,
}
MODELS = {
    "xgboost": train_xgboost,
    "gcn": train_gcn,
    "graphsage": train_graphsage,
}
LEAKY_SPLITS = {"temporal", "inductive"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--model", required=True, choices=list(MODELS))
    p.add_argument("--split", required=True, choices=list(SPLITS))
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    ds = load_dataset(Path(args.data))
    try:
        train_mask, test_mask = SPLITS[args.split](ds, seed=args.seed)
    except ValueError as e:
        print(json.dumps({"error": "split_not_applicable", "detail": str(e)}))
        return 3

    forced_strict = args.model != "xgboost" and args.split in LEAKY_SPLITS

    result = edge_shuffle_ablation(
        ds=ds,
        train_fn=MODELS[args.model],
        train_mask=train_mask,
        test_mask=test_mask,
        seed=args.seed,
        strict_edges=forced_strict,
    )
    result["split"] = args.split
    result["model"] = args.model
    result["strict_edges_forced"] = forced_strict
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
