# CausalMechanismModel — Structural Causal Model

Build a probabilistic model of the causal drivers that determine when (and whether) the event occurs. Predict by forward-simulating from the current state of those drivers.

## When to use

- You can name the key causal factors and their direction of influence on the outcome.
- You have at least rough measurements of those factors today.
- You want forecasts that are **sensitive to news and policy changes** — this method updates naturally when a causal driver changes.
- You want to answer "what would happen if X changes?" (counterfactual / intervention analysis).

## Conceptual structure

```
Causal driver 1 (e.g., sanctions_severity)   ─┐
Causal driver 2 (e.g., oil_price_usd)        ─┤→ latent_pressure → P(event)
Causal driver 3 (e.g., diplomatic_activity)  ─┘
```

The latent pressure variable represents "how much the system is being pushed toward resolution". When pressure exceeds a threshold (uncertain), the event occurs.

## Data preparation

You need current measurements of the causal drivers. Historical values are helpful for calibration but not strictly required.

| column | type | notes |
|---|---|---|
| `driver_name` | string | e.g., `sanctions_severity`, `oil_price_usd` |
| `current_value` | float | Normalised 0–1 scale (0 = no pressure, 1 = maximum pressure) |
| `uncertainty_sigma` | float | Standard deviation of your uncertainty about the current value |
| `direction` | `+` / `-` | Does higher value push *toward* resolution (+) or *away from* it (-)? |

## PyMC implementation

```python
import pymc as pm
import numpy as np
import arviz as az

# --- inputs (fill from domain analysis and data) ---
# Causal drivers: current values and uncertainties on a 0–1 scale
driver_names = ["sanctions_severity", "oil_price_pressure", "diplomatic_activity",
                "military_escalation_risk"]
# + = higher value → more pressure toward resolution
# - = higher value → less pressure toward resolution (delays resolution)
directions   = [+1, +1, +1, -1]   # sanctions, oil_pressure, diplomacy, military_risk

# Your best estimate of current driver values (0–1 scale)
current_mu   = np.array([0.75, 0.60, 0.35, 0.45])
current_sig  = np.array([0.10, 0.15, 0.20, 0.20])

# Weights (prior belief about relative importance)
weight_mu    = np.ones(len(driver_names)) / len(driver_names)  # uniform → equal weight
weight_alpha = np.ones(len(driver_names)) * 3                  # concentration: moderate confidence

n_drivers = len(driver_names)

with pm.Model() as causal_model:
    # Uncertain current driver values
    driver_values = pm.TruncatedNormal("driver_values",
                                        mu=current_mu, sigma=current_sig,
                                        lower=0, upper=1,
                                        shape=n_drivers)

    # Weights over drivers (how much does each driver matter?)
    weights = pm.Dirichlet("weights", a=weight_alpha, shape=n_drivers)

    # Apply direction signs and compute latent pressure
    signed_drivers = pm.math.stack([directions[i] * driver_values[i]
                                    for i in range(n_drivers)])
    latent_pressure = pm.Deterministic("latent_pressure",
                                        pm.math.dot(weights, signed_drivers))

    # Resolution threshold (uncertain)
    threshold = pm.Beta("threshold", alpha=3, beta=3)  # prior: ~0.5

    # P(event) = logistic activation above threshold
    sharpness = pm.Gamma("sharpness", mu=8, sigma=3)  # how abrupt the transition is
    p_event_now = pm.Deterministic("p_event_now",
        pm.math.invlogit(sharpness * (latent_pressure - threshold)))

    # Calibration: if you have labelled historical cases (event / no event at known
    # pressure levels), add them here:
    # obs = pm.Bernoulli("obs", p=p_event_calibration, observed=historical_outcomes)

    idata = pm.sample(
        draws=500, tune=500, chains=4,
        target_accept=0.92,
        nuts_sampler="numpyro",
        idata_kwargs={"log_likelihood": True, "log_prior": True},
    )
```

## Extending to time horizons

`p_event_now` is the instantaneous probability. To forecast over time, you need an assumption about how driver values evolve. Two options:

