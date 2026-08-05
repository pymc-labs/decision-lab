"""Metric and ablation tests: precision@K, degree preservation of the edge
shuffle, and the strict-edges recomputation guard."""
from collections import Counter

import numpy as np

from conftest import build_dataset
from netforensics_lib.eval import (
    _degree_preserving_shuffle,
    edge_shuffle_ablation,
    evaluate,
    precision_at_k,
)


def test_precision_at_k_hand_computed():
    y_true = np.array([1, 0, 1, 0, 0])
    y_score = np.array([0.9, 0.8, 0.7, 0.2, 0.1])
    assert precision_at_k(y_true, y_score, k=1) == 1.0
    assert precision_at_k(y_true, y_score, k=2) == 0.5
    assert precision_at_k(y_true, y_score, k=5) == 0.4
    # k larger than n falls back to n
    assert precision_at_k(y_true, y_score, k=50) == 0.4
    assert np.isnan(precision_at_k(np.array([]), np.array([]), k=10))


def test_evaluate_perfect_predictions():
    y_true = np.array([1, 1, 0, 0, 0, 1])
    result = evaluate(y_true, y_true.astype(float))
    assert result["f1_positive"] == 1.0
    assert result["auroc"] == 1.0
    assert result["n_test"] == 6
    assert result["n_positive"] == 3
    for key in ("precision_at_50", "precision_at_500", "pr_auc"):
        assert key in result


def test_evaluate_single_class_gives_nan_auroc():
    y_true = np.ones(10, dtype=int)
    result = evaluate(y_true, np.linspace(0, 1, 10))
    assert np.isnan(result["auroc"])


def test_shuffle_preserves_degree_sequence():
    # Simple graph (no self-loops, no duplicates) so the nx round-trip inside
    # the shuffle does not collapse edges and degrees are directly comparable.
    rng = np.random.default_rng(3)
    n = 100
    pairs = {(int(u), int(v)) for u, v in zip(rng.integers(0, n, 400), rng.integers(0, n, 400)) if u < v}
    edges = np.array(sorted(pairs), dtype=np.int64)
    ds = build_dataset(n_nodes=n, seed=3, edges=edges)
    shuffled = _degree_preserving_shuffle(ds, seed=0)

    def degree_multiset(edge_array: np.ndarray) -> Counter:
        deg: Counter = Counter()
        for u, v in edge_array:
            deg[int(u)] += 1
            deg[int(v)] += 1
        return Counter(sorted(deg.values()))

    assert degree_multiset(edges) == degree_multiset(shuffled.edges)
    # ...and it must actually rewire something.
    real_set = {tuple(sorted(e)) for e in edges.tolist()}
    shuf_set = {tuple(sorted(e)) for e in shuffled.edges.tolist()}
    assert real_set != shuf_set


def test_edge_shuffle_recomputes_strict_edges_per_dataset():
    """The leakage guard: with strict_edges=True the training-edge filter must
    be recomputed against EACH dataset (real and shuffled), never carried over
    from the real graph."""
    ds = build_dataset(n_nodes=60, seed=4)
    train_mask, test_mask = np.zeros(60, dtype=bool), np.zeros(60, dtype=bool)
    labeled = np.where(ds.labels != -1)[0]
    train_mask[labeled[: len(labeled) // 2]] = True
    test_mask[labeled[len(labeled) // 2 :]] = True

    seen: list[tuple[np.ndarray, np.ndarray]] = []

    def fake_train_fn(ds, train_mask, test_mask, seed, training_edges=None, **_):
        seen.append((ds.edges.copy(), training_edges.copy()))
        return {"f1_positive": 0.5, "auroc": float("nan")}

    result = edge_shuffle_ablation(
        ds, fake_train_fn, train_mask, test_mask, seed=0, strict_edges=True
    )
    assert len(seen) == 2
    for dataset_edges, training_edges in seen:
        edge_set = {tuple(e) for e in dataset_edges.tolist()}
        for e in training_edges.tolist():
            assert tuple(e) in edge_set, "training_edges not from this dataset"
        train_idx = set(np.where(train_mask)[0].tolist())
        for u, v in training_edges.tolist():
            assert u in train_idx and v in train_idx
    assert result["f1_gap"] == 0.0
    assert result["strict_edges"] is True
