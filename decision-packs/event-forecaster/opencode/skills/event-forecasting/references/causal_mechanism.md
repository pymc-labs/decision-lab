# CausalMechanismModel — Structural Causal Model

Build a probabilistic model of the causal drivers that determine when (and whether) the event occurs. Predict by forward-simulating from the current state of those drivers.

## When to use

- You can name the key causal factors and their direction of influence on the outcome.
- You have at least rough measurements of those factors today.
- You want forecasts that are **sensitive to news and policy changes** — this method updates naturally when a causal driver changes.
- You want to answer "what would happen if X changes?" (counterfactual / intervention analysis).

## Conceptual structure

```
Causal driver A (e.g., regulatory_pressure)  ─┐
Causal driver B (e.g., market_stress_index) ─┤→ latent_pressure → P(event)
Causal driver C (e.g., resolution_signal)   ─┘
```

The latent pressure variable represents "how much the system is being pushed toward resolution". When pressure exceeds a threshold (uncertain), the event occurs. Signed drivers lie in \([-1, 1]\) after applying direction; the threshold prior matches that scale.

This diagram is a **working abstraction** — not a claim that only three factors matter. Before fitting, sketch the fuller causal graph and document what you are assuming away (see below).

## Causal structure and DAG reasoning

Think critically about the causal structure before choosing drivers. A forecast that treats correlated signals as independent causes can look precise while encoding the wrong mechanism.

### When to expand beyond the simple diagram

Add nodes (confounders, mediators, regime indicators, external shocks) when any of the following apply:

- Two measured drivers move together because a **shared cause** drives both.
- A driver affects the event **through** an intermediate step you can name but did not model (mediator).
- A variable is caused by **both** drivers and the outcome (collider) — conditioning on it can distort inference.
- **External shocks** (policy shifts, crises, institutional deadlines) plausibly affect both driver levels and resolution timing.
- Past cases differ in ways that measured drivers do not capture (**unmeasured confounding** or regime change).

Stay with the simple latent-pressure model when extra nodes would not change which variables you measure, how you set priors, or how you interpret counterfactuals. Complexity should buy identifiability or a more honest uncertainty story — not diagram decoration.

### Common confounder patterns in event forecasting

| Pattern | Structure (schematic) | Risk if ignored |
|---|---|---|
| External shock | Shock → multiple drivers; Shock → Event | Over-credit drivers jointly elevated by the same shock |
| Institutional calendar | Deadline → urgency signals; Deadline → Event | Mistake deadline-driven activity for organic pressure |
| Regime / phase | Regime → driver dynamics; Regime → baseline hazard | Drivers mean different things across phases |
| Measurement overlap | True state → multiple proxies | Double-count one underlying factor as separate drivers |

Domain-agnostic example — a latent shock affecting both drivers and the outcome directly:

```
External shock (unmeasured?) ──┬──→ driver_A ──┐
                               ├──→ driver_B ──┤→ latent_pressure → Event
                               └──→ (direct) ──┘
```

If `driver_A` and `driver_B` are proxies for the same shock, merge them or widen uncertainty; do not treat them as independent evidence.

### Colliders, mediators, and unmeasured confounding

- **Mediator** (Driver → Mediator → Event): Either include the mediator as a measured driver or state that you are modelling the **total effect** of the driver and omitting the pathway. Do not silently treat a mediator as an independent driver.
- **Collider** (Driver A → Collider ← Driver B): Avoid conditioning on colliders unless the forecasting question requires it — doing so opens non-causal associations.
- **Unmeasured confounder** (U → Drivers; U → Event): The fitted model assumes **conditional ignorability given measured drivers**. That assumption is almost always approximate — name what U might be and how it could bias the forecast.

### What to disclose when confounders are unmeasured

If a plausible confounder has no measurement:

1. **Name it** and describe its hypothesized paths (e.g., "leadership intent affects both compliance signals and resolution timing").
2. **Direction of bias**: Does omitting U likely inflate or deflate P(event) relative to a fully adjusted model? If unknown, say so.
3. **Modelling choice**: Encode as a latent driver with a wide prior if it materially shifts the forecast; otherwise document under structural limitations and widen driver uncertainty.
4. **Identification caveat**: Do not imply the forecast is **causally identified** from observables alone. Counterfactuals are **model-relative** — valid under the stated DAG, not ground truth.

