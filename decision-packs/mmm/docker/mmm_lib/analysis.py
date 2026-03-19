"""
Model Analysis Functions (Kept Utilities)

Most analysis and plotting functions have been replaced by pymc-marketing 0.18.0
built-in APIs:
  - mmm.summary.roas(), mmm.summary.contributions(), mmm.summary.saturation_curves()
  - mmm.plot.posterior_predictive(), mmm.plot.contributions_over_time(), etc.
  - mmm.sensitivity.run_sweep(), compute_marginal_effects()

This module retains only functions NOT covered by pymc-marketing:
  - is_multidimensional_mmm() - model type detection
  - sample_posterior_predictive() - thin wrapper with validation
  - plot_trace() - arviz trace plot
  - optimize_budget_allocation() - budget optimization wrapper
  - check_posterior_predictive() - fit quality metrics
  - generate_recommendations() - business recommendation generator
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import arviz as az
from typing import Optional, Dict, Any, List, Tuple


# =============================================================================
# MODEL TYPE DETECTION
# =============================================================================

def is_multidimensional_mmm(mmm) -> bool:
    """Check if model has non-empty dims (panel data).

    All models use pymc_marketing.mmm.multidimensional.MMM. This checks
    whether dims is non-empty (e.g. dims=("geo",) for panel data) vs
    empty (dims=() or None for single time series).

    Parameters
    ----------
    mmm : MMM
        Fitted model instance.

    Returns
    -------
    bool
        True if model has non-empty dims (panel data).
    """
    return hasattr(mmm, 'dims') and mmm.dims is not None and len(mmm.dims) > 0


# =============================================================================
# POSTERIOR PREDICTIVE ANALYSIS
# =============================================================================

def sample_posterior_predictive(
    mmm,
    X: np.ndarray | pd.DataFrame,
    extend_idata: bool = True,
    verbose: bool = True,
):
    """
    Sample from posterior predictive distribution.

    Parameters
    ----------
    mmm : MMM
        Fitted MMM instance.
    X : np.ndarray | pd.DataFrame
        Input data for prediction. If DataFrame, must include the date column.
    extend_idata : bool
        Extend existing InferenceData (default: True).
    verbose : bool
        Print sampling info (default: True).

    Returns
    -------
    xarray.Dataset
        Posterior predictive samples.
    """
    if isinstance(X, pd.DataFrame):
        date_col = mmm.date_column
        if date_col not in X.columns:
            raise ValueError(
                f"X DataFrame must include the date column '{date_col}'. "
                f"Got columns: {list(X.columns)}. "
                f"Use: X = df[['{date_col}', ...channel_cols..., ...control_cols...]]"
            )

    if verbose:
        n_obs = len(X) if hasattr(X, '__len__') else X.shape[0]
        print("SAMPLING POSTERIOR PREDICTIVE")
        print(f"  n_observations = {n_obs}")
        print(f"  extend_idata = {extend_idata}")

    result = mmm.sample_posterior_predictive(X, extend_idata=extend_idata)

    if verbose:
        print(f"  sampling completed")

    return result


# =============================================================================
# PARAMETER ANALYSIS
# =============================================================================

def plot_trace(
    mmm,
    var_names: List[str] = None,
    compact: bool = True,
    figsize: tuple = (12, 10),
) -> plt.Figure:
    """
    Plot MCMC trace for diagnostics.

    Parameters
    ----------
    mmm : MMM
        Fitted MMM instance.
    var_names : list of str, optional
        Variables to plot.
    compact : bool
        Use compact layout (default: True).
    figsize : tuple
        Figure size (default: (12, 10)).

    Returns
    -------
    matplotlib.Figure
    """
    if var_names is None:
        var_names = [
            "intercept", "y_sigma", "saturation_beta",
            "saturation_lam", "adstock_alpha"
        ]

    az.plot_trace(
        data=mmm.fit_result,
        var_names=var_names,
        compact=compact,
        backend_kwargs={"figsize": figsize, "layout": "constrained"},
    )
    plt.gcf().suptitle("Model Trace", fontsize=16)
    fig = plt.gcf()
    fig.tight_layout()

    return fig


# =============================================================================
# BUDGET OPTIMIZATION
# =============================================================================

def optimize_budget_allocation(
    mmm,
    total_budget: float,
    num_periods: int = 1,
    channel_bounds: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Tuple[Dict[str, float], Any]:
    """
    Optimize budget allocation across channels.

    Parameters
    ----------
    mmm : MMM
        Fitted MMM instance.
    total_budget : float
        Total budget to allocate.
    num_periods : int
        Number of time periods (default: 1).
    channel_bounds : dict, optional
        Dict mapping channel to (min, max) budget.

    Returns
    -------
    tuple of (dict, Any)
        (optimal_budgets, optimization_results)
    """
    from pymc_marketing.mmm.budget_optimizer import BudgetOptimizer

    optimizer = BudgetOptimizer(model=mmm, num_periods=num_periods)

    optimal_budgets, results = optimizer.allocate_budget(
        total_budget=total_budget,
        budget_bounds=channel_bounds,
    )

    return optimal_budgets, results


# =============================================================================
# BUSINESS INSIGHTS FUNCTIONS
# =============================================================================

def check_posterior_predictive(
    y_true: np.ndarray,
    y_pred_samples: np.ndarray,
    coverage_levels: List[float] = [0.5, 0.9, 0.95],
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Check posterior predictive fit quality.

    Parameters
    ----------
    y_true : np.ndarray
        Observed target values.
    y_pred_samples : np.ndarray
        Posterior predictive samples (shape: [n_samples, n_observations]).
    coverage_levels : list of float
        Coverage levels to check (default: [0.5, 0.9, 0.95]).
    verbose : bool
        Print fit quality metrics (default: True).

    Returns
    -------
    dict
        Dictionary with: mean_prediction, residuals, mae, mape, coverage, in_sample_r2
    """
    y_pred_mean = y_pred_samples.mean(axis=0)
    residuals = y_true - y_pred_mean
    mae = float(np.mean(np.abs(residuals)))
    mape = float(np.mean(np.abs(residuals / (y_true + 1e-10))) * 100)

    coverage = {}
    for level in coverage_levels:
        lower_q = (1 - level) / 2
        upper_q = 1 - lower_q

        lower_bound = np.quantile(y_pred_samples, lower_q, axis=0)
        upper_bound = np.quantile(y_pred_samples, upper_q, axis=0)

        in_interval = (y_true >= lower_bound) & (y_true <= upper_bound)
        actual_coverage = float(in_interval.mean())

        coverage[f"{int(level*100)}%"] = {
            "expected": level,
            "actual": actual_coverage,
            "difference": actual_coverage - level
        }

    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((y_true - y_true.mean()) ** 2)
    r2 = float(1 - (ss_res / ss_tot))

    result = {
        "mean_prediction": y_pred_mean.tolist(),
        "residuals": residuals.tolist(),
        "mae": mae,
        "mape": mape,
        "coverage": coverage,
        "in_sample_r2": r2
    }

    if verbose:
        print("POSTERIOR PREDICTIVE CHECK")
        print(f"  n_observations = {len(y_true)}")
        print(f"  n_samples = {y_pred_samples.shape[0]}")
        print(f"  in_sample_r2 = {r2:.4f}")
        print(f"  mae = {mae:.4f}")
        print(f"  mape = {mape:.2f}%")
        for level_str, cov_data in coverage.items():
            print(f"  coverage_{level_str} = {cov_data['actual']:.2%} (expected {cov_data['expected']:.0%})")

    return result


