---
name: PyMC Basics
description: >
  Core PyMC patterns for hierarchical Bayesian regression: sampling parameters,
  convergence diagnostics, hierarchical model structure with coords/dims,
  prior predictive checks, and ArviZ summaries. Use for any PyMC modeling task.
---

# PyMC Basics

## Sampling

```python
with model:
    idata = pm.sample(
        draws=1000,        # posterior samples per chain (1000 is usually enough)
        tune=1000,         # tuning steps discarded before draws
        chains=2,          # 2 chains minimum to compute R-hat
        target_accept=0.9, # increase toward 0.99 if divergences persist
        random_seed=None,  # leave None so parallel instances produce diverse results
    )
```

**Common adjustments:**
- Divergences > 1%: raise `target_accept` to 0.95 or 0.99
- Slow sampling: `nuts_sampler="numpyro"` (requires numpyro installed)
- Shape errors at init: check that all data arrays have matching lengths

---

## Convergence diagnostics

Always run after sampling:

```python
summary = az.summary(idata, var_names=["alpha", "beta", "sigma"])
print(summary[["mean", "hdi_3%", "hdi_97%", "r_hat", "ess_bulk"]])
```

**Thresholds — all must pass:**

| Diagnostic | Pass | Warning | Fail |
|-----------|------|---------|------|
| R-hat | < 1.05 | 1.05–1.1 | > 1.1 |
| ESS bulk | > 400 | 200–400 | < 200 |
| Divergences | 0 | 1–10 | > 10 |

```python
# Count divergences
n_div = idata.sample_stats["diverging"].values.sum()

# Quick check
assert summary["r_hat"].max() < 1.05, "R-hat too high"
assert summary["ess_bulk"].min() > 400, "ESS too low"
```

If convergence fails: report the diagnostics honestly. Do not proceed to inference.

---

## Hierarchical model pattern (partial pooling)

Partial pooling shrinks group estimates toward a common mean — the key advantage over separate models or fully pooled models.

```python
import pymc as pm
import numpy as np

# coords make dimensions explicit and labels readable in ArviZ
coords = {
    "obs": np.arange(len(y)),
    "group": group_labels,   # e.g. ["Adelie", "Chinstrap", "Gentoo"]
}

with pm.Model(coords=coords) as hierarchical_model:
    # Hyperpriors — shared across groups
    mu_alpha = pm.Normal("mu_alpha", mu=0, sigma=10)
    sigma_alpha = pm.HalfNormal("sigma_alpha", sigma=5)
    mu_beta = pm.Normal("mu_beta", mu=0, sigma=2)
    sigma_beta = pm.HalfNormal("sigma_beta", sigma=1)

    # Group-level parameters — one per group, shrunk toward hyperpriors
    alpha = pm.Normal("alpha", mu=mu_alpha, sigma=sigma_alpha, dims="group")
    beta = pm.Normal("beta", mu=mu_beta, sigma=sigma_beta, dims="group")

    # Observation noise
    sigma = pm.HalfNormal("sigma", sigma=2)

    # Linear predictor — index into group parameters with group_idx
    mu = alpha[group_idx] + beta[group_idx] * x

    # Likelihood
    y_obs = pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y, dims="obs")
```

**Key points:**
- `dims="group"` tells PyMC the parameter has one value per group
- `group_idx` is an integer array mapping each observation to its group
- `alpha[group_idx]` broadcasts correctly without any reshape

**Building group_idx from a categorical column:**

```python
import pandas as pd

df = df.dropna()
group_labels, group_idx = pd.factorize(df["species"])
# group_labels: array of unique species names (use as coords["group"])
# group_idx:    integer index per row (use in alpha[group_idx])
```

---

## Prior predictive check

Run before sampling to verify priors produce plausible data ranges:

```python
with model:
    prior_pred = pm.sample_prior_predictive(samples=100)

# Inspect the range of prior-predicted y values
prior_y = prior_pred.prior_predictive["y_obs"].values
print(f"Prior y range: [{prior_y.min():.1f}, {prior_y.max():.1f}]")
# If range is implausibly wide (e.g. -1e6 to 1e6), tighten priors
```

---

## ArviZ posterior summary

```python
import arviz as az

# Full summary table
summary = az.summary(idata, hdi_prob=0.94)  # 94% HDI is conventional in PyMC

# Per-group estimates when using dims
# e.g. for alpha with dims="group":
#   summary index will be "alpha[Adelie]", "alpha[Chinstrap]", "alpha[Gentoo]"

# Plot posteriors
az.plot_posterior(idata, var_names=["alpha", "beta"])

# Pair plot for correlations between parameters
az.plot_pair(idata, var_names=["mu_alpha", "mu_beta", "sigma"])
```

---

## Loading Palmer Penguins

```python
import seaborn as sns
import pandas as pd

df = sns.load_dataset("penguins").dropna()

# Key columns:
#   species:          Adelie / Chinstrap / Gentoo (use as grouping factor)
#   bill_length_mm:   predictor
#   bill_depth_mm:    outcome
#   body_mass_g:      alternative outcome
#   island, sex:      additional covariates

print(df.shape)            # (333, 7) after dropna
print(df["species"].value_counts())
```

---

## Common errors

**`ValueError: shape mismatch`** — `x` and `y` arrays have different lengths after filtering. Always apply the same mask to both.

**`SamplingError: Bad initial energy`** — initial parameter values are in a zero-density region. Check that observed data matches the model's expected scale; consider `pm.find_MAP()` to diagnose.

**`KeyError` in ArviZ summary** — variable name does not exist in the trace. Print `idata.posterior.data_vars` to see what was actually sampled.

**Slow sampling on first run** — PyTensor compiles C++ on first call. Subsequent runs in the same Python process are faster.
