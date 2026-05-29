# ScenarioDecomposition — Explicit Scenario Tree

Decompose the question into a set of mutually exclusive, collectively exhaustive (MECE) scenarios. For each scenario, elicit P(scenario) and P(event | scenario, horizon). Aggregate using the law of total probability.

## When to use

- The question has **identifiable discrete paths** to resolution.
- Domain knowledge is strong enough to estimate conditional probabilities with some confidence.
- Quantitative time-series data is absent or too sparse for statistical methods alone.
- You want a transparent, auditable forecast that can be updated as scenarios evolve.

## Conceptual steps

1. **Enumerate scenarios**: List the 3–6 mutually exclusive paths through which the event could (or couldn't) resolve.
2. **Elicit probabilities**: For each scenario, estimate P(scenario) and P(event resolves by W | scenario).
3. **Check MECE**: Probabilities must sum to 1.0 (allow small tolerance). Each scenario must be clearly distinct.
4. **Aggregate**: P(event in W) = Σ P(scenario_i) × P(event in W | scenario_i).
5. **Quantify uncertainty**: Use Dirichlet priors over scenario probabilities and Beta priors over conditional probabilities.

## PyMC implementation

```python
import pymc as pm
import numpy as np
import arviz as az

# --- Define your scenarios (fill from domain analysis) ---
# Replace these with scenarios appropriate to your specific question.
# Examples are shown as placeholders — do not copy them without domain justification.

scenario_names = [
    "fast_resolution",        # e.g. diplomatic deal, court ruling, sudden shock
    "gradual_resolution",     # e.g. negotiated settlement, economic pressure
    "partial_resolution",     # e.g. incremental progress, interim measures
    "prolonged_stalemate",    # e.g. deadlock, ongoing conflict, regulatory delay
]
n_scenarios = len(scenario_names)

# Dirichlet concentration (prior belief strength per scenario)
# Values proportional to your prior belief. Higher total = more confident.
# Example: [3, 3, 2, 2] gives roughly equal weight with moderate confidence.
# Adjust to your domain knowledge.
concentration = np.array([3.0, 3.0, 2.0, 2.0])

# P(event resolves within W days | scenario) — prior means
# Shape: (n_scenarios, n_horizons)
# These MUST be derived from your domain knowledge of each path, not copied.
horizons_days = [90, 180, 365]   # replace with actual horizon dates

cond_p_mu = np.array([
    # 90d    180d   365d
    [0.0,   0.0,   0.0],   # FILL IN — fast_resolution conditional probs
    [0.0,   0.0,   0.0],   # FILL IN — gradual_resolution
    [0.0,   0.0,   0.0],   # FILL IN — partial_resolution
    [0.0,   0.0,   0.0],   # FILL IN — prolonged_stalemate
])
# IMPORTANT: Do NOT copy values from examples. Derive from your domain analysis.

cond_p_kappa = 5.0   # concentration for Beta priors (higher = tighter around mean)

with pm.Model() as scenario_model:
    # Uncertainty over scenario probabilities
    scenario_probs = pm.Dirichlet("scenario_probs",
                                   a=concentration,
                                   shape=n_scenarios)

    # Conditional probabilities (uncertain)
    alpha_params = cond_p_mu * cond_p_kappa
    beta_params  = (1 - cond_p_mu) * cond_p_kappa

    cond_probs = pm.Beta("cond_probs",
                          alpha=alpha_params,
                          beta=beta_params,
                          shape=(n_scenarios, len(horizons_days)))

    # Aggregate: P(event in W) = sum over scenarios
    p_event = pm.Deterministic("p_event",
        pm.math.dot(scenario_probs, cond_probs))

    idata = pm.sample(
        draws=200, tune=200, chains=2,
        target_accept=0.9,
        nuts_sampler="numpyro",
        # do NOT pass random_seed
    )
```

## Extracting the forecast

```python
p_event_samples = idata.posterior["p_event"].values   # (chains, draws, n_horizons)
p_event_flat    = p_event_samples.reshape(-1, len(horizons_days))

p_event_by_horizon = [float(np.mean(p_event_flat[:, i])) for i in range(len(horizons_days))]
ci_low_by_horizon  = [float(np.percentile(p_event_flat[:, i], 3))  for i in range(len(horizons_days))]
ci_high_by_horizon = [float(np.percentile(p_event_flat[:, i], 97)) for i in range(len(horizons_days))]

# Infer median days assuming exponential: lambda = -log(1 - P_longest_horizon) / longest_horizon
lambda_samples = -np.log(1 - p_event_flat[:, -1] + 1e-9) / horizons_days[-1]
median_days    = float(np.mean(np.log(2) / lambda_samples))
p10_days       = float(np.percentile(np.log(2) / lambda_samples, 10))
p90_days       = float(np.percentile(np.log(2) / lambda_samples, 90))
```

## Writing the scenario narrative

In `summary.md`, include a table showing your scenario decomposition:

```markdown
| Scenario | P(scenario) prior | P(event in 180d | scenario) | Contribution |
|---|---|---|---|
| [Scenario A description] | <prob> | <cond_prob> | <product> |
| [Scenario B description] | <prob> | <cond_prob> | <product> |
| [Scenario C description] | <prob> | <cond_prob> | <product> |
| [Scenario D description] | <prob> | <cond_prob> | <product> |
| **Total** | 1.00 | — | **<sum>** |
```

Document explicitly: where did each P(scenario) come from? Where did each conditional probability come from? What sources or reasoning justify the values?

## Elicitation guidelines

- Define each scenario with a **precise, falsifiable description** — not "things go well" or "situation improves".
- Assign probabilities that reflect your **prior before this analysis**, not after anchoring on an aggregate outcome.
- P(scenario) should integrate domain knowledge about which path is most likely — do not default to uniform unless you are genuinely ignorant.
- Conditional probabilities P(event | scenario) should reflect the mechanism: fast-resolution scenarios have high P(event | scenario) at short horizons; prolonged scenarios have low P(event | scenario) at all but the longest horizons.
- The 3-month conditional probability for a "fast resolution" scenario should be grounded in realistic timelines for that type of resolution (e.g., "diplomatic deals of this type typically take 6–12 weeks to implement after announcement").

## Consistency checks

- Scenario probabilities must sum to 1.0.
- The aggregate P(event in 365d) should be within ~2× of the `ReferenceClassModel` base rate. If they diverge by more, re-examine scenario probabilities or conditional probs.
- Conditional probabilities must be monotonically non-decreasing across horizons for each scenario (P(event by 6mo | S) ≥ P(event by 3mo | S)).

## Model checks

**ConsistencyCheck** — primary check. Verify:
1. Scenario probabilities sum to 1.0 (±0.02 tolerance)
2. For each scenario, P(event | scenario, T1) ≤ P(event | scenario, T2) for T1 < T2
3. The aggregate P(event by T) is monotonically non-decreasing across horizons

**ReferenceClassCongruence** — compare the aggregate P(event by T_mid) to a
ReferenceClassModel base rate. A ratio > 4× or < 0.25× means your scenario weights
or conditional probabilities are inconsistent with historical analogues.
Document and justify any large divergence.

**PriorSensitivity** — perturb the Dirichlet concentration vector by ±50% and
re-run. If P(event by T_mid) changes by > 10pp, the forecast is sensitive to
scenario weight assumptions. Report as WARN.

## Gotchas

- **Scenario overlap**: Scenarios must be mutually exclusive. If two paths can happen simultaneously, merge them.
- **Missing scenarios**: If the aggregate P(event in 365d) is very low (<30%) and domain knowledge suggests the event is likely, a key scenario path is probably missing.
- **Anchoring bias**: Elicit each P(scenario) independently before computing their sum. If they don't sum to ~1, normalise and acknowledge the inconsistency.
- **Conditional probability direction**: Always write P(event | scenario), not P(scenario | event). These are very different quantities.
- **Do not copy example values.** The placeholder values in the code above are structural examples only. Every number must be derived from your specific domain analysis of this event.
