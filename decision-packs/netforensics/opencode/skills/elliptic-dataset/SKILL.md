---
name: Elliptic Bitcoin Dataset
description: Schema, conventions, and known methodological pitfalls of the Elliptic Bitcoin transaction dataset — the canonical demo dataset for this decision-pack. Use when working with Elliptic specifically, or when interpreting results that follow Elliptic's distribution shape.
---

# Elliptic Bitcoin Dataset

## What it is

A graph of ~203,769 Bitcoin transactions with ~234,355 directed money-flow edges, distributed by Elliptic Inc. as the benchmark dataset for crypto AML research. Each transaction is anonymized but carries 166 features and an optional label.

## Schema

- **`elliptic_txs_features.csv`** (or `txs_features.csv`)
  - Column 1: transaction ID (integer, no header)
  - Column 2: timestep (1–49, a contiguous integer roughly meaning "two-week window")
  - Columns 3–96: 94 "local" features — per-transaction statistics
  - Columns 97–167: 71 "aggregated" features — 1-hop neighborhood aggregates (already partially encode the graph)

- **`elliptic_txs_edgelist.csv`** (or `txs_edgelist.csv`)
  - Two columns: source transaction ID, destination transaction ID
  - Directed: money flows from source to destination

- **`elliptic_txs_classes.csv`** (or `txs_classes.csv`)
  - Two columns: transaction ID, class label
  - Class values: `1` = illicit, `2` = licit, `unknown` = no label
  - Distribution: ~2% illicit, ~21% licit, ~77% unknown

## Loading

`load_dataset(<dir>)` auto-detects the Elliptic filenames and standardizes
labels to `{1=positive/illicit, 0=negative/licit, -1=unknown}`.

The 49 timesteps are loaded into `ds.timestamps`; `ds.has_timestamps` will
return True. This means **temporal_split is applicable and required** for any
honest evaluation.

## Known methodological pitfalls

1. **Random splits inflate F1 by ~30+ points on the illicit class.** This is well-documented in arXiv 2411.10957 and arXiv 2602.23599. Always use `temporal_split` for the headline result.

2. **GNN training on the full graph is itself leaky.** The standard PyG training loop does message-passing over all edges, including those touching the test set. With `temporal_split`, also pass `strict_edges=true` to `train-model`.

3. **Distribution shift mid-stream.** Class balance changes around timestep 43 (a real darknet market closed). Models that don't account for distribution shift collapse after that timestep.

4. **The 71 aggregated features encode neighborhood info.** A "graph model" that beats `feature_mode=raw_local` (94 features) but ties with `feature_mode=all` (166 features) is matched by the hand-aggregated tabular baseline. The graph isn't adding learned representation power.

5. **Report F1 on illicit class, not AUROC.** With 2% positives, AUROC will read ~0.95 for almost any reasonable model and obscure large differences in precision.

## Suggested first-pass workflow on Elliptic

1. `inspect-graph` to confirm the schema loaded correctly and the class balance matches the documented ~2/21/77 split.
2. Parallel fan-out: train XGBoost, GCN, GraphSAGE — all with `temporal_split` and (for GNNs) `strict_edges=true`.
3. Parallel fan-out: train XGBoost with `feature_mode ∈ {all, raw_local, topology_only}`. This localizes the signal.
4. Parallel fan-out: train the same model under all three split protocols. This quantifies the leakage gap.
5. `eval-edge-shuffle` on whichever model claimed to win.

The expected outcome on Elliptic: GNNs do not beat XGBoost on temporal split. The graph adds little once aggregated features are included. Report this honestly.

## Where to get the data

Original Elliptic CSVs: Kaggle (`ellipticco/elliptic-data-set`). Requires Kaggle credentials.
Mirror with extended actor-level data: `git-disl/EllipticPlusPlus` on GitHub (LFS — may exceed quota).
Programmatic download in Python: `torch_geometric.datasets.EllipticBitcoinDataset(root)` downloads from a stable URL.
