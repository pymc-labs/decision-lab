---
name: Graph Baselines and Feature Ablation
description: The "no-graph baseline" doctrine and how to localize where signal lives in a node-classification problem (raw features, aggregated features, or graph topology). Use when comparing model families or before claiming a graph-based method "works" on a dataset.
---

# Graph Baselines and Feature Ablation

## The doctrine: every graph-ML claim is a comparative claim

A statement like "our GCN achieves F1=0.78 on Elliptic" is not a result. It's a result only if accompanied by:

- The same metric for a non-graph baseline trained on the same features (typically XGBoost or LightGBM).
- An ablation that decomposes the GCN's signal into "from features" vs. "from graph structure."

Without those, you cannot tell whether the graph contributes anything. In our experience, often it doesn't — papers often report large GNN-vs-MLP gaps that disappear when the MLP is tuned properly.

## The three feature regimes (for any node-classification dataset)

For a dataset with per-node features, there are typically three feature regimes worth comparing:

1. **`feature_mode=all`** — all provided features. Includes any "aggregated" features that pre-encode neighborhood info.
2. **`feature_mode=raw_local`** — only the features that describe a single node, not its neighborhood. For Elliptic this is the first 94 columns (per-transaction stats: timestamps, amounts, fees). The remaining 71 are 1-hop neighborhood aggregates and *partially encode the graph*.
3. **`feature_mode=topology_only`** — ignore the provided features; use only computed graph statistics (degree, PageRank, clustering, etc.). Tests whether the graph alone is informative.

The three together let you say:

- *Raw features → full features* gap = the contribution of pre-aggregated neighborhood features.
- *Topology-only* result = how much the graph alone tells you.
- *Full features → GNN* gap = the contribution of learned graph representations beyond what the aggregated features already capture.

A common finding: full features ≈ GNN, because the aggregated features already capture most of what message-passing would learn. This is informative — it means the graph isn't useless, but a tree model + aggregations is sufficient and more interpretable.

## The Elliptic-specific note

The Elliptic Bitcoin dataset distinguishes two feature groups by convention:
- Columns 2–95: 94 "local" features (no graph access).
- Columns 96–166: 71 features built from 1-hop transaction neighborhoods (graph-derived).

When running ablation on Elliptic, set `n_raw_features=94`. On other datasets, the meaningful split depends on the dataset's own documentation.

## When to call this skill

Whenever the orchestrator is about to spawn a `feature-ablator` parallel run, or whenever a sub-agent is asked to compare model families. The output is informative whether or not the dataset has a "leakage trap" — it tells the analyst where the signal lives, which is the start of any deployment decision.

## What to look for in results

Common patterns and what they mean:

| Pattern | Interpretation |
|---|---|
| `topology_only` ≈ random | The graph has little signal for the task. Recommend abandoning graph methods. |
| `raw_local` ≪ `all` | Most signal comes from aggregated features; a tabular model on `all` is probably sufficient. |
| `all` ≈ `GCN(all)` | GCN's learned representations don't add much beyond hand-aggregated features. Use the simpler model. |
| `GCN(all)` ≫ `all` | The GCN is genuinely extracting additional graph signal. Report enthusiastically. |
| Big gap between transductive and temporal `GCN(all)` results | Leakage. The "GCN wins" claim isn't valid. |
