# MarkovStateModel — Continuous-Time Markov / Multi-State Model

Model the system as occupying one of a small set of discrete states, with an
**absorbing "resolved" state** representing the event. Estimate the transition-rate
(generator) matrix **Q** from historical state-dwell data, then read
P(event by t) directly off the transition matrix **P(t) = expm(Q · t)**.

This gives `ScenarioDecomposition` what it lacks: **dynamics**. Instead of eliciting
a separate conditional probability for each scenario at each horizon, you estimate
the rates at which the system moves between states and let the matrix exponential
propagate them forward. The horizon curve is monotone by construction.

## When to use

- The situation can be described by a small set (3–5) of **discrete, identifiable
  regimes** — e.g. calm → tension → crisis → resolved.
- You have observable (even rough) historical transitions between those regimes:
  how long the system tended to dwell in each state, and which state it moved to next.
- You want forecasts that respond to **which state the system is in now** (the start
  state), not just a global base rate.
- You want a transparent, dynamic alternative to a static scenario tree.

Contrast with:
- **`ScenarioDecomposition`** — a *static* snapshot: P(scenario) × P(event | scenario)
  with hand-elicited per-horizon conditionals. `MarkovStateModel` instead estimates
  transition *rates* and derives every horizon from them.
- **`HazardModel`** — a single absorbing event with no intermediate states.
  `MarkovStateModel` is the right tool when the path to resolution passes through
  meaningful intermediate regimes.

## Conceptual structure

```
States:   [calm, tension, crisis, resolved]   (resolved is absorbing)

Generator matrix Q (rows = from-state, cols = to-state):
   - off-diagonal q_ij ≥ 0 = instantaneous rate of moving from state i to state j
   - diagonal     q_ii    = -Σ_{j≠i} q_ij   (each row sums to 0)
   - absorbing "resolved" row is all zeros (no exit)

Transition probabilities over a horizon of t days:
   P(t) = expm(Q · t)            [matrix exponential]

Forecast:
   P(event by t) = P(t)[start_state, resolved_state]
```

## Data preparation

Aggregate historical analogues into observed transitions. You need, per observed
sojourn:

| column | type | notes |
|---|---|---|
| `from_state` | int/str | State the system was in |
| `to_state` | int/str | State it transitioned to (may be the absorbing state) |
| `dwell_days` | float | Days spent in `from_state` before the transition |
| `censored` (optional) | bool | `True` if the sojourn was still ongoing at data cut-off (no observed transition yet) |

Map states to integer indices `0 … S-1` with the absorbing "resolved" state last.
Document explicitly **which state the current situation is in** — this is the
`start_state` used for the forecast.

If you only have aggregate counts, the minimal sufficient statistics are:
- `n_ij` — number of observed `i → j` transitions, and
- `total_time_i` — total exposure time spent in state `i`.

The MLE of each rate is `q_ij ≈ n_ij / total_time_i`; the Bayesian model below
puts a prior around this.

## PyMC implementation

Keep the state count small (3–5). Put a weakly-informative prior on each
off-diagonal rate, build `Q` deterministically, and use the exponential-dwell +
which-transition-fired likelihood (this is the standard competing-exponentials
representation of a CTMC).

