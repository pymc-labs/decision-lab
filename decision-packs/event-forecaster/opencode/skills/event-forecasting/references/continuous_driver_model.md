# ContinuousDriverModel — Continuous Driver + First-Passage Time

Fit a Bayesian model to a continuous driver time-series (price, index, rate, or any measurable quantity). Forward-simulate paths and report the distribution of **first-passage times** — how long until the simulated driver first crosses a threshold that signals the event.

Use this method when:
- A measurable continuous driver (price, rate, index) has a plausible causal or leading relationship to the event.
- The event can be operationalised as the driver crossing a threshold (above or below).
- ≥ 100 observations of the driver are available.

## Event definition

You must operationalise the event as: **the driver crosses threshold τ in direction D.**

- **Direction D**: does the event fire when the driver rises above τ, or falls below τ? Choose based on the problem.
- **Threshold τ**: a concrete number derived from reference data, historical cases, or domain knowledge (see Step 1).

If the driver has already crossed τ (the event may have already occurred), re-examine the threshold definition or use a fallback threshold.

## Threshold selection

The threshold τ should be derived from the specific problem. Common approaches:

| Approach | When to use | Example |
|---|---|---|
| Percentile of a reference period | Driver returns to a "normal" level after a stress episode | 95th pct of a pre-stress baseline → stress premium evaporating |
| Value at a historical case | One past instance of the event at a known driver level | Driver level when a previous resolution occurred |
| Expert-elicited value | No historical cases or natural reference period | Domain expert specifies "event fires when X exceeds Y" |
| Structural formula | Driven by a mechanical rule | Break-even price for a specific market actor |

Do NOT simply default to the 95th percentile without checking whether it makes sense for your specific problem. Document your choice explicitly.

## Step 1 — Load driver data and compute τ

```python
import numpy as np

# Load driver values (replace with your actual data loading)
# driver_series: 1D array of the driver variable, chronologically ordered
# reference_values: subset of driver_series representing the "normal" reference period
#   (e.g., a pre-event baseline, a calm period, or a historical analogue period)

driver_series = ...      # shape (T,), chronological order
reference_values = ...   # subset used to compute the threshold

current_value = float(driver_series[-1])

# --- Choose ONE threshold approach (document your choice) ---

# Option A: Percentile of reference period
q = 0.95  # change to match your problem's definition of "extreme"
tau = float(np.percentile(reference_values, q))
tau_source = f"{int(q*100)}th pct of reference period"

# Option B: Historical case value
# tau = <value at which the event fired in the most similar historical case>
# tau_source = "historical case value"

# Option C: Expert-elicited
# tau = <expert-specified threshold>
# tau_source = "expert elicitation"

print(f"τ = {tau:.4f}  ({tau_source})")
print(f"Current driver value = {current_value:.4f}")

# State the crossing direction explicitly
# "falls_below": event fires when driver <= tau (e.g., price returning to normal from elevated)
# "rises_above": event fires when driver >= tau (e.g., index exceeding a crisis threshold)
crossing_direction = "falls_below"  # or "rises_above"
print(f"Event fires when driver {crossing_direction} τ")
```

## Step 2 — Transform and standardise

Working on standardised log-values (if the driver is strictly positive and log-normal) or directly on levels (if already approximately normal) reduces numerical issues.

```python
# For strictly positive drivers (prices, rates > 0): work on log scale
log_driver = np.log(driver_series)
mean_log = float(np.mean(log_driver))
std_log  = float(np.std(log_driver))
y = (log_driver - mean_log) / std_log          # standardised
tau_scaled = (np.log(tau) - mean_log) / std_log

# For drivers that can be negative or are already on a linear scale:
# mean_d = float(np.mean(driver_series))
# std_d  = float(np.std(driver_series))
# y = (driver_series - mean_d) / std_d
# tau_scaled = (tau - mean_d) / std_d

print(f"τ on standardised scale: {tau_scaled:.4f}")
```

## Step 3 — Choose and fit a price/driver model

Three model variants are available. Choose based on your driver's behaviour:

| Variant | Model | Use when |
|---|---|---|
| **OU** | Ornstein-Uhlenbeck (mean-reverting) | Driver tends to revert to a long-run level (commodity prices, spread indices) |
| **RWD** | Random walk with drift | No clear mean reversion; driver drifts with some trend |
| **SV** | Stochastic volatility | Volatility is non-constant; fat tails or volatility clustering present |

### Variant OU — Ornstein-Uhlenbeck