Surface these points in `## Causal structure notes` in `summary.md` and in `forecast.json` (`key_assumptions`, `key_uncertainties`, and `causal_structure_notes` when using this method).

## Data preparation

You need current measurements of the causal drivers. Historical values are helpful for calibration but not strictly required.

| column | type | notes |
|---|---|---|
| `driver_name` | string | e.g., `regulatory_pressure`, `market_stress_index` |
| `current_value` | float | Normalised 0–1 scale (0 = no pressure, 1 = maximum pressure) |
| `uncertainty_sigma` | float | Standard deviation of your uncertainty about the current value |
| `direction` | `+` / `-` | Does higher value push *toward* resolution (+) or *away from* it (-)? |

## PyMC implementation

```python
import pymc as pm
import numpy as np

# --- inputs (fill from domain analysis and data) ---
# Causal drivers: current values and uncertainties on a 0–1 scale
driver_names = ["regulatory_pressure", "market_stress_index", "resolution_signal",
                "escalation_risk"]
# + = higher value → more pressure toward resolution
# - = higher value → less pressure toward resolution (delays resolution)
directions   = [+1, +1, +1, -1]

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

    # Apply direction signs: signed drivers in [-1, 1]
    signed_drivers = pm.math.stack([directions[i] * driver_values[i]
                                    for i in range(n_drivers)])
    latent_pressure = pm.Deterministic("latent_pressure",
                                        pm.math.dot(weights, signed_drivers))

    # Threshold on the same scale as latent_pressure (roughly [-1, 1])
    threshold = pm.Normal("threshold", mu=0.0, sigma=0.5)

    # P(event) = logistic activation above threshold
    sharpness = pm.Gamma("sharpness", mu=8, sigma=3)  # how abrupt the transition is
    p_event_now = pm.Deterministic("p_event_now",
        pm.math.invlogit(sharpness * (latent_pressure - threshold)))

    # Calibration: if you have labelled historical cases (event / no event at known
    # pressure levels), add them here:
    # obs = pm.Bernoulli("obs", p=p_event_calibration, observed=historical_outcomes)

    idata = pm.sample(
        draws=500,
        tune=500,
        chains=6,
        backend="numba",
        nuts_sampler="nutpie",
        nuts={"target_accept": 0.92},
    )
    pm.stats.compute_log_likelihood(idata, model=causal_model)
    pm.stats.compute_log_prior(idata, model=causal_model)
```

## Extending to time horizons

`p_event_now` is the instantaneous probability. To forecast over time, you need an assumption about how driver values evolve. Two options:

**Option A — Static drivers (approximate):**
Assume drivers remain at current values. The independence formula
`P(event in W) ≈ 1 - (1 - p_event_now)^(W / W_ref)` is a rough survival approximation
when weekly probabilities are treated as independent — it can **overestimate** long
horizons when drivers persist. Prefer Option B when trends are identifiable, or use
a constant-hazard extrapolation in **days**:

```python
W_ref = 90.0  # reference window (days) for p_event_now
lambda_h = -np.log(1 - p_now_samples + 1e-9) / W_ref
p_h = 1 - np.exp(-lambda_h * horizon_days)  # monotone in calendar days
```

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
W_ref = float(horizon_days[0])

p_event_by_horizon = []
ci_low_by_horizon  = []
ci_high_by_horizon = []
lambda_samples = -np.log(1 - p_now_samples + 1e-9) / W_ref
for t in horizon_days:
    p_h = 1 - np.exp(-lambda_samples * t)
    p_event_by_horizon.append(float(np.mean(p_h)))
    ci_low_by_horizon.append(float(np.percentile(p_h, 3)))
    ci_high_by_horizon.append(float(np.percentile(p_h, 97)))

# Derived quantities for PriorSensitivity (psense)
import xarray as xr

