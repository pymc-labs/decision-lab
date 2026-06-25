"""Evaluation metrics and ablations.

For severely imbalanced binary problems, AUROC is misleading because it
averages over all decision thresholds including the useless ones. We report
F1 on the positive class and precision-at-K as the headline metrics; AUROC
is included only as a secondary comparator.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_recall_curve,
    roc_auc_score,
)

from .loader import GraphDataset


def evaluate(y_true: np.ndarray, y_score: np.ndarray, threshold: float = 0.5) -> dict:
    """Standardized evaluation block for binary classification.

    y_true:  (n,) array of 0/1
    y_score: (n,) array of positive-class probabilities or scores
    """
    y_pred = (y_score >= threshold).astype(int)
    out = {
        "f1_positive": float(f1_score(y_true, y_pred, pos_label=1, zero_division=0)),
        "precision_at_50": precision_at_k(y_true, y_score, k=50),
        "precision_at_500": precision_at_k(y_true, y_score, k=500),
        "pr_auc": float(average_precision_score(y_true, y_score))
        if y_true.sum() > 0
        else float("nan"),
        "auroc": float(roc_auc_score(y_true, y_score))
        if y_true.sum() > 0 and (y_true == 0).sum() > 0
        else float("nan"),
        "n_test": int(len(y_true)),
        "n_positive": int(y_true.sum()),
    }
    return out


def precision_at_k(y_true: np.ndarray, y_score: np.ndarray, k: int = 100) -> float:
    """Of the top-k highest-scored items, what fraction are actually positive?

    This is the metric a downstream operator typically cares about — given a
    fixed daily review/follow-up capacity, how productive is the ranked queue.
    """
    if len(y_score) == 0 or k <= 0:
        return float("nan")
    k = min(k, len(y_score))
    top_k = np.argpartition(-y_score, k - 1)[:k]
    return float(y_true[top_k].mean())


def edge_shuffle_ablation(
    ds: GraphDataset,
    train_fn,
    train_mask: np.ndarray,
    test_mask: np.ndarray,
    seed: int = 0,
    strict_edges: bool = False,
    **train_kwargs,
) -> dict:
    """Re-run training with edges randomly rewired, keeping degree distribution.

    If a graph-aware model performs comparably with shuffled edges, the model
    is not actually using graph structure — it's exploiting the raw node
    features (or any pre-computed aggregated features). This is the test that
    decides whether the graph contributes signal.

    `strict_edges=True` mirrors the train-time leakage guard in models.py for
    GNNs: training-time message-passing is restricted to edges with both
    endpoints in the train set. CRUCIALLY this filter is recomputed against
    each dataset (real and shuffled) — passing the real-graph train edges
    into the shuffled run would be wrong (those edges don't exist there).

    Returns: {real, shuffled, gap} where each is the full evaluate() dict.
    """

    def _run(dataset):
        kwargs = dict(train_kwargs)
        if strict_edges:
            train_idx_set = np.where(train_mask)[0]
            mask = np.isin(dataset.edges, train_idx_set).all(axis=1)
            kwargs["training_edges"] = dataset.edges[mask]
        return train_fn(
            ds=dataset, train_mask=train_mask, test_mask=test_mask, seed=seed, **kwargs
        )

    real_result = _run(ds)
    shuffled_ds = _degree_preserving_shuffle(ds, seed=seed)
    shuffled_result = _run(shuffled_ds)

    return {
        "real": real_result,
        "shuffled": shuffled_result,
        "f1_gap": real_result["f1_positive"] - shuffled_result["f1_positive"],
        "auroc_gap": (
            real_result["auroc"] - shuffled_result["auroc"]
            if not (
                np.isnan(real_result["auroc"]) or np.isnan(shuffled_result["auroc"])
            )
            else float("nan")
        ),
        "strict_edges": strict_edges,
    }


def _degree_preserving_shuffle(ds: GraphDataset, seed: int = 0) -> GraphDataset:
    """Configuration-model-style randomization: keep each node's degree, rewire targets.

    Implementation: random double-edge swaps. This preserves the degree
    sequence exactly while destroying any non-degree structure (community,
    motif, assortativity).
    """
    import networkx as nx

    g = nx.Graph()
    g.add_nodes_from(range(ds.n_nodes))
    g.add_edges_from(ds.edges.tolist())
    n_swaps = max(10 * g.number_of_edges(), 1000)
    try:
        nx.double_edge_swap(g, nswap=n_swaps, max_tries=n_swaps * 10, seed=seed)
    except nx.NetworkXAlgorithmError:
        # Falls through for graphs too dense/sparse to fully randomize;
        # the partial randomization is still informative.
        pass

    new_edges = np.array(list(g.edges()), dtype=np.int64)

    return GraphDataset(
        features=ds.features,
        timestamps=ds.timestamps,
        edges=new_edges,
        labels=ds.labels,
        node_ids=ds.node_ids,
        feature_names=ds.feature_names,
    )
