"""Run full post-fit analysis on an MMM.

Function API: call analyze_mmm() with a pre-built fitted MMM instance.
When called without config, parameter recovery and GT saturation overlay
are skipped — all other analyses still work.

Usage:
    from mmm_lib.analyze_model import analyze_mmm
    analyze_mmm(mmm, df, idata_path="fitted_model.nc")
"""

import json
import warnings
from pathlib import Path

import arviz as az
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import xarray as xr

from pymc_marketing.mmm.multidimensional import (
    MultiDimensionalBudgetOptimizerWrapper,
)


plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams["figure.figsize"] = [12, 7]
plt.rcParams["figure.dpi"] = 100

# Known MMM parameter variable names (filtered against actual posterior at runtime)
_KNOWN_PARAM_VAR_NAMES = [
    "intercept_contribution",
    "y_sigma",
    "saturation_beta",
    "saturation_lam",
    "adstock_alpha",
    "adstock_theta",
    "gamma_control",
    "gamma_fourier",
]


def _get_param_var_names(posterior):
    """Return the subset of known parameter names that exist in the posterior."""
    return [v for v in _KNOWN_PARAM_VAR_NAMES if v in posterior]


# =========================================================================
# Model metadata helpers (MMM attributes first, config fallback)
# =========================================================================

def _get_target_col(mmm, config=None):
    if config:
        return config["model"]["target_column"]
    return mmm.target_column


def _get_date_col(mmm, config=None):
    if config:
        return config["model"]["date_column"]
    return mmm.date_column


def _get_channel_columns(mmm, config=None):
    if config:
        return config["model"]["channel_columns"]
    return list(mmm.channel_columns)


def _get_dims(mmm, config=None):
    if config:
        return config["model"]["dims"]
    dims = mmm.dims
    if dims:
        return list(dims)
    return []


# =========================================================================
# Saturation function dispatch
# =========================================================================

def _logistic_sat(x, lam):
    """Logistic (inverse-scaled logistic) saturation: (1 - exp(-lam*x)) / (1 + exp(-lam*x))"""
    return (1 - np.exp(-lam * x)) / (1 + np.exp(-lam * x))


def _tanh_sat(x, b, c):
    """Tanh saturation: b * tanh(c * x)"""
    return b * np.tanh(c * x)


def _michaelis_menten_sat(x, lam, mu):
    """Michaelis-Menten saturation: lam * x / (mu + x)"""
    return lam * x / (mu + x)


def _hill_sat(x, slope, kappa):
    """Hill saturation (unit-scale): 1 - kappa^slope / (kappa^slope + x^slope).

    Beta is multiplied externally by the overlay code.
    """
    kappa_s = kappa ** slope
    return 1.0 - kappa_s / (kappa_s + x ** slope)


def _hill_sigmoid_sat(x, sigma, lam, beta):
    """Hill sigmoid saturation: sigma * x**beta / (lam**beta + x**beta)"""
    return sigma * x**beta / (lam**beta + x**beta)


def _root_sat(x, alpha):
    """Root saturation: x**alpha"""
    return x**alpha


_SATURATION_FUNCTIONS = {
    "logistic": _logistic_sat,
    "inverse_scaled_logistic": _logistic_sat,
    "tanh": _tanh_sat,
    "michaelis_menten": _michaelis_menten_sat,
    "hill": _hill_sat,
    "hill_sigmoid": _hill_sigmoid_sat,
    "root": _root_sat,
}


# =========================================================================
# Config-dependent helpers (only used when config is provided)
# =========================================================================

def _add_original_scale_vars_if_needed(mmm, var_list):
    """Add original-scale variables only if they don't already exist in the model."""
    existing = {v.name for v in mmm.model.deterministics}
    registered = set(mmm.model.named_vars_to_dims)
    needed = [
        v for v in var_list
        if f"{v}_original_scale" not in existing and v in registered
    ]
    if needed:
        mmm.add_original_scale_contribution_variable(var=needed)


