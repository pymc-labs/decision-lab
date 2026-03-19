#!/usr/bin/env python
"""Compare MCMC sampling time: numpyro vs C++ PyTensor backend.

Usage:
    conda activate mmm-docker
    python compare_backends.py
"""

import time
import tempfile
from pathlib import Path

import cloudpickle
import numpy as np
import pandas as pd

from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation
from pymc_marketing.mmm.multidimensional import MMM
from pymc_extras.prior import Prior


def create_synthetic_data(n_weeks: int = 20) -> pd.DataFrame:
    """Create minimal synthetic MMM data."""
    np.random.seed(42)
    dates = pd.date_range(start="2024-01-01", periods=n_weeks, freq="W-MON")

    tv_spend = np.maximum(0, 5000 + 2000 * np.random.randn(n_weeks))
    digital_spend = np.maximum(0, 3000 + 1000 * np.random.randn(n_weeks))
    price_index = 100 + 5 * np.random.randn(n_weeks)

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


def create_mmm():
    """Create a fresh MMM instance."""
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

    return MMM(
        date_column="date",
        target_column="sales",
        channel_columns=["tv_spend", "digital_spend"],
        control_columns=["price_index"],
        adstock=adstock,
        saturation=saturation,
        yearly_seasonality=2,
    )


def time_fit(mmm, X, y, backend: str, draws: int = 50, tune: int = 50, chains: int = 2):
    """Time the fitting process for a given backend."""
    print(f"\n{'='*60}")
    print(f"Testing backend: {backend}")
    print(f"{'='*60}")

    start = time.time()

    if backend == "numpyro":
        mmm.fit(
            X=X,
            y=y,
            nuts_sampler="numpyro",
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=0.8,
            random_seed=42,
        )
    else:
        # Default PyMC sampler with C++ backend
        mmm.fit(
            X=X,
            y=y,
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=0.8,
            random_seed=42,
        )

    elapsed = time.time() - start
    print(f"Fit time: {elapsed:.1f}s")

    return elapsed


def main():
    print("Creating synthetic data...")
    df = create_synthetic_data(n_weeks=20)
    y = df["sales"]
    X = df.drop(columns=["sales"])

    # Test parameters
    draws = 50
    tune = 50
    chains = 2

    print(f"\nTest config: draws={draws}, tune={tune}, chains={chains}")
    print(f"Data: {len(X)} rows, {len(X.columns)} features")

    results = {}

    # Test numpyro
    print("\n" + "="*60)
    print("NUMPYRO BACKEND (JAX)")
    print("="*60)
    mmm_numpyro = create_mmm()
    mmm_numpyro.build_model(X=X, y=y)
    results["numpyro"] = time_fit(mmm_numpyro, X, y, "numpyro", draws, tune, chains)

    # Test C++ backend
    print("\n" + "="*60)
    print("C++ PYTENSOR BACKEND (default PyMC)")
    print("="*60)
    mmm_cpp = create_mmm()
    mmm_cpp.build_model(X=X, y=y)
    results["c++"] = time_fit(mmm_cpp, X, y, "c++", draws, tune, chains)

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"  numpyro:  {results['numpyro']:6.1f}s")
    print(f"  C++:      {results['c++']:6.1f}s")
    print(f"  Speedup:  {results['c++'] / results['numpyro']:.1f}x (numpyro is faster)" if results['numpyro'] < results['c++'] else f"  Speedup:  {results['numpyro'] / results['c++']:.1f}x (C++ is faster)")


if __name__ == "__main__":
    main()
