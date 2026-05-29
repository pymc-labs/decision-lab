# Method Selection Guide

## Decision tree

Answer these questions in order to select your methods.

### 1. What kind of question is this?

| Question form | Implication |
|---|---|
| "When will X happen?" | Time-to-event. Fit a survival curve. |
| "Will X happen by date Y?" | P(event in window). All methods can answer this. |
| "How likely is X in the next N months?" | Probability over a horizon. All methods can answer this. |
| "What factors control when X happens?" | Causal structure matters. Prioritise `CausalMechanismModel`. |

### 2. How many historical cases of this exact event exist?

Answer this before selecting methods — it determines whether `HazardModel` is viable and how wide the reference class must be.

| Historical cases (N) | Implication |
|---|---|
| N = 0 | No historical case. `HazardModel` impossible. Must use broader analogues for `ReferenceClassModel`. |
| N = 1 | One case. `HazardModel` not viable. Use as threshold / calibration anchor for `ThresholdCrossingModel`. Force-broaden reference class. |
| N = 2–4 | Too few for reliable survival analysis. `HazardModel` is very prior-dominated; only run with explicit caveat. |
| N ≥ 5 | `HazardModel` is viable as a primary method. |

### 3. What data is available?

Inspect every available data file, then answer:

| Data available | Methods unlocked |
|---|---|
| Historical durations of N ≥ 5 analogous events | `HazardModel` (primary) |
| Historical analogues even if durations are rough | `ReferenceClassModel` (always) |
| Time-series of a measurable continuous driver + ≥ 1 historical case | `ContinuousDriverModel`, `ThresholdCrossingModel` |
| Continuous driver with discrete shocks / fat-tailed increments (≥ ~100 obs) + threshold | `JumpDiffusionModel` |
| Time-series of relevant leading indicators (updated regularly) | `IndicatorModel` |
| Historical transitions / dwell times across discrete regimes (calm → crisis → resolved) | `MarkovStateModel` |
| Domain knowledge of decision-makers or resolution mechanisms | `ScenarioDecomposition`, `CausalMechanismModel` |
| Little data, open-ended question | `ReferenceClassModel` + `ScenarioDecomposition` |

### 4. Select your method

Choose the ONE method that best fits your data structure and research findings.

Use the decision tree above (questions 1–3) to identify which methods are feasible,
then select the most appropriate single method:

- Best data fit: the method whose data requirements most closely match what you have
- Best question fit: the method whose structure best matches how the event resolves
- Most defensible: the method you can implement correctly and whose assumptions you
  can justify with your evidence

If multiple methods seem equally appropriate, prefer the one with the richest
implementation guidance in its reference file (more PyMC code examples = fewer
unknowns).

You may also choose a method not listed in the skill if your research or data
suggests something better — document your reasoning in summary.md.

---

## `forecast.json` schema

Every forecasting method must write `forecast.json` with this exact structure:

```json
{
  "method": "<ClassName>",
  "question": "<verbatim question from orchestrator>",
  "model_backend": "Bayesian | Analytic | Hybrid",
  "forecast_as_of": "<YYYY-MM-DD>",
  "horizon_dates": ["<YYYY-MM-DD>", "..."],
  "p_event_by_horizon": [<float>, "..."],
  "ci_low_by_horizon":  [<float>, "..."],
  "ci_high_by_horizon": [<float>, "..."],
  "ci_level": 0.94,
  "median_days_to_event": <float or null>,
  "p10_days": <float or null>,
  "p90_days": <float or null>,
  "convergence_status": "OK | MARGINAL | FAIL | N_A",
  "rhat_max": <float or null>,
  "ess_bulk_min": <float or null>,
  "divergence_rate": <float or null>,
  "key_assumptions": ["<string>", "..."],
  "key_uncertainties": ["<string>", "..."]
}
```

Rules:
- `horizon_dates` must match exactly the dates specified in the prompt.
- `p_event_by_horizon[i]` is strictly non-decreasing with i (probabilities cannot go down as horizon extends — document any exception).
- Null is allowed for fields the method does not produce; `NaN` is never allowed.
- `ci_level` must always be stated — default 0.94 (94% HDI for Bayesian; approximate 94% CI for analytic).

---

## Convergence classification (Bayesian methods)

| Status | Criteria |
|---|---|
| `OK` | All R-hat < 1.01 AND ESS bulk > 400 AND divergence rate < 0.5% |
| `MARGINAL` | All R-hat < 1.05 AND ESS bulk > 100 AND divergence rate < 2% |
| `FAIL` | Anything worse |

With short chains (draws=200, chains=2): relax to R-hat < 1.05, ESS > 50. Flag in summary.md.

On `FAIL`, write the failure to `summary.md` and stop. Do NOT silently retry with different sampler parameters. The orchestrator decides Round 2.

---

## Agreement criteria (used in evaluation)

Two methods **agree on direction** if both P(event by T_mid) estimates are on the same side of 0.50.

Two methods **agree on magnitude** if their P(event by T_mid) estimates are within 15 percentage points of each other.

Disagreement beyond these thresholds must be surfaced and explained — not averaged away.
