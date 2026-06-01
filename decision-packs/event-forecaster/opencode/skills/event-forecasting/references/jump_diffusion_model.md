# JumpDiffusionModel — Jump-Diffusion Driver + First-Passage Time

Fit a **Merton-style jump-diffusion** to a continuous driver time-series, then
forward-simulate paths and report the distribution of **first-passage times** —
how long until the simulated driver first crosses a threshold τ that signals the
event. A peaks-over-threshold (Generalized Pareto) tail model provides an analytic
cross-check on the exceedance probability.

This is the discontinuous-path counterpart to `ContinuousDriverModel`. That model's
variants (OU/RWD/SV/LL/LLT) all assume **Gaussian increments** — continuous paths.
Geopolitical drivers (risk premia, shipping insurance, commodity indices) move by **discrete
shocks**, and the threshold-crossing probability is dominated by the fat right tail
those jumps create. A pure-diffusion model systematically understates P(event) when
the event is a tail crossing.

## When to use

- A measurable continuous driver has a plausible leading relationship to the event.
- The driver exhibits **discrete shocks / fat tails** — large single-period moves
  that a Gaussian model would treat as near-impossible.
- The event can be operationalised as the driver crossing a threshold τ in a
  direction.
- ≥ ~100 observations of the driver are available.

If the driver's increments look approximately Gaussian (no jumps, no heavy tails),
prefer `ContinuousDriverModel`. If the tail behaviour is the *whole* question and
you have no usable path dynamics, the EVT/POT section below can stand alone.

## Event definition and threshold

Operationalise the event as **the driver crosses threshold τ in direction D**, using
the same conventions as `ContinuousDriverModel`:

| Approach | When to use |
|---|---|
| Percentile of a reference period | Driver returns to / departs from a "normal" level |
| Value at a historical case | One past instance of the event at a known driver level |
| Expert-elicited value | No historical cases or natural reference period |
| Structural formula | A mechanical rule (e.g. a break-even price) |

State the crossing direction explicitly (`falls_below` → event fires when
`driver <= τ`; `rises_above` → when `driver >= τ`). Document your τ choice — do not
default to the 95th percentile without justification. See
`continuous_driver_model.md` for the full threshold-selection discussion.

## Model specification

A jump-diffusion adds a compound-Poisson jump term to a drifting Brownian motion:

```
dX = μ dt + σ dW + J dN

  μ        drift of the diffusion part
  σ        diffusion volatility (per step)
  dW       Brownian increment (Gaussian)
  dN       Poisson arrivals, intensity λ (expected jumps per unit time)
  J        jump size, J ~ Normal(μ_J, σ_J)   (Laplace / StudentT for heavier tails)
```

Work on the log / standardised scale, consistently with `ContinuousDriverModel`
(log scale for strictly-positive drivers like prices).

## Step 1 — Load driver data, compute τ, standardise

```python
import numpy as np

driver_series    = ...     # 1D array, chronological order
reference_values = ...     # subset used to compute the threshold
current_value    = float(driver_series[-1])

q   = 0.95                                       # choose per problem, document it
tau = float(np.percentile(reference_values, q))
tau_source = f"{int(q*100)}th pct of reference period"
crossing_direction = "rises_above"               # or "falls_below"

# Log-standardise (strictly-positive driver)
log_driver = np.log(driver_series)
mean_log   = float(np.mean(log_driver))
std_log    = float(np.std(log_driver))
y          = (log_driver - mean_log) / std_log
tau_scaled = (np.log(tau) - mean_log) / std_log
print(f"τ = {tau:.4f} ({tau_source}); current = {current_value:.4f}; "
      f"event fires when driver {crossing_direction} τ")
```

## Step 2 — PyMC implementation (mixture likelihood)

The exact jump-diffusion likelihood over a single time step is a Poisson mixture over
the number of jumps. For the small `dt` of daily/weekly data, P(≥2 jumps in one step)
is negligible, so a **two-component mixture on the increments** is the standard,
robust approximation — a "no-jump" component and a "jump" component, mixed by
`p_jump ≈ λ·dt`. This avoids a latent per-step jump count and samples cleanly.

