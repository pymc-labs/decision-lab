# HazardModel — Bayesian Survival Analysis

Fit a parametric survival model to historical event-resolution durations. Predicts time-to-event as a probability distribution.

## When to use

- You have N ≥ 5 historical events with **known or bounded durations** (e.g., past analogous episodes with recorded resolution times).
- Some events may be **right-censored** (still ongoing at the time of data collection) — the model handles this.
- You want a full survival curve S(t), not just a point estimate.

## Data preparation

You need a table with one row per historical analogous event:

| column | type | notes |
|---|---|---|
| `duration_days` | int/float | Days from event start to resolution. For ongoing events: days so far. |
| `censored` | bool | `True` if event has not yet resolved (right-censored). |
| `context` (optional) | string | Free-text label for reference in notes |

The current event (the one you are forecasting) is always right-censored at its current duration.

## PyMC implementation

```python
import pymc as pm
import numpy as np
from arviz_stats import summary

# --- inputs (fill from your data) ---
durations = np.array([...])   # days to resolution (or current duration if censored)
censored  = np.array([...], dtype=bool)  # True = still ongoing / right-censored

# observed: events that resolved
observed_dur  = durations[~censored]
# censored: events still ongoing — contribute P(T > t) to likelihood
censored_dur  = durations[censored]

with pm.Model() as hazard_model:
    # Weibull shape and scale (weakly informative priors)
    # alpha > 1 → hazard increases over time (wear-out)
    # alpha < 1 → hazard decreases over time (infant mortality)
    # alpha = 1 → constant hazard (exponential)
    alpha = pm.Gamma("alpha", mu=1.5, sigma=0.75)   # shape
    beta  = pm.Gamma("beta",  mu=np.mean(durations), sigma=np.std(durations) + 1)  # scale

    # Likelihood for resolved events
    resolved_obs = pm.Weibull("resolved_obs", alpha=alpha, beta=beta,
                              observed=observed_dur)

    # Likelihood contribution for right-censored events: log P(T > t)
    # P(T > t | Weibull) = exp(-(t/beta)^alpha)  →  log-surv = -(t/beta)^alpha
    log_surv = -(censored_dur / beta) ** alpha
    censored_potential = pm.Potential("censored", log_surv.sum())

    idata = pm.sample(
        draws=500,
        tune=500,
        chains=6,
        backend="numba",
        nuts_sampler="nutpie",
        nuts={"target_accept": 0.92},
        # do NOT pass random_seed
    )
    pm.stats.compute_log_likelihood(idata, model=hazard_model)
    pm.stats.compute_log_prior(idata, model=hazard_model)
```

## Extracting the forecast

After sampling, compute the survival curve and convert to `forecast.json` fields:

```python
# Posterior predictive survival function at specific horizons
from scipy.stats import weibull_min

alpha_samples = idata.posterior["alpha"].values.flatten()
beta_samples  = idata.posterior["beta"].values.flatten()

horizon_days = [90, 180, 365]  # days from today — set from orchestrator horizons
p_event_by_horizon = []
ci_low_by_horizon  = []
ci_high_by_horizon = []

for t in horizon_days:
    # P(event by t) = 1 - S(t) = 1 - exp(-(t/beta)^alpha)
    p_samples = 1 - np.exp(-(t / beta_samples) ** alpha_samples)
    p_event_by_horizon.append(float(np.mean(p_samples)))
    ci_low_by_horizon.append(float(np.percentile(p_samples, 3)))   # ~94% HDI low
    ci_high_by_horizon.append(float(np.percentile(p_samples, 97))) # ~94% HDI high

# Median time to event: solve S(t) = 0.5
# t_med = beta * (-ln(0.5))^(1/alpha)
t_med_samples = beta_samples * (np.log(2) ** (1.0 / alpha_samples))
median_days = float(np.mean(t_med_samples))
p10_days    = float(np.percentile(t_med_samples, 10))
p90_days    = float(np.percentile(t_med_samples, 90))
```

