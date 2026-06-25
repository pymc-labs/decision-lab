"""Dataset loading and the canonical GraphDataset container.

Convention for any dataset directory passed in via --data:
    <dir>/features.csv     node_id [, timestamp] , feat_1 ... feat_K
    <dir>/edges.csv        src_id, dst_id
    <dir>/labels.csv       node_id, label

Elliptic's distributed CSVs use different filenames; if those are present, we
auto-map them. Otherwise, the convention above is enforced.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class GraphDataset:
    """Container holding the four arrays an analysis needs.

    features:   (n_nodes, n_features) float32
    timestamps: (n_nodes,) int   — -1 if no temporal column present
    edges:      (n_edges, 2) int  — indices into features
    labels:     (n_nodes,) int   — 0=negative, 1=positive, -1=unknown
    node_ids:   (n_nodes,) object — original IDs (for traceability)
    feature_names: list[str]
    """

    features: np.ndarray
    timestamps: np.ndarray
    edges: np.ndarray
    labels: np.ndarray
    node_ids: np.ndarray
    feature_names: list[str]

    @property
    def n_nodes(self) -> int:
        return self.features.shape[0]

    @property
    def n_edges(self) -> int:
        return self.edges.shape[0]

    @property
    def n_features(self) -> int:
        return self.features.shape[1]

    @property
    def has_timestamps(self) -> bool:
        return bool((self.timestamps >= 0).any())

    @property
    def labeled_mask(self) -> np.ndarray:
        return self.labels != -1


def _detect_files(data_dir: Path) -> tuple[Path, Path, Path]:
    """Find the three CSVs, accepting Elliptic's native names as aliases."""
    candidates = {
        "features": ["features.csv", "elliptic_txs_features.csv", "txs_features.csv"],
        "edges": ["edges.csv", "elliptic_txs_edgelist.csv", "txs_edgelist.csv"],
        "labels": ["labels.csv", "elliptic_txs_classes.csv", "txs_classes.csv"],
    }
    found = {}
    for key, names in candidates.items():
        for n in names:
            p = data_dir / n
            if p.exists():
                found[key] = p
                break
        if key not in found:
            raise FileNotFoundError(
                f"Could not find {key} CSV in {data_dir}. "
                f"Looked for: {names}"
            )
    return found["features"], found["edges"], found["labels"]


def _parse_label(value) -> int:
    """Map any label encoding to {-1, 0, 1}.

    We standardize to {1=positive, 0=negative, -1=unknown}.
    Elliptic's {1=illicit, 2=licit, "unknown"} convention is accepted as one
    of several supported aliases (see below); the standardized output is
    domain-agnostic.
    """
    s = str(value).strip().lower()
    if s in {"1", "illicit", "positive", "true"}:
        return 1
    if s in {"2", "licit", "negative", "false", "0"}:
        return 0
    return -1


def load_dataset(data_dir: str | Path) -> GraphDataset:
    """Load a graph dataset from a directory of CSVs."""
    data_dir = Path(data_dir)
    features_path, edges_path, labels_path = _detect_files(data_dir)

    feat_df = pd.read_csv(features_path, header=None, low_memory=False)
    # Elliptic has no header; first col is node_id, second is timestamp.
    # If a header is present (custom datasets), we'll handle that too.
    if not np.issubdtype(feat_df.iloc[0, 0].__class__, np.number):
        # Looks like header row — re-read with header=0
        feat_df = pd.read_csv(features_path, low_memory=False)

    node_ids = feat_df.iloc[:, 0].to_numpy()
    # Heuristic: if column 1 has small integer range (1..100), treat as timestep
    second_col = feat_df.iloc[:, 1].to_numpy()
    if (
        np.issubdtype(second_col.dtype, np.number)
        and second_col.min() >= 0
        and second_col.max() < 1000
        and len(np.unique(second_col)) < 200
    ):
        timestamps = second_col.astype(np.int64)
        features = feat_df.iloc[:, 2:].to_numpy(dtype=np.float32)
        feature_names = [f"f{i}" for i in range(features.shape[1])]
    else:
        timestamps = np.full(len(feat_df), -1, dtype=np.int64)
        features = feat_df.iloc[:, 1:].to_numpy(dtype=np.float32)
        feature_names = [f"f{i}" for i in range(features.shape[1])]

    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}

    edges_df = pd.read_csv(edges_path)
    if edges_df.shape[1] != 2:
        edges_df = pd.read_csv(edges_path, header=None)
    edges_src = edges_df.iloc[:, 0].to_numpy()
    edges_dst = edges_df.iloc[:, 1].to_numpy()
    edges = np.column_stack([
        [id_to_idx.get(s, -1) for s in edges_src],
        [id_to_idx.get(d, -1) for d in edges_dst],
    ])
    keep = (edges[:, 0] >= 0) & (edges[:, 1] >= 0)
    edges = edges[keep].astype(np.int64)

    labels_df = pd.read_csv(labels_path)
    if labels_df.shape[1] != 2 or labels_df.columns[0].startswith("Unnamed"):
        labels_df = pd.read_csv(labels_path, header=None)
    label_map = {row[0]: _parse_label(row[1]) for row in labels_df.itertuples(index=False)}
    labels = np.array([label_map.get(nid, -1) for nid in node_ids], dtype=np.int64)

    return GraphDataset(
        features=features,
        timestamps=timestamps,
        edges=edges,
        labels=labels,
        node_ids=node_ids,
        feature_names=feature_names,
    )
