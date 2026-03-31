"""Pytest fixtures for MMM decision-pack tests."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def multidim_market_data() -> pd.DataFrame:
    """Create synthetic multi-dimensional market data for testing.

    Returns
    -------
    pd.DataFrame
        Panel data with 52 weeks x 4 geos = 208 rows.
        Columns: date, geo, tv_spend, digital_spend, radio_spend,
                 price_index, competitor_spend, sales
    """
    np.random.seed(42)

    n_weeks = 52
    geos = ["North", "South", "East", "West"]
    n_geos = len(geos)

    # Create date range
    dates = pd.date_range(start="2023-01-01", periods=n_weeks, freq="W-MON")

    # Build panel data
    rows = []
    for geo in geos:
        # Geo-specific baseline
        geo_multiplier = {"North": 1.2, "South": 0.9, "East": 1.0, "West": 1.1}[geo]

        for i, date in enumerate(dates):
            # Seasonality component (yearly)
            week_of_year = date.isocalendar()[1]
            seasonality = 1 + 0.3 * np.sin(2 * np.pi * week_of_year / 52)

            # Channel spends with some geo variation
            tv_spend = max(0, 10000 + 5000 * np.random.randn()) * geo_multiplier
            digital_spend = max(0, 8000 + 3000 * np.random.randn()) * geo_multiplier
            radio_spend = max(0, 3000 + 1500 * np.random.randn()) * geo_multiplier

            # Controls
            price_index = 100 + 10 * np.random.randn()
            competitor_spend = max(0, 5000 + 2000 * np.random.randn())

            # Sales with effects from channels and controls
            base_sales = 50000 * geo_multiplier * seasonality
            tv_effect = 0.5 * np.sqrt(tv_spend)
            digital_effect = 0.8 * np.sqrt(digital_spend)
            radio_effect = 0.3 * np.sqrt(radio_spend)
            price_effect = -100 * (price_index - 100)
            competitor_effect = -0.1 * competitor_spend
            noise = 2000 * np.random.randn()

            sales = max(0, base_sales + tv_effect + digital_effect + radio_effect +
                       price_effect + competitor_effect + noise)

            rows.append({
                "date": date,
                "geo": geo,
                "tv_spend": tv_spend,
                "digital_spend": digital_spend,
                "radio_spend": radio_spend,
                "price_index": price_index,
                "competitor_spend": competitor_spend,
                "sales": sales,
            })

    df = pd.DataFrame(rows)
    return df


@pytest.fixture
def channel_columns() -> list:
    """Channel column names."""
    return ["tv_spend", "digital_spend", "radio_spend"]


@pytest.fixture
def control_columns() -> list:
    """Control column names."""
    return ["price_index", "competitor_spend"]
