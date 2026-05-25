---
name: Graph ML Evaluation
description: Methodological standards for evaluating supervised graph learning models — choosing the right train/test protocol, picking class-imbalance-appropriate metrics, and avoiding the leakage traps that have inflated published results across multiple subfields. Use when designing or critiquing the evaluation of any node-classification, edge-classification, or graph-classification model.
---

# Graph ML Evaluation

## The leakage trap (the most common mistake)

When the underlying data has a temporal or geographic axis but you split train/test randomly, your model sees information at training time that it will not have at deployment. For graphs specifically, randomly splitting nodes leaves edges crossing the train/test boundary — the model effectively learns from neighborhoods that overlap with the test set.

This is *the* reason published graph-ML accuracy numbers on benchmarks like Elliptic Bitcoin look implausibly high. Under a strict temporal split (train on past, test on future), the same models commonly drop 20–40 F1 points on the minority class. This has been documented in recent reanalyses (e.g., arXiv 2411.10957 IMPaCT GNN; arXiv 2602.23599).

**The rule:** If the data has a temporal column, evaluate with `temporal_split`. Random splits are almost never a good default.

## The two-level leakage problem in transductive GNN training

Random splits create per-node leakage (test nodes in training neighborhoods). But even with a temporal split, standard GNN training is often *itself* leaky: the message-passing step at training time uses the full edge set, including edges with one endpoint in the test set. The model effectively sees the test region's structure before it predicts.

**The rule:** When using a temporal or inductive split with a GNN, pass `strict_edges=true` to `train-model`. This restricts training-time message-passing to edges with both endpoints in the train set. Eval still uses the full edge set, because at deployment time the test node's real neighborhood would be available.

If a GNN's F1 collapses when you switch from `strict_edges=false` to `strict_edges=true`, the model was relying on training-time structural leakage.

## Class-imbalance-appropriate metrics

Elliptic is ~2% positive, ~21% negative, ~77% unknown. With this imbalance, AUROC is misleading: a model with AUROC 0.97 can still be useless if you only operate at thresholds with reasonable precision. Report:

- **F1 on the positive class** (`f1_positive`) — single-number summary that respects the minority class.
- **Precision-at-K** — what the analyst actually cares about. If they can investigate 50 leads/day, how many are real?
- **PR-AUC** — better than AUROC under heavy imbalance.

AUROC can be reported but not headlined. Never lead a binary-classification claim with AUROC under imbalance > 10×.

## The no-graph baseline (the floor)

A graph model's results are only meaningful relative to a non-graph baseline trained on the same node features. If XGBoost on raw features matches or beats your GNN, **your graph isn't contributing**. The "graph model" is doing tabular work.

Always run `train-model --model xgboost --feature-mode all` as part of any comparison. Use it as the floor.

## The edge-shuffle ablation (the proof)

Even if your GNN beats XGBoost, you should verify it's actually using the graph rather than exploiting features that pre-encode neighborhood information (e.g., Elliptic's 71 "aggregated" features). The `eval-edge-shuffle` tool re-trains the model on a degree-preserving randomized graph. If F1 barely drops, the model wasn't really using graph structure.

**The rule:** Before claiming "the graph helps," run `eval-edge-shuffle`. A gap of <5 F1 points between real and shuffled means the graph signal is weak.

## Convergence reporting

When the same model is evaluated under multiple protocols and the F1 numbers diverge by >10 points, **the model has not been validated** — one of the evaluations is wrong, and almost always the optimistic one is. Report all of them; never headline only the favorable number.

The expected workflow on an Elliptic-style dataset:
1. `transductive_split` + GCN with `strict_edges=false` → likely high F1 (the leakage regime)
2. `temporal_split` + GCN with `strict_edges=true` → likely lower F1 (the honest regime)
3. `transductive_split` + XGBoost → the no-graph floor
4. `edge_shuffle_ablation` on the honest regime → the graph-signal test

If 1 ≫ 2, leakage. If 2 ≈ 3, graph adds nothing. If 4 has small gap, graph adds nothing even when 2 > 3.

## Seeds and variance

A single-seed result on a small positive class is noise. Run any reported number with ≥3 seeds and report the median plus min/max. If the spread is larger than the gap you're claiming, the gap is not real.
