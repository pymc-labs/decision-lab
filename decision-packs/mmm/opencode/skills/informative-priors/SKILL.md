---
name: Informative Priors for MMM
description: Expert guide on calculating and setting informative priors for PyMC-Marketing MMM models based on data characteristics and domain knowledge. Use when configuring priors for intercept, channel effects, or adstock parameters.
---

# Guide: Calculating Informative Priors for MMM

This guide describes how to calculate tighter, more informative priors for PyMC-Marketing MMM based on data characteristics.

**Important:** The default wide priors (`intercept: Normal(mu=0, sigma=2)`) often lead to better-calibrated posteriors. Only use informative priors when you have strong domain knowledge or specific requirements. Overly tight priors can lead to overconfident (underdispersed) posteriors.

## When to Use Informative Priors

- You have domain knowledge about expected ROAS ranges, decay rates, or effect sizes
- You have results from previous studies or models to inform your beliefs
- Business constraints require certain parameter ranges
- You're doing sensitivity analysis to understand prior impact

## Step 1: Calculate Scaled Statistics

PyMC-Marketing uses MaxAbsScaler for target and channels (divides by max absolute value).

```python
# Calculate how your data looks in scaled space
y_scaled_max = 1.0  # By definition (MaxAbsScaler)
y_scaled_mean = y.mean() / y.max()  # Typically 0.6-0.8
y_scaled_min = y.min() / y.max()   # Typically 0.4-0.6

print(f"Scaled y statistics:")
print(f"  min:  {y_scaled_min:.3f}")
print(f"  mean: {y_scaled_mean:.3f}")
print(f"  max:  {y_scaled_max:.3f}")
```

## Step 2: Reason About Intercept Prior

The intercept represents predicted y when all channels = 0 (no marketing spend).

```python
# Intercept should be LESS than scaled mean (marketing contributes positively!)
# Reasonable range in scaled space: 0.3 to 0.7

# If you believe ~20% of sales come from marketing:
intercept_mu = y_scaled_mean * 0.8

# Sigma controls uncertainty - smaller = more confident
# 0.2 = tight (use if you have strong beliefs)
# 0.5 = moderate
# 1.0+ = wide (closer to default)
intercept_sigma = 0.2

print(f"Intercept prior: Normal(mu={intercept_mu:.2f}, sigma={intercept_sigma})")
```

## Step 3: Reason About Channel Effect Priors

`saturation_beta` represents the effect size per channel in scaled space.

```python
# If 3 channels share ~20% of y, each contributes ~0.07 on average
n_channels = len(channel_columns)
expected_total_channel_contribution = 1 - intercept_mu  # What's left after baseline
expected_per_channel = expected_total_channel_contribution / n_channels

# Prior sigma: allow 2-3x expected value for exploration
beta_sigma = expected_per_channel * 2.5

print(f"Channel beta prior: HalfNormal(sigma={beta_sigma:.2f})")
print(f"  Expected per-channel contribution: ~{expected_per_channel:.2f}")
```

## Step 4: Set model_config

```python
from pymc_extras.prior import Prior

model_config = {
    "intercept": Prior("Normal", mu=intercept_mu, sigma=intercept_sigma),
    "saturation_beta": Prior("HalfNormal", sigma=beta_sigma),
    # adstock_alpha: Beta(2,3) favors values 0.3-0.6, good default
    "adstock_alpha": Prior("Beta", alpha=2, beta=3),
}

mmm = MMM(
    date_column=date_column,
    channel_columns=channel_columns,
    adstock=GeometricAdstock(l_max=l_max),
    saturation=LogisticSaturation(),
    model_config=model_config,
    # ... other parameters
)
```

## Step 5: Validate with Prior Predictive Checks

After setting informative priors, always validate:

```python
mmm.build_model(X=X, y=y)
mmm.sample_prior_predictive(X=X, samples=1000, random_seed=None  # Set for reproducibility)

# Check prior predictive coverage
from mmm_lib import check_prior_predictive_coverage
coverage = check_prior_predictive_coverage(mmm, y, hdi_prob=0.94)

# With informative priors, expect:
# - HDI should be ~2-5x observed range (tighter than defaults)
# - Some negative predictions OK, but <10% of samples
# - Coverage should still be high (>80%)
```

## Adjusting Based on Prior Predictive

| Observation | Action |
|-------------|--------|
| HDI too wide (>10x observed range) | Decrease sigma values |
| HDI too narrow (<2x observed range) | Increase sigma values |
| Too many negative predictions (>10%) | Increase intercept mu or use HalfNormal |
| Coverage too low (<50%) | Loosen priors (increase sigmas) |

