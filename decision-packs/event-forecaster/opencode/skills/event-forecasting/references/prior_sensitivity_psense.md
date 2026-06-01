# Prior sensitivity via ArviZ power-scaling (psense)

Use this reference for **PyMC >= 6.0** forecasting methods. Implements Check 1 in [`model_checks.md`](model_checks.md).

**Method:** Kallioinen et al., power-scaling + PSIS ([EABM Ch. 6](https://arviz-devs.github.io/EABM/Chapters/Sensitivity_checks.html), [API](https://python.arviz.org/projects/stats/en/latest/api/generated/arviz_stats.psense_summary.html)).

**Stack:** PyMC >= 6.0.0, ArviZ >= 1.0.0 (`arviz-stats`, `arviz-plots`).

---

## Sensitivity tiers

| Tier | Methods | Approach |
|------|---------|----------|
| **A** | HazardModel, CausalMechanismModel, IndicatorModel, CureRateModel, MarkovStateModel, ReferenceClassModel | Attach **deterministic** `p_event_by_horizon` to `idata.posterior`; run `psense_summary` |
| **B** | ContinuousDriverModel, JumpDiffusionModel, ThresholdCrossingModel | **Resampled re-simulation** at power-scaled α — do **not** attach MC-noisy derived quantities for psense |
| **C** | ScenarioDecomposition | Analytic Dirichlet concentration perturbation (see [`model_checks.md`](model_checks.md)) |

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

## Tier A — Standard psense on deterministic derived quantities

Use when `p_event_by_horizon` is a **deterministic function** of posterior parameters (Weibull CDF, logistic, matrix exponential, Beta-Binomial). **Do not use Tier A for path-simulation forecasts** — see Tier B below.

### Step 1 — Derived quantity: `p_event_by_horizon`

Define cumulative P(event by each orchestrator horizon date, **per MCMC draw**, using the **same** definition as `forecast.json` `p_event_by_horizon`.

#### Example: parametric survival (HazardModel)

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

#### Naming for `psense_summary`

Either one variable with a `horizon` coordinate (preferred) or one scalar per date:

```python
# Option B: separate vars (simpler for psense_summary var_names list)
for i, days in enumerate(horizon_days):
    idata.posterior[f"p_event_h{i}"] = p_by_h.isel(horizon=i).drop_vars("horizon")
```

### Step 2 — Run psense on predictions only

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

### Step 3 — pp movement for PASS/WARN/FAIL (T_mid)

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

### Step 4 — Write `check_prior_sensitivity.json`

```python
def tier_from_pp(delta_pp: float) -> str:
    if delta_pp < 10:
        return "PASS"
    if delta_pp <= 20:
        return "WARN"
    return "FAIL"

# Build by_horizon from psense_df rows + p_event at baseline
# status = tier_from_pp(delta_pp_at_mid_index)
# method = "psense"
```

See full schema in [`model_checks.md`](model_checks.md).

---

## Tier B — Simulation-based forecasts (resampled re-simulation)

**Methods:** `ContinuousDriverModel`, `JumpDiffusionModel`, `ThresholdCrossingModel`.

**Problem:** When `p_event_by_horizon` is computed as the mean over `n_paths` simulated forward paths per posterior draw, Monte Carlo noise (~3–5 pp at `n_paths=100`) is indistinguishable from posterior variation in psense. **Never attach MC-noisy derived quantities to `idata.posterior` and run `psense_summary` on them.**

**Approach:** Use power-scaling importance weights to resample posterior parameter draws, then re-run forward simulation on the resampled draws with enough paths that MC error is negligible.

### Workflow

1. Sample PyMC model; compute `log_prior` and `log_likelihood` as usual.
2. Build **baseline forecast** with forward simulation (`n_paths=100` is acceptable for point estimates and CIs in `forecast.json`).
3. Compute power-scaling importance weights from `log_prior` at **α = 0.8** and **α = 1.25**.
4. Resample posterior parameter draws using those weights.
5. Re-run forward simulation on resampled draws with **`n_paths ≥ 500`** (or until MC SE at T_mid < 2 pp).
6. Compare weighted mean `P(event by T_mid)` at α=0.8 vs 1.25 vs baseline (α=1.0) for tier classification.
7. Write `check_prior_sensitivity.json` with `"method": "resampled_simulation"`.

Use a **fixed RNG seed per (chain, draw)** during re-simulation so sensitivity reflects prior perturbation, not resampling noise.

### Code sketch

```python
import numpy as np
import xarray as xr

ALPHAS = (0.8, 1.25)
N_RESAMPLE = 2000          # resampled draws per alpha
N_PATHS_SENS = 500         # paths per resampled draw for sensitivity pass
MID_HORIZON_IDX = 2        # index of T_mid in horizon_trading_days

# --- 1. Sum log_prior per draw (chain, draw) ---
lp_ds = idata.log_prior.to_dataset()
log_prior_flat = sum(lp_ds[v].values for v in lp_ds.data_vars).reshape(-1)

# --- 2. Power-scaling weights (prior group) ---
def power_scale_weights(log_prior_flat, alpha):
    lw = (alpha - 1.0) * log_prior_flat
    lw = lw - lw.max()           # stabilize
    w = np.exp(lw)
    return w / w.sum()

# --- 3. Flatten posterior params for resampling ---
n_chains = idata.posterior.sizes["chain"]
n_draws = idata.posterior.sizes["draw"]
flat_idx = np.arange(n_chains * n_draws)

# Extract arrays needed for your forward sim (example: OU)
kappa_flat = idata.posterior["kappa"].values.reshape(-1)
mu_flat    = idata.posterior["mu_tilde"].values.reshape(-1)
sigma_flat = idata.posterior["sigma"].values.reshape(-1)

log_prior_flat = log_prior.values.reshape(-1)
rng = np.random.default_rng()

def resample_params(log_prior_flat, alpha, n_resample):
    lw = (alpha - 1.0) * log_prior_flat
    lw = lw - lw.max()
    w = np.exp(lw)
    w = w / w.sum()
    idx = rng.choice(len(flat_idx), size=n_resample, p=w)
    return idx

def simulate_first_passage(kappa, mu, sigma, n_paths, horizon_days, tau_scaled, y_current, seed):
    """Return P(event by each horizon) for one parameter draw. Use fixed seed per draw."""
    sub_rng = np.random.default_rng(seed)
    noise = sub_rng.standard_normal((n_paths, horizon_days))
    paths = np.empty((n_paths, horizon_days + 1))
    paths[:, 0] = y_current
    for t in range(horizon_days):
        drift = kappa * (mu - paths[:, t])
        paths[:, t + 1] = paths[:, t] + drift + sigma * noise[:, t]
    crossed = paths[:, 1:] <= tau_scaled   # adjust direction for your problem
    fp = np.where(crossed.any(axis=1),
                 np.argmax(crossed, axis=1).astype(float) + 1, np.inf)
    return fp

horizon_trading_days = [21, 42, 63, 126, 252]

def p_mid_at_alpha(alpha):
    idx = resample_params(log_prior_flat, alpha, N_RESAMPLE)
    p_mids = []
    for k, i in enumerate(idx):
        fp = simulate_first_passage(
            kappa_flat[i], mu_flat[i], sigma_flat[i],
            N_PATHS_SENS, max(horizon_trading_days), tau_scaled, y_current,
            seed=1000 * i + k,   # fixed seed per source draw
        )
        p_mids.append(float(np.mean(fp <= horizon_trading_days[MID_HORIZON_IDX])))
    return float(np.mean(p_mids))

p_baseline = p_mid_at_alpha(1.0)   # uniform resample ≈ baseline; or use baseline forecast value
p_low      = p_mid_at_alpha(ALPHAS[0])
p_high     = p_mid_at_alpha(ALPHAS[1])
delta_pp   = max(abs(p_low - p_baseline), abs(p_high - p_baseline)) * 100
```

Adapt `simulate_first_passage` to your method (jump-diffusion, threshold crossing, etc.). See each method's reference file for the forward-simulation loop.

### Optional: parameter-level psense for disclosure

You may run `psense_summary` on **named hyperparameters** (e.g. `kappa`, `sigma`, `log_threshold`) for diagnostic CJS values in `by_horizon.psense_diagnosis`. **Tier status comes from re-simulated forecast**, not parameter psense.

### JSON output

```python
check = {
    "check": "PriorSensitivity",
    "status": tier_from_pp(delta_pp),
    "method": "resampled_simulation",
    "t_mid_horizon": horizon_dates[MID_HORIZON_IDX],
    "original_p_mid_horizon": p_baseline,
    "absolute_change_pp": delta_pp,
    "note": f"Resampled re-simulation at alpha={ALPHAS}; n_paths={N_PATHS_SENS} per draw",
    "by_horizon": [...],   # optional per-horizon pp if computed
}
```

### n_paths guidance

| Pass | n_paths | Purpose |
|------|---------|---------|
| Baseline forecast | 100 | Point estimate + CIs in `forecast.json` |
| Sensitivity pass | ≥ 500 | Prior sensitivity tier at T_mid (target MC SE < 2 pp) |

---

## When user asks for causal interpretation

Add `psense_summary` on **named interpretable** parameters (driver levels, effects, thresholds) **in addition to** forecast sensitivity. Do not psense every latent state. For `CausalMechanismModel`, combine with driver ±1σ checks in [`causal_mechanism.md`](causal_mechanism.md).

For Tier B methods, parameter-level psense is optional disclosure only; forecast tier still uses resampled re-simulation.

---

## Hierarchical models

Compute `log_prior` only for **top-level** hyperparameters when using parameter-level psense:

```python
pm.stats.compute_log_prior(idata, var_names=["mu", "sigma", ...], model=model)  # omit group-level random effects
```

---

## Structural threshold τ (optional extra)

If τ is elicited and perturbed outside the posterior (±10% path re-simulation), document in JSON `note` as `structural_perturbation` — supplementary to Tier A/B forecast sensitivity, not a substitute.

---

## References

- [Exploratory Analysis of Bayesian Models — Sensitivity checks](https://arviz-devs.github.io/EABM/Chapters/Sensitivity_checks.html)
- [arviz_stats.psense_summary](https://python.arviz.org/projects/stats/en/latest/api/generated/arviz_stats.psense_summary.html)