### Derived quantities for PriorSensitivity (psense)

Attach per-draw cumulative probabilities to `idata.posterior` before running
[`prior_sensitivity_psense.md`](prior_sensitivity_psense.md):

```python
import xarray as xr

alpha = idata.posterior["alpha"]
beta = idata.posterior["beta"]
horizon_days = np.array([...])  # same as orchestrator horizons

t = xr.DataArray(horizon_days, dims="horizon", coords={"horizon": horizon_days})
p_by_h = 1.0 - np.exp(-((t / beta) ** alpha))
p_by_h = p_by_h.transpose("chain", "draw", "horizon")

idata.posterior["p_event_by_horizon"] = p_by_h
```

## Convergence diagnostics

```python
summary_df = summary(idata)
rhat_max      = float(summary_df["r_hat"].max())
ess_bulk_min  = float(summary_df["ess_bulk"].min())
divergences   = int(idata.sample_stats["diverging"].sum())
total_draws   = int(idata.sample_stats.sizes["chain"] * idata.sample_stats.sizes["draw"])
divergence_rate = divergences / total_draws
```

## Model checks

**HistoricalCalibration** — primary check. Apply the model to past events in your
reference class (leave-one-out or hold-out): did the model assign high probability
to the events that resolved quickly and low probability to those that took longer?
See `model_checks.md` for Brier score implementation.

**PriorSensitivity** — run derived-quantity psense on `p_event_by_horizon` per
[`prior_sensitivity_psense.md`](prior_sensitivity_psense.md) and [`model_checks.md`](model_checks.md).
If WARN/FAIL at T_mid, disclose prior dependence (common with small N); not automatic invalidation.

**ConsistencyCheck** — verify that S(t) is strictly decreasing (survival function
should never increase). Check P(event by T1) ≤ P(event by T2) for all T1 < T2.

## Gotchas

- **Too few events**: With N < 5, the likelihood is very weak and the posterior is prior-dominated. Report this in `summary.md` and widen the prior to reflect ignorance.
- **All events censored**: This happens when no historical events have resolved. The model will still work but the posterior is entirely prior-driven. Flag clearly.
- **Mixture populations**: If some historical events resolved quickly (diplomatic) and some slowly (military), a single Weibull may be a bad fit. Consider a mixture model or document the limitation.
- **Current event duration**: The event you're forecasting may already have been ongoing for a long time. Include it as a right-censored observation — this raises the expected remaining duration via the hazard rate.
- **Scale of `beta`**: Beta is in the same units as `durations`. If durations are in days, beta is in days. Always verify units.

## Model variants

| Variant | When | Change |
|---|---|---|
| Exponential | Constant hazard expected | Set `alpha = 1` (constant) or use `pm.Exponential` directly |
| Log-normal | Roughly symmetric on log scale | Replace Weibull with `pm.LogNormal` |
| Mixture | Two distinct resolution modes | Add a `pm.Mixture` with two Weibull components |

### Log-logistic survival (non-monotonic hazard)

Appropriate when hazard is expected to first increase then decrease — e.g., events
that are more likely to resolve after an initial period of pressure but less likely
if they persist very long (negotiations that either close quickly or drag on).

```python
# Log-logistic: log(duration) ~ Logistic(μ, s)
# Equivalent to: duration ~ LogLogistic(alpha=exp(μ), beta=1/s)
log_dur_obs = np.log(observed_dur + 1e-9)
log_dur_cens = np.log(censored_dur + 1e-9)

with pm.Model() as loglogistic_model:
    mu = pm.Normal("mu", mu=np.mean(log_dur_obs), sigma=1.0)
    log_s = pm.Normal("log_s", mu=0.0, sigma=0.5)
    s = pm.Deterministic("s", pm.math.exp(log_s))

    # Likelihood for observed events: logistic PDF on log-scale
    pm.Logistic("resolved", mu=mu, s=s, observed=log_dur_obs)

    # Right-censored contribution: P(T > t) = 1 - CDF(log(t))
    log_surv = pm.math.log(1 - pm.math.invlogit((log_dur_cens - mu) / s) + 1e-9)
    pm.Potential("censored", log_surv.sum())

    idata = pm.sample(
        draws=500,
        tune=500,
        chains=6,
        backend="numba",
        nuts_sampler="nutpie",
        nuts={"target_accept": 0.9},
    )
    pm.stats.compute_log_likelihood(idata, model=loglogistic_model)
    pm.stats.compute_log_prior(idata, model=loglogistic_model)
```

