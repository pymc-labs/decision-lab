# ReferenceClassModel — Base Rate + Bayesian Updating

Estimate the probability of event resolution within a window by grounding the forecast in the empirical base rate from historical analogues, then updating with current evidence.

## When to use

- You can identify a class of historical analogous events (even roughly similar ones).
- Quantitative time-series data may be sparse or absent.
- **This method is always appropriate as a baseline.** It provides the prior that other methods update.

## Conceptual steps

1. **Define the reference class**: What past events are structurally similar to the one you're forecasting?
2. **Measure the base rate**: Among those events, what fraction resolved within T days?
3. **Bayesian prior**: Encode the base rate + its uncertainty as a Beta distribution.
4. **Update with current evidence**: Use closer analogues, current conditions, or indicator signals to shift the posterior.
5. **Extract forecast.json fields**.

## Choosing the reference class

Apply the **reference class selection ladder**. Start at the narrowest level and widen until you reach N ≥ 5:

| Level | Breadth | Example (fill in your event type) |
|---|---|---|
| Too narrow | The exact event, this specific instance | Usually N < 5 |
| Narrow | Events of this type in this context | Target: N ≥ 5 |
| Medium | Events of this type more broadly | N typically 10–30 |
| Broad | All events in the general category | N typically 30–100+ |

**Use the narrowest class with N ≥ 5 events.** If you cannot reach N = 5 at the narrow level, combine the narrow class (as additional evidence) with the next broader level as the prior. Document what you included and why.

When broadening, explicitly note:
- What differences exist between the analogues and the current event
- In which direction those differences likely shift the base rate (faster or slower resolution)

## PyMC implementation

```python
import pymc as pm
import numpy as np
import xarray as xr

# --- inputs (fill from data summary, domain knowledge, or prompt context) ---
# Broad reference class (prior evidence)
N_broad = ...      # total events in broad class
k_broad = ...      # events that resolved within T days

# Narrow reference class (update evidence)
N_narrow = ...
k_narrow = ...     # resolved within T days

# T = the horizon you are estimating for (e.g., 180 days)
T_days = 180

with pm.Model() as reference_model:
    # Hierarchical: broad class informs the prior on the narrow class rate
    p_broad = pm.Beta("p_broad",
                      alpha=k_broad + 1,
                      beta=(N_broad - k_broad) + 1)

    # Narrow class as a partial update — drawn from a distribution centred on broad rate
    # Concentration controls how much we trust the broad rate as a prior
    concentration = pm.Gamma("concentration", mu=5, sigma=3)
    p_narrow = pm.Beta("p_narrow",
                       alpha=p_broad * concentration,
                       beta=(1 - p_broad) * concentration)

    # Observed narrow class outcomes
    obs = pm.Binomial("obs", n=N_narrow, p=p_narrow, observed=k_narrow)

    # Optional: current-conditions adjustment (see below)

    idata = pm.sample(
        draws=500,
        tune=500,
        chains=6,
        backend="numba",
        nuts_sampler="nutpie",
        nuts={"target_accept": 0.9},
        # do NOT pass random_seed
    )
    pm.stats.compute_log_likelihood(idata, model=reference_model)
    pm.stats.compute_log_prior(idata, model=reference_model)
```

## Extracting the forecast