```python
import pymc as pm
from arviz_stats import summary

r = np.diff(y)            # standardised increments

with pm.Model() as jd_model:
    # Diffusion part
    mu        = pm.Normal("mu", mu=0.0, sigma=0.01)
    log_sigma = pm.Normal("log_sigma",
                          mu=float(np.log(np.std(r) + 1e-8)), sigma=0.5)
    sigma     = pm.Deterministic("sigma", pm.math.exp(log_sigma))

    # Jump part
    # p_jump ≈ λ·dt = probability a given step contains a jump (expect small)
    p_jump  = pm.Beta("p_jump", alpha=2, beta=20)         # prior mean ~0.09 jumps/step
    mu_J    = pm.Normal("mu_J", mu=0.0, sigma=0.5)        # set sign prior if shocks are directional
    sigma_J = pm.HalfNormal("sigma_J", sigma=1.0)

    # Two-component mixture on each increment.
    # Constrain the jump component to LARGER variance for identifiability:
    # its std is sqrt(sigma^2 + sigma_J^2) >= sigma by construction.
    comp_diffusion = pm.Normal.dist(mu=mu, sigma=sigma)
    comp_jump      = pm.Normal.dist(mu=mu + mu_J,
                                    sigma=pm.math.sqrt(sigma**2 + sigma_J**2))
    pm.Mixture("obs",
               w=pm.math.stack([1 - p_jump, p_jump]),
               comp_dists=[comp_diffusion, comp_jump],
               observed=r)

    idata = pm.sample(
        draws=500,
        tune=500,
        chains=6,
        backend="numba",
        nuts_sampler="nutpie",
        nuts={"target_accept": 0.92},
        # do NOT pass random_seed
    )
    pm.stats.compute_log_likelihood(idata, model=jd_model)
    pm.stats.compute_log_prior(idata, model=jd_model)

# Recover the jump intensity λ (per step) for documentation / simulation
lam_per_step = idata.posterior["p_jump"].values.flatten()   # ≈ λ·dt
```

## Step 3 — Convergence diagnostics

```python
summary_df      = summary(idata, var_names=["mu", "sigma", "p_jump", "mu_J", "sigma_J"])
rhat_max        = float(summary_df["r_hat"].max())
ess_bulk_min    = float(summary_df["ess_bulk"].min())
divergences     = int(idata.sample_stats["diverging"].sum())
total_draws     = int(idata.sample_stats.sizes["chain"] * idata.sample_stats.sizes["draw"])
divergence_rate = divergences / total_draws
```

## Step 4 — Forward simulation and first-passage times

Reuse the `ContinuousDriverModel` forward-sim structure; each step is a Gaussian
increment **plus** a Bernoulli(p_jump) jump drawing `Normal(μ_J, σ_J)`.

```python
mu_s    = idata.posterior["mu"].values.flatten()
sigma_s = idata.posterior["sigma"].values.flatten()
pj_s    = idata.posterior["p_jump"].values.flatten()
muJ_s   = idata.posterior["mu_J"].values.flatten()
sigJ_s  = idata.posterior["sigma_J"].values.flatten()
n_post  = len(mu_s)

n_paths      = 200           # increase for production
horizon_days = 252           # trading days; adjust to your problem
y_current    = float(y[-1])
rng = np.random.default_rng()

paths = np.empty((n_post, n_paths, horizon_days + 1))
paths[:, :, 0] = y_current

for t in range(horizon_days):
    diffusion = mu_s[:, None] + sigma_s[:, None] * rng.standard_normal((n_post, n_paths))
    jump_occurs = rng.random((n_post, n_paths)) < pj_s[:, None]
    jump_size   = muJ_s[:, None] + sigJ_s[:, None] * rng.standard_normal((n_post, n_paths))
    paths[:, :, t + 1] = paths[:, :, t] + diffusion + jump_occurs * jump_size

# First-passage: first step where the path crosses tau_scaled in direction D
if crossing_direction == "falls_below":
    crossed = paths[:, :, 1:] <= tau_scaled
else:
    crossed = paths[:, :, 1:] >= tau_scaled

fp_days = np.where(crossed.any(axis=2),
                   np.argmax(crossed, axis=2).astype(float) + 1,
                   np.inf)

finite_fp      = fp_days[np.isfinite(fp_days)]
median_days_fp = float(np.median(finite_fp)) if len(finite_fp) else float("nan")
p10_fp         = float(np.percentile(finite_fp, 10)) if len(finite_fp) else float("nan")
p90_fp         = float(np.percentile(finite_fp, 90)) if len(finite_fp) else float("nan")
```

