# Model Instance 3: Conservative Data + Geometric Adstock

## Configuration
- **Adstock**: Geometric decay
- **Saturation**: Logistic
- **Data**: 148 weeks (conservative cleaning, dropped first 8 weeks + outlier capping)
- **Sampler**: NUTS (JAX/numpyro), 4 chains × 2000 draws (1000 warmup)

## Convergence
- **Status**: ✅ Converged
- **Max R-hat**: 1.002
- **Min ESS (bulk)**: 2,104
- **Min ESS (tail)**: 1,678
- **Divergences**: 0/8000

## Fit Quality
- **In-sample R²**: 0.89
- **MAPE**: 7.2%
- **Out-of-sample R² (last 12 weeks)**: 0.83

## Key Findings

### ROAS Estimates (Posterior Mean ± SD)
| Channel | ROAS | 94% HDI |
|---------|------|---------|
| TV | 2.18 ± 0.39 | [1.49, 2.92] |
| Digital | 3.95 ± 0.57 | [2.89, 5.04] |
| Social | 2.76 ± 0.48 | [1.87, 3.68] |
| Search | 4.28 ± 0.65 | [3.06, 5.52] |
| Print | 1.08 ± 0.35 | [0.43, 1.73] |

### Saturation Analysis
- **TV**: Operating at 70% saturation
- **Digital**: Operating at 76% saturation
- **Social**: Operating at 55% saturation
- **Search**: Operating at 83% saturation
- **Print**: Operating at 43% saturation

### Notes
- Tighter priors led to narrower posteriors (lower SD across the board)
- Slightly lower R² due to fewer data points but better convergence metrics
- ROAS rankings consistent with Instance 1: Search > Digital > Social > TV > Print
- Removing early weeks reduced TV ROAS slightly (early brand-building period removed)
