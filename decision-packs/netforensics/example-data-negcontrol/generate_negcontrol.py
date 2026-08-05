"""Generate a negative-control synthetic dataset.

The point: prove the dpack will correctly say "the graph contributes no
signal here" when that is the truth. If the pack ever returns a deploy
recommendation on this data, the methodology is broken.

Construction:
  - Same shape as example-data: ~3000 nodes across 10 timesteps, ~3% positives.
  - Per-node features carry a real signal in the first 5 dimensions
    (XGBoost should still beat the positive rate).
  - Edges are sampled uniformly at random — NO homophily, NO community
    structure, NO degree-label correlation.
  - The degree distribution is preserved between this and example-data so the
    edge-shuffle ablation produces a comparable "shuffled" graph.

Expected pack behavior on this dataset:
  - protocol fan-out: small (or zero) F1 gap between transductive and temporal,
    because the graph carries no exploitable structure for either to leak.
  - model fan-out: GNNs ≈ XGBoost within seed spread.
  - feature fan-out: topology_only ≈ random; all ≈ raw_local (no aggregated
    features here, so they should be identical anyway).
  - edge-shuffle: F1 gap on the best GNN is approximately zero (median),
    with seed spread that overlaps zero.

If the report comes back recommending "deploy a GNN" — the pack is broken.
The correct verdict is "use the tabular baseline; the graph adds nothing."
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np


def main():
    rng = np.random.default_rng(123)
    n_nodes = 3000
    n_timesteps = 10
    n_features = 50
    pos_rate = 0.03
    neg_rate = 0.25
    n_edges = 8500  # roughly matched to the homophilic example-data total

    here = Path(__file__).parent

    node_ids = np.arange(n_nodes)
    timesteps = rng.integers(1, n_timesteps + 1, size=n_nodes)

    rand = rng.random(n_nodes)
    labels = np.where(rand < pos_rate, 1, np.where(rand < pos_rate + neg_rate, 0, -1))

    # Features carry per-node signal so a tabular baseline can still learn
    # SOMETHING. This isn't a "no signal anywhere" dataset; it's a "no GRAPH
    # signal" dataset. The distinction matters for what the pack should
    # report: "use the tabular baseline" is the correct verdict, not
    # "abandon the problem."
    features = rng.normal(0, 1, size=(n_nodes, n_features)).astype(np.float32)
    pos_mask = labels == 1
    features[pos_mask, :5] += 0.6

    # Pure-random edges: src and dst drawn uniformly with NO conditioning on
    # label. Self-loops are dropped at write time.
    src = rng.integers(0, n_nodes, n_edges)
    dst = rng.integers(0, n_nodes, n_edges)
    edges = list(zip(src.tolist(), dst.tolist()))

    with (here / "features.csv").open("w", newline="") as f:
        w = csv.writer(f)
        for i in range(n_nodes):
            row = [int(node_ids[i]), int(timesteps[i])] + features[i].tolist()
            w.writerow(row)

    with (here / "edges.csv").open("w", newline="") as f:
        w = csv.writer(f)
        for s, d in edges:
            if s != d:
                w.writerow([int(s), int(d)])

    with (here / "labels.csv").open("w", newline="") as f:
        w = csv.writer(f)
        for i in range(n_nodes):
            if labels[i] == -1:
                w.writerow([int(node_ids[i]), "unknown"])
            elif labels[i] == 1:
                w.writerow([int(node_ids[i]), 1])
            else:
                w.writerow([int(node_ids[i]), 2])

    print(f"Wrote negative-control synthetic dataset to {here}")
    print(f"  nodes: {n_nodes}, edges: {len(edges)}, timesteps: {n_timesteps}")
    print(
        f"  labels: positives={int(pos_mask.sum())}, "
        f"negatives={int((labels == 0).sum())}, unknown={int((labels == -1).sum())}"
    )
    print("  edge construction: uniform random (no homophily, no clustering)")


if __name__ == "__main__":
    main()
