"""CLI bridge for the train-model tool.

Usage:
    python -m netforensics_lib.train_cli \\
        --data <dir> --model {xgboost,gcn,graphsage} \\
        --split {transductive,temporal,inductive} \\
        --feature-mode {all,raw_local,topology_only} \\
        [--n-raw-features 94] [--seed 0] [--strict-edges]

Prints a JSON line with the evaluation metrics. The agent reads this and
writes it into summary.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--model", required=True, choices=list(MODELS))
    p.add_argument("--split", required=True, choices=list(SPLITS))
    p.add_argument("--feature-mode", default="all", choices=["all", "raw_local", "topology_only"])
    p.add_argument("--n-raw-features", type=int, default=None)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--strict-edges",
        action="store_true",
        help="For GNN models, restrict training-time message-passing to edges with both endpoints in the train set. Use this with temporal/inductive splits to avoid information leakage from the test region.",
    )
    args = p.parse_args()

    ds = load_dataset(Path(args.data))
    split_fn = SPLITS[args.split]
    try:
        train_mask, test_mask = split_fn(ds, seed=args.seed)
    except ValueError as e:
        # Splits raise ValueError for inapplicable protocols (e.g., inductive
        # on a single-giant-component graph). Surface this to the agent so it
        # can record "protocol not applicable" instead of fabricating numbers.
        print(json.dumps({"error": "split_not_applicable", "detail": str(e)}))
        return 3

    if int(test_mask.sum()) == 0:
        print(json.dumps({"error": "empty test set; check split arguments"}), file=sys.stderr)
        return 2

    train_kwargs = dict(
        feature_mode=args.feature_mode,
        n_raw_features=args.n_raw_features,
        seed=args.seed,
    )
    if args.model != "xgboost" and args.strict_edges:
        # Restrict training edges to those with both endpoints in train set.
        train_endpoints = np.isin(ds.edges, np.where(train_mask)[0]).all(axis=1)
        train_kwargs["training_edges"] = ds.edges[train_endpoints]

    result = MODELS[args.model](ds=ds, train_mask=train_mask, test_mask=test_mask, **train_kwargs)
    result["split"] = args.split
    result["n_train"] = int(train_mask.sum())
    result["n_test"] = int(test_mask.sum())
    result["strict_edges"] = bool(args.strict_edges)

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