```python
import pymc as pm
import arviz as az

with pm.Model() as ou_model:
    # Long-run mean on standardised scale (prior centred at 0 after standardisation)
    mu_tilde = pm.Normal("mu_tilde", mu=0.0, sigma=0.5)

    # Mean-reversion speed; log-normal prior
    log_kappa = pm.Normal("log_kappa", mu=np.log(0.02), sigma=1.5)
    kappa     = pm.Deterministic("kappa", pm.math.exp(log_kappa))

    # Step std dev on standardised scale
    log_sigma = pm.Normal("log_sigma",
                          mu=float(np.log(np.std(np.diff(y)) + 1e-8)),
                          sigma=0.5)
    sigma = pm.Deterministic("sigma", pm.math.exp(log_sigma))

    # AR(1) likelihood (OU discretised)
    mu_step = y[:-1] + kappa * (mu_tilde - y[:-1])
    pm.Normal("obs", mu=mu_step, sigma=sigma, observed=y[1:])

    idata = pm.sample(
        draws=200, tune=200, chains=2,          # short chains for quick runs
        target_accept=0.9,
        nuts_sampler="numpyro",
        idata_kwargs={"log_likelihood": True},
        # do NOT pass random_seed
    )
```

### Variant RWD — Random Walk with Drift

```python
with pm.Model() as rwd_model:
    mu    = pm.Normal("mu", mu=0.0, sigma=0.002)
    log_sigma = pm.Normal("log_sigma",
                          mu=float(np.log(np.std(np.diff(y)) + 1e-8)),
                          sigma=0.5)
    sigma = pm.Deterministic("sigma", pm.math.exp(log_sigma))
    pm.Normal("obs", mu=mu, sigma=sigma, observed=np.diff(y))
    idata = pm.sample(draws=200, tune=200, chains=2, target_accept=0.92,
                      nuts_sampler="numpyro", idata_kwargs={"log_likelihood": True})
```

## Variant: ContinuousDriverModel-RWD (Random Walk with Drift)

Simplest model — no mean reversion. Appropriate when the driver shows no tendency
to return to a long-run level and the primary uncertainty is in the direction of drift.
Also useful as a baseline and for an **analytic cross-check** of the Monte Carlo
first-passage pipeline.

### Model specification

```
y_{t+1} = y_t + μ + σ·ε_t,   ε_t ~ N(0,1)
```

### PyMC implementation

```python
with pm.Model() as rwd_model:
    # Drift: weakly informative, centred at 0 (no trend assumption)
    mu = pm.Normal("mu", mu=0.0, sigma=0.002)
    # Step std dev on standardised scale
    log_sigma = pm.Normal("log_sigma",
                          mu=float(np.log(np.std(np.diff(y)) + 1e-8)),
                          sigma=0.5)
    sigma = pm.Deterministic("sigma", pm.math.exp(log_sigma))

    # Likelihood: iid increments
    pm.Normal("obs", mu=mu, sigma=sigma, observed=np.diff(y))

    idata = pm.sample(
        draws=200, tune=200, chains=2, target_accept=0.92,
        nuts_sampler="numpyro",
        idata_kwargs={"log_likelihood": True},
    )
```

### Forward simulation

```python
mu_s    = idata.posterior["mu"].values.flatten()
sigma_s = idata.posterior["sigma"].values.flatten()
n_post  = len(mu_s)

paths = np.empty((n_post, n_paths, horizon_days + 1))
paths[:, :, 0] = float(y[-1])
rng = np.random.default_rng()

for t in range(horizon_days):
    paths[:, :, t+1] = paths[:, :, t] + mu_s[:, None] + sigma_s[:, None] * rng.standard_normal((n_post, n_paths))

fp_days = first_passage_times(paths, tau_scaled)
```

### Analytic cross-check (inverse-Gaussian)

When drift μ < 0 and the threshold is below the current level (driver must fall),
the first-passage time follows an **inverse-Gaussian** distribution — use this
to validate the Monte Carlo simulation:

```python
from scipy.stats import invgauss

mu_mean    = float(np.mean(mu_s))
sigma_mean = float(np.mean(sigma_s))
# Distance from current standardised level to threshold
a = float(y[-1] - tau_scaled)  # must be positive (threshold below current level)

if mu_mean < 0 and a > 0:
    ig_mean  = a / abs(mu_mean)
    ig_shape = a**2 / sigma_mean**2
    # Compare analytic CDF to Monte Carlo at e.g. horizon=63 steps
    analytic_p = invgauss.cdf(63, mu=ig_mean / ig_shape, scale=ig_shape)
    mc_p = float(np.mean(fp_days <= 63))
    print(f"Analytic: {analytic_p:.3f}  |  Monte Carlo: {mc_p:.3f}")
    if abs(analytic_p - mc_p) > 0.05:
        print("WARNING: >5pp discrepancy — check first_passage_times() implementation")
else:
    print("Analytic check not applicable (drift not toward threshold)")
```

