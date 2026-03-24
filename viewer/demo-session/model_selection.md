# Model Selection

## Selected Model: Instance 2 (Flexible Adstock MMM — Weibull CDF)

### Rationale
1. **Best fit quality**: R² = 0.93 (vs 0.91, 0.89), MAPE = 5.9% (vs 6.8%, 7.2%)
2. **Good convergence**: All R-hat < 1.01, 12 divergences out of 8000 draws (0.15%) is acceptable
3. **Captures delayed effects**: Weibull adstock better represents TV's delayed peak and Print's slow build
4. **Consistent with ensemble**: ROAS estimates fall within the range of all three models
5. **Out-of-sample performance**: Best holdout R² = 0.86

### Trade-off Considered
Instance 3 had the best convergence diagnostics (0 divergences, highest ESS), but its slightly lower fit quality and the loss of 8 weeks of data made it less suitable as the primary model. Its tight agreement with Instance 2 validates the Weibull model's estimates.
