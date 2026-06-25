"""netforensics_lib — graph dataset loading, splitting, modeling, and evaluation primitives.

Designed for binary node-classification on any node-feature + edge-list dataset:
  - features.csv:  node_id, [timestamp], feat_1, ..., feat_K
  - edges.csv:     src_id, dst_id
  - labels.csv:    node_id, label  (binary; "unknown" rows ignored at eval time)

All three split functions (transductive/temporal/inductive) take and return
the same shape: (train_mask, test_mask) over labeled rows of features.

All three model trainers (XGBoost, GCN, GraphSAGE) accept the same arguments
and return the same dict: {f1_positive, precision_at_k, auroc, predictions, runtime_s}.
"""

from .loader import load_dataset, GraphDataset
from .splits import transductive_split, temporal_split, inductive_subgraph_split
from .models import train_xgboost, train_gcn, train_graphsage
from .eval import evaluate, edge_shuffle_ablation, precision_at_k
from .inspect_graph import inspect

__all__ = [
    "load_dataset",
    "GraphDataset",
    "transductive_split",
    "temporal_split",
    "inductive_subgraph_split",
    "train_xgboost",
    "train_gcn",
    "train_graphsage",
    "evaluate",
    "edge_shuffle_ablation",
    "precision_at_k",
    "inspect",
]