def generate_recommendations(
    roas_by_channel: Dict[str, Dict[str, float]],
    min_roas_threshold: float = 1.0,
    high_roas_threshold: float = 3.0
) -> List[str]:
    """
    Generate actionable business recommendations based on ROAS analysis.

    Parameters
    ----------
    roas_by_channel : dict
        Dict of {channel: {mean, median, ...}}.
    min_roas_threshold : float
        Minimum acceptable ROAS (default: 1.0).
    high_roas_threshold : float
        Threshold for "high performing" channels (default: 3.0).

    Returns
    -------
    list of str
        List of recommendation strings.
    """
    recommendations = []

    sorted_channels = sorted(
        roas_by_channel.items(),
        key=lambda x: x[1]["median"],
        reverse=True
    )

    high_performers = [
        ch for ch, roas in sorted_channels
        if roas["median"] > high_roas_threshold
    ]

    if high_performers:
        recommendations.append(
            f"**Increase investment in high-performing channels**: {', '.join(high_performers)} "
            f"(ROAS > {high_roas_threshold})"
        )

    low_performers = [
        ch for ch, roas in sorted_channels
        if roas["median"] < min_roas_threshold
    ]

    if low_performers:
        recommendations.append(
            f"**Reduce or reallocate budget from underperforming channels**: {', '.join(low_performers)} "
            f"(ROAS < {min_roas_threshold})"
        )

    middle_performers = [
        ch for ch, roas in sorted_channels
        if min_roas_threshold <= roas["median"] <= high_roas_threshold
    ]

    if middle_performers:
        recommendations.append(
            f"**Optimize spend for moderate performers**: {', '.join(middle_performers)} "
            f"(ROAS between {min_roas_threshold} and {high_roas_threshold}) - test increased spend to see if ROAS improves"
        )

    high_variance_channels = [
        ch for ch, roas in roas_by_channel.items()
        if roas.get("std", 0) / (roas.get("mean", 1) + 1e-10) > 0.5
    ]

    if high_variance_channels:
        recommendations.append(
            f"**High uncertainty in**: {', '.join(high_variance_channels)} - "
            "consider additional data collection or testing to reduce uncertainty"
        )

    if not recommendations:
        recommendations.append("All channels performing within expected range. Continue current strategy.")

    return recommendations


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "is_multidimensional_mmm",
    "sample_posterior_predictive",
    "plot_trace",
    "optimize_budget_allocation",
    "check_posterior_predictive",
    "generate_recommendations",
]