## Step 5 — EVT / POT analytic cross-check (Generalized Pareto)

The first-passage probability over a horizon is driven by the chance of a large
adverse move. Extreme-value theory says the exceedances of a high threshold `u`
follow a **Generalized Pareto distribution (GPD)**. Fit the GPD to the tail of the
increments, use it to estimate the per-step probability of a move large enough to
breach τ from the current level, inflate to the horizon, and compare to the
Monte-Carlo result. This is the jump-diffusion analogue of the inverse-Gaussian
cross-check in `continuous_driver_model.md`.

```python
from scipy.stats import genpareto

# Distance (in standardised units) the driver must move in one step to breach τ.
# For rises_above the relevant tail is the upper tail of the increments; mirror for falls_below.
if crossing_direction == "rises_above":
    excesses_dir = r                       # large positive increments breach an upper τ
    gap = tau_scaled - y_current           # > 0 if τ is above current level
else:
    excesses_dir = -r                      # large negative increments breach a lower τ
    gap = y_current - tau_scaled

# Peaks-over-threshold: take u at, e.g., the 90th pct of the directional moves
u          = float(np.percentile(excesses_dir, 90))
exceed     = excesses_dir[excesses_dir > u] - u
n_exceed   = len(exceed)
p_exceed_u = n_exceed / len(excesses_dir)

if n_exceed >= 10 and gap > 0:
    xi, _, beta = genpareto.fit(exceed, floc=0)        # shape ξ, scale β
    # P(single-step directional move >= gap) via the POT formula
    if gap > u:
        p_step = p_exceed_u * genpareto.sf(gap - u, c=xi, loc=0, scale=beta)
    else:
        p_step = float(np.mean(excesses_dir >= gap))   # gap inside the body; use empirical
    # Inflate one-step prob to the horizon (independent-steps approximation)
    p_evt_horizon = 1 - (1 - p_step) ** horizon_days
    p_mc_horizon  = float(np.mean(fp_days <= horizon_days))
    print(f"EVT/POT: ξ={xi:.3f} β={beta:.3f} | "
          f"P_evt={p_evt_horizon:.3f} vs P_mc={p_mc_horizon:.3f}")
    if abs(p_evt_horizon - p_mc_horizon) > 0.10:
        print("WARNING: >10pp EVT vs Monte-Carlo discrepancy — re-examine jump params or τ")
else:
    print("EVT cross-check not applicable (too few exceedances or τ already breached)")
```

The independent-steps inflation is a deliberately rough upper-bound style check, not
a second forecast: a > ~10pp gap signals that the jump component and the empirical
tail disagree and warrants investigation. A Bayesian GPD (priors on ξ, β via PyMC)
can replace `genpareto.fit` if you want a posterior on the tail.

## Step 6 — Extract horizon probabilities and write `forecast.json`

Compute per-draw horizon probabilities for CIs (do **not** attach to `idata.posterior`
for psense — use Tier B resampled re-simulation for PriorSensitivity):

```python
horizon_trading_days = [21, 42, 63, 126, 252]      # adjust to your problem
n_chains, n_draws = idata.posterior.sizes["chain"], idata.posterior.sizes["draw"]
p_by_h = np.array([
    [float(np.mean(fp_days[i] <= h)) for h in horizon_trading_days]
    for i in range(n_post)
]).reshape(n_chains, n_draws, len(horizon_trading_days))
```

