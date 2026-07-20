"""Loader tests: header sniffing, filename aliases, label parsing, timestamps.

The headerless-convention tests assert that NO row is lost — the regression
here was pandas consuming the first edge / first label as a header row.
"""
import numpy as np
import pytest

from conftest import write_csv_dir
from netforensics_lib.loader import _parse_label, load_dataset


def test_headerless_convention_loses_no_rows(tmp_path):
    data_dir, truth = write_csv_dir(tmp_path, with_header=False)
    ds = load_dataset(data_dir)

    assert ds.n_nodes == 30
    assert ds.n_edges == len(truth["edges"])
    # Row 0 is labeled positive in the fixture — it must not be eaten.
    assert ds.labels[0] == 1
    expected = {"1": 1, "2": 0, "unknown": -1}
    for i, raw in truth["labels"].items():
        assert ds.labels[i] == expected[raw], f"node {i}"


def test_headered_files_load_identically(tmp_path):
    plain_dir, truth = write_csv_dir(tmp_path / "plain", with_header=False)
    headered_dir, _ = write_csv_dir(tmp_path / "headered", with_header=True)

    ds_plain = load_dataset(plain_dir)
    ds_headered = load_dataset(headered_dir)

    assert ds_plain.n_nodes == ds_headered.n_nodes
    assert ds_plain.n_edges == ds_headered.n_edges == len(truth["edges"])
    np.testing.assert_array_equal(ds_plain.labels, ds_headered.labels)
    np.testing.assert_array_equal(ds_plain.edges, ds_headered.edges)


def test_elliptic_filename_aliases(tmp_path):
    data_dir, truth = write_csv_dir(
        tmp_path,
        with_header=True,
        filenames=(
            "elliptic_txs_features.csv",
            "elliptic_txs_edgelist.csv",
            "elliptic_txs_classes.csv",
        ),
    )
    ds = load_dataset(data_dir)
    assert ds.n_nodes == 30
    assert ds.n_edges == len(truth["edges"])


def test_missing_file_raises(tmp_path):
    data_dir, _ = write_csv_dir(tmp_path)
    (data_dir / "labels.csv").unlink()
    with pytest.raises(FileNotFoundError):
        load_dataset(data_dir)


def test_label_aliases():
    assert _parse_label("1") == 1
    assert _parse_label("illicit") == 1
    assert _parse_label("Positive") == 1
    assert _parse_label(True) == 1
    assert _parse_label("2") == 0
    assert _parse_label("licit") == 0
    assert _parse_label(0) == 0
    assert _parse_label("false") == 0
    assert _parse_label("unknown") == -1
    assert _parse_label("") == -1


def test_timestamp_column_detected(tmp_path):
    data_dir, _ = write_csv_dir(tmp_path, with_timestamps=True, n_features=4)
    ds = load_dataset(data_dir)
    assert ds.has_timestamps
    assert ds.n_features == 4
    assert set(np.unique(ds.timestamps)) <= set(range(1, 6))


def test_no_timestamp_column_treated_as_feature(tmp_path):
    data_dir, _ = write_csv_dir(tmp_path, with_timestamps=False, n_features=4)
    ds = load_dataset(data_dir)
    # First feature column is gaussian floats — must not be read as timesteps.
    assert not ds.has_timestamps
    assert ds.n_features == 4


def test_edges_with_unknown_ids_dropped(tmp_path):
    data_dir, truth = write_csv_dir(tmp_path)
    with (data_dir / "edges.csv").open("a") as f:
        f.write("9999,0\n0,12345\n")
    ds = load_dataset(data_dir)
    assert ds.n_edges == len(truth["edges"])
