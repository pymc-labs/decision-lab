# Prior sensitivity via ArviZ power-scaling (psense)

Use this reference for **PyMC >= 6.0** forecasting methods (all methods in this skill use raw PyMC). Implements Check 1 in [`model_checks.md`](model_checks.md). Derived quantities are added to `idata.posterior` after sampling.

**Method:** Kallioinen et al., power-scaling + PSIS ([EABM Ch. 6](https://arviz-devs.github.io/EABM/Chapters/Sensitivity_checks.html), [API](https://python.arviz.org/projects/stats/en/latest/api/generated/arviz_stats.psense_summary.html)).

**Stack:** PyMC >= 6.0.0, ArviZ >= 1.0.0 (`arviz-stats`, `arviz-plots`).

---

## Requirements

```python
import pymc as pm
from arviz_stats import psense_summary
from arviz_plots import plot_psense_quantities
```

Sample with Nutpie (Numba backend) and compute log densities **after** sampling — Nutpie ignores `idata_kwargs`:

```python
with model:
    idata = pm.sample(
        draws=500,
        tune=500,                   # required — nutpie defaults to 400 if omitted
        chains=6,
        backend="numba",
        nuts_sampler="nutpie",
        nuts={"target_accept": 0.9},
        # do NOT pass random_seed
    )
    pm.stats.compute_log_likelihood(idata, model=model)
    pm.stats.compute_log_prior(idata, model=model)
```

**Fallback:** if Nutpie fails (discrete parameters, incompatible transforms), use
`nuts_sampler="numpyro"` with `idata_kwargs={"log_likelihood": True, "log_prior": True}`.

---

## Step 1 — Derived quantity: `p_event_by_horizon`

Define cumulative P(event by each orchestrator horizon date, **per MCMC draw**, using the **same** definition as `forecast.json` `p_event_by_horizon`.

### Example: parametric survival (HazardModel)

After sampling, with `horizon_dates` as day offsets from `forecast_as_of` (or calendar dates converted to days):

```python
import numpy as np
import xarray as xr

# horizon_days: float array, days from as-of to each horizon
horizon_days = np.array([...])  # align with prompt horizon_dates

post = idata.posterior
alpha = post["alpha"]  # dims: chain, draw
beta = post["beta"]

# Weibull: P(T <= t) = 1 - exp(-(t/beta)^alpha)  — adjust to your parameterisation
t = xr.DataArray(horizon_days, dims="horizon", coords={"horizon": horizon_days})
# Broadcast: survival prob S(t); event by t is 1 - S(t)
p_by_h = 1.0 - np.exp(-((t / beta) ** alpha))
# xarray broadcasts horizon first; psense expects (chain, draw, horizon)
p_by_h = p_by_h.transpose("chain", "draw", "horizon")

idata.posterior["p_event_by_horizon"] = p_by_h
```

### Example: path simulation (ContinuousDriverModel)

For each draw, simulate paths; compute fraction of paths with first passage before each horizon day count, then stack into `p_event_by_horizon` with dims `(chain, draw, horizon)`.

### Naming for `psense_summary`

Either one variable with a `horizon` coordinate (preferred) or one scalar per date:

```python
# Option B: separate vars (simpler for psense_summary var_names list)
for i, days in enumerate(horizon_days):
    idata.posterior[f"p_event_h{i}"] = p_by_h.isel(horizon=i).drop_vars("horizon")
```

---

## Step 2 — Run psense on predictions only

```python
# All horizon cumulative probabilities
horizon_vars = [v for v in idata.posterior.data_vars if v.startswith("p_event_h")]
# or var_names=["p_event_by_horizon"] if single stacked variable

psense_df = psense_summary(
    idata,
    var_names=horizon_vars,  # or ["p_event_by_horizon"]
    threshold=0.05,
)
print(psense_df)
```

Columns: `prior`, `likelihood`, `diagnosis` (`✓`, `prior-data conflict`, `strong prior / weak likelihood`).

**Interpretation (not pass/fail by itself):**

| Pattern | Typical narrative |
|---------|-------------------|
| Low `prior`, higher `likelihood` at short horizon | Data dominate near-term cumulative risk |
| Higher `prior` at long horizon only | Tail / structural assumptions matter at long scale |
| Both > 0.05, `prior-data conflict` | Prior and data both pull; disclose in `summary.md` |
| `strong prior / weak likelihood` | Small N or very informative prior — often acceptable |

---

## Step 3 — pp movement for PASS/WARN/FAIL (T_mid)

Orchestrator tier uses **percentage-point** change at T_mid. Option A: visual/quantile check via plots:

```python
plot_psense_quantities(
    idata,
    var_names=["p_event_h1"],  # index of mid-horizon
    quantities=["mean"],
)
```

Option B: compare reweighted predictive means at α=0.8 and 1.25 vs 1.0 (read off plot or use psense utilities). Map `absolute_change_pp` to model_checks thresholds (< 10 / 10–20 / > 20 pp).

Set **top-level** `status` from T_mid only; fill `by_horizon` array in JSON from `psense_df` plus per-horizon pp if computed.

---

## Step 4 — Write `check_prior_sensitivity.json`

```python
def tier_from_pp(delta_pp: float) -> str:
    if delta_pp < 10:
        return "PASS"
    if delta_pp <= 20:
        return "WARN"
    return "FAIL"

# Build by_horizon from psense_df rows + p_event at baseline
# status = tier_from_pp(delta_pp_at_mid_index)
```

See full schema in [`model_checks.md`](model_checks.md).

---

## When user asks for causal interpretation

Add `psense_summary` on **named interpretable** parameters (driver levels, effects, thresholds) **in addition to** all `p_event_*` horizon vars. Do not psense every latent state. For `CausalMechanismModel`, combine with driver ±1σ checks in [`causal_mechanism.md`](causal_mechanism.md).

---

## Hierarchical models

Compute `log_prior` only for **top-level** hyperparameters when using parameter-level psense:

```python
pm.stats.compute_log_prior(idata, var_names=["mu", "sigma", ...], model=model)  # omit group-level random effects
```

---

## Structural threshold τ (optional extra)

If τ is elicited and perturbed outside the posterior (±10% path re-simulation), document in JSON `note` as `structural_perturbation` — separate from psense, not a substitute for derived-quantity psense on `p_event_by_horizon`.

---

## References

- [Exploratory Analysis of Bayesian Models — Sensitivity checks](https://arviz-devs.github.io/EABM/Chapters/Sensitivity_checks.html)
- [arviz_stats.psense_summary](https://python.arviz.org/projects/stats/en/latest/api/generated/arviz_stats.psense_summary.html)
