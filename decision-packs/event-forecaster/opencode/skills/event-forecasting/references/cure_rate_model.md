# CureRateModel — Long-Term Survivor / Zero-Inflated Survival

Model the possibility that the event **never resolves** in the foreseeable future.
Standard survival models implicitly assume every event eventually occurs (S(∞) = 0),
but many real-world events have a non-negligible probability of permanent
non-resolution — geopolitical stalemates, unresolved regulatory disputes,
technology lock-ins, or chronic conditions.

The cure rate model separates the population into:
- **Non-cured** fraction (1 − π): will eventually experience the event; follow a
  survival distribution
- **Cured** fraction (π): will never experience the event within any finite horizon

## When to use

- There is genuine expert belief or historical evidence that some fraction of
  analogous events never resolved (e.g., some territorial disputes persist for
  decades with no resolution)
- Standard survival models give unreasonably high probabilities at very long
  horizons (e.g., P(event by 10 years) > 95% when experts believe 20–30% never
  resolve)
- The question includes an explicit "or never" framing
- You have historical data where some censored observations are very long and likely
  permanent non-resolutions, not just administrative right-censoring

## When NOT to use

- All historical analogues eventually resolved (π = 0 is appropriate)
- The event is physically or logically certain to occur eventually (e.g., a
  biological process that cannot be permanently prevented)
- You have fewer than 5 historical analogues — the cure fraction π is very
  hard to estimate from small samples

## Conceptual structure

```
P(event by T) = (1 − π) × [1 − S_uncured(T)]
                └─────────────────────────────┘
                 Only the non-cured fraction contributes
                 to event probability at any finite T

As T → ∞:  P(event) → (1 − π)   [not 1!]
```

## PyMC implementation

```python
import pymc as pm
import numpy as np
import xarray as xr

# --- inputs ---
# durations: array of event durations (or current elapsed time for censored)
# censored: boolean array, True = still ongoing
# N_never: estimated number of "permanent" non-resolutions in your reference class
# N_total: total reference class size (including N_never)

durations = np.array([...])
censored  = np.array([...], dtype=bool)

observed_dur = durations[~censored]
censored_dur = durations[censored]

with pm.Model() as cure_model:
    # Cure fraction: P(event never occurs)
    # If you have historical evidence (N_never out of N_total appear permanent):
    # pi = pm.Beta("pi", alpha=N_never + 1, beta=(N_total - N_never) + 1)
    # If eliciting from domain knowledge:
    pi = pm.Beta("pi", alpha=2, beta=8)   # prior: ~20% cure rate, adjust to domain

    # Survival distribution for the non-cured fraction (Weibull)
    alpha = pm.Gamma("alpha", mu=1.5, sigma=0.75)
    beta  = pm.Gamma("beta", mu=np.mean(durations), sigma=np.std(durations) + 1)

    # Likelihood for OBSERVED events (definitely not cured)
    pm.Weibull("resolved", alpha=alpha, beta=beta, observed=observed_dur)

    # Likelihood for CENSORED observations:
    # P(censored at t) = π + (1-π) × S_uncured(t)
    # = probability of being cured + probability of being uncured but not yet resolved
    weibull_surv = pm.math.exp(-(censored_dur / beta) ** alpha)
    p_censored = pi + (1 - pi) * weibull_surv
    pm.Potential("censored_lik", pm.math.log(p_censored + 1e-9).sum())

    idata = pm.sample(
        draws=500,
        tune=500,
        chains=6,
        backend="numba",
        nuts_sampler="nutpie",
        nuts={"target_accept": 0.92},
    )
    pm.stats.compute_log_likelihood(idata, model=cure_model)
    pm.stats.compute_log_prior(idata, model=cure_model)
```

## Extracting the forecast

```python
pi_samples    = idata.posterior["pi"].values.flatten()        # cure fraction
alpha_samples = idata.posterior["alpha"].values.flatten()
beta_samples  = idata.posterior["beta"].values.flatten()

horizon_days = [90, 180, 365, 730]   # from orchestrator horizons

p_event_by_horizon = []
ci_low_by_horizon  = []
ci_high_by_horizon = []

for t in horizon_days:
    # P(event by t) = (1 - pi) * (1 - S_uncured(t))
    weibull_cdf_t = 1 - np.exp(-(t / beta_samples) ** alpha_samples)
    p_h = (1 - pi_samples) * weibull_cdf_t
    p_event_by_horizon.append(float(np.mean(p_h)))
    ci_low_by_horizon.append(float(np.percentile(p_h, 3)))
    ci_high_by_horizon.append(float(np.percentile(p_h, 97)))

# Long-run probability (as T → ∞): P(event ever) = 1 - pi
p_ever = float(np.mean(1 - pi_samples))
p_ever_ci = [float(np.percentile(1 - pi_samples, 3)),
             float(np.percentile(1 - pi_samples, 97))]

print(f"P(event ever resolves) = {p_ever:.2%} [{p_ever_ci[0]:.2%}, {p_ever_ci[1]:.2%}]")

# Median days among those who do resolve
# median = beta * (-ln(0.5))^(1/alpha), but only for the non-cured fraction
t_med_samples = beta_samples * (np.log(2) ** (1.0 / alpha_samples))
median_days = float(np.mean(t_med_samples))

# Derived quantities for PriorSensitivity (psense)
t = xr.DataArray(horizon_days, dims="horizon", coords={"horizon": horizon_days})
weibull_cdf = 1.0 - np.exp(-((t / idata.posterior["beta"]) ** idata.posterior["alpha"]))
p_by_h = (1 - idata.posterior["pi"]) * weibull_cdf
p_by_h = p_by_h.transpose("chain", "draw", "horizon")
idata.posterior["p_event_by_horizon"] = p_by_h
```

## `forecast.json` additions

Include two extra fields beyond the standard schema:
```json
{
  ...standard fields...,
  "cure_fraction": <float>,          // P(event never resolves) = posterior mean of pi
  "cure_fraction_ci": [<low>, <high>], // 94% HDI
  "p_event_ever": <float>            // 1 - cure_fraction
}
```

## Model checks

**PriorSensitivity** — derived `p_event_by_horizon` (and P(event ever) if reported)
via psense per [`prior_sensitivity_psense.md`](prior_sensitivity_psense.md). π is
often prior-driven with small N; WARN/FAIL requires disclosure, not rejection.

**ConsistencyCheck** — verify that P(event by T) is monotonically non-decreasing
AND that P(event by T) converges to P(event ever) = 1 − mean(π) as T grows large.

**ReferenceClassCongruence** — compare P(event ever) to the fraction of resolved
events in the broad reference class. If the model assigns 30% permanent
non-resolution but 90% of historical analogues resolved, document the justification.

## Gotchas

- **Identifiability with small N**: With fewer than 10 events, π is very hard to
  separate from the survival distribution. The cure fraction will track the prior
  closely. Report PriorSensitivity WARN/FAIL prominently with justification.
- **Long censoring times ≠ cure**: A censored observation that is "very long" is
  not necessarily cured — it may just have a slow resolution. Be careful not to
  classify long censored cases as permanent non-resolutions without domain evidence.
- **Asymptote interpretation**: The ceiling P(event ever) = 1 − π is often the
  most policy-relevant output. Present it prominently alongside the horizon
  probabilities.
- **Cure rate ≠ zero-inflated count**: This model is for time-to-event data, not
  count outcomes. Do not confuse with zero-inflated Poisson or negative binomial.