Attach per-draw cumulative probabilities for psense:

```python
import xarray as xr
from scipy.special import expit

horizon_days = np.array([...])
t = xr.DataArray(horizon_days, dims="horizon", coords={"horizon": horizon_days})
p_by_h = expit((np.log(t + 1e-9) - idata.posterior["mu"]) / idata.posterior["s"])
p_by_h = p_by_h.transpose("chain", "draw", "horizon")
idata.posterior["p_event_by_horizon"] = p_by_h
```

### Two-component Weibull mixture (fast and slow resolvers)

Appropriate when the reference class has two distinct subpopulations: events that
resolve quickly (diplomatic breakthroughs) and events that take much longer
(prolonged stalemates).

```python
with pm.Model() as mixture_model:
    # Mixing weight
    w = pm.Beta("w", alpha=2, beta=2)  # prior: roughly equal weight

    # Fast component (short durations)
    alpha_fast = pm.Gamma("alpha_fast", mu=2.0, sigma=1.0)
    beta_fast  = pm.Gamma("beta_fast", mu=90.0, sigma=45.0)   # ~3 months

    # Slow component (long durations)
    alpha_slow = pm.Gamma("alpha_slow", mu=1.5, sigma=0.75)
    beta_slow  = pm.Gamma("beta_slow", mu=365.0, sigma=180.0)  # ~1 year

    # Mixture likelihood for observed events
    weibull_fast = pm.Weibull.dist(alpha=alpha_fast, beta=beta_fast)
    weibull_slow = pm.Weibull.dist(alpha=alpha_slow, beta=beta_slow)
    pm.Mixture("resolved", w=pm.math.stack([w, 1 - w]),
               comp_dists=[weibull_fast, weibull_slow],
               observed=observed_dur)

    # Right-censored: mixture survival S(t) = w*S_fast(t) + (1-w)*S_slow(t)
    if len(censored_dur) > 0:
        surv_fast = pm.math.exp(-(censored_dur / beta_fast) ** alpha_fast)
        surv_slow = pm.math.exp(-(censored_dur / beta_slow) ** alpha_slow)
        log_surv = pm.math.log(w * surv_fast + (1 - w) * surv_slow + 1e-12)
        pm.Potential("censored", log_surv.sum())

    idata = pm.sample(
        draws=500,
        tune=500,
        chains=6,
        backend="numba",
        nuts_sampler="nutpie",
        nuts={"target_accept": 0.92},
    )
    pm.stats.compute_log_likelihood(idata, model=mixture_model)
    pm.stats.compute_log_prior(idata, model=mixture_model)
```

For psense, attach mixture CDF per horizon (same pattern as Weibull, with component weights):

```python
t = xr.DataArray(horizon_days, dims="horizon", coords={"horizon": horizon_days})
cdf_fast = 1.0 - np.exp(-((t / idata.posterior["beta_fast"]) ** idata.posterior["alpha_fast"]))
cdf_slow = 1.0 - np.exp(-((t / idata.posterior["beta_slow"]) ** idata.posterior["alpha_slow"]))
p_by_h = idata.posterior["w"] * cdf_fast + (1 - idata.posterior["w"]) * cdf_slow
p_by_h = p_by_h.transpose("chain", "draw", "horizon")
idata.posterior["p_event_by_horizon"] = p_by_h
```