### Variant SV — Stochastic Volatility

```python
r = np.diff(y)   # returns of standardised driver
with pm.Model() as sv_model:
    sigma_h = pm.HalfNormal("sigma_h", sigma=0.3)
    h = pm.GaussianRandomWalk("h", sigma=sigma_h, shape=len(r))
    nu = pm.Exponential("nu", lam=1/10)
    pm.StudentT("r", nu=nu, mu=0.0, sigma=pm.math.exp(h/2), observed=r)
    idata = pm.sample(draws=200, tune=200, chains=2, target_accept=0.95,
                      nuts_sampler="numpyro", idata_kwargs={"log_likelihood": True})
```

## Step 4 — Convergence diagnostics

```python
summary         = az.summary(idata)
rhat_max        = float(summary["r_hat"].max())
ess_bulk_min    = float(summary["ess_bulk"].min())
divergences     = int(idata.sample_stats["diverging"].sum())
total_draws     = int(idata.sample_stats.sizes["chain"] * idata.sample_stats.sizes["draw"])
divergence_rate = divergences / total_draws
```

## Step 5 — Forward simulation and first-passage times

```python
# Extract posterior draws (adjust parameter names to your chosen variant)
# For OU:
kappa_s = idata.posterior["kappa"].values.flatten()
mu_s    = idata.posterior["mu_tilde"].values.flatten()
sigma_s = idata.posterior["sigma"].values.flatten()
n_post  = len(kappa_s)

n_paths      = 25         # increase for production runs
horizon_days = 63         # trading days; adjust to your problem
y_current    = float(y[-1])

rng   = np.random.default_rng()
noise = rng.standard_normal((n_post, n_paths, horizon_days))

paths = np.empty((n_post, n_paths, horizon_days + 1))
paths[:, :, 0] = y_current

for t in range(horizon_days):
    # OU step: drift = kappa * (mu - y)
    drift           = kappa_s[:, None] * (mu_s[:, None] - paths[:, :, t])
    paths[:, :, t+1] = paths[:, :, t] + drift + sigma_s[:, None] * noise[:, :, t]
    # For RWD: paths[:,:,t+1] = paths[:,:,t] + mu_s[:,None] + sigma_s[:,None]*noise[:,:,t]

# First-passage: first step where path crosses tau_scaled in direction D
if crossing_direction == "falls_below":
    crossed = paths[:, :, 1:] <= tau_scaled     # (n_post, n_paths, horizon_days)
else:
    crossed = paths[:, :, 1:] >= tau_scaled

# First crossing time per path (inf if never crosses)
fp_days = np.where(crossed.any(axis=2),
                   np.argmax(crossed, axis=2).astype(float) + 1,
                   np.inf)

finite_fp       = fp_days[np.isfinite(fp_days)]
p_any_event     = float(np.mean(np.isfinite(fp_days)))
median_days_fp  = float(np.median(finite_fp)) if len(finite_fp) > 0 else float("nan")
p10_fp          = float(np.percentile(finite_fp, 10)) if len(finite_fp) > 0 else float("nan")
p90_fp          = float(np.percentile(finite_fp, 90)) if len(finite_fp) > 0 else float("nan")
```

## Step 6 — Extract horizon probabilities and write outputs

