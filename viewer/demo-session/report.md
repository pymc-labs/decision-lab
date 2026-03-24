# Marketing Mix Model — Executive Report

## Overview
We analyzed 3 years of weekly marketing data (156 weeks) across 5 channels to understand channel ROI and optimize Q2 2026 budget allocation. Three independent modeling approaches were run in parallel and cross-validated — all agreed on the key findings below.

## Key Findings

### Channel Performance (Return on Ad Spend)
1. **Search** ($4.12 per $1 spent) — Highest ROI but highly saturated (79%). Additional spend yields diminishing returns.
2. **Digital** ($3.62 per $1 spent) — Strong performer, approaching saturation (74%).
3. **Social** ($3.21 per $1 spent) — Strong ROI with significant room to grow (only 48% saturated).
4. **TV** ($2.58 per $1 spent) — Moderate ROI with delayed effects (peaks ~2 weeks after airing). Moderately saturated (61%).
5. **Print** ($1.41 per $1 spent) — Lowest ROI. Slow to build, limited impact.

### The Opportunity
**Social media is your biggest growth lever.** At only 48% saturation with a ROAS of 3.2x, every additional dollar in Social works nearly twice as hard as the same dollar in Search (which is 79% saturated). Meanwhile, Print's low returns suggest budget could be better deployed elsewhere.

## Budget Recommendation (±20% Reallocation)
Keeping total monthly budget at $2.4M:

| Channel | Current | Recommended | Change |
|---------|---------|-------------|--------|
| TV | $680K | $578K | -15% |
| Digital | $520K | $468K | -10% |
| Social | $380K | $456K | **+20%** |
| Search | $440K | $484K | +10% |
| Print | $180K | $144K | -20% |

**Expected impact**: +8.3% revenue uplift (~$662K/month additional revenue) with zero incremental spend.

## Confidence & Caveats
- **High confidence**: Three independent models (different adstock formulations, data cleaning approaches) produced consistent rankings and similar ROAS estimates
- **Model fit**: R² = 0.93, MAPE = 5.9% — strong predictive accuracy
- **Caveat**: Model assumes historical relationships persist. Major competitive shifts or market changes may alter channel effectiveness
- **Caveat**: Print may serve brand-building functions not fully captured by short-term revenue attribution

## Methodology
Bayesian Media Mix Model using PyMC-Marketing with Weibull adstock transformations and logistic saturation curves. Fitted via NUTS sampler (4 chains × 2000 draws). All convergence diagnostics passed. Full technical details in the companion technical report.
