"""Test that budget optimization correctly aligns channels by name, not position.

The optimizer returns allocations in xarray's alphabetical coordinate order.
The reporting code must use .sel(channel=ch) — NOT positional .values — to
map allocations back to the original channel_columns order.

Regression test for the bug where Social-Media's allocation was labelled as
Radio, producing "+1022%" when the user asked for ±5% bounds.
"""

import re
import sys
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "docker"))

from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation
from pymc_marketing.mmm.multidimensional import MMM
from pymc_extras.prior import Prior

from mmm_lib import prepare_mmm_data
from mmm_lib.analyze_model import (
    _add_original_scale_vars_if_needed,
    budget_optimization,
    compute_contribution_split,
)


@pytest.fixture(scope="module")
def fitted_budget_mmm():
    """Create and fit a small MMM with non-alphabetical channel order.

    Channel order: tv_spend, digital_spend, radio_spend
    Alphabetical:  digital_spend, radio_spend, tv_spend

    This mismatch is what triggers the bug if positional .values is used.
    """
    np.random.seed(42)

    n_weeks = 52
    geos = ["East", "West"]
    rows = []
    for geo in geos:
        geo_mult = {"East": 1.0, "West": 1.1}[geo]
        for i, date in enumerate(
            pd.date_range("2023-01-01", periods=n_weeks, freq="W-MON")
        ):
            tv = max(0, 10000 + 3000 * np.random.randn()) * geo_mult
            digital = max(0, 8000 + 2000 * np.random.randn()) * geo_mult
            radio = max(0, 3000 + 1000 * np.random.randn()) * geo_mult
            base = 50000 * geo_mult
            sales = max(0, base + 0.5 * np.sqrt(tv) + 0.8 * np.sqrt(digital)
                        + 0.3 * np.sqrt(radio) + 2000 * np.random.randn())
            rows.append({
                "date": date, "geo": geo,
                "tv_spend": tv, "digital_spend": digital, "radio_spend": radio,
                "sales": sales,
            })

    df = pd.DataFrame(rows)
    channel_columns = ["tv_spend", "digital_spend", "radio_spend"]

    adstock = GeometricAdstock(
        l_max=4,
        priors={
            "alpha": Prior("Beta", alpha=2, beta=5, dims=("channel", "geo"))
        },
    )
    saturation = LogisticSaturation(
        priors={
            "lam": Prior("Gamma", mu=1, sigma=0.5, dims=("channel", "geo")),
            "beta": Prior("HalfNormal", sigma=2, dims=("channel", "geo")),
        },
    )

    mmm = MMM(
        date_column="date",
        target_column="sales",
        channel_columns=channel_columns,
        dims=("geo",),
        adstock=adstock,
        saturation=saturation,
        yearly_seasonality=2,
    )

    X, y = prepare_mmm_data(df, date_column="date", y_column="sales")
    mmm.fit(
        X=X, y=y,
        nuts_sampler="numpyro",
        draws=50, tune=50, chains=2,
        target_accept=0.8, random_seed=42,
    )

    # Register original-scale variables needed by budget_optimization
    original_scale_vars = [
        "channel_contribution", "control_contribution",
        "intercept_contribution", "y",
    ]
    if mmm.yearly_seasonality:
        original_scale_vars.append("yearly_seasonality_contribution")
    _add_original_scale_vars_if_needed(mmm, original_scale_vars)

    return mmm, df, channel_columns


