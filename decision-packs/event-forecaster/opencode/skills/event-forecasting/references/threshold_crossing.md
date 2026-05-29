# ThresholdCrossingModel — Stochastic Driver + First-Passage Time

> **Which reference should I use?**
> - If the threshold is **computed from historical data** (e.g., a percentile of a reference period) and you have a clean price time series: use **`price_forecasting.md`** — it integrates the OU model, threshold computation, and forward simulation into a single clean workflow.
> - If the threshold is **latent and must be estimated** from N=1 or a few historical cases (you observed the driver level at which the event occurred, but don't know the true threshold precisely): use this file (Section B below).

---

## Section A: Data-derived threshold (use `price_forecasting.md` for full implementation)

When the threshold is a statistic you can compute directly from data:

```python
import numpy as np

# Load your driver time-series (replace with your actual data loading)
driver_series = ...          # 1D array, chronological order
reference_values = ...       # subset representing a "normal" or "baseline" period

# Choose a threshold derivation appropriate to your problem:

# Option A: Percentile of reference period
# Use when the event fires when the driver exceeds/falls below a "stressed" level
q = ...    # e.g., 0.95 for "upper tail stress" or 0.05 for "lower tail distress"
           # Choose based on problem logic, not convention
threshold = float(np.percentile(reference_values, q * 100))
print(f"Data-derived threshold ({q*100:.0f}th pct of reference): {threshold:.4f}")

# Option B: Value from a specific historical date or event
# threshold = driver_value_at_historical_event

# Option C: Structural formula (e.g., break-even calculation)
# threshold = ...

current_value = float(driver_series[-1])
print(f"Current driver value: {current_value:.4f}")
print(f"Already crossed: {current_value >= threshold}")   # adjust direction to your problem
```

See `price_forecasting.md` for the complete OU model + forward simulation built on a data-derived threshold.

---

## Section B: Latent threshold estimated from N≥1 historical cases

### Extracting threshold anchors from historical cases

When the event has occurred once or a few times historically, extract the driver value at those event times as a noisy proxy for the threshold:

```python
import numpy as np

# driver_series: your full driver time-series (array or DataFrame)
# event_dates: list of dates when the event occurred historically

# Example: if you have a time-indexed DataFrame
# historical_driver_at_events = driver_df.loc[event_dates, "driver_column"].values

# If multiple historical events: use the mean as the threshold anchor
# Widen the sigma in proportion to the spread across events
threshold_anchor = float(np.mean(historical_driver_at_events))
threshold_noise  = max(float(np.std(historical_driver_at_events)), threshold_anchor * 0.10)
print(f"Threshold anchor: {threshold_anchor:.4f} ± {threshold_noise:.4f}")

# If N=1: the single case is a noisy proxy for the true threshold
# Use ±20-30% of the value as sigma in the model prior (encodes uncertainty)
```

Use `threshold_anchor` as the prior mean for `event_driver_value` in the model below.

---

## Section B: Latent threshold estimated from N≥1 historical case (general)

Model the event as occurring when a **key causal driver** (e.g., oil price, economic cost index, political pressure score) first crosses a latent threshold. Forecast the driver as a stochastic process; compute P(first passage before T) via Monte Carlo simulation.

## When to use

- The event has a clear primary driver that can be measured and forecasted quantitatively.
- There is strong domain knowledge that the event is triggered when the driver exceeds some level (economic pain crosses a threshold, price signal becomes too costly to ignore).
- You have time-series data for the driver (at least several months; ideally 2+ years).
- There may be **only one historical case** of the event — the threshold can be estimated from that single case plus domain knowledge, without needing a large N.
- The threshold may be partially observable via market signals (e.g., unusual futures/options activity that precedes the event decision).

## Conceptual structure

```
driver(t) ← stochastic process (e.g., price, cost index, score, rate)
            forecasted forward in time

threshold ← latent; estimated from:
              - historical cases where driver ~ threshold at event time
              - domain knowledge about decision-maker incentives
              - observable proxy signals (market microstructure, sentiment)

P(event by T) = P(∃t ∈ [now, T] : driver(t) ≥ threshold)   [or ≤, depending on direction]
              = fraction of simulated paths that cross threshold before T
```

## Data preparation

You need two components:

**A. Driver time series**

| column | type | notes |
|---|---|---|
| `date` | datetime | Daily or weekly |
| `driver_value` | float | e.g., oil price in USD/barrel |

**B. Historical event record (even N=1)**

| field | value | notes |
|---|---|---|
| `event_date` | date | When the event occurred |
| `driver_at_event` | float | Driver value at or just before the event |
| `driver_pre_period` | array | Driver values in the months before the event |

If N = 1, the single case gives you a noisy observation of the threshold. The model encodes this as an informative prior on the threshold parameter, not as a hard constraint.

## PyMC implementation

```python
import pymc as pm
import numpy as np
import arviz as az
import pandas as pd

# --- inputs ---
# driver_history: array of historical driver values (most recent last)
# driver_dates:   corresponding dates
# current_value:  driver value today
# event_driver_value: driver value at the one known historical event (threshold proxy)
# horizon_dates:  list of future dates for P(event by date)

# Step 1: Estimate stochastic process parameters from historical driver data
# Using an Ornstein-Uhlenbeck (mean-reverting) process:
#   d_driver = kappa * (mu - driver) * dt + sigma * sqrt(dt) * dW
# This is appropriate for oil prices and many geopolitical cost indices.

log_driver = np.log(driver_history)  # model on log scale for oil prices

# Approximate MLE for OU parameters from data (as prior initialisation)
dt = 1.0  # weeks (adjust for your frequency)
diffs = np.diff(log_driver)
lagged = log_driver[:-1]
# Regression diffs ~ alpha + beta * lagged gives beta = -kappa * dt, alpha = kappa * mu * dt
from numpy.linalg import lstsq
A = np.column_stack([np.ones(len(lagged)), lagged])
coeffs, _, _, _ = lstsq(A, diffs, rcond=None)
kappa_init = max(-coeffs[1] / dt, 0.005)
mu_init    = coeffs[0] / (kappa_init * dt)
sigma_init = float(np.std(diffs - (coeffs[0] + coeffs[1] * lagged)))

with pm.Model() as threshold_model:
    # OU process parameters (log-scale driver)
    log_mu    = pm.Normal("log_mu",    mu=mu_init,    sigma=0.3)   # long-run mean
    log_kappa = pm.Normal("log_kappa", mu=np.log(kappa_init), sigma=0.5)
    log_sigma = pm.Normal("log_sigma", mu=np.log(sigma_init), sigma=0.3)

    kappa = pm.Deterministic("kappa", pm.math.exp(log_kappa))
    mu    = pm.Deterministic("mu",    pm.math.exp(log_mu))
    sigma = pm.Deterministic("sigma", pm.math.exp(log_sigma))

    # Latent threshold: informed by the single historical case
    # "The event occurred when the driver was near event_driver_value"
    # Uncertainty: ±30% — the exact threshold is unknown; we observed one crossing
    log_threshold = pm.Normal(
        "log_threshold",
        mu=np.log(event_driver_value),
        sigma=0.25  # ~±28% uncertainty on the threshold level
    )
    threshold = pm.Deterministic("threshold", pm.math.exp(log_threshold))

    # Optional: calibration against the one observed event
    # P(threshold ≈ driver_at_event) — soft likelihood from the single case
    # This is a weak observation: the event happened when driver ~ threshold
    threshold_obs = pm.Normal(
        "threshold_obs",
        mu=threshold,
        sigma=event_driver_value * 0.15,   # 15% of value = rough measurement error
        observed=event_driver_value
    )

    idata = pm.sample(
        draws=500, tune=500, chains=4,
        target_accept=0.92,
        nuts_sampler="numpyro",
    )
```

## Monte Carlo first-passage simulation

After sampling the OU parameters and threshold from the posterior, simulate forward paths and compute first-passage times:

```python
import numpy as np

# Extract posterior samples
kappa_samp    = idata.posterior["kappa"].values.flatten()
mu_samp       = idata.posterior["mu"].values.flatten()
sigma_samp    = idata.posterior["sigma"].values.flatten()
threshold_samp = idata.posterior["threshold"].values.flatten()

n_samples     = len(kappa_samp)
n_paths       = 500          # Monte Carlo paths per posterior sample (reduce if slow)
dt_weeks      = 1.0          # simulation step in weeks
horizon_days  = [90, 180, 365]   # from orchestrator
horizon_weeks = [d / 7 for d in horizon_days]
max_weeks     = int(max(horizon_weeks)) + 1

log_current   = np.log(current_value)

# Storage: for each posterior draw, fraction of paths where event occurred by each horizon
p_by_horizon  = np.zeros((n_samples, len(horizon_days)))
median_weeks_arr = np.zeros(n_samples)

rng = np.random.default_rng()

for i in range(n_samples):
    k = kappa_samp[i]
    m = np.log(mu_samp[i])          # OU mean in log space
    s = sigma_samp[i]
    thr = np.log(threshold_samp[i]) # threshold in log space

    # Simulate n_paths paths of max_weeks steps
    paths = np.zeros((n_paths, max_weeks + 1))
    paths[:, 0] = log_current

    for t in range(max_weeks):
        drift     = k * (m - paths[:, t]) * dt_weeks
        diffusion = s * np.sqrt(dt_weeks) * rng.standard_normal(n_paths)
        paths[:, t + 1] = paths[:, t] + drift + diffusion

    # First-passage time: first week where path >= threshold
    crossed    = paths >= thr       # (n_paths, max_weeks+1)
    first_week = np.argmax(crossed, axis=1)
    # argmax returns 0 if never crossed — distinguish using any()
    ever_crossed = crossed.any(axis=1)
    first_week[~ever_crossed] = max_weeks + 9999  # sentinel for "never"

    for j, hw in enumerate(horizon_weeks):
        p_by_horizon[i, j] = float(np.mean(first_week <= hw))

    # Median first-passage time across paths
    resolved_weeks = first_week[ever_crossed]
    median_weeks_arr[i] = float(np.median(resolved_weeks)) if len(resolved_weeks) > 0 else np.nan

# Aggregate across posterior
p_event_by_horizon = [float(np.mean(p_by_horizon[:, j])) for j in range(len(horizon_days))]
ci_low_by_horizon  = [float(np.percentile(p_by_horizon[:, j], 3))  for j in range(len(horizon_days))]
ci_high_by_horizon = [float(np.percentile(p_by_horizon[:, j], 97)) for j in range(len(horizon_days))]

median_days = float(np.nanmean(median_weeks_arr) * 7)
p10_days    = float(np.nanpercentile(median_weeks_arr * 7, 10))
p90_days    = float(np.nanpercentile(median_weeks_arr * 7, 90))
```

## Informed-actor signal as a threshold indicator

When the threshold is latent and decision-makers act on private information, observable proxy signals can indicate the threshold is being approached:

| Signal type | What to look for | How to use |
|---|---|---|
| Options/derivatives on the driver | Unusual volume in out-of-the-money contracts near expected threshold | Logit-scale upward shift on P(threshold near) |
| Related asset prices | Abnormal returns in assets that benefit from the event | Cross-check against event window |
| Insurance or risk premiums | Sudden decrease in risk pricing | Suggests informed belief that event is imminent |
| Currency or sovereign spreads | Rapid appreciation/tightening tied to resolution | Economic relief anticipated |

*Replace with the specific signals relevant to your driver and event domain.*

Encode these as a `logit_adj` term on the threshold model:

```python
# If signals suggest the threshold is being approached:
# Shift the threshold DOWNWARD (easier to cross) by a small logit amount
signal_composite = <computed from available market data, normalized 0–1>
signal_strength  = pm.Normal("signal_strength", mu=0, sigma=0.5)
log_threshold_adjusted = pm.Deterministic(
    "log_threshold_adj",
    log_threshold - signal_strength * signal_composite  # positive signal → lower effective threshold
)
```

Only add the signal adjustment if you have actual market microstructure data. Do NOT fabricate signal values.

## Model checks

**PriorSensitivity on threshold** — critical. The threshold estimate from N=1 is
inherently uncertain. Perturb the threshold prior mean by ±15% and re-run. If
P(event by T_mid) changes by > 10pp:
- WARN: the forecast is moderately threshold-sensitive
- FAIL (> 20pp): the forecast is threshold-dominated — report explicitly

Also perturb sigma on the threshold prior from 0.25 to 0.15 and 0.40 and check
for stability.

**ReferenceClassCongruence** — compare P(event by T_mid) to a historical base rate.
If the ratio exceeds 4×, document why the threshold model diverges from analogues.

**ConsistencyCheck** — verify P(first crossing by T) is monotonically non-decreasing.
Any non-monotonicity indicates a bug in the Monte Carlo simulation.

## Gotchas

- **N=1 threshold observation**: With a single data point, the threshold posterior is dominated by the prior. Be explicit about this in `summary.md`. Run `PriorSensitivity` on the threshold prior — a WARN or FAIL here means the forecast depends heavily on guessing the threshold level.
- **Log vs linear scale**: Strictly positive drivers (prices, rates, indices bounded below zero) are often better modelled on a log scale (multiplicative shocks, always positive). Use `np.log(driver)` throughout — but verify this matches your driver's distribution.
- **OU mean reversion level**: `mu` is the long-run mean of the driver. If you believe the equilibrium has structurally shifted, update `mu` and document the assumption.
- **Multiple thresholds**: The decision-maker may have multiple thresholds (e.g., "if oil is above X AND diplomatic talks stall, OR oil is above Y regardless"). If this is plausible, model two separate threshold components with a logical OR.
- **Threshold stability**: The threshold from the one historical case may not apply today if the political economy has changed. This is the single biggest uncertainty — encode it in the prior sigma on `log_threshold`.
- **Simulation efficiency**: For n_samples = 1000 and n_paths = 500, this is 500K path simulations. If slow, reduce `n_paths` to 200. The error from fewer paths is usually < 2 pp.
