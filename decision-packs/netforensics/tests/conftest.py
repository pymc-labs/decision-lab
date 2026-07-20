"""Shared fixtures for netforensics_lib tests.

The library lives in the pack's docker/ directory (shipped into the image at
/opt); for testing we import it straight from there.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT / "docker"))

from netforensics_lib.loader import GraphDataset  # noqa: E402


def build_dataset(
    n_nodes: int = 80,
    n_features: int = 6,
    n_timesteps: int = 6,
    seed: int = 0,
    with_timestamps: bool = True,
    edges: np.ndarray | None = None,
) -> GraphDataset:
    """Small deterministic dataset with informative features.

    Labels: ~40% positive, ~40% negative, ~20% unknown. Positive-class rows
    get a mean shift on the first two features so XGBoost has signal.
    """
    rng = np.random.default_rng(seed)
    labels = rng.choice([1, 0, -1], size=n_nodes, p=[0.4, 0.4, 0.2])
    features = rng.normal(0, 1, size=(n_nodes, n_features)).astype(np.float32)
    features[labels == 1, :2] += 1.5
    if with_timestamps:
        timestamps = rng.integers(1, n_timesteps + 1, size=n_nodes).astype(np.int64)
    else:
        timestamps = np.full(n_nodes, -1, dtype=np.int64)
    if edges is None:
        src = rng.integers(0, n_nodes, size=3 * n_nodes)
        dst = rng.integers(0, n_nodes, size=3 * n_nodes)
        edges = np.column_stack([src, dst]).astype(np.int64)
    return GraphDataset(
        features=features,
        timestamps=timestamps,
        edges=edges,
        labels=labels.astype(np.int64),
        node_ids=np.arange(n_nodes),
        feature_names=[f"f{i}" for i in range(n_features)],
    )


@pytest.fixture
def dataset() -> GraphDataset:
    return build_dataset()


@pytest.fixture
def dataset_no_timestamps() -> GraphDataset:
    return build_dataset(with_timestamps=False)


def write_csv_dir(
    tmp_path: Path,
    n_nodes: int = 30,
    n_features: int = 4,
    with_header: bool = False,
    with_timestamps: bool = True,
    filenames: tuple[str, str, str] = ("features.csv", "edges.csv", "labels.csv"),
    label_values: tuple[str, str, str] = ("1", "2", "unknown"),
) -> tuple[Path, dict]:
    """Write a dataset directory in the pack's CSV convention.

    Returns the directory and the ground truth (edges list, label per node).
    Node i gets label cycle [pos, neg, unknown, pos, ...] so row 0 is ALWAYS
    labeled — this is what catches header-sniffing bugs that eat row 0.
    """
    rng = np.random.default_rng(1)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    pos, neg, unk = label_values

    features_lines = []
    if with_header:
        cols = ",".join(f"f{i}" for i in range(n_features))
        prefix = "id,ts," if with_timestamps else "id,"
        features_lines.append(prefix + cols)
    for i in range(n_nodes):
        feats = ",".join(f"{v:.4f}" for v in rng.normal(0, 1, n_features))
        ts_part = f",{(i % 5) + 1}" if with_timestamps else ""
        features_lines.append(f"{i}{ts_part},{feats}")
    (data_dir / filenames[0]).write_text("\n".join(features_lines) + "\n")

    edges = [(i, (i + 1) % n_nodes) for i in range(n_nodes)]
    edge_lines = ["src,dst"] if with_header else []
    edge_lines += [f"{s},{d}" for s, d in edges]
    (data_dir / filenames[1]).write_text("\n".join(edge_lines) + "\n")

    cycle = [pos, neg, unk]
    labels = {i: cycle[i % 3] for i in range(n_nodes)}
    label_lines = ["id,label"] if with_header else []
    label_lines += [f"{i},{v}" for i, v in labels.items()]
    (data_dir / filenames[2]).write_text("\n".join(label_lines) + "\n")

    return data_dir, {"edges": edges, "labels": labels}
