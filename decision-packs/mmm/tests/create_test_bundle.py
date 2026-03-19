#!/usr/bin/env python
"""Create a minimal model_to_fit.pkl bundle for testing Coiled fitting.

This script creates a small MMM model with synthetic data that can be used
to test the fit_model_coiled.py CLI without requiring real data.

Usage:
    conda activate dlab
    python create_test_bundle.py [output_path]

The bundle will be saved to the specified path (default: test_model_to_fit.pkl)

Note: Do NOT set PYTENSOR_FLAGS="cxx=" - C++ compilation is faster for deterministics.
"""

import sys
from pathlib import Path

import cloudpickle
import numpy as np
import pandas as pd

from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation
from pymc_marketing.mmm.multidimensional import MMM
from pymc_extras.prior import Prior


def create_synthetic_data(n_weeks: int = 20) -> pd.DataFrame:
    """Create minimal synthetic MMM data.

    Parameters
    ----------
    n_weeks : int
        Number of weeks of data.

    Returns
    -------
    pd.DataFrame
        Synthetic data with date, channels, control, and sales columns.
    """
    np.random.seed(42)
    dates = pd.date_range(start="2024-01-01", periods=n_weeks, freq="W-MON")

    # Simple channel spends
    tv_spend = np.maximum(0, 5000 + 2000 * np.random.randn(n_weeks))
    digital_spend = np.maximum(0, 3000 + 1000 * np.random.randn(n_weeks))

    # Control variable
    price_index = 100 + 5 * np.random.randn(n_weeks)

    # Sales with simple effects
    base = 10000
    tv_effect = 0.5 * np.sqrt(tv_spend)
    digital_effect = 0.8 * np.sqrt(digital_spend)
    price_effect = -50 * (price_index - 100)
    noise = 500 * np.random.randn(n_weeks)
    sales = np.maximum(0, base + tv_effect + digital_effect + price_effect + noise)

    return pd.DataFrame({
        "date": dates,
        "tv_spend": tv_spend,
        "digital_spend": digital_spend,
        "price_index": price_index,
        "sales": sales,
    })


def create_mmm_bundle(
    draws: int = 100,
    tune: int = 100,
    chains: int = 2,
    target_accept: float = 0.9,
) -> dict:
    """Create a model bundle ready for Coiled fitting.

    Parameters
    ----------
    draws : int
        Number of MCMC draws.
    tune : int
        Number of tuning samples.
    chains : int
        Number of MCMC chains.
    target_accept : float
        Target acceptance rate.

    Returns
    -------
    dict
        Bundle with mmm, X, y, and sampling params.
    """
    print("Creating synthetic data...")
    df = create_synthetic_data(n_weeks=20)

    channel_columns = ["tv_spend", "digital_spend"]
    control_columns = ["price_index"]

    print("Creating MMM instance...")
    # Simple non-hierarchical priors for fast testing
    adstock = GeometricAdstock(
        l_max=4,
        priors={"alpha": Prior("Beta", alpha=2, beta=5, dims="channel")},
    )
    saturation = LogisticSaturation(
        priors={
            "lam": Prior("Gamma", mu=1, sigma=0.5, dims="channel"),
            "beta": Prior("HalfNormal", sigma=2, dims="channel"),
        }
    )

    mmm = MMM(
        date_column="date",
        target_column="sales",
        channel_columns=channel_columns,
        control_columns=control_columns,
        adstock=adstock,
        saturation=saturation,
        yearly_seasonality=2,
    )

    print("Preparing data...")
    # Manual data preparation (equivalent to prepare_mmm_data)
    y = df["sales"]
    X = df.drop(columns=["sales"])

    print("Building model...")
    mmm.build_model(X=X, y=y)

    print("Sampling prior predictive...")
    mmm.sample_prior_predictive(X, samples=50)

    print("Creating bundle...")
    bundle = {
        "mmm": mmm,
        "X": X,
        "y": y,
        "draws": draws,
        "tune": tune,
        "chains": chains,
        "target_accept": target_accept,
    }

    return bundle


def main():
    """Create and save test bundle."""
    output_path = sys.argv[1] if len(sys.argv) > 1 else "test_model_to_fit.pkl"

    # Use minimal settings for fast testing
    bundle = create_mmm_bundle(
        draws=50,
        tune=50,
        chains=2,
        target_accept=0.8,
    )

    print(f"Saving bundle to {output_path}...")
    with open(output_path, "wb") as f:
        cloudpickle.dump(bundle, f)

    # Show bundle size
    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"Bundle created: {output_path} ({size_mb:.2f} MB)")
    print()
    print("Bundle contents:")
    print(f"  - mmm: {type(bundle['mmm']).__name__}")
    print(f"  - X shape: {bundle['X'].shape}")
    print(f"  - y shape: {bundle['y'].shape}")
    print(f"  - draws: {bundle['draws']}")
    print(f"  - tune: {bundle['tune']}")
    print(f"  - chains: {bundle['chains']}")
    print(f"  - target_accept: {bundle['target_accept']}")

    # Show idata groups (prior predictive should exist)
    if bundle["mmm"].idata:
        print(f"  - idata groups: {list(bundle['mmm'].idata.groups())}")


if __name__ == "__main__":
    main()