```python
# Posterior of p_narrow is our P(event resolves within T days)
p_samples = idata.posterior["p_narrow"].values.flatten()

p_event_at_T   = float(np.mean(p_samples))
ci_low_at_T    = float(np.percentile(p_samples, 3))
ci_high_at_T   = float(np.percentile(p_samples, 97))

# For multiple horizon dates, derive a hazard rate and propagate:
# Fit lambda = -log(1 - p_T) / T (exponential waiting time assumption)
lambda_samples = -np.log(1 - p_samples + 1e-9) / T_days

horizon_days = [90, 180, 365]   # replace with your actual horizon dates
p_event_by_horizon = []
for t in horizon_days:
    p_h = 1 - np.exp(-lambda_samples * t)
    p_event_by_horizon.append(float(np.mean(p_h)))

# Median days to event (from exponential model)
median_days = float(np.mean(np.log(2) / lambda_samples))
p10_days    = float(np.percentile(np.log(2) / lambda_samples, 10))
p90_days    = float(np.percentile(np.log(2) / lambda_samples, 90))

# Derived quantities for PriorSensitivity (psense)
t = xr.DataArray(horizon_days, dims="horizon", coords={"horizon": horizon_days})
lambda_post = -np.log(1 - idata.posterior["p_narrow"] + 1e-9) / T_days
p_by_h = 1.0 - np.exp(-t * lambda_post)
p_by_h = p_by_h.transpose("chain", "draw", "horizon")
idata.posterior["p_event_by_horizon"] = p_by_h
```

## Adding a current-conditions signal

If you have a signal that current conditions are better or worse than the historical average, add a logit-scale offset:

```python
# signal_mu: your prior on the logit-scale adjustment
#   0.0 = conditions match historical average
#   positive = conditions favour faster resolution than average
#   negative = conditions favour slower resolution than average
logit_adj = pm.Normal("logit_adj", mu=signal_mu, sigma=0.75)
p_adjusted = pm.Deterministic("p_adjusted",
    pm.math.invlogit(pm.math.logit(p_narrow) + logit_adj))
```

Use `p_adjusted` in place of `p_narrow` for the forecast.

## Special case: N=1 for the exact event type

When there is only **one historical case** of the specific event you are forecasting, a narrow reference class gives an enormously uncertain estimate (94% CI from Beta(2,1) spans nearly the full [0, 1] range).

**Required response**: Force-broaden the reference class to a wider category with N ≥ 5. Be explicit about:
- What analogues you are including
- The main structural differences from the current event
- Which direction those differences push the base rate

Use the single historical case to inform the `ThresholdCrossingModel` or `ContinuousDriverModel` (driver value at resolution = noisy threshold observation) rather than the reference class calculation.

## The current event is already ongoing

The base rate from historical analogues gives P(event resolves within T days from event start). If the event has already been ongoing for `s` days, adjust for conditional remaining duration:

```
P(resolves in next T days | already ongoing for s days) = 1 - S(s + T) / S(s)
```

Where S(t) is the survival function. With the exponential approximation:
```python
# lambda_samples estimated above
p_remaining = 1 - np.exp(-lambda_samples * T_days)   # this IS the conditional if exponential (memoryless)
# For non-exponential, use HazardModel which handles this correctly
```

For non-exponential hazard rates (increasing or decreasing hazard), use `HazardModel` which handles right-censoring and the current duration correctly.

## Model checks

**PriorSensitivity** — analytic fallback: perturb Beta concentration (e.g. 5 → 2)
at each horizon per [`model_checks.md`](model_checks.md). WARN/FAIL at T_mid means
disclose weak reference-class information, not that the forecast is wrong.

**ReferenceClassCongruence** — not applicable here (this IS the reference class).
Instead: compare the posterior base rate to an even broader class as a sanity check.
If they differ by > 2×, document why the narrow class is more appropriate.

**HistoricalCalibration** — if N ≥ 5 events: apply leave-one-out and check that
the model's predicted probability for each left-out event was calibrated (Brier
skill score > 0.05). If N < 5, skip and note it.

**ConsistencyCheck** — verify P(event by T) is monotonically non-decreasing across
all horizon dates. Also verify scenario probabilities sum to 1.0 if using a
scenario-conditioned extension.

## Gotchas

- **Selection bias**: Only include events where resolution was observable, not only the ones you happen to know about.
- **Anachronism**: Historical analogues from a different era may have a systematically different base rate. Check for trend.
- **P = 1 or P = 0 from the reference class**: Never report certainty from finite samples. Use a non-zero prior for the denominator.
- **Mixing time units**: Ensure all durations are in consistent units (all in days, all in months, etc.).
