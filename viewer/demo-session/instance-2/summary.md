# Model Instance 2: Flexible Adstock MMM (Weibull CDF)

## Configuration
- **Adstock**: Weibull CDF (flexible peak timing)
- **Saturation**: Logistic
- **Data**: Full 156 weeks, minimal cleaning
- **Sampler**: NUTS (JAX/numpyro), 4 chains × 2000 draws (1000 warmup)

## Convergence
- **Status**: ✅ Converged
- **Max R-hat**: 1.006
- **Min ESS (bulk)**: 1,203
- **Min ESS (tail)**: 987
- **Divergences**: 12/8000 (0.15% — acceptable)

## Fit Quality
- **In-sample R²**: 0.93
- **MAPE**: 5.9%
- **Out-of-sample R² (last 12 weeks)**: 0.86

## Key Findings

### ROAS Estimates (Posterior Mean ± SD)
| Channel | ROAS | 94% HDI |
|---------|------|---------|
| TV | 2.58 ± 0.51 | [1.67, 3.54] |
| Digital | 3.62 ± 0.58 | [2.54, 4.72] |
| Social | 3.21 ± 0.63 | [2.04, 4.41] |
| Search | 3.89 ± 0.68 | [2.63, 5.20] |
| Print | 1.41 ± 0.44 | [0.59, 2.24] |

### Saturation Analysis
- **TV**: Operating at 61% saturation
- **Digital**: Operating at 74% saturation
- **Social**: Operating at 48% saturation
- **Search**: Operating at 79% saturation
- **Print**: Operating at 38% saturation

### Adstock (Weibull Parameters)
- TV: shape=1.8, scale=4.1 (peak at ~2 weeks, long tail)
- Digital: shape=2.3, scale=1.4 (sharp peak at ~1 week)
- Social: shape=2.1, scale=1.0 (sharp peak, fast decay)
- Search: shape=3.2, scale=0.7 (very sharp, immediate)
- Print: shape=1.4, scale=3.8 (slow build, peak ~2.5 weeks)

### Notable Differences from Instance 1
- Weibull captures TV's delayed peak effect better — TV ROAS slightly higher
- Social benefits from flexible decay shape — ROAS bumped up
- Overall better fit (R² 0.93 vs 0.91) with only slightly more parameters