**Option A — Static drivers (conservative):**
Assume drivers remain at current values. `P(event in W days) ≈ 1 - (1 - p_event_now)^W_weeks`. Convert days to weeks to keep the exponent manageable.

**Option B — Driver trend (better when trends are identifiable):**
```python
# Add a trend per driver: driver_t = driver_0 + trend * t
# trend ~ Normal(0, 0.01) per week (prior: slow drift)
trend = pm.Normal("trend", mu=driver_trend_mu, sigma=0.02, shape=n_drivers)

horizon_weeks = [12, 24, 52]  # 3 months, 6 months, 1 year
p_by_horizon = []
for wk in horizon_weeks:
    d_t = pm.math.clip(driver_values + trend * wk, 0, 1)
    signed_t = pm.math.stack([directions[i] * d_t[i] for i in range(n_drivers)])
    pressure_t = pm.math.dot(weights, signed_t)
    p_t = pm.math.invlogit(sharpness * (pressure_t - threshold))
    p_cumulative = 1 - (1 - p_t) ** wk  # accumulate weekly
    p_by_horizon.append(pm.Deterministic(f"p_{wk}wk", p_cumulative))
```

## Extracting the forecast

```python
# For Option A (static):
p_now_samples = idata.posterior["p_event_now"].values.flatten()

horizon_days  = [90, 180, 365]
horizon_weeks = [d / 7 for d in horizon_days]

p_event_by_horizon = []
ci_low_by_horizon  = []
ci_high_by_horizon = []
for wk in horizon_weeks:
    p_h = 1 - (1 - p_now_samples) ** wk
    p_event_by_horizon.append(float(np.mean(p_h)))
    ci_low_by_horizon.append(float(np.percentile(p_h, 3)))
    ci_high_by_horizon.append(float(np.percentile(p_h, 97)))
```

## Counterfactual / intervention analysis

A key advantage of this model is the ability to ask "what if driver X changes?":

```python
# What if diplomatic_activity jumps to 0.80 (from 0.35)?
with causal_model:
    pm.set_data({"driver_values": np.array([0.75, 0.60, 0.80, 0.45])})
    ppc_intervention = pm.sample_posterior_predictive(idata, var_names=["p_event_now"])
```

Report this as a sensitivity analysis in `summary.md`.

## Model checks

**PriorSensitivity** — always run derived `p_event_by_horizon` via psense per
[`prior_sensitivity_psense.md`](prior_sensitivity_psense.md). **When the user asks for
causal interpretation**, also run psense on named driver/effect parameters and keep
the ±1σ driver perturbation check below. Prediction-only briefs skip parameter-level psense.

Driver perturbation (causal narrative): shift each `current_mu` by ±1σ and check Δ P(event);
> 15pp → dominant uncertainty — flag in `summary.md` (not automatic invalidation).

**ConsistencyCheck** — verify that the causal direction is as expected:
increasing each driver with direction=+1 should increase P(event), and
increasing each driver with direction=-1 should decrease P(event). Run a
simple sensitivity check:

```python
# Test causal direction for driver i
driver_high = current_mu.copy()
driver_high[i] += current_sig[i]
# Check that p_event increases for direction=+1 drivers
# and decreases for direction=-1 drivers
```

**ReferenceClassCongruence** — compare P(event by T_mid) to a historical base rate.
A ratio > 4× suggests the causal model is overly optimistic/pessimistic.

## Gotchas

- **Unmeasurable drivers**: If a key causal driver can't be measured (e.g., "leadership intent"), encode it as a latent variable with a wide prior rather than omitting it.
- **Collinear drivers**: Sanctions severity and oil price often move together. If correlation > 0.8, combine them into a single composite driver or include a correlation structure.
- **Calibration without historical data**: If no labelled historical examples exist to calibrate against, all parameters are prior-driven. Widen all priors and report the model as *structural reasoning, not data-driven*.
- **Direction reversal**: The direction of a driver's effect can flip under different regimes. Document this explicitly in the `key_assumptions` field of `forecast.json`.