def savefig(fig, output_dir, name):
    """Save figure and close."""
    path = output_dir / f"{name}.png"
    fig.savefig(path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  Saved {path}")


def build_dim_coords(config, df):
    """Build dimension coordinate maps (same logic as build_deterministic_mmm)."""
    model_cfg = config["model"]
    channel_columns = model_cfg["channel_columns"]
    control_columns = model_cfg["control_columns"]
    dims = model_cfg["dims"]
    yearly_seasonality = model_cfg.get("yearly_seasonality")

    dim_coords = {
        "channel": channel_columns,
        "control": control_columns,
    }
    if dims:
        dim_name = dims[0]
        dim_coords[dim_name] = sorted(df[dim_name].unique())
    if yearly_seasonality:
        n = yearly_seasonality
        dim_coords["fourier_mode"] = (
            [f"sin_{i}" for i in range(1, n + 1)]
            + [f"cos_{i}" for i in range(1, n + 1)]
        )
    return dim_coords


def extract_ground_truth_values(config, dim_coords):
    """Extract all ground truth parameter values as a dict of arrays."""
    ground_truth = {}
    for param in config.get("parameters", []):
        arr, dims = build_param_array(param, dim_coords)
        ground_truth[param["name"]] = {"value": arr, "dims": dims}
    for param in config["adstock"].get("parameters", []):
        arr, dims = build_param_array(param, dim_coords)
        ground_truth[f"adstock_{param['name']}"] = {"value": arr, "dims": dims}
    for param in config["saturation"].get("parameters", []):
        arr, dims = build_param_array(param, dim_coords)
        ground_truth[f"saturation_{param['name']}"] = {"value": arr, "dims": dims}
    return ground_truth


def _build_param_map(config):
    """Build ground_truth_name -> posterior_var_name mapping from config."""
    param_map = {}
    name_to_posterior = {
        "intercept": "intercept_contribution",
        "sigma": "y_sigma",
    }
    for param in config.get("parameters", []):
        name = param["name"]
        post_name = name_to_posterior.get(name, name)
        param_map[name] = post_name
    for param in config["adstock"].get("parameters", []):
        name = param["name"]
        param_map[f"adstock_{name}"] = f"adstock_{name}"
    for param in config["saturation"].get("parameters", []):
        name = param["name"]
        param_map[f"saturation_{name}"] = f"saturation_{name}"
    return param_map


# =========================================================================
# Analysis sections
# =========================================================================

def prior_predictive_checks(mmm, X, y, output_dir, rng):
    """Prior predictive checks matching the pymc-marketing case study notebook."""
    print("\n=== Prior Predictive Checks ===")

    # Ensure original-scale variables exist for prior predictive
    if not hasattr(mmm, "model") or mmm.model is None:
        mmm.build_model(X, y)
    original_scale_vars = [
        "channel_contribution", "control_contribution",
        "intercept_contribution", "y",
    ]
    if mmm.yearly_seasonality:
        original_scale_vars.append("yearly_seasonality_contribution")
    _add_original_scale_vars_if_needed(mmm, original_scale_vars)

    mmm.sample_prior_predictive(X, y, samples=4000, random_seed=rng)

    prior_y = (
        mmm.idata["prior"]["y_original_scale"]
        .stack(sample=("chain", "draw"))
        .transpose("sample", ...)
    )
    dates = mmm.model.coords["date"]

    # Sum over non-sample/date dims (e.g., geo) for total prior
    extra_dims = [
        d for d in prior_y.dims
        if d not in {"sample", "date", "chain", "draw"}
    ]
    if extra_dims:
        prior_y = prior_y.sum(dim=extra_dims)

    # Sum actual y per date for multi-geo
    date_col = mmm.date_column
    if len(y) != len(dates) and date_col in X.columns:
        y_per_date = (
            pd.DataFrame({date_col: X[date_col], "y": y.values})
            .groupby(date_col)["y"].sum()
            .reindex(dates)
            .values
        )
    else:
        y_per_date = y.values

    fig, ax = plt.subplots()
    ax.plot(dates, y_per_date, color="black", label=mmm.target_column)
    for i, hdi_prob in enumerate([0.94, 0.50]):
        az.plot_hdi(
            x=dates, y=prior_y,
            smooth=False, color="C0", hdi_prob=hdi_prob,
            fill_kwargs={
                "alpha": 0.3 + i * 0.1,
                "label": f"{hdi_prob:.0%} HDI",
            },
            ax=ax,
        )
    ax.legend(loc="upper left")
    ax.set(xlabel="date", ylabel=mmm.target_column)
    ax.set_title("Prior Predictive Checks", fontsize=18, fontweight="bold")
    savefig(fig, output_dir, "01_prior_predictive")

    # --- Text summary ---
    prior_vals = prior_y.values  # (sample, date)
    prior_median_ts = np.median(prior_vals, axis=0)
    obs_min, obs_max = float(y_per_date.min()), float(y_per_date.max())
    print(f"  Prior predictive median range: {prior_median_ts.min():,.0f}–{prior_median_ts.max():,.0f}"
          f" (observed: {obs_min:,.0f}–{obs_max:,.0f})")

    prior_arr = prior_y.values  # (sample, date)
    hdi_lo = np.percentile(prior_arr, 3, axis=0)
    hdi_hi = np.percentile(prior_arr, 97, axis=0)
    covered = np.sum((y_per_date >= hdi_lo) & (y_per_date <= hdi_hi))
    pct_covered = covered / len(y_per_date)
    print(f"  94% HDI covers {pct_covered:.0%} of observed data points ({covered}/{len(y_per_date)})")

    hdi_width = hdi_hi - hdi_lo
    hdi_width_mape = np.mean(np.abs(hdi_width) / np.maximum(np.abs(y_per_date), 1e-8))
    print(f"  Prior 94% HDI width MAPE: {hdi_width_mape:.1%} (mean |upper-lower| / |observed|)")

    prior_data = mmm.idata["prior"]
    had_posterior = "posterior" in mmm.idata
    if not had_posterior:
        mmm.idata.add_groups(posterior=prior_data)
    try:
        fig, ax = mmm.plot.channel_contribution_share_hdi(hdi_prob=0.94)
        ax.set_title("Prior Channel Contribution Share")
        savefig(fig, output_dir, "02_prior_contribution_share")
    finally:
        if not had_posterior:
            del mmm.idata.posterior


def model_diagnostics(mmm, output_dir):
    """Model diagnostics: divergences, r-hat, trace plots."""
    print("\n=== Model Diagnostics ===")

    posterior = mmm.idata["posterior"]
    param_var_names = _get_param_var_names(posterior)

    diverging = mmm.idata["sample_stats"]["diverging"]
    n_div = int(diverging.sum().item())
    n_total = int(diverging.size)
    div_rate = n_div / max(n_total, 1)
    div_label = "PASS" if div_rate == 0 else ("WARNING" if div_rate < 0.05 else "FAIL")
    print(f"  Divergences: {n_div}/{n_total} ({div_rate:.1%})  [{div_label}]")

    summary = az.summary(
        data=mmm.idata,
        var_names=param_var_names,
    )

    # R-hat analysis
    rhat = summary["r_hat"].dropna()
    n_rhat_11 = int((rhat > 1.1).sum())
    n_params = len(rhat)
    print(f"  R-hat: {n_rhat_11}/{n_params} params > 1.1")
    worst_rhat = rhat.nlargest(3)
    if len(worst_rhat) > 0:
        worst_str = ", ".join(f"{idx}={val:.3f}" for idx, val in worst_rhat.items())
        print(f"  Worst R-hat: {worst_str}")

    # ESS analysis
    if "ess_bulk" in summary.columns:
        ess_bulk = summary["ess_bulk"].dropna()
        ess_tail = summary["ess_tail"].dropna() if "ess_tail" in summary.columns else ess_bulk
        print(f"  ESS bulk: min={ess_bulk.min():.0f} ({ess_bulk.idxmin()}), median={ess_bulk.median():.0f}")
        print(f"  ESS tail: min={ess_tail.min():.0f} ({ess_tail.idxmin()}), median={ess_tail.median():.0f}")

    # Overall verdict
    issues = []
    if div_rate > 0:
        issues.append(f"divergences ({div_rate:.1%})")
    if "ess_bulk" in summary.columns and ess_bulk.min() < 100:
        issues.append(f"low ESS ({ess_bulk.min():.0f})")
    if issues:
        print(f"  Verdict: WARNING — {'; '.join(issues)}")
    else:
        print(f"  Verdict: PASS — no divergences, R-hat < 1.1, ESS adequate")

    axes = az.plot_trace(
        data=mmm.fit_result,
        var_names=param_var_names,
        compact=True,
    )
    fig = axes.ravel()[0].get_figure()
    n_rows = axes.shape[0]
    fig.set_size_inches(16, 2.5 * n_rows)
    savefig(fig, output_dir, "03_trace_plots")

    return summary


def posterior_predictive_checks(mmm, df, output_dir, *, target_col, dims,
                                date_col=None):
    """Posterior predictive checks using mmm.plot API."""
    print("\n=== Posterior Predictive Checks ===")

    if date_col is None:
        date_col = mmm.date_column

    # Ensure y_original_scale exists in posterior_predictive.
    # After MMM.load(), posterior_predictive only contains "y" (scaled).
    # We compute y_original_scale = y * target_scale so mmm.plot works.
    # TODO: Remove this workaround once pymc-marketing fixes save/load.
    pp_group: str = "posterior_predictive"
    if (pp_group in mmm.idata.groups()
            and "y" in mmm.idata[pp_group]
            and "y_original_scale" not in mmm.idata[pp_group]):
        target_scale_val: float = float(mmm.model["target_scale"].get_value())
        if target_scale_val > 0:
            mmm.idata[pp_group]["y_original_scale"] = (
                mmm.idata[pp_group]["y"] * target_scale_val
            )

    fig, axes = mmm.plot.posterior_predictive(
        var=["y_original_scale"], hdi_prob=0.50,
    )

    # Overlay observed data on each axis
    axes_flat = np.ravel(axes)
    if dims:
        dim_name = dims[0]
        dim_coords = mmm.model.coords.get(dim_name, [])
        for i, ax in enumerate(axes_flat):
            if i < len(dim_coords):
                level = dim_coords[i]
                mask = df[dim_name] == level
                level_df = df.loc[mask].sort_values(date_col)
                ax.plot(level_df[date_col].values, level_df[target_col].values,
                        'k-', lw=1.2, alpha=0.8, label='Observed')
    else:
        sorted_df = df.sort_values(date_col)
        axes_flat[0].plot(sorted_df[date_col].values, sorted_df[target_col].values,
                          'k-', lw=1.2, alpha=0.8, label='Observed')

    for ax in axes_flat:
        handles, labels = ax.get_legend_handles_labels()
        handles.append(Patch(facecolor="C0", alpha=0.3, label="50% HDI"))
        ax.legend(handles=handles)
    savefig(fig, output_dir, "05_posterior_predictive")

    fig, axes = mmm.plot.residuals_over_time()
    if not isinstance(fig, plt.Figure):
        fig = plt.gcf()
    savefig(fig, output_dir, "06_residuals_over_time")

    # Compute R-squared
    if "y_original_scale" in mmm.idata.get("posterior_predictive", {}):
        y_pp = mmm.idata["posterior_predictive"]["y_original_scale"]
    elif "y_original_scale" in mmm.idata["posterior"]:
        y_pp = mmm.idata["posterior"]["y_original_scale"]
    else:
        y_pp = None

    if y_pp is not None:
        y_pp_mean = y_pp.mean(dim=("chain", "draw"))

        # Collect all predictions and observations for overall metrics
        all_y_true = []
        all_y_pred = []

        if dims:
            dim_name = dims[0]
            if dim_name in y_pp_mean.dims:
                for level in y_pp_mean.coords[dim_name].values:
                    mask = df[dim_name] == level
                    y_true = df.loc[mask, target_col].values
                    y_pred_mean = y_pp_mean.sel({dim_name: level}).values
                    ss_res = np.sum((y_true - y_pred_mean) ** 2)
                    ss_tot = np.sum((y_true - y_true.mean()) ** 2)
                    r2 = 1 - ss_res / ss_tot
                    print(f"  R-squared ({level}): {r2:.4f}")
                    all_y_true.append(y_true)
                    all_y_pred.append(y_pred_mean)
            else:
                all_y_true.append(df[target_col].values)
                all_y_pred.append(y_pp_mean.values.ravel())
        else:
            all_y_true.append(df[target_col].values)
            all_y_pred.append(y_pp_mean.values.ravel())

        y_true_all = np.concatenate(all_y_true)
        y_pred_all = np.concatenate(all_y_pred)

        # Overall R-squared
        ss_res = np.sum((y_true_all - y_pred_all) ** 2)
        ss_tot = np.sum((y_true_all - y_true_all.mean()) ** 2)
        r2_overall = 1 - ss_res / ss_tot
        print(f"  R-squared (overall): {r2_overall:.4f}")

        # MAPE
        nonzero = np.abs(y_true_all) > 1e-8
        mape = np.mean(np.abs(y_true_all[nonzero] - y_pred_all[nonzero]) / np.abs(y_true_all[nonzero]))
        print(f"  MAPE (posterior mean vs observed): {mape:.2%}")

        # 50% HDI width MAPE
        y_pp_lo = y_pp.quantile(0.25, dim=("chain", "draw"))
        y_pp_hi = y_pp.quantile(0.75, dim=("chain", "draw"))
        hdi_width = (y_pp_hi - y_pp_lo).values.ravel()
        hdi_width_mape = np.mean(np.abs(hdi_width) / np.maximum(np.abs(y_true_all), 1e-8))
        print(f"  Posterior 50% HDI width MAPE: {hdi_width_mape:.2%} (mean |upper-lower| / |observed|)")

        # Max residual
        residuals = y_true_all - y_pred_all
        max_idx = np.argmax(np.abs(residuals))
        print(f"  Max |residual|: {np.abs(residuals[max_idx]):,.1f} (observation {max_idx})")


def parameter_recovery(mmm, config, df, output_dir):
    """Compare fitted posteriors to ground truth values.

    Only called when config is provided (ground truth available).
    """
    print("\n=== Parameter Recovery ===")

    dim_coords = build_dim_coords(config, df)
    ground_truth = extract_ground_truth_values(config, dim_coords)
    posterior = mmm.idata["posterior"]
    param_map = _build_param_map(config)

    coverage_results = []

    def _hdi_bounds(samples):
        hdi = az.hdi(samples.values.ravel(), hdi_prob=0.94)
        return float(hdi[0]), float(hdi[1])

    for ground_truth_name, post_name in param_map.items():
        if ground_truth_name not in ground_truth or post_name not in posterior:
            continue

        ground_truth_val = ground_truth[ground_truth_name]["value"]
        post_samples = posterior[post_name]

        if np.isscalar(ground_truth_val) or (isinstance(ground_truth_val, np.ndarray) and ground_truth_val.ndim == 0):
            lo, hi = _hdi_bounds(post_samples)
            in_hdi = lo <= float(ground_truth_val) <= hi
            coverage_results.append({
                "parameter": ground_truth_name,
                "ground_truth_value": float(ground_truth_val),
                "posterior_mean": float(post_samples.mean()),
                "hdi_low": lo, "hdi_high": hi, "in_94_hdi": in_hdi,
            })
        else:
            ground_truth_flat = np.ravel(ground_truth_val)
            post_dims = [d for d in post_samples.dims if d not in ("chain", "draw")]

            if len(post_dims) == 1:
                coords = post_samples.coords[post_dims[0]].values
                for i, coord in enumerate(coords):
                    samples_i = post_samples.sel({post_dims[0]: coord})
                    lo, hi = _hdi_bounds(samples_i)
                    ground_truth_i = float(ground_truth_flat[i])
                    coverage_results.append({
                        "parameter": f"{ground_truth_name}[{coord}]",
                        "ground_truth_value": ground_truth_i,
                        "posterior_mean": float(samples_i.mean()),
                        "hdi_low": lo, "hdi_high": hi,
                        "in_94_hdi": lo <= ground_truth_i <= hi,
                    })
            elif len(post_dims) == 2:
                coords0 = post_samples.coords[post_dims[0]].values
                coords1 = post_samples.coords[post_dims[1]].values
                for i, c0 in enumerate(coords0):
                    for j, c1 in enumerate(coords1):
                        samples_ij = post_samples.sel({post_dims[0]: c0, post_dims[1]: c1})
                        lo, hi = _hdi_bounds(samples_ij)
                        ground_truth_ij = float(ground_truth_val[i, j])
                        coverage_results.append({
                            "parameter": f"{ground_truth_name}[{c0},{c1}]",
                            "ground_truth_value": ground_truth_ij,
                            "posterior_mean": float(samples_ij.mean()),
                            "hdi_low": lo, "hdi_high": hi,
                            "in_94_hdi": lo <= ground_truth_ij <= hi,
                        })

    coverage_df = pd.DataFrame(coverage_results)
    total = len(coverage_df)
    covered = int(coverage_df["in_94_hdi"].sum())
    print(f"  Coverage: {covered}/{total} ({100*covered/total:.1f}%) of ground truth values in 94% HDI")

    # Coverage by parameter group
    def _group_name(p):
        if p.startswith("adstock_"):
            return "adstock"
        if p.startswith("saturation_"):
            return "saturation"
        return "model"
    coverage_df["group"] = coverage_df["parameter"].apply(_group_name)
    for grp, grp_df in coverage_df.groupby("group"):
        g_total = len(grp_df)
        g_covered = int(grp_df["in_94_hdi"].sum())
        print(f"    {grp}: {g_covered}/{g_total} ({100*g_covered/g_total:.1f}%)")

    # Relative error
    coverage_df["rel_error"] = (
        (coverage_df["posterior_mean"] - coverage_df["ground_truth_value"])
        / coverage_df["ground_truth_value"].replace(0, np.nan)
    )
    coverage_df["abs_rel_error"] = coverage_df["rel_error"].abs()
    median_rel_err = coverage_df["abs_rel_error"].median()
    print(f"  Median |relative error|: {median_rel_err:.2%}")

    # Worst recovered
    worst = coverage_df.nlargest(3, "abs_rel_error")
    if len(worst) > 0:
        print(f"  Worst recovery (by relative error):")
        for _, row in worst.iterrows():
            print(f"    {row['parameter']}: GT={row['ground_truth_value']:.4g}, "
                  f"post_mean={row['posterior_mean']:.4g} (rel_err={row['rel_error']:+.1%})")

    # Drop helper columns before saving
    coverage_df.drop(columns=["group", "rel_error", "abs_rel_error"], inplace=True)
    coverage_df.to_csv(output_dir / "parameter_recovery.csv", index=False)
    print(f"  Saved {output_dir / 'parameter_recovery.csv'}")

    # Prior vs posterior plots (dynamic)
    for var_name in list(posterior.data_vars):
        if var_name not in ground_truth and var_name not in param_map.values():
            continue
        post_var = posterior[var_name]
        post_dims = [d for d in post_var.dims if d not in ("chain", "draw")]
        if not post_dims:
            continue
        plot_dim = post_dims[0]
        fig, axes = mmm.plot.prior_vs_posterior(var=var_name, plot_dim=plot_dim)
        savefig(fig, output_dir, f"07_{var_name}_recovery")

    # Sigma recovery (scalar)
    if "y_sigma" in posterior and "sigma" in ground_truth:
        fig, ax = plt.subplots(figsize=(8, 5))
        s = posterior["y_sigma"].values.ravel()
        ground_truth_sigma = float(ground_truth["sigma"]["value"])
        ax.hist(s, bins=50, alpha=0.5, density=True, label="Posterior")
        ax.axvline(ground_truth_sigma, color="red", ls="--", lw=2,
                    label=f"ground truth={ground_truth_sigma:.6f}")
        ax.set_title("Sigma Recovery")
        ax.legend()
        savefig(fig, output_dir, "09_sigma_recovery")

    return coverage_df


def compute_contribution_split(mmm, *, dims):
    """Compute high-level revenue decomposition: baseline vs channels vs controls etc.

    Each contribution variable may have different dims:
      channel_contribution: (chain, draw, date, geo, channel)
      intercept_contribution: (chain, draw, geo) — no date!
      trend_effect_contribution: (chain, draw, date) — no geo!
    To get comparable totals we broadcast missing dims before summing.

    Parameters
    ----------
    mmm : MMM
        Fitted model with idata attached.
    dims : list[str]
        Dimension names (e.g. ["geo"]).

    Returns
    -------
    dict or None
        Percentages keyed as baseline_pct, channels_pct, controls_pct,
        plus seasonality_pct and trend_pct if present. None if grand_total <= 0.
    """
    posterior = mmm.idata["posterior"]
    target_scale = float(mmm.scalers._target.values)

    n_dates = len(posterior.coords["date"]) if "date" in posterior.coords else 1
    dim_name = dims[0] if dims else None
    n_levels = (len(posterior.coords[dim_name])
                if dim_name and dim_name in posterior.coords else 1)

    def _find_var(*candidates):
        for v in candidates:
            if v in posterior:
                return v
        return None

    def _contrib_total(var_name):
        if var_name is None:
            return 0.0
        var = posterior[var_name]
        val = float(var.mean(dim=("chain", "draw")).sum().values)
        if "original_scale" not in var_name:
            val *= target_scale
        var_dims = set(var.dims)
        if "date" not in var_dims:
            val *= n_dates
        if dim_name and dim_name not in var_dims:
            val *= n_levels
        return val

    ch_total = _contrib_total(
        _find_var("channel_contribution_original_scale", "channel_contribution"))
    ctrl_total = _contrib_total(
        _find_var("control_contribution_original_scale", "control_contribution"))
    ic_total = _contrib_total(
        _find_var("intercept_contribution_original_scale", "intercept_contribution"))
    seas_total = _contrib_total(
        _find_var("yearly_seasonality_contribution_original_scale",
                  "yearly_seasonality_contribution"))
    trend_total = _contrib_total(
        _find_var("trend_effect_contribution_original_scale",
                  "trend_effect_contribution"))

    grand_total = ic_total + ch_total + ctrl_total + seas_total + trend_total
    if grand_total <= 0:
        return None

    parts = [f"baseline {ic_total/grand_total:.1%}",
             f"channels {ch_total/grand_total:.1%}",
             f"controls {ctrl_total/grand_total:.1%}"]
    split = {
        "baseline_pct": round(ic_total / grand_total, 4),
        "channels_pct": round(ch_total / grand_total, 4),
        "controls_pct": round(ctrl_total / grand_total, 4),
    }
    if seas_total:
        parts.append(f"seasonality {seas_total/grand_total:.1%}")
        split["seasonality_pct"] = round(seas_total / grand_total, 4)
    if trend_total:
        parts.append(f"trend {trend_total/grand_total:.1%}")
        split["trend_pct"] = round(trend_total / grand_total, 4)
    print(f"\n  Contribution split: {', '.join(parts)}")

    return split


def channel_contributions(mmm, output_dir, *, dims):
    """Channel contributions over time and waterfall decomposition."""
    print("\n=== Channel Contributions ===")

    var_name = "channel_contribution_original_scale" if \
        "channel_contribution_original_scale" in mmm.idata["posterior"] \
        else "channel_contribution"
    post_var = mmm.idata["posterior"][var_name]

    if dims:
        dim_name = dims[0]
        if dim_name in post_var.dims:
            levels = post_var.coords[dim_name].values
            for level in levels:
                fig, ax = mmm.plot.contributions_over_time(
                    var=[var_name], combine_dims=True, hdi_prob=0.50,
                    dims={dim_name: level}, figsize=(14, 6),
                )
                if not isinstance(fig, plt.Figure):
                    fig = ax.get_figure() if hasattr(ax, "get_figure") else plt.gcf()
                ax_obj = np.ravel(fig.get_axes())[0] if hasattr(fig, "get_axes") else ax
                ax_obj.set_title(f"Channel Contributions Over Time ({level})")
                handles, labels = ax_obj.get_legend_handles_labels()
                short_labels = []
                for lbl in labels:
                    if "channel=" in lbl:
                        short_labels.append(lbl.split("channel=")[-1].rstrip(")"))
                    else:
                        short_labels.append(lbl)
                ax_obj.legend(
                    handles, short_labels,
                    bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=9,
                )
                fig.set_layout_engine("none")
                fig.subplots_adjust(right=0.78)
                savefig(fig, output_dir, f"11_contributions_over_time_{level}")
        else:
            fig, ax = mmm.plot.contributions_over_time(
                var=[var_name], combine_dims=True, hdi_prob=0.50,
                figsize=(14, 6),
            )
            if not isinstance(fig, plt.Figure):
                fig = ax.get_figure() if hasattr(ax, "get_figure") else plt.gcf()
            savefig(fig, output_dir, "11_contributions_over_time")
    else:
        fig, ax = mmm.plot.contributions_over_time(
            var=[var_name], combine_dims=True, hdi_prob=0.50,
            figsize=(14, 6),
        )
        if not isinstance(fig, plt.Figure):
            fig = ax.get_figure() if hasattr(ax, "get_figure") else plt.gcf()
        savefig(fig, output_dir, "11_contributions_over_time")

    fig, ax = mmm.plot.waterfall_components_decomposition(figsize=(18, 12))
    if not isinstance(fig, plt.Figure):
        fig = plt.gcf()
    savefig(fig, output_dir, "12_waterfall_decomposition")

    try:
        fig, ax = mmm.plot.channel_contribution_share_hdi(hdi_prob=0.94)
        savefig(fig, output_dir, "12b_channel_contribution_share")
    except ValueError as e:
        print(f"  Channel contribution share HDI skipped: {e}")

    print("\nChannel contributions (all_time):")
    ch_contrib_df = mmm.summary.contributions(frequency="all_time")
    print(ch_contrib_df)
    print("\nControl contributions (all_time):")
    ctrl_contrib_df = mmm.summary.contributions(component="control", frequency="all_time")
    print(ctrl_contrib_df)
    print("\nBaseline (all_time):")
    baseline_val = None
    try:
        baseline_df = mmm.summary.contributions(component="baseline", frequency="all_time")
        print(baseline_df)
        baseline_val = baseline_df["contribution"].sum() if "contribution" in baseline_df.columns else None
    except ValueError:
        ic = mmm.idata.posterior["intercept_contribution"].values.squeeze()
        ts = float(mmm.scalers._target.values)
        baseline_val = float(ic) * ts
        print(f"  intercept_contribution (pooled): {baseline_val:.2f}")

    contribution_split = compute_contribution_split(mmm, dims=dims)

    # Per-channel contribution (top/bottom)
    posterior = mmm.idata["posterior"]
    target_scale = float(mmm.scalers._target.values)
    ch_var = ("channel_contribution_original_scale"
              if "channel_contribution_original_scale" in posterior
              else "channel_contribution")
    ch_per_channel = posterior[ch_var].mean(dim=("chain", "draw")).sum(
        dim=[d for d in posterior[ch_var].dims if d not in ("chain", "draw", "channel")]
    )
    ch_vals = ch_per_channel.values
    if "original_scale" not in ch_var:
        ch_vals = ch_vals * target_scale
    channels = ch_per_channel.coords["channel"].values
    # Scale per-channel values to share of total revenue using channels_pct
    channels_pct = contribution_split.get("channels_pct", 1.0) if contribution_split else 1.0
    ch_sum = ch_vals.sum()
    ch_pcts = (ch_vals / ch_sum * channels_pct) if ch_sum > 0 else ch_vals
    top_idx = np.argmax(ch_vals)
    bot_idx = np.argmin(ch_vals)
    print(f"  Top channel: {channels[top_idx]} ({ch_pcts[top_idx]:.1%} of total)")
    print(f"  Bottom channel: {channels[bot_idx]} ({ch_pcts[bot_idx]:.1%} of total)")

    return contribution_split


def saturation_curves(mmm, df, output_dir, *, config=None, dims=None):
    """Saturation scatterplot, optionally with ground truth curves overlaid.

    When config is None, only the posterior scatterplot is shown (no GT overlay).

    Returns
    -------
    dict or None
        Saturation operating points per channel, or None if not computed.
    """
    print("\n=== Saturation Curves ===")
    fig, axes = mmm.plot.saturation_scatterplot(
        width_per_col=12, height_per_row=4, original_scale=True,
    )
    if not isinstance(fig, plt.Figure):
        fig = plt.gcf()

    # Overlay ground truth curves only when config is provided
    if config is not None:
        target_col = config["model"]["target_column"]
        target_scale = df[target_col].max()
        channel_columns = config["model"]["channel_columns"]
        dims = config["model"]["dims"]
        sat_type = config["saturation"]["type"]
        sat_params = {p["name"]: p for p in config["saturation"].get("parameters", [])}
        dim_coords = build_dim_coords(config, df)

        sat_func = _SATURATION_FUNCTIONS.get(sat_type)
        if sat_func is None:
            print(f"  Unknown saturation type '{sat_type}', skipping GT overlay")
        else:
            ground_truth_param_arrays = {}
            for pname, pspec in sat_params.items():
                arr, _ = build_param_array(pspec, dim_coords)
                ground_truth_param_arrays[pname] = arr

            posterior = mmm.idata["posterior"]
            post_param_arrays = {}
            for pname in sat_params:
                post_var_name = f"saturation_{pname}"
                if post_var_name in posterior:
                    post_param_arrays[pname] = posterior[post_var_name].values

            axes_flat = np.ravel(axes)
            if dims:
                dim_name = dims[0]
                levels = sorted(df[dim_name].unique())
            else:
                levels = [None]

            for i, ch in enumerate(channel_columns):
                ch_max = df[ch].max()

                ground_truth_ch = {}
                for pname, arr in ground_truth_param_arrays.items():
                    ground_truth_ch[pname] = arr[i] if arr.ndim > 0 else float(arr)

                post_ch = {}
                for pname, arr in post_param_arrays.items():
                    post_ch[pname] = arr[:, :, i].ravel() if arr.ndim > 2 else arr.ravel()

                for j, level in enumerate(levels):
                    ax_idx = i * len(levels) + j
                    if ax_idx >= len(axes_flat):
                        break
                    ax = axes_flat[ax_idx]
                    x_orig = np.linspace(0, ax.get_xlim()[1], 200)
                    x_scaled = x_orig / ch_max

                    if sat_type in ("logistic", "inverse_scaled_logistic"):
                        beta_s = post_ch.get("beta")
                        lam_s = post_ch.get("lam")
                        if beta_s is not None and lam_s is not None:
                            y_all = (beta_s[:, None]
                                     * _logistic_sat(x_scaled[None, :], lam_s[:, None])
                                     * target_scale)
                            y_median = np.median(y_all, axis=0)
                            y_lo = np.percentile(y_all, 25, axis=0)
                            y_hi = np.percentile(y_all, 75, axis=0)
                            ax.fill_between(x_orig, y_lo, y_hi, alpha=0.25, color="gray",
                                            label="50% HDI", zorder=3)
                            ax.plot(x_orig, y_median, "k-", lw=1.5, label="Posterior median",
                                    zorder=4)

                        gt_beta = ground_truth_ch.get("beta")
                        gt_lam = ground_truth_ch.get("lam")
                        if gt_beta is not None and gt_lam is not None:
                            y_gt = gt_beta * _logistic_sat(x_scaled, gt_lam) * target_scale
                            ax.plot(x_orig, y_gt, "r--", lw=1.5, label="Ground Truth", zorder=5)
                    else:
                        y_gt = ground_truth_ch.get("beta", 1.0) * sat_func(
                            x_scaled, **{k: v for k, v in ground_truth_ch.items() if k != "beta"}
                        ) * target_scale
                        ax.plot(x_orig, y_gt, "r--", lw=1.5, label="Ground Truth", zorder=5)

                    ax.legend(fontsize=7)

    savefig(fig, output_dir, "13_saturation_scatterplot")

    # --- Saturation operating point summary ---
    if config is not None:
        sat_type = config["saturation"]["type"]
        sat_func = _SATURATION_FUNCTIONS.get(sat_type)
        channel_columns = config["model"]["channel_columns"]
        dim_coords = build_dim_coords(config, df)
        sat_params = {p["name"]: p for p in config["saturation"].get("parameters", [])}

        if sat_func is not None:
            gt_arrays = {}
            for pname, pspec in sat_params.items():
                arr, _ = build_param_array(pspec, dim_coords)
                gt_arrays[pname] = arr

            print("\n  Saturation operating points (mean spend as % of max response):")
            sat_points = {}
            for i, ch in enumerate(channel_columns):
                ch_mean_scaled = df[ch].mean() / df[ch].max()
                ch_params = {k: (v[i] if v.ndim > 0 else float(v))
                             for k, v in gt_arrays.items() if k != "beta"}

                resp_at_mean = sat_func(ch_mean_scaled, **ch_params)
                resp_at_max = sat_func(1.0, **ch_params)
                pct_saturated = resp_at_mean / resp_at_max if resp_at_max > 0 else 0

                # Marginal efficiency: derivative at mean vs derivative at ~0
                eps = 1e-4
                marginal_at_mean = (sat_func(ch_mean_scaled + eps, **ch_params)
                                    - sat_func(ch_mean_scaled, **ch_params)) / eps
                marginal_at_zero = (sat_func(eps, **ch_params)
                                    - sat_func(0, **ch_params)) / eps
                eff_ratio = marginal_at_mean / marginal_at_zero if marginal_at_zero > 0 else 0

                sat_points[ch] = pct_saturated
                print(f"    {ch}: {pct_saturated:.0%} saturated "
                      f"(marginal efficiency: {eff_ratio:.2f}x of initial)")

            most_sat = max(sat_points, key=sat_points.get)
            least_sat = min(sat_points, key=sat_points.get)
            print(f"  Most saturated: {most_sat} ({sat_points[most_sat]:.0%}), "
                  f"least saturated: {least_sat} ({sat_points[least_sat]:.0%})")

    else:
        # Posterior-based saturation operating points (no config needed).
        # channel_contribution = beta_param * f(adstock(x/x_max)) where f ∈ [0,1].
        # So channel_contribution / beta_param = saturation fraction.
        _BETA_PARAM_MAP = {
            "logistic": "saturation_beta",
            "inverse_scaled_logistic": "saturation_beta",
            "tanh": "saturation_b",
            "michaelis_menten": "saturation_alpha",
            "hill": "saturation_beta",
        }
        sat_type = mmm.saturation.lookup_name
        beta_var = _BETA_PARAM_MAP.get(sat_type)
        posterior = mmm.idata["posterior"]

        if beta_var is None:
            print(f"\n  Saturation operating points: not available for '{sat_type}' "
                  f"(no bounded [0,1] core function)")
            return None
        if beta_var not in posterior:
            print(f"\n  Saturation operating points: '{beta_var}' not found in posterior")
            return None
        if "channel_contribution" not in posterior:
            print("\n  Saturation operating points: 'channel_contribution' not found in posterior")
            return None

        channel_columns = list(mmm.channel_columns)
        # channel_contribution: (chain, draw, date, *dims, channel)
        # beta: (chain, draw, channel) or (chain, draw, channel, *dims)
        cc_mean = posterior["channel_contribution"].mean(dim=("chain", "draw"))
        beta_mean = posterior[beta_var].mean(dim=("chain", "draw"))

        print("\n  Saturation operating points (from posterior, all time periods):")
        sat_points: dict[str, dict[str, float]] = {}

        if dims:
            dim_name = dims[0]
            if dim_name in cc_mean.dims:
                beta_has_dim = dim_name in beta_mean.dims
                beta_has_channel = "channel" in beta_mean.dims
                levels = cc_mean.coords[dim_name].values
                for level in levels:
                    print(f"   {dim_name}={level}:")
                    cc_level = cc_mean.sel({dim_name: level})
                    beta_level = beta_mean.sel({dim_name: level}) if beta_has_dim else beta_mean
                    for i, ch in enumerate(channel_columns):
                        cc_ch = cc_level.isel(channel=i).values.ravel()
                        beta_ch = float(
                            beta_level.isel(channel=i).values.mean()
                            if beta_has_channel
                            else beta_level.values.mean()
                        )
                        if beta_ch <= 0:
                            print(f"      {ch}: beta <= 0, skipping")
                            continue
                        sat_frac = np.clip(cc_ch / beta_ch, 0.0, 1.0)
                        avg_pct = float(np.mean(sat_frac))
                        med_pct = float(np.median(sat_frac))
                        max_pct = float(np.max(sat_frac))
                        key = f"{ch}_{level}"
                        sat_points[key] = {"avg": avg_pct, "median": med_pct, "max": max_pct}
                        print(f"      {ch}: avg {avg_pct:.0%}, median {med_pct:.0%}, "
                              f"max {max_pct:.0%} of max response")
            else:
                # dim not in posterior — fall through to non-dim path
                dims = None

        if not dims:
            beta_has_channel = "channel" in beta_mean.dims
            for i, ch in enumerate(channel_columns):
                cc_ch = cc_mean.isel(channel=i).values.ravel()
                beta_ch = float(
                    beta_mean.isel(channel=i).values.mean()
                    if beta_has_channel
                    else beta_mean.values.mean()
                )
                if beta_ch <= 0:
                    print(f"    {ch}: beta <= 0, skipping")
                    continue
                sat_frac = np.clip(cc_ch / beta_ch, 0.0, 1.0)
                avg_pct = float(np.mean(sat_frac))
                med_pct = float(np.median(sat_frac))
                max_pct = float(np.max(sat_frac))
                sat_points[ch] = {"avg": avg_pct, "median": med_pct, "max": max_pct}
                print(f"    {ch}: avg {avg_pct:.0%}, median {med_pct:.0%}, "
                      f"max {max_pct:.0%} of max response")

        if sat_points:
            most_sat = max(sat_points, key=lambda c: sat_points[c]["avg"])
            least_sat = min(sat_points, key=lambda c: sat_points[c]["avg"])
            print(f"  Most saturated: {most_sat} (avg {sat_points[most_sat]['avg']:.0%}), "
                  f"least: {least_sat} (avg {sat_points[least_sat]['avg']:.0%})")

        return sat_points


def sensitivity_analysis(mmm, output_dir, *, dims=None):
    """Sensitivity analysis sweep."""
    print("\n=== Sensitivity Analysis ===")
    sweeps = np.linspace(0, 1.5, 16)
    var_name = "channel_contribution_original_scale" if \
        "channel_contribution_original_scale" in mmm.idata["posterior"] \
        else "channel_contribution"
    mmm.sensitivity.run_sweep(
        sweep_values=sweeps,
        var_input="channel_data",
        var_names=var_name,
        extend_idata=True,
    )
    result = mmm.plot.sensitivity_analysis(
        xlabel="Spend multiplier",
        ylabel="Total contribution",
        hue_dim="channel",
        x_sweep_axis="relative",
        subplot_kwargs={"figsize": (16, 6)},
        legend_kwargs={
            "bbox_to_anchor": (1.02, 1),
            "loc": "upper left",
            "fontsize": 9,
        },
    )
    # Handle both (fig, axes) tuple and bare axes return
    if isinstance(result, tuple):
        fig = result[0]
    elif isinstance(result, plt.Figure):
        fig = result
    else:
        fig = result.get_figure() if hasattr(result, "get_figure") else plt.gcf()
    fig.subplots_adjust(right=0.80)
    savefig(fig, output_dir, "14_sensitivity_analysis")

    # --- Sensitivity text summary ---
    # run_sweep stores results in idata.sensitivity_analysis["x"]
    # dims: (sample, sweep, *dims_order) where dims_order includes "channel"
    # Values are total contribution summed over date axis.
    sensitivity_group = getattr(mmm.idata, "sensitivity_analysis", None)
    if sensitivity_group is not None and "x" in sensitivity_group:
        sweep_result = sensitivity_group["x"]
        channels = sweep_result.coords["channel"].values
        sweep_coords = sweep_result.coords["sweep"].values

        sweep_idx_1x = int(np.argmin(np.abs(sweep_coords - 1.0)))
        sweep_idx_15x = int(np.argmin(np.abs(sweep_coords - 1.5)))

        print("\n  Sensitivity to +50% spend increase:")
        results: dict[str, dict[str, float]] = {}

        if dims:
            dim_name = dims[0]
            if dim_name in sweep_result.dims:
                levels = sweep_result.coords[dim_name].values
                for level in levels:
                    print(f"   {dim_name}={level}:")
                    level_slice = sweep_result.sel({dim_name: level})
                    for ch in channels:
                        contrib_1x = float(level_slice.sel(
                            channel=ch, sweep=sweep_coords[sweep_idx_1x]
                        ).mean())
                        contrib_15x = float(level_slice.sel(
                            channel=ch, sweep=sweep_coords[sweep_idx_15x]
                        ).mean())
                        abs_change = contrib_15x - contrib_1x
                        pct_change = (contrib_15x / contrib_1x - 1) if contrib_1x > 0 else float("inf")
                        key = f"{ch}_{level}"
                        results[key] = {"pct_change": pct_change, "abs_change": abs_change,
                                        "at_1x": contrib_1x, "at_15x": contrib_15x}
                    # Print sorted within this level
                    level_keys = [f"{ch}_{level}" for ch in channels if f"{ch}_{level}" in results]
                    for key in sorted(level_keys, key=lambda c: results[c]["pct_change"], reverse=True):
                        r = results[key]
                        sign = "+" if r["abs_change"] >= 0 else ""
                        ch_name = key.rsplit(f"_{level}", 1)[0]
                        print(f"      {ch_name}: {sign}{r['pct_change']:.0%} contribution "
                              f"({sign}{r['abs_change']:,.0f})")
            else:
                dims = None

        if not dims:
            for ch in channels:
                contrib_1x = float(sweep_result.sel(
                    channel=ch, sweep=sweep_coords[sweep_idx_1x]
                ).mean())
                contrib_15x = float(sweep_result.sel(
                    channel=ch, sweep=sweep_coords[sweep_idx_15x]
                ).mean())
                abs_change = contrib_15x - contrib_1x
                pct_change = (contrib_15x / contrib_1x - 1) if contrib_1x > 0 else float("inf")
                results[ch] = {"pct_change": pct_change, "abs_change": abs_change,
                               "at_1x": contrib_1x, "at_15x": contrib_15x}
            for ch in sorted(results, key=lambda c: results[c]["pct_change"], reverse=True):
                r = results[ch]
                sign = "+" if r["abs_change"] >= 0 else ""
                print(f"    {ch}: {sign}{r['pct_change']:.0%} contribution "
                      f"({sign}{r['abs_change']:,.0f})")

        if results:
            most_resp = max(results, key=lambda c: results[c]["pct_change"])
            least_resp = min(results, key=lambda c: results[c]["pct_change"])
            print(f"  Most responsive: {most_resp}, least responsive: {least_resp}")
    else:
        print("\n  Sensitivity text summary unavailable "
              "(no sensitivity_analysis group in idata)")


def roas_analysis(mmm, df, output_dir, *, target_col, channel_columns, dims,
                  roas_applicable=True):
    """ROAS analysis and forest plot.

    Args:
        roas_applicable: If False, skip ROAS (channels not in monetary units).
    """
    print("\n=== ROAS ===")
    if not roas_applicable:
        print("  SKIPPED — channels are not in comparable monetary units.")
        print("  ROAS requires all channel inputs and target to be in monetary units.")
        print("  Use budget optimization for directional guidance on reallocation.")
        return

    roas_df = mmm.summary.roas(frequency="all_time")
    print(roas_df)
    roas_df.to_csv(output_dir / "roas.csv", index=False)
    print(f"  Saved {output_dir / 'roas.csv'}")

    var_name = "channel_contribution_original_scale" if \
        "channel_contribution_original_scale" in mmm.idata["posterior"] \
        else "channel_contribution"
    contrib = mmm.idata["posterior"][var_name]

    X = df.drop(columns=[target_col])
    if dims:
        dim_name = dims[0]
        if dim_name in contrib.dims:
            levels = contrib.coords[dim_name].values
            fig, axes = plt.subplots(1, len(levels), figsize=(8 * len(levels), 6))
            if len(levels) == 1:
                axes = [axes]
            for ax, level in zip(axes, levels):
                c_level = contrib.sel({dim_name: level}).sum(dim="date")
                level_mask = df[dim_name] == level if dim_name in df.columns else slice(None)
                level_spend = X.loc[level_mask, channel_columns].sum().values
                roas_samples = c_level / level_spend[np.newaxis, np.newaxis, :]
                az.plot_forest(roas_samples, combined=True, ax=ax)
                ax.set_title(f"ROAS - {level}")
            fig.tight_layout()
        else:
            spend_sum = X[channel_columns].sum().values
            roas_samples = contrib.sum(dim="date") / spend_sum[np.newaxis, np.newaxis, :]
            fig, ax = plt.subplots(figsize=(10, 6))
            az.plot_forest(roas_samples, combined=True, ax=ax)
            ax.set_title("ROAS by Channel")
    else:
        spend_sum = X[channel_columns].sum().values
        roas_samples = contrib.sum(dim="date") / spend_sum[np.newaxis, np.newaxis, :]
        fig, ax = plt.subplots(figsize=(10, 6))
        az.plot_forest(roas_samples, combined=True, ax=ax)
        ax.set_title("ROAS by Channel")

    savefig(fig, output_dir, "15_roas_forest")

    # --- ROAS ranking summary ---
    # Compute per-channel ROAS (pooled across geos)
    X = df.drop(columns=[target_col])
    spend_total = X[channel_columns].sum()
    contrib_total = contrib.mean(dim=("chain", "draw")).sum(
        dim=[d for d in contrib.dims if d not in ("chain", "draw", "channel")]
    )
    roas_median = {}
    for ch in channel_columns:
        ch_contrib = float(contrib_total.sel(channel=ch).values)
        ch_spend = float(spend_total[ch])
        roas_median[ch] = ch_contrib / ch_spend if ch_spend > 0 else 0.0

    print(f"\n  ROAS ranking (all_time, posterior mean):")
    for rank, ch in enumerate(sorted(roas_median, key=roas_median.get, reverse=True), 1):
        print(f"    {rank}. {ch}: {roas_median[ch]:.4f}")
    best_ch = max(roas_median, key=roas_median.get)
    worst_ch = min(roas_median, key=roas_median.get)
    print(f"  Best: {best_ch} ({roas_median[best_ch]:.4f}), "
          f"Worst: {worst_ch} ({roas_median[worst_ch]:.4f})")


def budget_optimization(mmm, df, output_dir, *, target_col, date_col,
                        channel_columns, dims, pct=0.5, reweight_df=None,
                        seed=None, roas_applicable=True):
    """Budget optimization following the pymc-marketing case study approach.

    Args:
        df: DataFrame used for optimization dates, budget, and bounds.
        pct: Risk appetite — fraction of historical spend used as bounds
             (e.g. 0.5 means channels can vary +/-50% from historical).
        reweight_df: Optional separate DataFrame for uplift reweighting
                     (e.g. training data). If None, uses df for both.
        roas_applicable: If False, show allocation as multipliers/percentages
                         only (channels not in comparable monetary units).
    """
    print("\n=== Budget Optimization ===")
    if not roas_applicable:
        print("  NOTE: Channels are not in comparable monetary units.")
        print("  Showing relative changes only — use as directional guidance")
        print("  (increase/decrease channel activity), not direct budget amounts.\n")

    X = df.drop(columns=[target_col])
    rng = np.random.default_rng(seed)

    dates = sorted(df[date_col].unique())
    start_date = str(pd.Timestamp(dates[0]).date())
    end_date = str(pd.Timestamp(dates[-1]).date())
    num_periods = len(dates)

    if dims:
        dim_name = dims[0]
        levels = sorted(df[dim_name].unique())
        n_levels = len(levels)
    else:
        levels = None
        dim_name = None
        n_levels = 1

    all_budget = X[channel_columns].sum().sum()
    per_channel_budget = all_budget / (num_periods * len(channel_columns))
    print(f"  Per-channel budget per period: {per_channel_budget:,.0f}")

    mean_spend = X[channel_columns].sum(axis=0) / (num_periods * len(channel_columns))
    print(f"  Risk appetite (pct): {pct} — bounds are +/-{pct:.0%} of historical")

    if levels:
        mean_spend_per_level = mean_spend / n_levels
        bounds_data = np.zeros((n_levels, len(channel_columns), 2))
        for j, ch in enumerate(channel_columns):
            v = mean_spend_per_level[ch]
            bounds_data[:, j, 0] = np.maximum(0, (1 - pct) * v)
            bounds_data[:, j, 1] = (1 + pct) * v
        budget_bounds_xr = xr.DataArray(
            data=bounds_data,
            dims=[dim_name, "channel", "bound"],
            coords={dim_name: levels, "channel": channel_columns, "bound": ["lower", "upper"]},
        )
    else:
        budget_bounds_xr = xr.DataArray(
            data=[[max(0, (1 - pct) * v), (1 + pct) * v] for v in mean_spend.values],
            dims=["channel", "bound"],
            coords={"channel": channel_columns, "bound": ["lower", "upper"]},
        )

    optimizable_model = MultiDimensionalBudgetOptimizerWrapper(
        model=mmm,
        start_date=start_date,
        end_date=end_date,
    )

    # Workaround: pymc-marketing bug — budget_optimizer extracts bounds
    # positionally via .values but the optimizer variable follows
    # model.coords["channel"] (alphabetically sorted by xarray), not
    # mmm.channel_columns (original order). Reindex bounds to match.
    # See: https://github.com/pymc-labs/pymc-marketing/issues/2323
    model_channel_order = list(mmm.model.coords["channel"])
    budget_bounds_xr = budget_bounds_xr.reindex(channel=model_channel_order)

    allocation, opt_result = optimizable_model.optimize_budget(
        budget=per_channel_budget,
        budget_bounds=budget_bounds_xr,
        minimize_kwargs={
            "method": "SLSQP",
            "options": {"ftol": 1e-4, "maxiter": 10_000},
        },
    )

    print(f"  Optimization success: {opt_result.success}")
    print(f"  Optimal allocation:\n{allocation}")

    if hasattr(allocation, "dims") and levels and dim_name in allocation.dims:
        alloc_per_channel = allocation.sum(dim=dim_name)
    else:
        alloc_per_channel = allocation
    # Use .sel() to align by channel name, not positional .values
    # (model coords are alphabetical, channel_columns may differ)
    alloc_series = pd.Series(
        {ch: float(alloc_per_channel.sel(channel=ch)) for ch in channel_columns},
    )
    comparison = pd.DataFrame({
        "optimized": alloc_series,
        "historical": mean_spend,
    }).sort_index(ascending=False)
    fig, ax = plt.subplots(figsize=(10, 6))
    comparison.plot.barh(ax=ax, color=["C1", "C0"])
    ax.set_title("Budget Allocation: Optimized vs Historical")
    ax.set_xlabel("Spend per period (per channel)")
    savefig(fig, output_dir, "16_budget_allocation_comparison")

    shares_hist = mean_spend / mean_spend.sum()
    shares_opt = alloc_series / alloc_series.sum()
    multipliers = shares_opt / shares_hist

    print("\n  Channel multipliers (optimized / historical share):")
    for ch in channel_columns:
        print(f"    {ch}: {multipliers[ch]:.3f}")

    # Reallocation summary: increases vs decreases
    pct_changes = (alloc_series - mean_spend) / mean_spend
    increases = pct_changes[pct_changes > 0.01].sort_values(ascending=False)
    decreases = pct_changes[pct_changes < -0.01].sort_values()
    if len(increases) > 0:
        print(f"\n  Reallocation — increase:")
        for ch in increases.index:
            print(f"    {ch}: {pct_changes[ch]:+.0%}")
    if len(decreases) > 0:
        print(f"  Reallocation — decrease:")
        for ch in decreases.index:
            print(f"    {ch}: {pct_changes[ch]:+.0%}")

    # Bounds binding check (use .sel() for channel alignment)
    bounds_hit = []
    if levels:
        for j, ch in enumerate(channel_columns):
            alloc_ch = float(alloc_per_channel.sel(channel=ch)) / n_levels
            lb = bounds_data[0, j, 0]
            ub = bounds_data[0, j, 1]
            if abs(alloc_ch - lb) / max(abs(lb), 1e-8) < 0.01:
                bounds_hit.append(f"{ch} (lower)")
            if abs(alloc_ch - ub) / max(abs(ub), 1e-8) < 0.01:
                bounds_hit.append(f"{ch} (upper)")
    else:
        for j, ch in enumerate(channel_columns):
            alloc_ch = float(alloc_per_channel.sel(channel=ch))
            lb = max(0, (1 - pct) * float(mean_spend.values[j]))
            ub = (1 + pct) * float(mean_spend.values[j])
            if abs(alloc_ch - lb) / max(abs(lb), 1e-8) < 0.01:
                bounds_hit.append(f"{ch} (lower)")
            if abs(alloc_ch - ub) / max(abs(ub), 1e-8) < 0.01:
                bounds_hit.append(f"{ch} (upper)")
    if bounds_hit:
        print(f"  Bounds hit: {', '.join(bounds_hit)}")
    else:
        print(f"  Bounds hit: none (all channels within interior)")

    # Reweight training data (or same df) to compute uplift
    X_rw = reweight_df.drop(columns=[target_col]) if reweight_df is not None else X
    X_weighted = X_rw.copy()
    for ch in channel_columns:
        X_weighted[ch] = X_weighted[ch] * multipliers[ch]

    normalization = (
        X_rw[channel_columns].sum().sum()
        / X_weighted[channel_columns].sum().sum()
    )
    X_weighted[channel_columns] = X_weighted[channel_columns] * normalization

    # Sample both channel_contribution (for per-channel uplift) and y (for
    # total sales uplift). We need y because total sales uplift must account
    # for baseline revenue (intercept + controls + seasonality), not just
    # channel contributions.
    contrib_var = "channel_contribution"
    var_names = [contrib_var, "y"]

    print("\n  Sampling posterior predictive (original)...")
    pp_original = mmm.sample_posterior_predictive(
        X_rw, var_names=var_names, extend_idata=False,
        progressbar=False, random_seed=rng,
    )
    print("  Sampling posterior predictive (reweighted)...")
    pp_weighted = mmm.sample_posterior_predictive(
        X_weighted, var_names=var_names, extend_idata=False,
        progressbar=False, random_seed=rng,
    )

    def _get_var(result, var):
        if hasattr(result, "posterior_predictive"):
            return result["posterior_predictive"][var]
        return result[var]

    orig_contrib = _get_var(pp_original, contrib_var).sum(
        dim=("date", "channel")
    )
    weighted_contrib = _get_var(pp_weighted, contrib_var).sum(
        dim=("date", "channel")
    )
    uplift_samples = weighted_contrib / orig_contrib - 1

    if levels and dim_name in uplift_samples.dims:
        uplift_per_level = uplift_samples
        for level in uplift_per_level.coords[dim_name].values:
            vals = uplift_per_level.sel({dim_name: level}).values.ravel()
            med = np.median(vals)
            lo, hi = np.percentile(vals, [3, 97])
            print(f"  Channel contribution uplift ({level}): {med:+.1%} [{lo:+.1%}, {hi:+.1%}]")
        uplift_all = uplift_samples.mean(dim=dim_name).values.ravel()
    else:
        uplift_all = uplift_samples.values.ravel()

    med = np.median(uplift_all)
    lo, hi = np.percentile(uplift_all, [3, 97])
    print(f"  Channel contribution uplift: {med:+.1%} [{lo:+.1%}, {hi:+.1%}]")

    # --- Total sales uplift ---
    # Use full model prediction y (includes intercept, controls, seasonality).
    # Using channel_contribution alone would overstate uplift because the
    # denominator would exclude baseline revenue.
    y_orig = _get_var(pp_original, "y")
    y_weighted = _get_var(pp_weighted, "y")

    # Sum across geos if present
    if levels and dim_name in y_orig.dims:
        y_orig = y_orig.sum(dim=dim_name)
        y_weighted = y_weighted.sum(dim=dim_name)

    y_orig_total = y_orig.sum(dim="date")
    y_weighted_total = y_weighted.sum(dim="date")
    sales_uplift = y_weighted_total / y_orig_total - 1
    sales_vals = sales_uplift.values.ravel()
    s_med = np.median(sales_vals)
    s_lo, s_hi = np.percentile(sales_vals, [3, 97])
    print(f"  Total sales uplift: {s_med:+.1%} [{s_lo:+.1%}, {s_hi:+.1%}]")

    # --- Sales curve: channel contributions before/after reallocation ---
    # Reduce all dims except "date" for per-date summaries
    def _reduce(da, func="median"):
        rdims = [d for d in da.dims if d != "date"]
        if func == "median":
            return da.median(dim=rdims).values
        elif func == "lo":
            return da.quantile(0.03, dim=rdims).values
        elif func == "hi":
            return da.quantile(0.97, dim=rdims).values

    c_med = np.median(uplift_all)

    # Use historical y as the baseline for the sales curve plot.
    hist_df = reweight_df if reweight_df is not None else df
    hist_y = hist_df.groupby(date_col)[target_col].sum().sort_index()
    dates = hist_y.index
    has_hist_y = hist_y.values.sum() > 0

    # Channel contribution per-date (for bottom plot)
    orig_ch_per_date = _get_var(pp_original, contrib_var).sum(dim="channel")
    weighted_ch_per_date = _get_var(pp_weighted, contrib_var).sum(dim="channel")
    if levels and dim_name in orig_ch_per_date.dims:
        orig_ch_per_date = orig_ch_per_date.sum(dim=dim_name)
        weighted_ch_per_date = weighted_ch_per_date.sum(dim=dim_name)

    if has_hist_y:
        # Compute per-date ratio using full model prediction y
        ratio_per_date = y_weighted / y_orig.where(y_orig != 0, 1)
        ratio_med = _reduce(ratio_per_date)
        ratio_lo = _reduce(ratio_per_date, "lo")
        ratio_hi = _reduce(ratio_per_date, "hi")

        sim_y_med = hist_y.values * ratio_med
        sim_y_lo = hist_y.values * ratio_lo
        sim_y_hi = hist_y.values * ratio_hi

        fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

        # Top: total sales
        ax = axes[0]
        ax.plot(dates, hist_y.values, label="Historical", color="C0", lw=1.5)
        ax.plot(dates, sim_y_med, label="After Reallocation", color="C1", lw=1.5)
        ax.fill_between(dates, sim_y_lo, sim_y_hi, alpha=0.2, color="C1")
        ax.set_title(f"Total Sales ({s_med:+.1%} uplift)")
        ax.set_ylabel("Sales")
        ax.legend()

        # Bottom: channel contributions only
        ax = axes[1]
        ax.plot(dates, _reduce(orig_ch_per_date), label="Historical", color="C0", lw=1.5)
        ax.plot(dates, _reduce(weighted_ch_per_date), label="After Reallocation", color="C1", lw=1.5)
        ax.fill_between(dates, _reduce(weighted_ch_per_date, "lo"),
                         _reduce(weighted_ch_per_date, "hi"), alpha=0.2, color="C1")
        ax.set_title(f"Channel Contributions ({c_med:+.1%} uplift)")
        ax.set_xlabel("Date")
        ax.set_ylabel("Channel Contribution (scaled)")
        ax.legend()
    else:
        # No valid historical y — show channel contributions only
        fig, ax = plt.subplots(figsize=(14, 5))
        ax.plot(dates if len(dates) == len(_reduce(orig_ch_per_date)) else range(len(_reduce(orig_ch_per_date))),
                _reduce(orig_ch_per_date), label="Historical", color="C0", lw=1.5)
        ax.plot(dates if len(dates) == len(_reduce(weighted_ch_per_date)) else range(len(_reduce(weighted_ch_per_date))),
                _reduce(weighted_ch_per_date), label="After Reallocation", color="C1", lw=1.5)
        ax.fill_between(dates if len(dates) == len(_reduce(weighted_ch_per_date)) else range(len(_reduce(weighted_ch_per_date))),
                         _reduce(weighted_ch_per_date, "lo"),
                         _reduce(weighted_ch_per_date, "hi"), alpha=0.2, color="C1")
        ax.set_title(f"Channel Contributions ({c_med:+.1%} uplift)")
        ax.set_xlabel("Date")
        ax.set_ylabel("Channel Contribution (scaled)")
        ax.legend()

    fig.tight_layout()
    savefig(fig, output_dir, "17_sales_after_reallocation")


# =========================================================================
# Function API
# =========================================================================

def analyze_mmm(mmm, df, idata_path, *, output_dir=None,
                config=None, skip_budget=False, budget_df=None, seed=None,
                roas_applicable=True):
    """Run full analysis pipeline on a fitted MMM.

    Args:
        mmm: A built MMM instance (model graph constructed, but idata will be
             loaded from idata_path). Must have original_scale_vars registered.
        df: DataFrame with all required columns.
        idata_path: Path to saved idata.nc file.
        output_dir: Where to save figures/CSVs. If None, uses idata_path's parent.
        config: Optional ground_truth.json dict. When provided, enables:
                - parameter_recovery (GT comparison)
                - GT saturation curve overlay
                When None, these are skipped — all other analyses still run.
        skip_budget: Skip the (slow) budget optimization step.
        budget_df: Optional separate DataFrame for budget optimization (e.g. test
                   set). If None, uses df. This allows fitting on training data
                   while optimizing over a forward-looking period.
        seed: Random seed (None for random).
        roas_applicable: If False, skip ROAS analysis and show budget optimization
                         as directional guidance only (channels not in monetary units).

    Returns:
        dict with keys: "diagnostics_summary", "coverage_df" (None if no config).
    """
    idata_path = Path(idata_path)
    if output_dir is None:
        output_dir = idata_path.parent
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract model metadata from MMM (with config fallback)
    target_col = _get_target_col(mmm, config)
    date_col = _get_date_col(mmm, config)
    channel_columns = _get_channel_columns(mmm, config)
    dims = _get_dims(mmm, config)

    rng = np.random.default_rng(seed)

    pd.set_option("display.max_columns", 20)
    pd.set_option("display.width", 200)

    X = df.drop(columns=[target_col])
    y = df[target_col]

    # Prior predictive (sampled fresh, before loading posterior)
    prior_predictive_checks(mmm, X, y, output_dir, rng)

    # Load saved idata, preserving the prior group
    print("\n=== Loading Fitted Model ===")
    prior_idata = mmm.idata
    idata = az.from_netcdf(idata_path)
    if "prior" in prior_idata and "prior" not in idata:
        idata.add_groups(prior=prior_idata["prior"])
    mmm.idata = idata

    # Run analysis pipeline
    diagnostics_summary = model_diagnostics(mmm, output_dir)
    posterior_predictive_checks(mmm, df, output_dir,
                                target_col=target_col, dims=dims,
                                date_col=date_col)

    coverage_df = None
    if config is not None:
        coverage_df = parameter_recovery(mmm, config, df, output_dir)
    else:
        print("\n=== Parameter Recovery (skipped — no config) ===")

    contribution_split = channel_contributions(mmm, output_dir, dims=dims)
    sat_operating_points = saturation_curves(mmm, df, output_dir, config=config, dims=dims)
    sensitivity_analysis(mmm, output_dir, dims=dims)
    roas_analysis(mmm, df, output_dir,
                  target_col=target_col, channel_columns=channel_columns, dims=dims,
                  roas_applicable=roas_applicable)

    if not skip_budget:
        budget_optimization(mmm, budget_df if budget_df is not None else df,
                            output_dir,
                            target_col=target_col, date_col=date_col,
                            channel_columns=channel_columns, dims=dims,
                            reweight_df=df, seed=seed,
                            roas_applicable=roas_applicable)
    else:
        print("\n=== Budget Optimization (skipped) ===")

    contrib_df = mmm.summary.contributions(frequency="all_time")
    contrib_df.to_csv(output_dir / "contributions.csv", index=False)
    print(f"\n  Saved {output_dir / 'contributions.csv'}")

    # --- Build analysis_summary.json ---
    summary = {}

    # Diagnostics
    diverging = mmm.idata["sample_stats"]["diverging"]
    n_div = int(diverging.sum().item())
    n_total = int(diverging.size)
    summary["divergences"] = n_div
    summary["divergence_rate"] = round(n_div / max(n_total, 1), 4)

    rhat = diagnostics_summary["r_hat"].dropna()
    summary["rhat_max"] = round(float(rhat.max()), 4)
    summary["rhat_gt_11"] = int((rhat > 1.1).sum())
    if "ess_bulk" in diagnostics_summary.columns:
        summary["ess_bulk_min"] = round(float(diagnostics_summary["ess_bulk"].dropna().min()), 1)
        summary["ess_tail_min"] = round(float(diagnostics_summary.get("ess_tail", diagnostics_summary["ess_bulk"]).dropna().min()), 1)

    # Posterior predictive R-squared
    if "y_original_scale" in mmm.idata.get("posterior_predictive", {}):
        y_pp = mmm.idata["posterior_predictive"]["y_original_scale"]
    elif "y_original_scale" in mmm.idata["posterior"]:
        y_pp = mmm.idata["posterior"]["y_original_scale"]
    else:
        y_pp = None
    if y_pp is not None:
        y_pp_mean = y_pp.mean(dim=("chain", "draw"))
        # Align predictions with observations (geo-aware)
        all_y_true, all_y_pred = [], []
        geo_col = "geo" if ("geo" in y_pp_mean.dims and "geo" in df.columns) else None
        if geo_col:
            for level in y_pp_mean.coords[geo_col].values:
                mask = df[geo_col] == level
                all_y_true.append(df.loc[mask, target_col].values)
                all_y_pred.append(y_pp_mean.sel({geo_col: level}).values)
        else:
            all_y_true.append(df[target_col].values)
            all_y_pred.append(y_pp_mean.values.ravel())
        y_true = np.concatenate(all_y_true)
        y_pred = np.concatenate(all_y_pred)
        ss_res = np.sum((y_true - y_pred) ** 2)
        ss_tot = np.sum((y_true - y_true.mean()) ** 2)
        summary["r_squared"] = round(float(1 - ss_res / ss_tot), 6)
        nonzero = np.abs(y_true) > 1e-8
        summary["mape"] = round(float(np.mean(np.abs(y_true[nonzero] - y_pred[nonzero]) / np.abs(y_true[nonzero]))), 6)

    # Parameter recovery
    if coverage_df is not None:
        total = len(coverage_df)
        covered = int(coverage_df["in_94_hdi"].sum())
        summary["parameter_coverage"] = f"{covered}/{total}"
        summary["parameter_coverage_rate"] = round(covered / total, 4)

    # Contribution split
    if contribution_split:
        summary["contribution_split"] = contribution_split

    # Saturation operating points
    if sat_operating_points:
        summary["saturation_operating_points"] = sat_operating_points

    # Write JSON
    summary_path = output_dir / "analysis_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Saved {summary_path}")

    print("\n=== Done ===")
    print(f"All results saved to {output_dir}")

    return {
        "diagnostics_summary": diagnostics_summary,
        "coverage_df": coverage_df,
        "summary": summary,
    }
