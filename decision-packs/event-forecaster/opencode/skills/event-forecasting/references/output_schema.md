# Output Schema and Convergence Thresholds

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