@pytest.mark.slow
def test_budget_allocation_respects_bounds(fitted_budget_mmm, tmp_path):
    """Every channel's % change must be within [-pct, +pct].

    With pct=0.05 (±5%), no channel should move more than ~5%.
    The old bug caused Radio to show +1022% because Social-Media's
    allocation was mislabelled as Radio.
    """
    mmm, df, channel_columns = fitted_budget_mmm
    pct = 0.05

    buf = StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        budget_optimization(
            mmm, df, tmp_path,
            target_col="sales",
            date_col="date",
            channel_columns=channel_columns,
            dims=["geo"],
            pct=pct,
            seed=42,
        )
    finally:
        sys.stdout = old_stdout

    output = buf.getvalue()

    # Parse multipliers from output
    # Lines like: "    tv_spend: 1.050"
    multiplier_pattern = re.compile(r"^\s+(\S+):\s+([\d.]+)\s*$", re.MULTILINE)
    multipliers = {}
    in_multipliers = False
    for line in output.splitlines():
        if "Channel multipliers" in line:
            in_multipliers = True
            continue
        if in_multipliers:
            m = multiplier_pattern.match(line)
            if m:
                multipliers[m.group(1)] = float(m.group(2))
            elif line.strip() and not line.strip().startswith("Channel"):
                # End of multipliers section
                in_multipliers = False

    assert len(multipliers) > 0, (
        f"No channel multipliers found in output:\n{output}"
    )

    # Parse percentage changes from "Reallocation" lines
    # Lines like: "    tv_spend: +5%"  or  "    radio_spend: -5%"
    pct_pattern = re.compile(r"^\s+(\S+):\s+([+-]\d+)%\s*$", re.MULTILINE)
    pct_changes = {}
    for m in pct_pattern.finditer(output):
        pct_changes[m.group(1)] = int(m.group(2))

    # Core assertion: no channel exceeds the requested bounds
    # Allow a small tolerance (1%) for numerical precision
    tolerance = pct + 0.02  # 5% + 2% tolerance = 7%
    for ch, change in pct_changes.items():
        assert abs(change) <= tolerance * 100, (
            f"Channel {ch} moved {change}% but bounds were ±{pct:.0%}. "
            f"This suggests channel allocation mislabelling.\n"
            f"Full output:\n{output}"
        )

    # Also verify multipliers are close to 1.0 (within bounds)
    for ch, mult in multipliers.items():
        # Share-based multiplier should be near 1.0 for tight bounds
        assert 0.5 < mult < 2.0, (
            f"Channel {ch} multiplier {mult} is unreasonable for ±{pct:.0%} bounds. "
            f"This suggests channel allocation mislabelling.\n"
            f"Full output:\n{output}"
        )


@pytest.mark.slow
def test_budget_channel_order_matches_input(fitted_budget_mmm, tmp_path):
    """The reported channel order must match channel_columns, not alphabetical."""
    mmm, df, channel_columns = fitted_budget_mmm

    buf = StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        budget_optimization(
            mmm, df, tmp_path,
            target_col="sales",
            date_col="date",
            channel_columns=channel_columns,
            dims=["geo"],
            pct=0.10,
            seed=42,
        )
    finally:
        sys.stdout = old_stdout

    output = buf.getvalue()

    # Extract channel names in order from multipliers section
    reported_channels = []
    in_multipliers = False
    for line in output.splitlines():
        if "Channel multipliers" in line:
            in_multipliers = True
            continue
        if in_multipliers:
            m = re.match(r"^\s+(\S+):\s+[\d.]+\s*$", line)
            if m:
                reported_channels.append(m.group(1))
            elif line.strip() and ":" not in line:
                break

    assert reported_channels == channel_columns, (
        f"Reported channels {reported_channels} != input order {channel_columns}. "
        f"Channels should be reported in input order, not alphabetical."
    )


@pytest.mark.slow
def test_budget_uplift_is_reasonable(fitted_budget_mmm, tmp_path):
    """With ±5% bounds, total uplift should be modest (< 20%), not 47%."""
    mmm, df, channel_columns = fitted_budget_mmm
    pct = 0.05

    buf = StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        budget_optimization(
            mmm, df, tmp_path,
            target_col="sales",
            date_col="date",
            channel_columns=channel_columns,
            dims=["geo"],
            pct=pct,
            seed=42,
        )
    finally:
        sys.stdout = old_stdout

    output = buf.getvalue()

    # Find "Total sales uplift: +X.X% [..."
    m = re.search(r"Total sales uplift:\s+([+-]?\d+(?:\.\d+)?)%", output)
    assert m is not None, f"No 'Total sales uplift' found in output:\n{output}"

    uplift = float(m.group(1))
    # With ±5% reallocation, uplift should be modest
    assert abs(uplift) < 20, (
        f"Total sales uplift is {uplift}% for ±{pct:.0%} bounds — "
        f"unreasonably large. The old bug produced +47% uplift.\n"
        f"Full output:\n{output}"
    )