## Example: Full Workflow

```python
import pandas as pd
import numpy as np
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation
from pymc_extras.prior import Prior

# Load data
df = pd.read_parquet('cleaned_data.parquet')
y = df[target_column]
channel_columns = ['tv', 'digital', 'radio']

# Step 1: Calculate scaled statistics
y_scaled_mean = y.mean() / y.max()
print(f"Scaled y mean: {y_scaled_mean:.3f}")

# Step 2: Set intercept (assume 25% from marketing)
intercept_mu = y_scaled_mean * 0.75
intercept_sigma = 0.3

# Step 3: Set channel effects
n_channels = len(channel_columns)
expected_per_channel = (1 - intercept_mu) / n_channels
beta_sigma = expected_per_channel * 2

# Step 4: Create model config
model_config = {
    "intercept": Prior("Normal", mu=intercept_mu, sigma=intercept_sigma),
    "saturation_beta": Prior("HalfNormal", sigma=beta_sigma),
    "adstock_alpha": Prior("Beta", alpha=2, beta=3),
}

print(f"Model config:")
print(f"  intercept: Normal(mu={intercept_mu:.2f}, sigma={intercept_sigma})")
print(f"  saturation_beta: HalfNormal(sigma={beta_sigma:.2f})")
print(f"  adstock_alpha: Beta(alpha=2, beta=3)")

# Create MMM with informative priors
mmm = MMM(
    date_column='date',
    channel_columns=channel_columns,
    adstock=GeometricAdstock(l_max=8),
    saturation=LogisticSaturation(),
    model_config=model_config,
)

# Step 5: Validate
X = df[['date'] + channel_columns]
mmm.build_model(X=X, y=y)
mmm.sample_prior_predictive(X=X, samples=1000, random_seed=None  # Set for reproducibility)

# Check and adjust if needed...
```

## Warning: Posterior Calibration

Informative priors that are too tight can cause **underdispersed posteriors** (overconfident uncertainty estimates). Signs of this:

- 94% HDI coverage << 94% (e.g., 50-60%)
- Posterior intervals that don't contain true values

If you observe this, **loosen your priors** by increasing sigma values, or revert to defaults.

## Additional Prior Types

### Beta Distribution for Bounded Parameters

For parameters that must be between 0 and 1 (like adstock decay):

```python
# Beta(2, 3) - mode around 0.33, favors lower values
# Beta(2, 2) - symmetric around 0.5
# Beta(3, 2) - mode around 0.67, favors higher values

model_config = {
    "adstock_alpha": Prior("Beta", alpha=2, beta=3),
}
```

### HalfNormal for Positive Parameters

For strictly positive parameters:

```python
model_config = {
    "saturation_beta": Prior("HalfNormal", sigma=0.5),
    "sigma": Prior("HalfNormal", sigma=1.0),
}
```

### LogNormal for Positive Parameters with Heavy Tails

When you expect occasional large values:

```python
model_config = {
    "saturation_lam": Prior("LogNormal", mu=0, sigma=1),
}
```

## Domain Knowledge Integration

### From Historical Data

If you have previous MMM results:

```python
# Use posterior mean from previous model as prior mean
# Use posterior std * 2 as prior std (to allow for model differences)
previous_intercept_mean = 0.65
previous_intercept_std = 0.1

model_config = {
    "intercept": Prior("Normal",
                       mu=previous_intercept_mean,
                       sigma=previous_intercept_std * 2),
}
```

### From Industry Benchmarks

If you have industry benchmarks for ROAS or effect sizes:

```python
# Example: TV typically has ROAS of 2-5x
# In scaled space, this might translate to beta of 0.05-0.15
model_config = {
    "saturation_beta": Prior("TruncatedNormal",
                             mu=0.1,
                             sigma=0.05,
                             lower=0),
}
```

### From Business Constraints

If business logic requires certain constraints:

```python
# Example: Marketing cannot contribute more than 50% of sales
# Set intercept prior to be at least 0.5
model_config = {
    "intercept": Prior("TruncatedNormal",
                       mu=0.7,
                       sigma=0.1,
                       lower=0.5),
}
```

## When to Use This Skill

- Setting up initial priors for a new MMM
- Adjusting priors based on prior predictive checks
- Incorporating domain knowledge into the model
- Debugging overly wide or narrow posterior distributions
- Sensitivity analysis to understand prior impact on results