```python
import pymc as pm
import numpy as np
from arviz_stats import summary

# --- inputs (fill from your data) ---
S = 4                      # number of states; absorbing "resolved" is index S-1
state_names = ["calm", "tension", "crisis", "resolved"]
absorbing   = S - 1
start_state = 0            # which state the current situation is in

# Observed sojourns (one row each)
from_state = np.array([...], dtype=int)   # state the system was in
to_state   = np.array([...], dtype=int)   # state it moved to
dwell_days = np.array([...], dtype=float) # days in from_state before the move
censored   = np.array([...], dtype=bool)  # True = ongoing, no transition observed

# Allowed transitions: list of (i, j) pairs that are structurally possible.
# Exclude transitions out of the absorbing state and any you deem impossible.
allowed = [(0, 1), (1, 0), (1, 2), (2, 1), (2, 3)]   # edit to your state graph
# A rough per-rate prior mean: 1 / typical dwell time in days (e.g. ~1/30 for a month)
rate_prior_mu = 1.0 / 30.0

# Precompute branch indices (numpy, before pm.Model) — vectorized branch likelihood
obs_mask = ~censored
obs_from = from_state[obs_mask].astype(int)
obs_to = to_state[obs_mask].astype(int)
branch_rate_idx = np.fromiter(
    (next(k for k, (a, b) in enumerate(allowed) if a == i and b == j)
     for i, j in zip(obs_from, obs_to)),
    dtype=int,
    count=len(obs_from),
)

with pm.Model() as markov_model:
    # One positive rate per allowed transition
    rates = pm.Gamma("rates", mu=rate_prior_mu, sigma=rate_prior_mu,
                     shape=len(allowed))

    # Total exit rate out of each (non-absorbing) state = sum of its outgoing rates
    # exit_rate[i] is used as the rate of the exponential dwell time in state i.
    exit_rate = [pm.math.constant(1e-9)] * S   # tiny floor avoids div-by-zero
    for r, (i, j) in zip(range(len(allowed)), allowed):
        exit_rate[i] = exit_rate[i] + rates[r]
    exit_rate = pm.math.stack(exit_rate)       # shape (S,)

    # Likelihood 1 — dwell times: time in a state ~ Exponential(exit_rate[from_state])
    pm.Exponential("dwell_obs", lam=exit_rate[obs_from], observed=dwell_days[obs_mask])
    if censored.any():
        cens_from = from_state[censored].astype(int)
        pm.Potential("dwell_cens", (-exit_rate[cens_from] * dwell_days[censored]).sum())

    # Likelihood 2 — branch choice (vectorized): log q_ij - log exit_rate(i)
    log_branch = (
        pm.math.log(rates[branch_rate_idx] + 1e-12)
        - pm.math.log(exit_rate[obs_from] + 1e-12)
    )
    pm.Potential("branch", log_branch.sum())

    idata = pm.sample(
        draws=500,
        tune=500,
        chains=6,
        backend="numba",
        nuts_sampler="nutpie",
        nuts={"target_accept": 0.9},
        # do NOT pass random_seed
    )
    pm.stats.compute_log_likelihood(idata, model=markov_model)
    pm.stats.compute_log_prior(idata, model=markov_model)
```

> The competing-exponentials factorisation above (dwell time × branch choice) is
> exactly equivalent to the CTMC likelihood and keeps the model out of any
> in-graph matrix exponential during sampling.

## Extracting the forecast

Reconstruct `Q` from each posterior rate draw and apply `scipy.linalg.expm` in
NumPy **after** sampling — mirroring the post-sampling forward-simulation pattern
used by `HazardModel` and `ContinuousDriverModel`.

```python
from scipy.linalg import expm

rate_draws = idata.posterior["rates"].values.reshape(-1, len(allowed))  # (n_post, n_rates)
n_post = rate_draws.shape[0]

def build_Q(rate_vec):
    Q = np.zeros((S, S))
    for r, (i, j) in enumerate(allowed):
        Q[i, j] = rate_vec[r]
    # diagonal = -row sum (absorbing row stays all-zero)
    for i in range(S):
        Q[i, i] = -Q[i].sum()
    return Q

horizon_days = [90, 180, 365]          # set from orchestrator horizons
p_event_draws = np.zeros((n_post, len(horizon_days)))

for d in range(n_post):
    Q = build_Q(rate_draws[d])
    for h, t in enumerate(horizon_days):
        P_t = expm(Q * t)
        p_event_draws[d, h] = P_t[start_state, absorbing]

# Derived quantities for PriorSensitivity (psense)
import xarray as xr

n_chains, n_draws = idata.posterior.sizes["chain"], idata.posterior.sizes["draw"]
idata.posterior["p_event_by_horizon"] = xr.DataArray(
    p_event_draws.reshape(n_chains, n_draws, len(horizon_days)),
    dims=("chain", "draw", "horizon"),
    coords={"horizon": horizon_days},
)

# Point estimates and CIs from full posterior draws (same array used for psense)
p_event_by_horizon = [float(np.mean(p_event_draws[:, h])) for h in range(len(horizon_days))]
ci_low_by_horizon  = [float(np.percentile(p_event_draws[:, h], 3))  for h in range(len(horizon_days))]
ci_high_by_horizon = [float(np.percentile(p_event_draws[:, h], 97)) for h in range(len(horizon_days))]

# Optional thinning for speed when computing median days only
thin = max(1, n_post // 2000)
idx = np.arange(0, n_post, thin)

# Median days to event: per draw, solve P(resolved by t) = 0.5 on a time grid
grid = np.arange(1, 365 * 5, 7)        # weekly grid out to 5 years; extend if needed
med_days = np.full(len(idx), np.nan)
for k, d in enumerate(idx):
    Q = build_Q(rate_draws[d])
    curve = np.array([expm(Q * t)[start_state, absorbing] for t in grid])
    if curve[-1] >= 0.5:
        med_days[k] = float(np.interp(0.5, curve, grid))
    # else: leaves NaN — this draw does not reach 50% within the grid (report honestly)

median_days = float(np.nanmean(med_days)) if np.isfinite(med_days).any() else None
p10_days    = float(np.nanpercentile(med_days, 10)) if np.isfinite(med_days).any() else None
p90_days    = float(np.nanpercentile(med_days, 90)) if np.isfinite(med_days).any() else None
```