```python
import json, os
from datetime import date, timedelta

os.makedirs("outputs", exist_ok=True)

# Convert trading-day horizon to calendar dates
# Adjust cal_per_tday if your driver uses calendar days or other units
cal_per_tday = 7 / 5
horizon_trading_days = [21, 42, 63, 126, 252]   # adjust to your problem
horizon_dates = [
    (date.today() + timedelta(days=int(h * cal_per_tday))).isoformat()
    for h in horizon_trading_days
]

# Empirical CDF at each horizon
def empirical_cdf(fp_days_flat, horizons):
    return np.array([np.mean(fp_days_flat <= h) for h in horizons])

# fp_days is (n_post, n_paths); flatten all paths
all_fp = fp_days.flatten()
cdf_vals = empirical_cdf(all_fp, horizon_trading_days)

forecast = {
    "method":                 "ContinuousDriverModel",
    "model_variant":          "OU",   # or RWD, SV
    "question":               "<VERBATIM QUESTION>",
    "model_backend":          "Bayesian",
    "forecast_as_of":         date.today().isoformat(),
    "event_definition":       f"Driver {crossing_direction} threshold tau",
    "threshold_tau":          float(tau),
    "threshold_source":       tau_source,
    "crossing_direction":     crossing_direction,
    "current_driver_value":   float(current_value),
    "horizon_dates":          horizon_dates,
    "p_event_by_horizon":     cdf_vals.tolist(),
    "ci_low_by_horizon":      [],   # compute via bootstrap across posterior if needed
    "ci_high_by_horizon":     [],
    "ci_level":               0.94,
    "median_days_to_event":   median_days_fp,
    "p10_days":               p10_fp,
    "p90_days":               p90_fp,
    "convergence_status":     "OK" if rhat_max < 1.01 and divergence_rate < 0.005
                              else "MARGINAL" if rhat_max < 1.05 else "FAIL",
    "rhat_max":               float(rhat_max),
    "ess_bulk_min":           float(ess_bulk_min),
    "divergence_rate":        float(divergence_rate),
    "key_assumptions":        [
        f"Driver follows a {crossing_direction} process (chosen variant: OU/RWD/SV)",
        f"Threshold τ = {tau:.4f} ({tau_source})",
        f"Event fires when driver {crossing_direction} τ",
    ],
    "key_uncertainties":      [
        "Correct threshold τ — sensitivity to this choice is the most important check",
        "Model variant choice (OU vs RWD vs SV) — does the driver actually mean-revert?",
        "Stationarity of the driver dynamics over the forecast horizon",
    ],
}

with open("forecast.json", "w") as f:
    json.dump(forecast, f, indent=2)

idata.to_netcdf("outputs/idata.nc")
```

## Step 7 — Model checks: PriorSensitivity on τ

The most important calibration check for this model is sensitivity to the threshold choice. Perturb τ by ±10-20% and re-run the forward simulation (no resampling needed — just change `tau_scaled` and re-simulate).

```python
# Perturb threshold by 10% and recompute P(event)
tau_perturbed = tau * 1.10   # or 0.90
tau_scaled_perturbed = (np.log(tau_perturbed) - mean_log) / std_log  # adjust for log/linear

if crossing_direction == "falls_below":
    crossed_p = paths[:, :, 1:] <= tau_scaled_perturbed
else:
    crossed_p = paths[:, :, 1:] >= tau_scaled_perturbed

fp_days_p  = np.where(crossed_p.any(axis=2),
                      np.argmax(crossed_p, axis=2).astype(float) + 1, np.inf)
p_mid_perturbed = float(np.mean(fp_days_p <= horizon_trading_days[2]))
p_mid_original  = float(cdf_vals[2])

delta_pp = abs(p_mid_perturbed - p_mid_original) * 100
print(f"PriorSensitivity on τ: {delta_pp:.1f}pp change with 10% threshold perturbation")
# PASS: < 10pp | WARN: 10–20pp | FAIL: > 20pp
```

## Gotchas

- **Crossing direction matters critically.** `<=` vs `>=` produces the inverse forecast. State the direction explicitly and verify a sample path manually.
- **Standardisation must be consistent.** Apply the same transform to both the driver series (`y`) and the threshold (`tau_scaled`). Mixing raw and scaled values is a silent bug.
- **Short chains underestimate uncertainty.** With `draws=200, chains=2`, credible intervals are approximate. Use `draws=1000+, chains=4` for production.
- **Verify units.** If the driver is in USD/bbl, ensure τ is also in USD/bbl before logging/scaling.
- **The driver may have already crossed τ.** If `current_value <= tau` (for `falls_below`), the event has already fired by this metric. Re-examine whether a different threshold or a different event definition is appropriate.

## Model checks for ContinuousDriverModel

**PriorSensitivity on τ (threshold)** — most important check for all variants.
Perturb the threshold by ±10% and recompute P(event). See `model_checks.md`.
- PASS: < 10pp change
- WARN: 10–20pp change  
- FAIL: > 20pp change — forecast is threshold-dominated, not data-driven

**ReferenceClassCongruence** — compare P(event by T_mid) to a historical base rate
from analogous events. A ratio > 4× or < 0.25× warrants explicit justification.

**ConsistencyCheck** — verify P(event by T) is monotonically non-decreasing across
all horizon dates. Any violation indicates a bug in the simulation or CDF computation.