```python
import json, os
from datetime import date, timedelta

os.makedirs("outputs", exist_ok=True)

cal_per_tday = 7 / 5
horizon_trading_days = [21, 42, 63, 126, 252]      # adjust to your problem
horizon_dates = [(date.today() + timedelta(days=int(h * cal_per_tday))).isoformat()
                 for h in horizon_trading_days]

all_fp   = fp_days.flatten()
cdf_vals = np.array([np.mean(all_fp <= h) for h in horizon_trading_days])

ci_low_by_horizon  = [
    float(np.percentile(p_by_h[:, :, h], 3)) for h in range(len(horizon_trading_days))
]
ci_high_by_horizon = [
    float(np.percentile(p_by_h[:, :, h], 97)) for h in range(len(horizon_trading_days))
]

forecast = {
    "method":                 "JumpDiffusionModel",
    "model_variant":          "JD-Normal-jumps",     # or JD-Laplace-jumps / JD-StudentT-jumps
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
    "ci_low_by_horizon":      ci_low_by_horizon,
    "ci_high_by_horizon":     ci_high_by_horizon,
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
        f"Driver follows a jump-diffusion (drift μ, vol σ, jump prob {float(np.mean(pj_s)):.3f}/step)",
        f"Jump sizes ~ Normal(μ_J, σ_J); ≤1 jump per step (small-dt approximation)",
        f"Threshold τ = {tau:.4f} ({tau_source}); event fires when driver {crossing_direction} τ",
    ],
    "key_uncertainties":      [
        "Correct threshold τ — most important sensitivity",
        "Jump intensity λ and jump scale σ_J — separate jumps from heavy-tailed diffusion?",
        "EVT cross-check agreement (see check output)",
        "Stationarity of the jump-diffusion dynamics over the horizon",
    ],
}

with open("forecast.json", "w") as f:
    json.dump(forecast, f, indent=2)

idata.to_netcdf("outputs/idata.nc")
```

## Calibration checks

**PriorSensitivity** — primary: **resampled re-simulation** (Tier B) per
[`prior_sensitivity_psense.md`](prior_sensitivity_psense.md). Do not run psense on
MC-noisy per-draw `p_event_by_horizon`. Optional **structural** check: perturb τ by ±10%
and re-evaluate crossings on fixed paths (document in JSON `note` as `structural_tau`).
WARN/FAIL at T_mid: disclose threshold/prior dependence; expected when jumps are rare —
lean on EVT cross-check.

**ConsistencyCheck** — verify P(event by T) is monotonically non-decreasing across
horizons and all values are in [0, 1].

**ReferenceClassCongruence** — compare P(event by T_mid) to a historical base rate;
a ratio > 4× or < 0.25× warrants explicit justification.

**EVT cross-check** — treat the Step-5 EVT vs Monte-Carlo comparison as an additional
internal-consistency check; a large gap is a flag, not an automatic failure.

## Gotchas

- **Mixture identifiability / label-switching.** Without a constraint, the two Normal
  components can swap roles. The model above forces the jump component to have the
  larger variance (`sqrt(σ²+σ_J²) ≥ σ`); keep that constraint. If `p_jump` and `σ_J`
  posteriors are very wide, the data has too few jumps to identify them — report it.
- **Jumps vs heavy-tailed diffusion.** Fat tails can be modelled either as jumps
  (this method) or as a Student-t / stochastic-vol diffusion (`ContinuousDriverModel`
  SV variant). Decide based on whether the large moves are *sudden and discrete*
  (jumps) or *clustered volatility* (SV). If unsure, run both and compare.
- **Standardisation consistency.** Apply the same log/standardise transform to both
  the series `y` and the threshold `tau_scaled`. Mixing raw and scaled values is a
  silent bug.
- **Crossing-direction sign.** `<=` vs `>=` inverts the forecast and also flips which
  tail the EVT check examines. Verify a sample path manually.
- **EVT threshold choice.** The POT threshold `u` trades bias (too low → body
  contaminates the tail) against variance (too high → too few exceedances, unstable
  ξ). The 90th percentile is a starting point; check sensitivity to ±5 percentile
  points. Few exceedances → a wide, unreliable ξ posterior.
- **Driver may have already crossed τ.** If `current_value` is already past τ in the
  crossing direction, the event has fired by this metric — re-examine the threshold
  or event definition.

## Variants

| Variant | When | Change |
|---|---|---|
| `JD-Laplace-jumps` | Jumps have heavier tails than Normal | Replace the jump component with a Laplace (`pm.Laplace`) |
| `JD-StudentT-jumps` | Very heavy jump tails / outliers | Use `pm.StudentT` for the jump component with a low-ν prior |
| Jump-diffusion **OU** | Driver mean-reverts *and* jumps | Add the OU drift `κ(μ̃ − y_t)` from `continuous_driver_model.md` to the diffusion part of both the likelihood and the forward sim |
