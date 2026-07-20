"""Model trainer tests. XGBoost runs everywhere; GNN tests are skipped when
torch / torch-geometric are not installed (they are heavy, CPU-only deps that
live in the pack's Docker image)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from conftest import PACK_ROOT, build_dataset, write_csv_dir

xgboost = pytest.importorskip("xgboost")

from netforensics_lib.models import _select_features, train_xgboost  # noqa: E402
from netforensics_lib.splits import transductive_split  # noqa: E402


def test_xgboost_end_to_end_learns_planted_signal():
    ds = build_dataset(n_nodes=300, seed=7)
    train_mask, test_mask = transductive_split(ds, seed=0)
    result = train_xgboost(ds, train_mask, test_mask, seed=0)
    assert result["model"] == "xgboost"
    assert result["feature_mode"] == "all"
    assert result["n_features_used"] == ds.n_features
    # Features carry a planted +1.5 sigma shift — must beat coin-flip F1.
    assert result["f1_positive"] > 0.6
    assert 0.0 <= result["auroc"] <= 1.0


def test_feature_modes_select_expected_columns():
    ds = build_dataset(n_nodes=100, seed=8)
    assert _select_features(ds, "all").shape[1] == ds.n_features
    assert _select_features(ds, "raw_local", n_raw_features=2).shape[1] == 2
    # topology features: in/out/total degree, pagerank, clustering, 2x log deg
    assert _select_features(ds, "topology_only").shape[1] == 7
    with pytest.raises(ValueError, match="n_raw_features"):
        _select_features(ds, "raw_local")
    with pytest.raises(ValueError, match="unknown feature_mode"):
        _select_features(ds, "bogus")


def _run_cli(module: str, *args: str, data_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(PACK_ROOT / "docker"))
    return subprocess.run(
        [sys.executable, "-m", module, "--data", str(data_dir), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_train_cli_smoke(tmp_path):
    data_dir, _ = write_csv_dir(tmp_path, n_nodes=60, n_features=4)
    result = _run_cli(
        "netforensics_lib.train_cli",
        "--model", "xgboost", "--split", "transductive",
        data_dir=data_dir,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["model"] == "xgboost"
    assert payload["split"] == "transductive"
    assert "f1_positive" in payload


def test_train_cli_reports_inapplicable_split(tmp_path):
    data_dir, _ = write_csv_dir(
        tmp_path, n_nodes=60, n_features=4, with_timestamps=False
    )
    result = _run_cli(
        "netforensics_lib.train_cli",
        "--model", "xgboost", "--split", "temporal",
        data_dir=data_dir,
    )
    # Contract with the agent: exit 3 + JSON error, never a fabricated number.
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["error"] == "split_not_applicable"


def test_gnn_end_to_end_smoke():
    pytest.importorskip("torch")
    pytest.importorskip("torch_geometric")
    from netforensics_lib.models import train_gcn

    ds = build_dataset(n_nodes=120, seed=9)
    train_mask, test_mask = transductive_split(ds, seed=0)
    result = train_gcn(ds, train_mask, test_mask, seed=0, n_epochs=3)
    assert result["model"] == "gcn"
    assert 0.0 <= result["f1_positive"] <= 1.0
    assert result["edges_visible_at_training"] == "all"

    strict = np.isin(ds.edges, np.where(train_mask)[0]).all(axis=1)
    result_strict = train_gcn(
        ds, train_mask, test_mask, seed=0, n_epochs=3,
        training_edges=ds.edges[strict],
    )
    assert result_strict["edges_visible_at_training"] == "train_only"
