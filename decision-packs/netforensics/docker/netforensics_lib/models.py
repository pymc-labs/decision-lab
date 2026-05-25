"""Three model trainers with identical APIs.

Every trainer returns the same dict from eval.evaluate(), so they can be
fanned out in parallel and their outputs compared cell-by-cell.

Key design point: GNN trainers accept an optional `training_edges` argument.
When None, all edges are visible during training (the "transductive leakage"
regime — what the published literature did wrong). When set, training uses
only those edges and evaluation falls back to the full edge set. This makes
the leakage trap explicit at the API surface.
"""
from __future__ import annotations

import time

import numpy as np

from .eval import evaluate
from .loader import GraphDataset


def _select_features(
    ds: GraphDataset,
    feature_mode: str,
    n_raw_features: int | None = None,
) -> np.ndarray:
    """feature_mode ∈ {'all', 'raw_local', 'topology_only'}.

    'raw_local' takes the first n_raw_features columns (for Elliptic: 94,
    which are per-transaction features without 1-hop aggregates).
    'topology_only' computes degree, in-degree, out-degree, PageRank,
    and clustering — ignoring the provided features entirely.
    """
    if feature_mode == "all":
        return ds.features
    if feature_mode == "raw_local":
        if n_raw_features is None:
            raise ValueError("raw_local feature_mode requires n_raw_features")
        return ds.features[:, :n_raw_features]
    if feature_mode == "topology_only":
        return _compute_topology_features(ds)
    raise ValueError(f"unknown feature_mode: {feature_mode!r}")


def _compute_topology_features(ds: GraphDataset) -> np.ndarray:
    """Compute graph-derived features so we can train a model that uses ONLY
    the graph (no provided features). If the model can't predict from these,
    the graph carries little signal for the task.
    """
    import networkx as nx

    g = nx.DiGraph()
    g.add_nodes_from(range(ds.n_nodes))
    g.add_edges_from(ds.edges.tolist())

    in_deg = np.array([g.in_degree(i) for i in range(ds.n_nodes)], dtype=np.float32)
    out_deg = np.array([g.out_degree(i) for i in range(ds.n_nodes)], dtype=np.float32)
    pr = nx.pagerank(g, max_iter=50, tol=1e-4)
    pagerank = np.array([pr.get(i, 0.0) for i in range(ds.n_nodes)], dtype=np.float32)
    ug = g.to_undirected()
    clust = nx.clustering(ug)
    clustering = np.array([clust.get(i, 0.0) for i in range(ds.n_nodes)], dtype=np.float32)

    return np.column_stack([
        in_deg, out_deg, in_deg + out_deg, pagerank, clustering,
        np.log1p(in_deg), np.log1p(out_deg),
    ]).astype(np.float32)


def train_xgboost(
    ds: GraphDataset,
    train_mask: np.ndarray,
    test_mask: np.ndarray,
    *,
    seed: int = 0,
    feature_mode: str = "all",
    n_raw_features: int | None = None,
    n_estimators: int = 200,
    max_depth: int = 6,
    **_unused,
) -> dict:
    """XGBoost on the chosen feature regime — the no-graph baseline."""
    from xgboost import XGBClassifier

    X = _select_features(ds, feature_mode=feature_mode, n_raw_features=n_raw_features)
    y = ds.labels

    pos = int(((y == 1) & train_mask).sum())
    neg = int(((y == 0) & train_mask).sum())
    scale_pos_weight = max(1.0, neg / max(pos, 1))

    t0 = time.time()
    clf = XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=0.1,
        objective="binary:logistic",
        scale_pos_weight=scale_pos_weight,
        random_state=seed,
        n_jobs=-1,
        tree_method="hist",
        eval_metric="aucpr",
    )
    clf.fit(X[train_mask], y[train_mask])
    y_score = clf.predict_proba(X[test_mask])[:, 1]
    runtime = time.time() - t0

    out = evaluate(y[test_mask], y_score)
    out.update(
        model="xgboost",
        feature_mode=feature_mode,
        n_features_used=X.shape[1],
        runtime_s=runtime,
        seed=seed,
    )
    return out


def _gnn_train(
    ds: GraphDataset,
    train_mask: np.ndarray,
    test_mask: np.ndarray,
    *,
    model_cls: str,  # 'GCN' | 'GraphSAGE'
    seed: int = 0,
    feature_mode: str = "all",
    n_raw_features: int | None = None,
    training_edges: np.ndarray | None = None,
    n_epochs: int = 50,
    hidden_channels: int = 64,
    lr: float = 0.01,
) -> dict:
    """Shared training loop for GCN and GraphSAGE."""
    import torch
    import torch.nn.functional as F
    from torch_geometric.data import Data
    from torch_geometric.nn import GCNConv, SAGEConv

    torch.manual_seed(seed)
    np.random.seed(seed)

    X = _select_features(ds, feature_mode=feature_mode, n_raw_features=n_raw_features)
    y = ds.labels

    train_edges = training_edges if training_edges is not None else ds.edges
    train_edge_index = torch.tensor(train_edges.T, dtype=torch.long)
    full_edge_index = torch.tensor(ds.edges.T, dtype=torch.long)

    x = torch.tensor(X, dtype=torch.float32)
    y_t = torch.tensor(y, dtype=torch.long)
    train_mask_t = torch.tensor(train_mask, dtype=torch.bool)
    test_mask_t = torch.tensor(test_mask, dtype=torch.bool)

    class Net(torch.nn.Module):
        def __init__(self, in_channels, hidden, out):
            super().__init__()
            conv = GCNConv if model_cls == "GCN" else SAGEConv
            self.c1 = conv(in_channels, hidden)
            self.c2 = conv(hidden, hidden)
            self.lin = torch.nn.Linear(hidden, out)

        def forward(self, x, edge_index):
            h = F.relu(self.c1(x, edge_index))
            h = F.dropout(h, p=0.3, training=self.training)
            h = F.relu(self.c2(h, edge_index))
            return self.lin(h)

    net = Net(x.shape[1], hidden_channels, 2)
    pos = int(((y == 1) & train_mask).sum())
    neg = int(((y == 0) & train_mask).sum())
    class_weight = torch.tensor([1.0, max(1.0, neg / max(pos, 1))], dtype=torch.float32)
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=5e-4)

    t0 = time.time()
    for _ in range(n_epochs):
        net.train()
        opt.zero_grad()
        logits = net(x, train_edge_index)
        loss = F.cross_entropy(logits[train_mask_t], y_t[train_mask_t], weight=class_weight)
        loss.backward()
        opt.step()
    runtime = time.time() - t0

    net.eval()
    with torch.no_grad():
        logits = net(x, full_edge_index)
        y_score = F.softmax(logits, dim=-1)[:, 1].numpy()

    out = evaluate(y[test_mask], y_score[test_mask])
    out.update(
        model=model_cls.lower(),
        feature_mode=feature_mode,
        n_features_used=X.shape[1],
        n_epochs=n_epochs,
        runtime_s=runtime,
        edges_visible_at_training=(
            "all" if training_edges is None else "train_only"
        ),
        seed=seed,
    )
    return out


def train_gcn(ds, train_mask, test_mask, **kwargs) -> dict:
    return _gnn_train(ds, train_mask, test_mask, model_cls="GCN", **kwargs)


def train_graphsage(ds, train_mask, test_mask, **kwargs) -> dict:
    return _gnn_train(ds, train_mask, test_mask, model_cls="GraphSAGE", **kwargs)