If a large fraction of draws never reach 50% within the grid, report
`median_days_to_event: null` and explain in `summary.md` (the system has a
meaningful chance of not resolving in the modelled window — consider
`CureRateModel` as a complementary view).

## Convergence diagnostics

```python
summary_df      = summary(idata)
rhat_max        = float(summary_df["r_hat"].max())
ess_bulk_min    = float(summary_df["ess_bulk"].min())
divergences     = int(idata.sample_stats["diverging"].sum())
total_draws     = int(idata.sample_stats.sizes["chain"] * idata.sample_stats.sizes["draw"])
divergence_rate = divergences / total_draws
```

## Calibration checks

**PriorSensitivity** — derived `p_event_by_horizon` via psense per
[`prior_sensitivity_psense.md`](prior_sensitivity_psense.md). Few transitions →
prior-dominated rates are common; WARN/FAIL at T_mid requires disclosure, not rejection.
See [`model_checks.md`](model_checks.md).

**ConsistencyCheck** — verify:
1. Each row of every sampled `Q` sums to ~0 (`np.allclose(Q.sum(axis=1), 0)`).
2. The absorbing row is all zeros.
3. P(event by t) is monotonically non-decreasing across horizons — this holds
   automatically for an absorbing CTMC; verify numerically as a guard against bugs.
4. All probabilities in [0, 1].

**ReferenceClassCongruence** — compare P(event by T_mid) to a `ReferenceClassModel`
base rate. A ratio outside [0.4, 2.5] warrants explicit justification (e.g. the
current start state is unusually close to / far from resolution).

## Gotchas

- **Few transitions → prior-dominated rates.** With only a handful of observed
  `i → j` moves, each rate posterior tracks its prior. Flag PriorSensitivity
  prominently in `summary.md` with justification; widen priors to reflect ignorance.
- **Memorylessness assumption.** A CTMC assumes exponential dwell times (constant
  hazard within a state). If the data shows that, e.g., a crisis becomes *more*
  likely to resolve the longer it persists, the exponential dwell is wrong — see
  the semi-Markov variant below.
- **Absorbing-state definition.** Be explicit about what "resolved" means and
  ensure no outgoing rates are placed on the absorbing row. A non-zero absorbing
  row silently breaks monotonicity.
- **State aggregation sensitivity.** Collapsing or splitting states changes the
  forecast. Document the state set and, if borderline, run the model under an
  alternative aggregation as a sensitivity check.
- **`expm` numerical stability / cost.** For very large `t · rate`, `scipy.linalg.expm`
  is still stable but slow if called per-draw per-horizon. Thin the posterior (see
  code) and reuse `expm(Q * t)` across the median-days grid where possible.
- **Start-state uncertainty.** If you are unsure which state the system is in today,
  forecast from each plausible start state and report the range, or put a prior
  over the start state and average.

## Variant: semi-Markov / phase-type dwell times

When dwell times are clearly non-exponential (e.g. a regime that almost never
resolves in the first month but frequently does after), replace the
`pm.Exponential` dwell likelihood with a `pm.Weibull` or `pm.Gamma` per state
(a semi-Markov model). The branch-choice likelihood is unchanged. Note that the
clean `expm(Q · t)` forecast no longer applies — you must forward-simulate sojourns
Monte-Carlo style (draw a dwell, draw a destination, repeat until absorbed or the
horizon is reached) and take the empirical CDF of absorption times. Document this
as a more flexible but heavier alternative.