---

## Variant: ContinuousDriverModel-LL (Local Level / Hidden State)

A state-space model where the driver's true level evolves as a latent random walk,
and observations are noisy measurements of that level. Appropriate when:

- The driver does not mean-revert to a fixed long-run level (unlike OU)
- Volatility is roughly constant over the forecast horizon (unlike SV)
- There is meaningful observation noise — the "true" driver level is partially hidden
- The driver trend evolves slowly and time-varyingly (unlike RWD's constant drift)

This is sometimes called a Basic Structural Time Series (BSTS) or Bayesian local
level model. The latent level is the "hidden state".

### Model specification

```
y_t   = μ_t + ε_t,    ε_t ~ N(0, σ_obs²)   [observation equation]
μ_t   = μ_{t-1} + η_t, η_t ~ N(0, σ_lvl²)  [state equation: level random walk]
```

- `μ_t` is the latent true level at time t (not directly observed)
- `σ_obs` is observation noise (short-term fluctuations around the true level)
- `σ_lvl` is level drift noise (how fast the true level changes)
- The ratio `σ_lvl / σ_obs` controls signal-to-noise: large ratio → level tracks data closely; small ratio → level evolves slowly

### PyMC implementation

```python
import pymc as pm
import numpy as np
import arviz as az

# y: standardised driver series (use same standardisation as other variants)

with pm.Model() as ll_model:
    # Observation noise: short-term fluctuations around the true level
    log_sigma_obs = pm.Normal(
        "log_sigma_obs",
        mu=float(np.log(np.std(np.diff(y)) + 1e-8)),
        sigma=0.5,
    )
    sigma_obs = pm.Deterministic("sigma_obs", pm.math.exp(log_sigma_obs))

    # Level drift noise: how much the hidden level moves per step
    # Prior: level drift << observation noise (level changes slowly)
    log_sigma_lvl = pm.Normal(
        "log_sigma_lvl",
        mu=float(np.log(np.std(np.diff(y)) * 0.1 + 1e-8)),
        sigma=0.5,
    )
    sigma_lvl = pm.Deterministic("sigma_lvl", pm.math.exp(log_sigma_lvl))

    # Latent level as a Gaussian random walk
    lvl = pm.GaussianRandomWalk("lvl", sigma=sigma_lvl, shape=len(y))

    # Observations are noisy measurements of the latent level
    pm.Normal("obs", mu=lvl, sigma=sigma_obs, observed=y)

    idata = pm.sample(
        draws=200, tune=200, chains=2,
        target_accept=0.92,
        nuts_sampler="numpyro",
        idata_kwargs={"log_likelihood": True},
        # do NOT pass random_seed
    )
```

### Forward simulation from the last filtered level

```python
# Extract last filtered level and noise posteriors
lvl_last    = idata.posterior["lvl"].values[:, :, -1].flatten()   # (n_post,)
sigma_obs_s = idata.posterior["sigma_obs"].values.flatten()
sigma_lvl_s = idata.posterior["sigma_lvl"].values.flatten()
n_post = len(lvl_last)

paths = np.empty((n_post, n_paths, horizon_days + 1))
paths[:, :, 0] = float(y[-1])   # start from last observation
rng = np.random.default_rng()

# Propagate both hidden level and noisy observations forward
lvl_current = lvl_last[:, None] * np.ones((n_post, n_paths))

for t in range(horizon_days):
    # Evolve the hidden level
    lvl_current = lvl_current + sigma_lvl_s[:, None] * rng.standard_normal((n_post, n_paths))
    # Observe with noise
    paths[:, :, t + 1] = lvl_current + sigma_obs_s[:, None] * rng.standard_normal((n_post, n_paths))

# First-passage times as before
if crossing_direction == "falls_below":
    crossed = paths[:, :, 1:] <= tau_scaled
else:
    crossed = paths[:, :, 1:] >= tau_scaled

fp_days = np.where(crossed.any(axis=2),
                   np.argmax(crossed, axis=2).astype(float) + 1,
                   np.inf)
```

### Gotchas

- **GaussianRandomWalk geometry**: NUTS can struggle with long chains of latent states. Use `target_accept=0.92` and monitor divergences. If divergence rate > 5%, try fewer states by downsampling the driver series first.
- **Identifiability**: `σ_obs` and `σ_lvl` can be hard to separate with short series. If posteriors for both are very wide, the model may be weakly identified — report WARN and widen the PriorSensitivity check to ±20%.
- **Initialisation**: PyMC's GaussianRandomWalk may need a good starting point on long series. Add `initvals={"lvl": np.zeros(len(y))}` if sampling is slow to warm up.
- **Comparison with OU**: If the posterior `σ_lvl` is very small relative to `σ_obs`, the latent level is nearly constant — effectively a model with no mean reversion and negligible drift. In this case, OU or RWD may be more interpretable.

## Variant: ContinuousDriverModel-LLT (Local Linear Trend)

Extends the Local Level model with a **slope state** that itself drifts. Appropriate
when the driver shows a discernible trend that is not constant (trend acceleration
or deceleration over time).

### Model specification

```
y_t = μ_t + ε_t,                ε_t ~ N(0, σ_obs²)   [observation]
μ_t = μ_{t-1} + ν_{t-1} + η_t,  η_t ~ N(0, σ_lvl²)  [level]
ν_t = ν_{t-1} + ζ_t,            ζ_t ~ N(0, σ_slp²)  [slope / trend]
```

The slope ν_t represents the current rate of change of the level. A large σ_slp
allows the trend to change direction quickly; a small σ_slp gives a smooth trend.

### PyMC implementation

```python
n = len(y)

with pm.Model() as llt_model:
    log_sigma_obs = pm.Normal("log_sigma_obs",
                              mu=float(np.log(np.std(np.diff(y)) + 1e-8)), sigma=0.5)
    sigma_obs = pm.Deterministic("sigma_obs", pm.math.exp(log_sigma_obs))

    log_sigma_lvl = pm.Normal("log_sigma_lvl",
                              mu=float(np.log(np.std(np.diff(y)) * 0.1 + 1e-8)), sigma=0.5)
    sigma_lvl = pm.Deterministic("sigma_lvl", pm.math.exp(log_sigma_lvl))

    log_sigma_slp = pm.Normal("log_sigma_slp",
                              mu=float(np.log(np.std(np.diff(y)) * 0.01 + 1e-8)), sigma=0.5)
    sigma_slp = pm.Deterministic("sigma_slp", pm.math.exp(log_sigma_slp))

    # Latent slope (trend) as a Gaussian random walk
    slope = pm.GaussianRandomWalk("slope", sigma=sigma_slp, shape=n)

    # Latent level: advances by the current slope each step
    # Use scan or cumulative sum approximation
    level_increments = slope[:-1]  # slope drives level changes
    level = pm.Deterministic("level",
        pm.math.concatenate([[y[0]], y[0] + pm.math.cumsum(level_increments)]))

    pm.Normal("obs", mu=level, sigma=sigma_obs, observed=y)

    idata = pm.sample(
        draws=200, tune=200, chains=2, target_accept=0.95,
        nuts_sampler="numpyro",
        idata_kwargs={"log_likelihood": True},
    )
```

### Forward simulation

```python
lvl_last   = idata.posterior["level"].values[:, :, -1].flatten()
slp_last   = idata.posterior["slope"].values[:, :, -1].flatten()
sigma_obs_s = idata.posterior["sigma_obs"].values.flatten()
sigma_lvl_s = idata.posterior["sigma_lvl"].values.flatten()
sigma_slp_s = idata.posterior["sigma_slp"].values.flatten()
n_post = len(lvl_last)

paths = np.empty((n_post, n_paths, horizon_days + 1))
paths[:, :, 0] = float(y[-1])
rng = np.random.default_rng()

lvl = lvl_last[:, None] * np.ones((n_post, n_paths))
slp = slp_last[:, None] * np.ones((n_post, n_paths))

for t in range(horizon_days):
    slp = slp + sigma_slp_s[:, None] * rng.standard_normal((n_post, n_paths))
    lvl = lvl + slp + sigma_lvl_s[:, None] * rng.standard_normal((n_post, n_paths))
    paths[:, :, t+1] = lvl + sigma_obs_s[:, None] * rng.standard_normal((n_post, n_paths))

fp_days = first_passage_times(paths, tau_scaled)
```

### Gotchas

- **Three GaussianRandomWalk chains**: LLT is harder to sample than LL. Expect more divergences. Use `target_accept=0.95` and increase `tune` if needed.
- **Identifiability**: σ_lvl and σ_slp can be weakly identified. If both posteriors are very wide, simplify to LL (drop the slope).
- **Over-smoothing**: Very small σ_slp produces a nearly linear trend. Check whether the fitted level tracks the data by plotting `level` posterior mean vs `y`.
