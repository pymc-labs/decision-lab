# Model Instance 1: Standard Saturating MMM (Geometric Adstock)

## Configuration
- **Adstock**: Geometric decay
- **Saturation**: Logistic
- **Data**: Full 156 weeks, minimal cleaning
- **Sampler**: NUTS (JAX/numpyro), 4 chains × 2000 draws (1000 warmup)

## Convergence
- **Status**: ✅ Converged
- **Max R-hat**: 1.003 (all params < 1.01)
- **Min ESS (bulk)**: 1,847
- **Min ESS (tail)**: 1,421
- **Divergences**: 0/8000

## Fit Quality
- **In-sample R²**: 0.91
- **MAPE**: 6.8%
- **Out-of-sample R² (last 12 weeks)**: 0.84

## Key Findings

### ROAS Estimates (Posterior Mean ± SD)
| Channel | ROAS | 94% HDI |
|---------|------|---------|
| TV | 2.31 ± 0.42 | [1.58, 3.12] |
| Digital | 3.87 ± 0.61 | [2.74, 5.03] |
| Social | 2.94 ± 0.55 | [1.92, 3.98] |
| Search | 4.12 ± 0.73 | [2.78, 5.51] |
| Print | 1.23 ± 0.38 | [0.52, 1.94] |

### Saturation Analysis
- **TV**: Operating at 67% saturation — moderate room for growth
- **Digital**: Operating at 78% saturation — approaching diminishing returns
- **Social**: Operating at 52% saturation — significant room for growth
- **Search**: Operating at 81% saturation — highly saturated
- **Print**: Operating at 41% saturation — low saturation but also low ROAS

### Adstock Half-lives
- TV: 3.2 weeks | Digital: 1.1 weeks | Social: 0.8 weeks | Search: 0.5 weeks | Print: 2.8 weeks
