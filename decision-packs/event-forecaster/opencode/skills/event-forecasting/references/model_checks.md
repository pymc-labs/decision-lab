# Model Checks

Five checks for validating and stress-testing forecasts. Run the checks specified by the orchestrator. Always run `PriorSensitivity` and `ConsistencyCheck` on every method. See each method's reference file for the specific checks recommended for that method.

---

## Check 1: PriorSensitivity

**Always run.** Tests whether the posterior changes materially when priors are weakened or shifted.

### Protocol

1. Identify the 2–3 most influential priors in your model (the ones with the tightest effect on the posterior).
2. Refit with each prior halved in concentration / doubled in sigma. Do NOT change the data.
3. Compare P(event by T_mid) between the original and perturbed fits.

### Classification

| Status | Criterion |
|---|---|
| `PASS` | Absolute change in P(event by T_mid) < 10 percentage points |
| `WARN` | Change is 10–20 pp |
| `FAIL` | Change > 20 pp |

### Output: `outputs/check_prior_sensitivity.json`

```json
{
  "check": "PriorSensitivity",
  "status": "PASS | WARN | FAIL",
  "original_p_mid_horizon": <float>,
  "perturbed_p_mid_horizon": <float>,
  "absolute_change_pp": <float>,
  "prior_changed": "<description of which prior was perturbed>",
  "note": "<one-line interpretation>"
}
```

---

## Check 2: ConsistencyCheck

**Always run.** Tests internal logical consistency of the forecast.

### Rules to check

| Rule | What to verify |
|---|---|
| Monotonicity | P(event by T1) ≤ P(event by T2) for T1 < T2 |
| MECE (scenario decomposition) | Scenario probabilities sum to 1.0 ± 0.02 |
| Plausibility | P10 days < median days < P90 days |
| No impossible values | All probabilities in [0, 1]; no NaN or inf |
| Reference class congruence | See Check 4 |

### Output: `outputs/check_consistency.json`

```json
{
  "check": "ConsistencyCheck",
  "status": "PASS | FAIL",
  "rules_checked": [
    {"rule": "Monotonicity", "pass": true},
    {"rule": "MECE", "pass": true, "sum": 0.99},
    {"rule": "Plausibility", "pass": true},
    {"rule": "NoImpossibleValues", "pass": true}
  ],
  "failures": ["<list any failed rules>"]
}
```

---

## Check 3: HistoricalCalibration

Tests whether this method, applied to analogous past events, would have produced well-calibrated forecasts. Requires N ≥ 3 historical episodes with known outcomes.

### Protocol

1. Collect 3–10 historical analogous events with known resolution dates.
2. For each, simulate what the model would have forecast at a comparable point in time (use the same data features available at that time).
3. Compute Brier score: `BS = mean((p_forecast - outcome)^2)`. Range 0–1; lower is better.
4. Compare to a naive baseline (always predicting the base rate p_base).

```python
# Brier score
outcomes = np.array([1, 0, 1, 1, 0, ...])    # 1 = event resolved in W days, 0 = not
p_forecasts = np.array([0.72, 0.30, 0.65, ...])

brier_score   = float(np.mean((p_forecasts - outcomes) ** 2))
brier_baseline = float(np.mean((np.full_like(outcomes, np.mean(outcomes)) - outcomes) ** 2))
brier_skill    = 1 - brier_score / brier_baseline  # >0 is better than naive
```

### Classification

| Status | Criterion |
|---|---|
| `PASS` | Brier skill score > 0.05 (beats naive baseline) |
| `WARN` | Brier skill score 0 to 0.05 (at par with naive) |
| `FAIL` | Brier skill score < 0 (worse than always predicting the base rate) |

If N < 3 historical episodes: skip this check and note "insufficient historical episodes for calibration".

### Output: `outputs/check_historical_calibration.json`

```json
{
  "check": "HistoricalCalibration",
  "status": "PASS | WARN | FAIL | SKIPPED",
  "n_episodes": <int>,
  "brier_score": <float or null>,
  "brier_baseline": <float or null>,
  "brier_skill": <float or null>,
  "note": "<one-line interpretation or reason for skip>"
}
```

---

## Check 4: ReferenceClassCongruence

Tests whether the method's aggregate P(event) is consistent with the naive reference-class base rate. Catches over-confident or implausibly optimistic/pessimistic forecasts.

### Protocol

1. Compute the naive base rate from `ReferenceClassModel` (or from the data explorer summary).
2. Compute the ratio: `ratio = P_method(event by T_mid) / P_base_rate(event by T_mid)`.
3. Check whether the ratio is within [0.4, 2.5] (i.e., within ~2× of the base rate).

### Classification

| Status | Criterion |
|---|---|
| `PASS` | 0.4 ≤ ratio ≤ 2.5 |
| `WARN` | 0.25 < ratio < 0.4 or 2.5 < ratio ≤ 4 |
| `FAIL` | ratio ≤ 0.25 or ratio > 4 |

A `FAIL` means the method is producing a forecast that is very far from the base rate. **This is not automatically wrong** — if the current situation is genuinely unusual compared to the reference class, a large divergence is justified. But you must explain it explicitly.

### Output: `outputs/check_reference_class_congruence.json`

```json
{
  "check": "ReferenceClassCongruence",
  "status": "PASS | WARN | FAIL",
  "p_method": <float>,
  "p_base_rate": <float>,
  "ratio": <float>,
  "t_mid_horizon": "<YYYY-MM-DD>",
  "note": "<explanation if ratio is far from 1.0>"
}
```

---

## Check 5: ExpertBenchmark (optional)

Compare the forecast to publicly available prediction market prices or expert consensus (Metaculus, Polymarket, Manifold Markets, etc.).

### Protocol

1. Look up current market-implied probability for the event on a relevant prediction platform. Note the source, access date, and contract definition.
2. Compute the absolute difference: `|P_method - P_market|`.

### Classification

| Status | Criterion |
|---|---|
| `PASS` | Difference < 15 pp |
| `WARN` | Difference 15–30 pp |
| `FAIL` | Difference > 30 pp (or market definition is incompatible with our question) |

A large divergence from markets is not automatically wrong, but it is a strong signal to re-examine assumptions.

### Output: `outputs/check_expert_benchmark.json`

```json
{
  "check": "ExpertBenchmark",
  "status": "PASS | WARN | FAIL | SKIPPED",
  "p_method": <float>,
  "p_market": <float or null>,
  "market_source": "<platform + contract name + URL>",
  "market_access_date": "<YYYY-MM-DD>",
  "difference_pp": <float or null>,
  "note": "<any important caveats on comparability>"
}
```
