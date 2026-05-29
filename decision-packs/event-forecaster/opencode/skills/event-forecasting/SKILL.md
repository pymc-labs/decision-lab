---
name: event-forecasting
description: Methodology for probabilistic forecasting of when and whether a future event will occur. Covers Bayesian survival models, reference class reasoning, driver threshold models, leading indicator models, scenario decomposition, and causal mechanism models. Use for any question of the form "When will X happen?" or "What is the probability that Y occurs by date Z?"
---

# Event Forecasting Analysis Skill

This skill provides methodology for estimating **probability distributions over when (and whether) future events will occur**. It is designed for open-ended, real-world questions where the answer is uncertain, data may be sparse, and domain knowledge matters as much as statistics.

The skill is agnostic to domain. It applies equally to geopolitical events, regulatory decisions, market regime changes, clinical endpoints, supply chain resolutions, and any other time-to-event question.

## When to use which reference

| Task | Read first |
|---|---|
| Deciding which methods to run | `references/method_selection.md` |
| Historical durations of analogous events available | `references/hazard_model.md` |
| Base rate from historical analogues + Bayesian updating | `references/reference_class.md` |
| Leading indicator regression (relevant time series available) | `references/indicator_model.md` |
| Explicit scenario tree (discrete resolution paths identifiable) | `references/scenario_decomposition.md` |
| Structural model of causal drivers | `references/causal_mechanism.md` |
| Continuous driver time-series + threshold crossing | `references/continuous_driver_model.md` |
| Event may never resolve (permanent non-resolution possible) | `references/cure_rate_model.md` |
| Event triggered by a driver crossing a latent estimated threshold | `references/threshold_crossing.md` |
| Validating and calibrating any forecast | `references/calibration_checks.md` |

## Eight methods in this skill

| Method | Data requirement | Appropriate when |
|---|---|---|
| `HazardModel` | Historical durations of analogous events | N ≥ 5 past events with known resolution times |
| `ReferenceClassModel` | Historical analogues (even rough ones) | Always useful as a baseline; tolerates sparse data |
| `IndicatorModel` | Time-series of relevant signals | Leading indicators are measurable and updated regularly |
| `ScenarioDecomposition` | Domain knowledge + expert judgment | Question has identifiable discrete paths to resolution |
| `CausalMechanismModel` | Structural knowledge of causal drivers | Key causal factors and direction of influence are known |
| `ContinuousDriverModel` | Continuous driver time-series (≥ 100 obs) + computable threshold | Event operationalised as driver crossing a threshold derived from data or domain knowledge |
| `ThresholdCrossingModel` | Driver time-series + ≥ 1 historical case with known driver level | Event triggered when driver exceeds a **latent estimated** threshold; works with N=1 |
| `CureRateModel` | Any (works without data) | Significant probability exists that the event will NEVER resolve; standard survival models assign zero probability to permanent non-resolution |

**Each forecaster selects ONE method** that best fits the data and research findings. Choose the method that is most appropriate for the available evidence — you do not need to run multiple methods. The ensemble of parallel forecasters provides coverage across methods.

### Backend preference

| Method | Interface | Reason |
|---|---|---|
| `ContinuousDriverModel` | Raw PyMC | OU/RWD/SV/LL/LLT structures; Bambi cannot express them directly — see `references/continuous_driver_model.md` |
| `HazardModel` | Bambi | `censored()` formula handles right-censoring cleanly |
| `IndicatorModel` | Bambi | Formula syntax, auto-priors, `predict()` for probability |
| `ReferenceClassModel` | Raw PyMC | Custom Beta-Beta hierarchy, not a regression |
| `ScenarioDecomposition` | Raw PyMC | Dirichlet + Beta structure, not a regression |
| `CausalMechanismModel` | Raw PyMC | Custom structural model |
| `ThresholdCrossingModel` | Raw PyMC | OU process + Monte Carlo simulation |

### Special case: N=1 historical event

When only **one historical case** of the event exists, `HazardModel` is not viable and `HistoricalCalibration` must be skipped. Adjust method selection:

- **Mandatory**: `ReferenceClassModel` with a broadened reference class (analogous event types, not the exact event). See `references/reference_class.md` for the broadening ladder.
- **If a dominant causal driver is measurable**: `ThresholdCrossingModel` — explicitly designed for the single-case situation.
- **If resolution paths are identifiable**: `ScenarioDecomposition`.
- **Do NOT run `HazardModel`** — report "not applicable: N=1, insufficient data".
- `PriorSensitivity` becomes especially important; flag WARN or FAIL prominently.

## Core output contract

Every method must produce `forecast.json`. Full schema in `references/method_selection.md`. Mandatory fields:

- `p_event_by_horizon` — P(event by date) for each horizon specified in the prompt
- `median_days_to_event` with `p10_days` / `p90_days`
- `convergence_status` (for Bayesian: `OK` / `MARGINAL` / `FAIL`; analytic: `N_A`)

## Principles that override method choice

1. **Never fabricate numbers.** If a value is `NaN`, report `NaN` and explain why. Never substitute 0 or a guess.
2. **Always report intervals.** Point estimates alone are forbidden. Use 94% HDI for Bayesian; 5th/95th percentile bootstraps for analytic.
3. **Graceful degradation.** Sparse data → wider priors and broader reference classes. Never refuse to forecast because data is thin; report wider intervals.
4. **Calibration over precision.** A well-calibrated wide interval is always better than an overconfident narrow one.
5. **Causal awareness.** Prefer methods that explain *why* the event occurs over purely statistical approaches when causal structure is identifiable. Historical patterns can fail when the causal structure changes.
6. **Reference class discipline.** When selecting a reference class, use the narrowest class with N ≥ 5 historical cases. Document why you chose it.
7. **No domain-specific defaults.** Do not import threshold values, percentile choices, scenario structures, or reference class compositions from other forecasting tasks. Every number must be derived from the current question and data.
