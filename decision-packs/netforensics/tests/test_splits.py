"""Split protocol invariants: disjointness, labeled-only, temporal ordering,
jitter safety, and degenerate-topology guards."""
import numpy as np
import pytest

from conftest import build_dataset
from netforensics_lib.splits import (
    inductive_subgraph_split,
    temporal_split,
    transductive_split,
)

SEEDS = [0, 1, 2, 3, 4]


def _assert_valid_masks(ds, train_mask, test_mask):
    assert not (train_mask & test_mask).any(), "train/test overlap"
    assert (ds.labels[train_mask] != -1).all(), "unlabeled node in train"
    assert (ds.labels[test_mask] != -1).all(), "unlabeled node in test"
    assert train_mask.sum() > 0 and test_mask.sum() > 0


def test_transductive_masks_valid_and_sized(dataset):
    train_mask, test_mask = transductive_split(dataset, test_frac=0.3, seed=0)
    _assert_valid_masks(dataset, train_mask, test_mask)
    n_labeled = int((dataset.labels != -1).sum())
    assert test_mask.sum() == int(n_labeled * 0.3)


def test_transductive_seed_changes_split(dataset):
    _, test_a = transductive_split(dataset, seed=0)
    _, test_b = transductive_split(dataset, seed=1)
    assert (test_a != test_b).any()


@pytest.mark.parametrize("seed", SEEDS)
def test_temporal_never_trains_on_future(dataset, seed):
    train_mask, test_mask = temporal_split(dataset, seed=seed)
    _assert_valid_masks(dataset, train_mask, test_mask)
    assert dataset.timestamps[train_mask].max() < dataset.timestamps[test_mask].min()


def test_temporal_jitter_varies_cutoff_across_seeds():
    # With jitter, at least two distinct cutoffs must appear in 10 seeds —
    # otherwise multi-seed variance of deterministic models degenerates to 0.
    # Jitter needs >= 3 test timesteps to activate (the (n_test-1)//2 term),
    # so use 12 timesteps: 4 test steps -> max_jitter = 1.
    ds = build_dataset(n_nodes=240, n_timesteps=12)
    cutoffs = {
        int(ds.timestamps[temporal_split(ds, seed=s)[1]].min()) for s in range(10)
    }
    assert len(cutoffs) >= 2, f"temporal cutoff never moved across seeds: {cutoffs}"


def test_temporal_jitter_zero_on_few_timesteps(dataset):
    # With a single test timestep there is no room to jitter — every seed
    # must produce the same (valid) cutoff rather than an empty fold.
    cutoffs = {
        int(dataset.timestamps[temporal_split(dataset, seed=s)[1]].min())
        for s in range(10)
    }
    assert len(cutoffs) == 1


def test_temporal_requires_timestamps(dataset_no_timestamps):
    with pytest.raises(ValueError, match="temporal_split requires"):
        temporal_split(dataset_no_timestamps)


def test_inductive_raises_on_giant_component():
    # A ring is one giant connected component — component splitting is
    # degenerate and must raise, not silently produce a trivial fold.
    n = 80
    ring = np.array([(i, (i + 1) % n) for i in range(n)], dtype=np.int64)
    ds = build_dataset(n_nodes=n, edges=ring, with_timestamps=False)
    with pytest.raises(ValueError, match="degenerate"):
        inductive_subgraph_split(ds)


def test_inductive_no_edges_cross_folds():
    # 40 components of 4 nodes each: enough labeled mass in both folds.
    n = 160
    edges = []
    for c in range(40):
        base = 4 * c
        edges += [(base, base + 1), (base + 1, base + 2), (base + 2, base + 3)]
    ds = build_dataset(
        n_nodes=n, edges=np.array(edges, dtype=np.int64), with_timestamps=False
    )
    train_mask, test_mask = inductive_subgraph_split(ds, min_fold_labeled=10)
    _assert_valid_masks(ds, train_mask, test_mask)
    for u, v in ds.edges:
        crosses = (train_mask[u] and test_mask[v]) or (test_mask[u] and train_mask[v])
        assert not crosses, f"edge ({u},{v}) crosses train/test"