p_now = idata.posterior["p_event_now"]
lambda_post = -np.log(1 - p_now + 1e-9) / W_ref
p_by_h_list = []
for t in horizon_days:
    p_h = 1 - np.exp(-lambda_post * t)
    p_by_h_list.append(p_h)
p_by_h = xr.concat(p_by_h_list, dim=xr.DataArray(horizon_days, dims="horizon"))
p_by_h = p_by_h.transpose("chain", "draw", "horizon")
idata.posterior["p_event_by_horizon"] = p_by_h
```

## Counterfactual / intervention analysis

A key advantage of this model is the ability to ask "what if driver X changes?".
`TruncatedNormal` driver values are not mutable via `pm.set_data` in PyMC 6 — recompute
from posterior draws instead:

```python
# What if driver C increases to 0.80 (from 0.35)?
post = idata.posterior
drivers_cf = np.array([0.75, 0.60, 0.80, 0.45])  # perturbed driver levels
signed_cf = directions * drivers_cf
latent_cf = (post["weights"] * xr.DataArray(signed_cf, dims=["driver"])).sum("driver")
p_cf = 1 / (1 + np.exp(-post["sharpness"] * (latent_cf - post["threshold"])))
print(f"Counterfactual P(event now): {float(p_cf.mean()):.3f}")
```

Report this as a sensitivity analysis in `summary.md`. For psense on derived
`p_event_by_horizon`, add at least one calibration observation (e.g. a labelled
historical episode) so `compute_log_likelihood` is non-empty; otherwise use the
analytic ±1σ driver perturbation check below.

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

## Reporting causal structure (required)

When using `CausalMechanismModel`, document DAG reasoning in **`summary.md`** and **`forecast.json`**. The orchestrator and consolidator rely on this to judge whether driver-level counterfactuals are trustworthy.

### `summary.md` — `## Causal structure notes`

```markdown
## Causal structure notes
- **Working DAG**: <nodes and directed edges — ASCII diagram or bullet list>
- **Measured drivers used**: <which DAG nodes map to model drivers and why>
- **Confounders considered**: <named confounders; controlled / unmeasured / ruled out>
- **Structural limitations**: <colliders, omitted mediators, regime-change risk, proxy overlap>
- **Identification caveat**: <what causal claim the forecast supports and what it does not>
```

### `forecast.json` fields

- **`causal_structure_notes`**: array of short strings summarising the DAG, confounder handling, and main structural limitation (required for this method).
- **`key_assumptions`**: include at least 2–3 entries on causal structure — e.g., ignorability given measured drivers, stability of driver directions, treatment of unmeasured confounders.
- **`key_uncertainties`**: include confounding and structural uncertainty where material — e.g., unmeasured shock, regime flip, ambiguous driver direction.

Example `causal_structure_notes` entries:

```json
"causal_structure_notes": [
  "Working DAG: external_shock → {driver_A, driver_B} → latent_pressure → event; shock may also affect event directly.",
  "driver_A and driver_B are compliance and enforcement proxies — treated as separate drivers with wide priors; correlation > 0.8 would warrant merging.",
  "Unmeasured confounder 'institutional_priority' not observed; omitted — may inflate P(event) if priority drives both drivers.",
  "Counterfactuals are conditional on measured drivers only; not identified for shock-level interventions."
]
```

## Gotchas

- **Unmeasurable drivers**: If a key causal driver can't be measured (e.g., "leadership intent"), encode it as a latent variable with a wide prior rather than omitting it — and disclose it in `causal_structure_notes` (see **Reporting causal structure** above).
- **Collinear drivers**: Correlated drivers (e.g., two measures of the same underlying stress) should be combined or modelled jointly. If correlation > 0.8, merge into a composite driver or include a correlation structure.
- **Calibration without historical data**: If no labelled historical examples exist to calibrate against, all parameters are prior-driven. Widen all priors and report the model as *structural reasoning, not data-driven*.
- **Direction reversal**: The direction of a driver's effect can flip under different regimes. Document this explicitly in the `key_assumptions` field of `forecast.json`.
