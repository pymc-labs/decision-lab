"""Test that budget optimization uplift computation produces no NaN values.

Loads a real fitted model, runs budget_optimization with a small risk
appetite (10%), and verifies the printed uplift lines are finite and
contain no 'nan' strings.
"""

import re
import sys
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "docker"))

from pymc_marketing.mmm.multidimensional import MMM

from mmm_lib.analyze_model import (
    _add_original_scale_vars_if_needed,
    budget_optimization,
)

PROJECT_ROOT = Path(__file__).parents[3]
MODEL_PATH = PROJECT_ROOT / "sandbox" / "test-sessions" / "test-new-analysis-realphalistikk" / "best_model.nc"


@pytest.fixture(scope="module")
def fitted_mmm():
    """Load the pre-fitted MMM and reconstruct its dataframe."""
    mmm = MMM.load(str(MODEL_PATH))
    df = mmm.idata.fit_data.to_dataframe().reset_index()

    # Register original-scale contribution variables
    X = df.drop(columns=[mmm.target_column])
    y = df[mmm.target_column]
    mmm.build_model(X, y)

    original_scale_vars = [
        "channel_contribution", "control_contribution",
        "intercept_contribution", "y",
    ]
    if mmm.yearly_seasonality:
        original_scale_vars.append("yearly_seasonality_contribution")
    _add_original_scale_vars_if_needed(mmm, original_scale_vars)

    return mmm, df


@pytest.mark.skipif(
    not MODEL_PATH.exists(),
    reason=f"Model file not found: {MODEL_PATH}",
)
def test_budget_uplift_no_nan(fitted_mmm, tmp_path):
    """budget_optimization uplift lines must be finite with no NaN values."""
    mmm, df = fitted_mmm

    target_col = mmm.target_column
    date_col = mmm.date_column
    channel_columns = list(mmm.channel_columns)
    dims = list(mmm.dims) if mmm.dims else []

    # Capture stdout
    buf = StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        budget_optimization(
            mmm, df, tmp_path,
            target_col=target_col,
            date_col=date_col,
            channel_columns=channel_columns,
            dims=dims,
            pct=0.10,
            seed=42,
        )
    finally:
        sys.stdout = old_stdout

    output = buf.getvalue()

    # Verify expected uplift headers appear
    assert "Channel contribution uplift" in output, (
        "Missing 'Channel contribution uplift' in output"
    )
    assert "Total sales uplift" in output, (
        "Missing 'Total sales uplift' in output"
    )

    # Collect all uplift lines and verify no nan
    uplift_lines = [
        line for line in output.splitlines()
        if "uplift" in line.lower() and ("%" in line or "[" in line)
    ]
    assert len(uplift_lines) > 0, "No uplift result lines found"

    for line in uplift_lines:
        assert "nan" not in line.lower(), f"NaN found in uplift line: {line}"

    # Parse median values from uplift lines and check they are finite
    # Lines look like: "  Channel contribution uplift (East): +1.2% [+0.3%, +2.1%]"
    pct_pattern = re.compile(r"([+-]?\d+(?:\.\d+)?)%")
    for line in uplift_lines:
        matches = pct_pattern.findall(line)
        assert len(matches) > 0, f"No percentage values found in: {line}"
        for val_str in matches:
            val = float(val_str) / 100.0
            assert -1 < val < 1, (
                f"Uplift value {val} out of range (-1, 1) in: {line}"
            )
