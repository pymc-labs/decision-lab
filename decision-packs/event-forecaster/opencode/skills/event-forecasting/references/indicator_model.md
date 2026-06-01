# IndicatorModel — Leading Indicator Regression

Use measurable, regularly updated time-series signals to predict whether the event will resolve in a future window. Appropriate when you have quantitative indicators that are plausibly causally or correlatively linked to the outcome.

## When to use

- You have ≥ 2 years of indicator data (oil prices, diplomatic sentiment scores, trade volumes, military activity indices, news sentiment, sanctions severity, etc.).
- The indicators vary over time and are updated at least weekly.
- Historical episodes give you labelled examples: indicator values at time t, event (resolved or not) within the next W days.
- Do NOT use this method if the only indicator data comes from the current episode with no historical comparators.

## Data preparation

You need a time-indexed table where each row is a historical time point:

| column | type | notes |
|---|---|---|
| `date` | datetime | Weekly or daily |
| `indicator_1`, ..., `indicator_k` | float | Normalise to mean 0 / std 1 |
| `event_within_W` | bool | Did the event resolve within W days of this date? |
| `weight` (optional) | float | Down-weight older rows if distribution shift suspected |

Building the labels: for each historical episode, generate labelled rows for the period leading up to resolution. Rows within W days of resolution get `event_within_W = True`.

## PyMC implementation

```python
import pymc as pm
import numpy as np
import arviz as az
import pandas as pd

# --- inputs ---
# X_train: (n_obs, n_features) normalised indicator matrix
# y_train: (n_obs,) binary labels — 1 = event resolved within W days
# X_current: (1, n_features) — current indicator values (for prediction)

n_features = X_train.shape[1]

with pm.Model() as indicator_model:
    # Intercept (base probability)
    alpha = pm.Normal("alpha", mu=0, sigma=2)

    # Coefficients (regularised; indicators are normalised)
    betas = pm.Normal("betas", mu=0, sigma=1, shape=n_features)

    # Logistic model
    logit_p = alpha + pm.math.dot(X_train, betas)
    p = pm.Deterministic("p_train", pm.math.invlogit(logit_p))

    # Likelihood
    obs = pm.Bernoulli("obs", p=p, observed=y_train)

    idata = pm.sample(
        draws=500, tune=500, chains=4,
        target_accept=0.9,
        nuts_sampler="numpyro",
        idata_kwargs={"log_likelihood": True, "log_prior": True},
    )
```

## Prediction at current indicator values

```python
# Sample posterior predictive at current conditions
alpha_samples = idata.posterior["alpha"].values.flatten()
betas_samples = idata.posterior["betas"].values  # shape: (chains*draws, n_features)
betas_flat    = betas_samples.reshape(-1, n_features)

logit_p_current = alpha_samples + betas_flat @ X_current.flatten()
p_current_samples = 1 / (1 + np.exp(-logit_p_current))

p_event_in_W   = float(np.mean(p_current_samples))
ci_low_in_W    = float(np.percentile(p_current_samples, 3))
ci_high_in_W   = float(np.percentile(p_current_samples, 97))
```

## Extending to multiple horizons

The base model gives P(event in next W days). **Preferred for psense:** fit once per
orchestrator horizon (different `event_within_W` labels per W), or refit for each W1, W2, W3.
After sampling, attach per-draw probabilities for PriorSensitivity:

```python
import xarray as xr

# Current indicators X_current; one fit per horizon W
logit_p = idata.posterior["alpha"] + (
    idata.posterior["betas"] @ xr.DataArray(X_current.flatten(), dims="feature")
)
p_draw = 1 / (1 + np.exp(-logit_p))
idata.posterior["p_event_h0"] = p_draw.squeeze()  # name per horizon index, e.g. p_event_h1
```

See [`prior_sensitivity_psense.md`](prior_sensitivity_psense.md). Approximation only if refit is infeasible:
- `P(event in W') ≈ 1 - (1 - P_W)^(W'/W)` for W' ≠ W (document as approximate).

## Feature selection

Do NOT include more than 5–7 indicator features without strong justification. With ≤ 50 historical labelled rows (common for rare geopolitical events), more features will overfit. Options:
- Domain-selection: pick the 3–5 causally most plausible indicators.
- Regularisation: use `pm.Laplace("betas", mu=0, b=0.5)` (Laplace prior = soft L1 regularisation).
- Hierarchical: pool feature effects when multiple indicators are from the same domain.

## Model checks

**HistoricalCalibration** — primary check for this method. Apply the model to
historical labelled episodes (leave-one-out or hold-out set). Compute Brier score
vs. naive baseline. If Brier skill < 0.05, the indicators do not improve over the
base rate and the method should be downgraded or replaced.

**PriorSensitivity** — derived `p_event_by_horizon` via psense per
[`prior_sensitivity_psense.md`](prior_sensitivity_psense.md) (sample with
`log_prior` and `log_likelihood`). WARN/FAIL at T_mid: disclose prior dependence
(small N / weak signal); justify in `summary.md`.

**ConsistencyCheck** — verify that increasing each indicator value in the "positive"
direction increases P(event) as expected. If the sign of a coefficient contradicts
the hypothesised causal direction, investigate before reporting.

## Gotchas

- **Spurious correlations**: Economic indicators often correlate with each other and with time. Check for multicollinearity before fitting. Remove indicators with pairwise correlation > 0.8.
- **Small N**: If you have < 20 labelled historical examples, the posterior will be prior-dominated. Use very conservative (wide) priors and acknowledge this.
- **Non-stationarity**: If the causal mechanism changed over time (e.g., sanctions regimes of the 2020s differ from the 1980s), older data can mislead. Downweight or exclude.
- **Label lookahead**: When constructing `event_within_W`, ensure you are not using future data to construct the indicator values. Each row's indicators must be available at that point in time.
- **No historical analogues**: If the event is truly unprecedented and you cannot construct a labelled dataset, do NOT use this method. Use `ScenarioDecomposition` or `ReferenceClassModel` instead.