@pytest.mark.slow
def test_contribution_split_baseline_not_near_zero(fitted_budget_mmm, tmp_path):
    """Baseline (intercept) should be a meaningful share of total revenue.

    Regression test: intercept_contribution has dims (chain, draw, geo) with
    no date dimension, while channel contributions sum over all dates. The old
    code did a raw .sum() on both, making intercept ~0.3% when it should be
    ~30-60%. The fix broadcasts missing dims (date, geo) before comparing.
    """
    mmm, df, channel_columns = fitted_budget_mmm

    split = compute_contribution_split(mmm, dims=["geo"])

    assert split is not None, "channel_contributions returned None"
    assert "baseline_pct" in split, f"Missing baseline_pct in {split}"
    assert "channels_pct" in split, f"Missing channels_pct in {split}"

    # Baseline should be meaningful (>5%) for synthetic data with a real intercept.
    # The old bug produced ~0.3%.
    assert split["baseline_pct"] > 0.05, (
        f"Baseline is {split['baseline_pct']:.1%} — suspiciously low. "
        f"Likely a dim-broadcasting bug in contribution split.\n"
        f"Full split: {split}"
    )

    # All components should sum to ~100%
    total = sum(split.values())
    assert 0.95 < total < 1.05, (
        f"Contribution split sums to {total:.1%}, expected ~100%.\n"
        f"Full split: {split}"
    )


@pytest.mark.slow
def test_contribution_split_no_dim_model(tmp_path):
    """Contribution split works for non-dimensional (single-geo) models.

    The intercept has dims (chain, draw) — no date, no geo. Must still
    be broadcast correctly against channels with dims (chain, draw, date, channel).
    """
    np.random.seed(123)
    n_weeks = 52
    rows = []
    for i, date in enumerate(
        pd.date_range("2023-01-01", periods=n_weeks, freq="W-MON")
    ):
        tv = max(0, 10000 + 3000 * np.random.randn())
        digital = max(0, 8000 + 2000 * np.random.randn())
        base = 50000
        sales = max(0, base + 0.5 * np.sqrt(tv) + 0.8 * np.sqrt(digital)
                    + 2000 * np.random.randn())
        rows.append({"date": date, "tv_spend": tv, "digital_spend": digital, "sales": sales})

    df = pd.DataFrame(rows)

    adstock = GeometricAdstock(
        l_max=4,
        priors={"alpha": Prior("Beta", alpha=2, beta=5, dims="channel")},
    )
    saturation = LogisticSaturation(
        priors={
            "lam": Prior("Gamma", mu=1, sigma=0.5, dims="channel"),
            "beta": Prior("HalfNormal", sigma=2, dims="channel"),
        },
    )

    mmm = MMM(
        date_column="date",
        target_column="sales",
        channel_columns=["tv_spend", "digital_spend"],
        adstock=adstock,
        saturation=saturation,
        yearly_seasonality=2,
    )

    X, y = prepare_mmm_data(df, date_column="date", y_column="sales")
    mmm.fit(
        X=X, y=y,
        nuts_sampler="numpyro",
        draws=50, tune=50, chains=2,
        target_accept=0.8, random_seed=123,
    )

    original_scale_vars = ["channel_contribution", "intercept_contribution", "y"]
    if mmm.yearly_seasonality:
        original_scale_vars.append("yearly_seasonality_contribution")
    _add_original_scale_vars_if_needed(mmm, original_scale_vars)

    split = compute_contribution_split(mmm, dims=[])

    assert split is not None
    assert split["baseline_pct"] > 0.05, (
        f"Baseline is {split['baseline_pct']:.1%} for no-dim model — "
        f"intercept broadcast bug.\nFull split: {split}"
    )
