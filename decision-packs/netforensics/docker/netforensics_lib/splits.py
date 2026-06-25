"""Three orthogonal evaluation protocols.

The choice of protocol is what determines whether a reported F1 is a real
estimate of deployment performance or an artifact of leakage. All three
functions return (train_mask, test_mask) — boolean arrays over the labeled
subset of nodes.
"""
from __future__ import annotations

import numpy as np

from .loader import GraphDataset


def transductive_split(
    ds: GraphDataset,
    test_frac: float = 0.30,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Random split over labeled nodes.

    This is the protocol the published Elliptic literature has historically
    used. It is wrong for any graph with a temporal axis because adjacent
    transactions from the same time window end up split across train and
    test, allowing the model to memorize neighborhood patterns it would not
    see in deployment.
    """
    labeled = np.where(ds.labels != -1)[0]
    rng = np.random.default_rng(seed)
    rng.shuffle(labeled)
    n_test = int(len(labeled) * test_frac)
    test_idx = labeled[:n_test]
    train_idx = labeled[n_test:]

    train_mask = np.zeros(ds.n_nodes, dtype=bool)
    test_mask = np.zeros(ds.n_nodes, dtype=bool)
    train_mask[train_idx] = True
    test_mask[test_idx] = True
    return train_mask, test_mask


def temporal_split(
    ds: GraphDataset,
    test_frac: float = 0.30,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Train on early timestamps, test on later ones.

    This is the protocol that should be used whenever the dataset has a
    temporal axis. It estimates how the model will perform on the
    distribution it will actually face: future events.

    Seed semantics — temporal cutoff jitter:
        Multi-seed reporting on a temporal split is only useful if different
        seeds produce different splits. Otherwise all "seeds" collapse to one
        run and variance is zero for deterministic models (e.g., XGBoost),
        which masquerades as "perfect stability" in reports. To prevent that,
        each seed draws a cutoff offset in [-max_jitter, +max_jitter]
        timesteps around the canonical (1 - test_frac) cutoff. `max_jitter` is
        derived from the timestep count so that no seed produces an empty
        train or test fold.

        Variance across seeds therefore reflects sensitivity to where the
        train/test temporal boundary is drawn — which is the methodological
        uncertainty you actually want to surface.
    """
    if not ds.has_timestamps:
        raise ValueError(
            "temporal_split requires a temporal column in features.csv. "
            "This dataset has none. Use transductive_split or build a different split."
        )
    timesteps = sorted(np.unique(ds.timestamps[ds.timestamps >= 0]))
    n_total = len(timesteps)
    n_test_steps = max(1, int(n_total * test_frac))
    n_train_steps = n_total - n_test_steps

    # Largest offset that keeps both folds non-empty with a 1-step safety
    # margin on each side; capped at 2 because larger swings cease to
    # represent "uncertainty about where to cut" and start representing
    # "different evaluations."
    max_jitter = max(0, min(2, (n_train_steps - 1) // 2, (n_test_steps - 1) // 2))
    rng = np.random.default_rng(seed)
    offset = int(rng.integers(-max_jitter, max_jitter + 1)) if max_jitter > 0 else 0

    cutoff_idx = n_train_steps + offset  # index of first test timestep
    test_cutoff = timesteps[cutoff_idx]
    train_mask = (ds.labels != -1) & (ds.timestamps < test_cutoff) & (ds.timestamps >= 0)
    test_mask = (ds.labels != -1) & (ds.timestamps >= test_cutoff)
    return train_mask, test_mask


def inductive_subgraph_split(
    ds: GraphDataset,
    test_frac: float = 0.30,
    seed: int = 0,
    min_fold_labeled: int = 30,
) -> tuple[np.ndarray, np.ndarray]:
    """Split by connected component so test nodes share no edges with train.

    Stricter than temporal: removes ANY structural overlap between train and
    test. Useful as a stress test for whether the model generalizes to
    structurally novel regions of the graph, not just future timesteps.

    Degenerate-case guard:
        On many real graphs a single giant component holds >90% of labeled
        nodes (e.g., a fully-connected interaction graph). In that case
        component-based splitting cannot produce two non-trivial folds — one
        of train/test will end up with a handful of labeled nodes from
        peripheral components, which is not a useful evaluation.

        We raise ValueError when either fold ends up with fewer than
        `min_fold_labeled` labeled nodes. The orchestrator catches this and
        records "inductive protocol not applicable to this graph topology"
        rather than reporting a meaningless F1.

    On datasets with timestamps, the orchestrator skips this protocol by
    default — see orchestrator.md Step 2 — because the inductive split
    ignores the temporal axis and so cannot validate against the deployment
    distribution shift. If you call it explicitly on a temporal dataset, the
    result is a stress test, not a deploy estimate.
    """
    import networkx as nx

    g = nx.Graph()
    g.add_nodes_from(range(ds.n_nodes))
    g.add_edges_from(ds.edges.tolist())
    components = [list(c) for c in nx.connected_components(g)]
    rng = np.random.default_rng(seed)
    rng.shuffle(components)

    labeled = ds.labels != -1
    total_labeled = int(labeled.sum())
    test_target = total_labeled * test_frac

    train_nodes: set[int] = set()
    test_nodes: set[int] = set()
    test_so_far = 0
    for comp in components:
        comp_labeled = sum(labeled[n] for n in comp)
        if test_so_far < test_target:
            test_nodes.update(comp)
            test_so_far += comp_labeled
        else:
            train_nodes.update(comp)

    train_mask = np.array(
        [(i in train_nodes) and labeled[i] for i in range(ds.n_nodes)], dtype=bool
    )
    test_mask = np.array(
        [(i in test_nodes) and labeled[i] for i in range(ds.n_nodes)], dtype=bool
    )

    n_train = int(train_mask.sum())
    n_test = int(test_mask.sum())
    if n_train < min_fold_labeled or n_test < min_fold_labeled:
        largest_share = max((sum(labeled[n] for n in c) for c in components), default=0)
        raise ValueError(
            "inductive_subgraph_split is degenerate on this graph "
            f"(n_train_labeled={n_train}, n_test_labeled={n_test}, "
            f"largest_component_holds={largest_share}/{total_labeled} labeled nodes). "
            "The graph is dominated by a single connected component, so a "
            "component-based train/test split cannot produce non-trivial folds. "
            "Skip the inductive protocol on this dataset and rely on the "
            "temporal/transductive comparison instead."
        )

    return train_mask, test_mask
