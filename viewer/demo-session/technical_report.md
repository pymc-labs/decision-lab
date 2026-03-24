# Marketing Mix Model — Technical Report

## 1. Data
- **Source**: `marketing_spend_weekly.csv` — 156 weeks (2023-W01 to 2025-W52)
- **Target**: Weekly revenue (USD)
- **Channels**: TV, Digital, Social, Search, Print (weekly spend)
- **Controls**: price_index, seasonality_index, competitor_spend, trend
- **Preprocessing**: 3 missing competitor_spend values interpolated. No non-linear transforms applied to channels or target.

## 2. Model Specification (Selected: Instance 2)

### Likelihood
```
revenue ~ Normal(μ, σ)
μ = intercept + Σ(channel_contributions) + Σ(control_effects)
```

### Channel Contribution
```
channel_contribution_c = β_c × saturation(adstock(spend_c))
adstock: Weibull CDF with shape_c, scale_c parameters
saturation: Logistic with lambda_c, L_c parameters
```

### Priors
| Parameter | Prior | Rationale |
|-----------|-------|-----------|
| intercept | Normal(8e6, 2e6) | Centered on mean revenue |
| β_channel | HalfNormal(σ=2) | Positive channel effects |
| weibull_shape | Gamma(α=2, β=1) | Flexible, peaks around 2 |
| weibull_scale | Gamma(α=2, β=0.5) | Weeks, channel-specific |
| saturation_lambda | Beta(α=2, β=2) | Mid-range default |
| saturation_L | HalfNormal(σ=3) | Channel capacity |
| β_control | Normal(0, 1) | Weakly informative |
| σ | HalfNormal(σ=1e6) | Observation noise |

### l_max Settings
- TV: 13 | Digital: 6 | Social: 4 | Search: 4 | Print: 8

## 3. Inference
- **Sampler**: NUTS via JAX/NumPyro backend
- **Chains**: 4
- **Draws**: 2000 per chain (1000 warmup)
- **Total posterior samples**: 4000
- **Runtime**: 487 seconds

## 4. Convergence Diagnostics

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Max R-hat | 1.006 | < 1.01 | ✅ |
| Min ESS (bulk) | 1,203 | > 400 | ✅ |
| Min ESS (tail) | 987 | > 400 | ✅ |
| Divergences | 12/8000 | < 1% | ✅ |
| Energy BFMI | 0.94 | > 0.3 | ✅ |

## 5. Posterior Estimates

### Channel ROAS
| Channel | Mean | SD | HDI 3% | HDI 97% |
|---------|------|----|--------|---------|
| TV | 2.58 | 0.51 | 1.67 | 3.54 |
| Digital | 3.62 | 0.58 | 2.54 | 4.72 |
| Social | 3.21 | 0.63 | 2.04 | 4.41 |
| Search | 3.89 | 0.68 | 2.63 | 5.20 |
| Print | 1.41 | 0.44 | 0.59 | 2.24 |

### Adstock Parameters (Weibull)
| Channel | Shape (mean) | Scale (mean) | Implied Peak Week |
|---------|-------------|-------------|-------------------|
| TV | 1.8 | 4.1 | ~2.0 |
| Digital | 2.3 | 1.4 | ~1.0 |
| Social | 2.1 | 1.0 | ~0.7 |
| Search | 3.2 | 0.7 | ~0.5 |
| Print | 1.4 | 3.8 | ~2.5 |

### Saturation Operating Points
| Channel | Current Saturation | Spend at 90% Sat | Headroom |
|---------|-------------------|-------------------|----------|
| TV | 61% | $1.12M/wk | Moderate |
| Digital | 74% | $780K/wk | Limited |
| Social | 48% | $820K/wk | Large |
| Search | 79% | $580K/wk | Very Limited |
| Print | 38% | $490K/wk | Large (but low ROAS) |

## 6. Model Comparison

| Metric | Instance 1 (Geo) | Instance 2 (Weibull) | Instance 3 (Geo+Conservative) |
|--------|------------------|---------------------|------------------------------|
| R² (in-sample) | 0.91 | **0.93** | 0.89 |
| MAPE | 6.8% | **5.9%** | 7.2% |
| R² (holdout) | 0.84 | **0.86** | 0.83 |
| Divergences | 0 | 12 | 0 |
| Max R-hat | 1.003 | 1.006 | 1.002 |

Instance 2 selected for best fit quality with acceptable convergence.

## 7. Conflict Detection
All three models produced consistent ROAS rankings (Search > Digital > Social > TV > Print) with max variation ratio of 1.31x (Print). No directional disagreements. Ensemble agreement strengthens confidence in recommendations.

## 8. Budget Optimization
SLSQP optimizer with ±20% bounds on each channel. Objective: maximize expected revenue. Constraint: total budget = $2.4M/month.

See `budget_20pct/optimization_summary.json` for detailed allocation.
