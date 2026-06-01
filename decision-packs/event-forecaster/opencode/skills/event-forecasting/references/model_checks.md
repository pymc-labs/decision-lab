# Model Checks

Five checks for validating and stress-testing forecasts. Run the checks specified by the orchestrator. Always run `PriorSensitivity` and `ConsistencyCheck` on every method. See each method's reference file for the specific checks recommended for that method.

---

## Check 1: PriorSensitivity

**Always run.** Tests how much the **forecast** depends on the prior and likelihood under systematic perturbation.

### Prior sensitivity is not inherently bad

This check measures **dependence and stability**, not model validity.

| What it measures | What it does **not** mean |
|------------------|---------------------------|
| The forecast moves when priors/likelihood are perturbed | The model is wrong and must be refit |
| `prior-data conflict` (ArviZ psense) | You must weaken the prior until the warning disappears |
| `WARN` / `FAIL` on Δ P(event) at T_mid | The forecast is incorrect — it means **material prior dependence** under the perturbation, which must be **disclosed** |

**Expected and acceptable** when: priors were intentionally informative (elicitation), N is small and the likelihood is weak, long horizons are prior/tail-dominated while short horizons are data-dominated, or structural quantities (threshold τ) were set by domain judgment.

Parallel reviewers use FAIL/WARN as **review urgency** ([forecaster.yaml](../../parallel_agents/forecaster.yaml)), not as grounds to discard a method without written justification — same spirit as ReferenceClassCongruence FAIL below.

---

### Sensitivity tiers

Full implementation: [`prior_sensitivity_psense.md`](prior_sensitivity_psense.md).

| Tier | Methods | `method` in JSON |
|------|---------|------------------|
| **A** — standard psense | HazardModel, CausalMechanismModel, IndicatorModel, CureRateModel, MarkovStateModel, ReferenceClassModel | `psense` |
| **B** — resampled re-simulation | ContinuousDriverModel, JumpDiffusionModel, ThresholdCrossingModel | `resampled_simulation` |
| **C** — analytic perturbation | ScenarioDecomposition | `analytic_perturbation` |

**Default scope:** cumulative **P(event by T)** at **each** `horizon_dates` entry (same definition as `forecast.json` `p_event_by_horizon`). Do **not** run psense on every latent, spline, or GP coefficient unless the user asks for causal interpretation (see below).

**Tier A workflow (deterministic derived quantity):**

1. Sample with Nutpie (`backend="numba"`, `draws=500`, `tune=500`, `chains=6`); then `pm.stats.compute_log_likelihood` and `pm.stats.compute_log_prior`.
2. Per MCMC draw, compute **deterministic** `p_event_by_horizon` for all horizons; add to `idata.posterior`.
3. `arviz_stats.psense_summary` on all horizon derived variables; optional `arviz_plots.plot_psense_quantities`.
4. Set top-level `status` from **T_mid** using pp movement at α=0.8 vs 1.25.

**Tier B workflow (path-simulation forecast):**

1. Sample and compute log densities as above.
2. Build baseline forecast with forward simulation (`n_paths=100` acceptable).
3. **Do not** attach MC-noisy `p_event_by_horizon` to `idata.posterior` for psense.
4. Resample posterior draws at power-scaled α ∈ {0.8, 1.25}; re-run forward simulation with `n_paths ≥ 500`.
5. Compare weighted mean P(event by T_mid) across α levels for tier classification.

**Tier C workflow:** perturb Dirichlet/Beta concentration ±50%; compare P(event) at each horizon.

Use per-horizon results in `note` / `by_horizon` for narratives such as: *short-horizon forecast data-dominated; 12-month forecast prior-sensitive*.

**Unless the user asks for causal interpretation** (mechanism, driver importance, coefficient stability, “why” not just “when”): keep PriorSensitivity **prediction-only**. Method name alone does not trigger parameter-level psense — e.g. `CausalMechanismModel` with a headline-probability-only brief uses prediction-only; `HazardModel` with “which factors drive timing?” adds psense on **named interpretable** parameters listed in the question. See [`causal_mechanism.md`](causal_mechanism.md).

**Hierarchical models:** power-scale **top-level** hyperpriors only when doing parameter-level psense (EABM §6.4).

### Classification (orchestrator tier — T_mid)

Based on absolute change in P(event by **T_mid**) under power-scaling (pp movement at α=0.8 vs 1.0 vs 1.25 on the derived forecast, or equivalent psense quantity perturbation):

| Status | Criterion |
|--------|-----------|
| `PASS` | Absolute change in P(event by T_mid) < 10 percentage points |
| `WARN` | Change is 10–20 pp |
| `FAIL` | Change > 20 pp |

On WARN/FAIL: explain in `summary.md` **why** sensitivity is plausible (small N, informative prior, long horizon, elicited τ). Do not treat FAIL as a veto.

Per-horizon `status` in `by_horizon` may use the same pp thresholds independently for reporting; top-level `status` remains T_mid unless the orchestrator designates another horizon.

### Supplementary / fallback paths

| Situation | Approach |
|-----------|----------|
| Path-simulation forecast (Tier B) | Resampled re-simulation at power-scaled α; `method: resampled_simulation` |
| Analytic / prior-only (`ScenarioDecomposition`, Tier C) | Dirichlet concentration ±50%; `method: analytic_perturbation` |
| ReferenceClassModel (Tier A) | Standard psense on deterministic Beta-Binomial derived quantity, or analytic κ ±50% |
| Elicited threshold τ not in posterior | Perturb τ ±10–20% and re-simulate paths (no MCMC refit); report separately in `note` as `structural_perturbation` |
| `log_prior` cannot be stored | Manual prior weakening + single refit, or document skip |

Avoid the legacy “pick 2–3 priors and refit” loop for PyMC when Tier A psense or Tier B resampled re-simulation is feasible.

### Output: `outputs/check_prior_sensitivity.json`

```json
{
  "check": "PriorSensitivity",
  "status": "PASS | WARN | FAIL",
  "method": "psense | resampled_simulation | refit | analytic_perturbation | structural_tau",
  "t_mid_horizon": "<YYYY-MM-DD>",
  "original_p_mid_horizon": <float>,
  "absolute_change_pp": <float>,
  "note": "<interpretation: e.g. short horizons data-dominated; long horizon prior-sensitive; prior-data conflict at 12mo>",
  "by_horizon": [
    {
      "horizon_date": "<YYYY-MM-DD>",
      "p_event": <float>,
      "absolute_change_pp": <float>,
      "prior_cjs": <float or null>,
      "likelihood_cjs": <float or null>,
      "psense_diagnosis": "<✓ | prior-data conflict | strong prior / weak likelihood | null>",
      "status": "PASS | WARN | FAIL"
    }
  ]
}
```

`by_horizon` is **required** for PyMC methods using psense; optional for analytic fallbacks. Fields `perturbed_p_mid_horizon` and `prior_changed` from the old schema may be omitted when using psense; use `note` for perturbation type.

---

## Check 2: ConsistencyCheck

**Always run.** Tests internal logical consistency of the forecast.

### Rules to check

| Rule | What to verify |
|------|----------------|
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
|--------|-----------|
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
|--------|-----------|
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
|--------|-----------|
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
