"""Generate a small homophilic synthetic graph for smoke-testing the dpack.

This is paired with `example-data-negcontrol/` (label-independent edges).
The two datasets together verify the pack can distinguish "graph helps"
from "graph doesn't help" — a single example with planted signal would
not exercise the negative-evidence branch of the pack's logic.

Produces three CSVs that load_dataset() can ingest:
  - features.csv   (id, timestep, f0..f49)
  - edges.csv      (src, dst)
  - labels.csv     (id, label)

Construction:
  - ~3000 nodes across 10 timesteps
  - ~3% labeled positive, ~25% labeled negative, rest unknown
  - Positives preferentially connect to other positives (planted homophily)
  - Per-node feature signal in dimensions f0..f5 (raise positive-class mean)

This is a SMOKE TEST. It has too few test positives (~25-30) to support a
deployment recommendation — see the README. Use it to verify the pack's
machinery is wired correctly and that the reports' wording is honest;
do NOT cite numbers from a synth run as performance estimates.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np


def main():
    rng = np.random.default_rng(42)
    n_nodes = 3000
    n_timesteps = 10
    n_features = 50
    pos_rate = 0.03
    neg_rate = 0.25

    here = Path(__file__).parent

    node_ids = np.arange(n_nodes)
    timesteps = rng.integers(1, n_timesteps + 1, size=n_nodes)

    # Latent class: 0 = licit, 1 = illicit, -1 = unknown
    rand = rng.random(n_nodes)
    labels = np.where(rand < pos_rate, 1, np.where(rand < pos_rate + neg_rate, 0, -1))

    # Features: gaussian with class-dependent mean on first 5 dims
    features = rng.normal(0, 1, size=(n_nodes, n_features)).astype(np.float32)
    pos_mask = labels == 1
    features[pos_mask, :5] += 0.6

    # Edges: 1) random background; 2) homophilic among positives
    n_random_edges = 8000
    src = rng.integers(0, n_nodes, n_random_edges)
    dst = rng.integers(0, n_nodes, n_random_edges)
    edges = list(zip(src.tolist(), dst.tolist()))

    pos_nodes = np.where(pos_mask)[0]
    if len(pos_nodes) >= 2:
        n_homo = min(500, len(pos_nodes) * 3)
        ehs = rng.choice(pos_nodes, n_homo)
        ehd = rng.choice(pos_nodes, n_homo)
        edges.extend(zip(ehs.tolist(), ehd.tolist()))

    # Write features.csv (no header, Elliptic-style)
    with (here / "features.csv").open("w", newline="") as f:
        w = csv.writer(f)
        for i in range(n_nodes):
            row = [int(node_ids[i]), int(timesteps[i])] + features[i].tolist()
            w.writerow(row)

    # Write edges.csv (no header)
    with (here / "edges.csv").open("w", newline="") as f:
        w = csv.writer(f)
        for s, d in edges:
            if s != d:
                w.writerow([int(s), int(d)])

    # Write labels.csv (no header)
    with (here / "labels.csv").open("w", newline="") as f:
        w = csv.writer(f)
        for i in range(n_nodes):
            if labels[i] == -1:
                w.writerow([int(node_ids[i]), "unknown"])
            elif labels[i] == 1:
                w.writerow([int(node_ids[i]), 1])
            else:
                w.writerow([int(node_ids[i]), 2])

    print(f"Wrote synthetic dataset to {here}")
    print(f"  nodes: {n_nodes}, edges: {len(edges)}, timesteps: {n_timesteps}")
    print(
        f"  labels: positives={int(pos_mask.sum())}, "
        f"negatives={int((labels == 0).sum())}, unknown={int((labels == -1).sum())}"
    )


if __name__ == "__main__":
    main()
