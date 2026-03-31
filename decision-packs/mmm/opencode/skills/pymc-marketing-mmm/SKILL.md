---
name: PyMC-Marketing MMM
description: Expert on PyMC-Marketing's Marketing Mix Model (MMM) framework including adstock transformations, saturation functions, hierarchical models, and GAM components. Use for MMM modeling, prior configuration, or pymc-marketing API questions.
---

# PyMC-Marketing GAM Options and Advanced Model Architectures

## Overview

PyMC-Marketing extends beyond traditional Marketing Mix Modeling to support custom **Bayesian Generalized Additive Models (GAMs)** with flexible architectures for complex probabilistic inference. This skill covers advanced modeling patterns, multidimensional hierarchical structures, and custom model components.

## MMM Import

Use `from pymc_marketing.mmm.multidimensional import MMM`. This handles both single time series (dims=None) and panel data with `dims=(<DIM>,)`.

**CRITICAL: The `dims` value MUST match the exact column name from your dataframe.** Inspect the data columns first, then use the actual column name. Do NOT assume a column name — always verify it exists in the data.

**WARNING: `from pymc_marketing.mmm import MMM` is DEPRECATED and will break save/load. Always use `from pymc_marketing.mmm.multidimensional import MMM`.**

## CRITICAL: Channel-Specific Parameters vs Dimensional Hierarchy

**These are TWO DIFFERENT things - don't confuse them!**

| Concept | What It Controls | Example |
|---------|------------------|---------|
| **`dims` parameter** | Hierarchical structure across *data dimensions* | Different baseline per region, pooled learning across regions |
| **Channel-specific parameters** | Per-channel adstock (alpha) and saturation (lambda) | TV has slower decay than Digital |

**WRONG: Single alpha/lambda shared across ALL channels**
```python
# This defeats the purpose of MMM!
mmm = MMM(
    channel_columns=["tv", "digital", "radio"],
    dims=<EXTRA_DIMS>,
    adstock=GeometricAdstock(l_max=8),  # Single alpha shared by all channels
    saturation=LogisticSaturation(),     # Single lambda shared by all channels
)
```

**CORRECT: PyMC-Marketing gives each channel its own parameters by default**

When you specify `channel_columns=["tv", "digital", "radio"]`, PyMC-Marketing automatically creates:
- `alpha[tv]`, `alpha[digital]`, `alpha[radio]` (3 separate adstock decay rates)
- `lam[tv]`, `lam[digital]`, `lam[radio]` (3 separate saturation parameters)
- `beta_channel[tv]`, `beta_channel[digital]`, `beta_channel[radio]` (3 separate effect sizes)

**The `dims` parameter adds ADDITIONAL hierarchy on top of this.** For example with `dims=<EXTRA_DIMS>`:
- `alpha[tv, dim_val_a]`, `alpha[tv, dim_val_b]`, `alpha[digital, dim_val_a]`, etc. (per channel AND per extra dimension)

**Key insight:** If you only see a SINGLE `alpha` and SINGLE `lam` in your trace plots (not arrays), something is wrong with your model configuration!

**After fitting, ALWAYS verify you have the right parameter shapes:**
```python
# Verify channel-specific parameters exist
# Parameter names: adstock_alpha, saturation_lam, saturation_beta
print(mmm.fit_result['adstock_alpha'].dims)      # Should be ('chain', 'draw', 'channel')
print(mmm.fit_result['saturation_lam'].dims)     # Should be ('chain', 'draw', 'channel')
print(mmm.fit_result['saturation_beta'].dims)    # Should be ('chain', 'draw', 'channel')

# Check shapes - should have n_channels in the last dimension
print(mmm.fit_result['adstock_alpha'].shape)     # e.g., (4, 2000, 3) for 4 chains, 2000 draws, 3 channels

# If using dims=<EXTRA_DIMS>, shapes should be (chain, draw, channel, *<EXTRA_DIMS>)
# NOT just (chain, draw) with a single scalar value!
```

## ⛔⛔⛔ CRITICAL: You MUST Configure Priors with dims - Default Does NOT Work!

**❌ WRONG - Creates USELESS models (parameters same for all dimension levels):**
```python
mmm = MMM(
    dims=<EXTRA_DIMS>,
    adstock=GeometricAdstock(l_max=12),  # NO priors! All dim levels share same alpha!
    saturation=LogisticSaturation(),     # NO priors! All dim levels share same params!
)
```

**The default `GeometricAdstock(l_max=12)` without `priors=` does NOT create dimension-specific parameters!**

**✅ CORRECT - Configure priors with dims:**
```python
from pymc_extras.prior import Prior

adstock = GeometricAdstock(
    priors={"alpha": Prior("Beta", alpha=<ALPHA>, beta=<BETA>, dims=("channel", <DIM>))},
    l_max=12
)
saturation = LogisticSaturation(
    priors={
        "lam": Prior("Gamma", mu=<MU>, sigma=<SIGMA>, dims=("channel", <DIM>)),
        "beta": Prior("Gamma", mu=<MU>, sigma=<SIGMA>, dims=("channel", <DIM>)),
    }
)
mmm = MMM(dims=<EXTRA_DIMS>, adstock=adstock, saturation=saturation)
```

## Parameter Pooling Strategies for Multidimensional MMM

When using `MMM` with dimensions like `dims=<EXTRA_DIMS>`, you MUST configure how parameters vary across dimensions. There are **three strategies**:

### Strategy 1: Fully Pooled (Shared across all dimension levels)

**Same parameter for all dimension levels - one value per channel, shared everywhere.**

```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation
from pymc_extras.prior import Prior

# Fully pooled: dims="channel" only (no extra dimension)
adstock = GeometricAdstock(
    priors={"alpha": Prior("Beta", alpha=<VALUE>, beta=<VALUE>, dims=("channel",))},
    l_max=8
)
saturation = LogisticSaturation(
    priors={
        "lam": Prior("Gamma", mu=<VALUE>, sigma=<VALUE>, dims=("channel",)),
        "beta": Prior("Gamma", mu=<VALUE>, sigma=<VALUE>, dims=("channel",)),
    }
)

mmm = MMM(
    date_column="date",
    target_column="sales",
    channel_columns=["tv", "radio", "digital"],
    dims=<EXTRA_DIMS>,
    adstock=adstock,
    saturation=saturation,
)
```

**Use when:**
- Limited data per dimension level
- You believe channel effects are truly the same across all dimension levels
- Starting simple

**Result:** 3 alpha values (one per channel), shared across all dimension levels.

### Strategy 2: Unpooled (Independent per dimension-channel)

**Separate parameter for every dimension-channel combination - no information sharing.**

```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation
from pymc_extras.prior import Prior

# Unpooled: dims includes both channel AND the extra dimension
adstock = GeometricAdstock(
    priors={"alpha": Prior("Beta", alpha=<ALPHA>, beta=<BETA>, dims=("channel", <DIM>))},
    l_max=8
)
saturation = LogisticSaturation(
    priors={
        "lam": Prior("Gamma", mu=<MU>, sigma=<SIGMA>, dims=("channel", <DIM>)),
        "beta": Prior("Gamma", mu=<MU>, sigma=<SIGMA>, dims=("channel", <DIM>)),
    }
)

mmm = MMM(
    date_column="date",
    target_column="sales",
    channel_columns=["tv", "radio", "digital"],
    dims=<EXTRA_DIMS>,
    adstock=adstock,
    saturation=saturation,
)
```

**Use when:**
- Lots of data per dimension level (50+ observations per level recommended)
- You believe effects truly vary by market
- Markets are very different (e.g., different countries with different media landscapes)

**Result:** 3 channels × N dimension levels = 3N alpha values, each estimated independently.

### Strategy 3: Hierarchical / Partial Pooling (RECOMMENDED)

**Dimension levels share information through channel-level hyperparameters, but still get dimension-specific estimates.**

```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation
from pymc_extras.prior import Prior

# Hierarchical: hyperparameters have dims="channel", final param has dims=("channel", <DIM>)
adstock = GeometricAdstock(
    priors={
        "alpha": Prior(
            "Beta",
            alpha=Prior("Gamma", mu=2, sigma=1, dims="channel"),   # Shared across dimension levels
            beta=Prior("Gamma", mu=5, sigma=2, dims="channel"),    # Shared across dimension levels
            dims=("channel", <DIM>),                                # But dimension-specific values
        )
    },
    l_max=8
)

saturation = LogisticSaturation(
    priors={
        # Lambda: fully pooled (channel efficiency assumed similar across dimension levels)
        "lam": Prior("Gamma", mu=<MU>, sigma=<SIGMA>, dims="channel"),

        # Beta: hierarchical (max impact varies by dimension but channels share structure)
        "beta": Prior(
            "Normal",
            mu=Prior("Gamma", mu=0.25, sigma=0.10, dims="channel"),
            sigma=Prior("Exponential", scale=0.10, dims="channel"),
            dims=("channel", <DIM>),
            centered=False,  # Non-centered helps MCMC convergence
        ),
    }
)

mmm = MMM(
    date_column="date",
    target_column="sales",
    channel_columns=["tv", "radio", "digital"],
    dims=<EXTRA_DIMS>,
    adstock=adstock,
    saturation=saturation,
)
```

**Use when:**
- Moderate data per dimension level
- You want dimension levels to "borrow strength" from each other
- Markets are related but not identical (e.g., different US states)

**Key insight:** The hierarchical prior allows TV in geo_a to inform TV in geo_b (through shared hyperparameters), while TV never influences radio (independent channel effects).

### Strategy 4: Mixed Pooling (Practical Default)

**Mix different strategies for different parameters based on domain knowledge.**

```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation
from pymc_extras.prior import Prior

# Adstock: unpooled (memory effects can vary significantly by market)
adstock = GeometricAdstock(
    priors={"alpha": Prior("Beta", alpha=<ALPHA>, beta=<BETA>, dims=("channel", <DIM>))},
    l_max=<LMAX>,
)

# Saturation: mixed
saturation = LogisticSaturation(
    priors={
        # Lambda (channel efficiency): pooled - assume similar efficiency across markets
        "lam": Prior("Gamma", mu=<MU>, sigma=<SIGMA>, dims="channel"),

        # Beta (max impact): unpooled - market size/potential varies
        "beta": Prior("Gamma", mu=<MU>, sigma=<SIGMA>, dims=("channel", <DIM>)),
    }
)

mmm = MMM(
    date_column="date",
    target_column="sales",
    channel_columns=["tv", "radio", "digital"],
    dims=<EXTRA_DIMS>,
    adstock=adstock,
    saturation=saturation,
)
```

**This is often the most practical starting point:**
- Adstock alpha varies by dimension (different media consumption patterns)
- Lambda pooled (channel response shape similar across markets)
- Beta varies by dimension (different market sizes)

### Best Practice: Start Simple, Add Complexity

From the PyMC-Marketing documentation:

> "The choice is primarily driven by computational considerations. Partial pooling is generally a more reasonable assumption but it can make the model slower to estimate, more complicated to debug, and more difficult to reason about."

**Recommended progression:**
1. Start with **fully pooled** or **mixed pooling** (Strategy 1 or 4)
2. Fit model, check convergence, validate results
3. If you have enough data and see evidence of dimension-level variation, try **unpooled** (Strategy 2)
4. Only use **hierarchical** (Strategy 3) if you need information sharing AND have convergence issues with unpooled

### Verifying Parameter Shapes After Fitting

**ALWAYS check that you got the dimensionality you expected:**

```python
# After fitting
print("Adstock alpha dims:", mmm.fit_result['adstock_alpha'].dims)
print("Adstock alpha shape:", mmm.fit_result['adstock_alpha'].shape)

# Expected for 3 channels, 5 dimension levels:
# Fully pooled:  ('chain', 'draw', 'channel') → shape (N_CHAINS, TOTAL_DRAWS, 3)
# Unpooled:      ('chain', 'draw', 'channel', <DIM>) → shape (N_CHAINS, TOTAL_DRAWS, 3, 5)
# Hierarchical:  ('chain', 'draw', 'channel', <DIM>) → shape (N_CHAINS, TOTAL_DRAWS, 3, 5)

# If you see shape (N_CHAINS, TOTAL_DRAWS) with no channel/extra dimension, something is WRONG!
```

## Key Concept: MMM as a GAM Framework

PyMC-Marketing is **not only a framework for marketing optimization but also a general-purpose engine for building interpretable Bayesian GAMs**. The architecture enables seamless transitions from standard MMM to fully specified graphical models capturing richer causal relationships.

## Core Capabilities

### 1. Flexible Architecture Progression

The framework supports progression from simple to complex models:

1. **Simple Linear Regression**
   - Automatic scaling and preprocessing
   - Basic channel effects

2. **Linear MMM with Transformations**
   - Adstock transformations (carryover effects)
   - Saturation transformations (diminishing returns)

3. **Multidimensional Hierarchical Models**
   - Country/region/product dimensions
   - Dimension-specific parameters
   - Automatic broadcasting across dimensions

4. **Custom Bayesian GAMs**
   - Temporal components (trends, seasonality)
   - Custom additive effects
   - Fully specified graphical models

### 2. Composable Components

All components can be mixed and matched:
- Adstock transformations
- Saturation functions
- Temporal effects
- Hierarchical priors
- Multiple dimensions

## Model Components in Detail

### Adstock Transformations

**Purpose**: Model how marketing impact decays over time (carryover effects)

**Options**:

1. **GeometricAdstock** (most common)
   ```python
   from pymc_marketing.mmm import GeometricAdstock

   adstock = GeometricAdstock(l_max=<LMAX>)
   ```
   - `l_max`: Maximum lag (number of periods for decay)
   - Models exponential decay of marketing effects

2. **NoAdstock** (instant impact, no carryover)
   ```python
   from pymc_marketing.mmm import NoAdstock

   adstock = NoAdstock(l_max=1)
   ```
   - Use when effects are immediate with no carryover

**Multidimensional Configuration**:
```python
adstock = GeometricAdstock(l_max=6).set_dims_for_all_priors(
    ('country', 'region', 'product_type', 'channel')
)
```

### Saturation Functions

**Purpose**: Model diminishing returns as marketing spend increases

**Options**:

1. **LogisticSaturation** (most common)
   ```python
   from pymc_marketing.mmm import LogisticSaturation

   saturation = LogisticSaturation()
   ```
   - Models S-curve response to spending
   - Captures diminishing returns

#### ⚠️ Understanding LogisticSaturation Parameters

**Formula**: `saturation_level = (1 - exp(-lam * x)) / (1 + exp(-lam * x))`

Where:
- `x` is scaled spend (in [0, 1] range after MaxAbsScaler)
- `lam` (lambda) is the **rate of saturation** (NOT a spend threshold!)
- `beta` scales the maximum effect

**Parameter interpretation:**

| Parameter | Higher value means... |
|-----------|----------------------|
| `lam` | **Faster saturation** - channel reaches diminishing returns sooner |
| `beta` | Larger maximum effect - channel contributes more to target |

**⚠️ CRITICAL: Lambda is NOT a spend level!**

- **WRONG interpretation**: "Lambda of 45,200 means saturation at $45K spend"
- **RIGHT interpretation**: "Lambda is dimensionless; higher = faster saturation rate"

**Computing actual saturation level at current spend:**

```python
# Get lambda from posterior
lam_mean = mmm.fit_result['saturation_lam'].sel(channel=channel).mean()

# Scaled spend (MaxAbsScaler divides by max)
scaled_spend = df[channel].mean() / df[channel].max()
```

2. **NoSaturation** (linear response)
   ```python
   from pymc_marketing.mmm import NoSaturation

   saturation = NoSaturation()
   ```
   - Use when response is perfectly linear

**With Hierarchical Priors**:
```python
from pymc_extras.prior import Prior, LogNormalPrior

saturation = NoSaturation(
    priors={
        "beta": LogNormalPrior(
            mean=Prior("Normal", mu=1, sigma=2, dims="country"),
            std=Prior("Normal", mu=1, sigma=2, dims="region")
        )
    }
)
```

### Temporal Components

**LinearTrend**: Piecewise linear trends with learned changepoints

```python
from pymc_marketing.mmm import LinearTrend
from pymc_marketing.mmm.additive_effect import LinearTrendEffect

trend = LinearTrend(
    n_changepoints=<N_CHANGEPOINTS>,  # Number of evenly-spaced changepoints
    include_intercept=<BOOL>,          # Whether to include base intercept k
    # dims=<DIM>,                      # For hierarchical trend across panel dimensions
)
# Integrate with MMM via mu_effects (before build_model/fit):
trend_effect = LinearTrendEffect(trend=trend, prefix="trend")
mmm.mu_effects.append(trend_effect)
```

**Mathematical expression**: `Trend(t) = k + sum(delta_j * I(t > s_j))`
- `k`: Base intercept (only if `include_intercept=True`)
- `delta_j ~ Laplace(0, b)`: Change in slope at changepoint j (sparse prior)
- `s_j`: Evenly spaced changepoints from 0 to max(t)
- `I`: Indicator function

**Choosing `n_changepoints`**: Use approximately one changepoint per year of data. The Laplace prior on deltas is sparse — unnecessary changepoints shrink toward zero — so slightly overestimating is safe. Underestimating risks missing real slope changes.

**WeeklyFourier**: Seasonal patterns using Fourier series

```python
from pymc_marketing.mmm.fourier import WeeklyFourier

weekly = WeeklyFourier(n_order=<N_ORDER>)  # Number of Fourier terms
```

**Mathematical expression**: `Seasonality(t) = sum[a_n*cos(2*pi*n*t/P) + b_n*sin(2*pi*n*t/P)]`
- `P`: Period (e.g., weekly, yearly)
- `N`: Number of Fourier terms (n_order)
- Higher `n_order` captures more complex seasonal patterns

## Model Building Patterns

### Pattern 1: Basic Linear Model (No Transformations)

```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import NoAdstock, NoSaturation

linear_model = MMM(
    date_column="date_week",
    channel_columns=["x1", "x2", "x3", "x4"],
    adstock=NoAdstock(l_max=1),
    saturation=NoSaturation()
)
linear_model.fit(X=X, y=y)  # y passed separately
```

**Use case**: Baseline comparison, testing data pipeline

### Pattern 2: Standard MMM with Transformations

```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation

mmm = MMM(
    date_column="date_week",
    channel_columns=["tv", "digital", "radio"],
    adstock=GeometricAdstock(l_max=8),
    saturation=LogisticSaturation()
)
mmm.fit(X=X, y=y)  # y passed separately
```

**Use case**: Standard marketing mix modeling with carryover and saturation

### Pattern 3: Multidimensional Hierarchical Model - FOR REGIONAL DATA

**Use this pattern when you have panel data with repeated dates per dimension level (e.g., region, market, country).**

```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation

hierarchical_mmm = MMM(
    date_column="date_week",
    target_column="y",              # Target column name
    channel_columns=["tv", "digital", "radio"],
    dims=<EXTRA_DIMS>,                  # Dimension column(s) - e.g., region, market, country
    adstock=GeometricAdstock(l_max=8),
    saturation=LogisticSaturation(),
    yearly_seasonality=2,
)
X = df.drop(columns=["y"])
y = df["y"]
hierarchical_mmm.fit(X=X, y=y, nuts_sampler="numpyro")
```

**When to use**: Data has a dimension column (e.g., `region`, `market`, `country`) with repeated dates per level.

**Key insight**: Use `dims` parameter for panel/multi-region data; omit it (or set to None) for single time series.

**Automatic broadcasting**: MMM handles broadcasting automatically, allowing parameters of different shapes without manual dimension management.

### Pattern 4: GAM with Temporal Components

```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation, LinearTrend
from pymc_marketing.mmm.additive_effect import LinearTrendEffect, FourierEffect
from pymc_marketing.mmm.fourier import WeeklyFourier

# Create base MMM
mmm = MMM(
    date_column=<DATE_COL>,
    target_column=<TARGET_COL>,
    channel_columns=<CHANNEL_COLS>,
    adstock=GeometricAdstock(l_max=<L_MAX>),
    saturation=LogisticSaturation()
)

# Create temporal components
trend = LinearTrend(n_changepoints=<N_CHANGEPOINTS>)
weekly = WeeklyFourier(n_order=<N_ORDER>)

# Add to model as additive effects (before build_model/fit)
mmm.mu_effects.extend([
    LinearTrendEffect(trend=trend, prefix="trend"),
    FourierEffect(fourier=weekly, prefix="weekly")
])
```

**Use case**: Capture both marketing effects AND temporal patterns (trends, seasonality)

### Pattern 5: Custom Hierarchical Priors - FOR REGIONAL DATA

```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, NoSaturation
from pymc_extras.prior import Prior, LogNormalPrior

# Hierarchical saturation with country/region structure
saturation = NoSaturation(
    priors={
        "beta": LogNormalPrior(
            mean=Prior("Normal", mu=1, sigma=2, dims="country"),
            std=Prior("Normal", mu=1, sigma=2, dims="region")
        )
    }
)

# Hierarchical adstock across all dimensions
adstock = GeometricAdstock(l_max=6).set_dims_for_all_priors(
    ('country', 'region', 'product_type', 'channel')
)

mmm = MMM(
    date_column="date_week",
    target_column="y",
    channel_columns=["tv", "digital", "radio"],
    adstock=adstock,
    saturation=saturation,
    dims=("country", "region", "product_type")
)
```

**Use case**: Complex hierarchical structure where parameters vary across multiple dimensions (multi-region data)

## Workflow: From Model Building to Inference

### Step 1: Build the Model

**Single time series (no dims):**
```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation

mmm = MMM(
    date_column="date_week",
    channel_columns=["tv", "digital", "radio"],
    adstock=GeometricAdstock(l_max=8),
    saturation=LogisticSaturation()
)
mmm.build_model(X=X, y=y)
```

**Panel / multi-region data (with dims):**
```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation

mmm = MMM(
    date_column="date_week",
    target_column="y",
    channel_columns=["tv", "digital", "radio"],
    dims=<EXTRA_DIMS>,
    adstock=GeometricAdstock(l_max=8),
    saturation=LogisticSaturation()
)
X = df.drop(columns=["y"])
y = df["y"]
mmm.build_model(X=X, y=y)  # Both X and y required
```

### Step 2: Visualize Model Structure (Optional)

```python
# Visualize the graphical model
mmm.model.to_graphviz()
```

**Use case**: Understand model structure, debug complex models

### Step 3: Prior Predictive Checks

```python
# Sample from prior predictive distribution
prior_pred = mmm.sample_prior_predictive(
    X=X,
    samples=1000,
    random_seed=None  # Set for reproducibility
)
```

**Use case**: Validate that priors produce reasonable predictions before fitting

### Step 4: Fit the Model

```python
sample_kwargs = {
    "tune": 800,
    "draws": 200,
    "chains": 2,
    "target_accept": 0.84
}

mmm.fit(X=X, y=y, **sample_kwargs)
```

### Step 5: Posterior Predictive Checks

```python
# Sample from posterior predictive distribution
posterior_pred = mmm.sample_posterior_predictive(
    X_pred=X_test,
    random_seed=None  # Set for reproducibility
)
```

### Step 6: Original Scale Contribution Variables

`build_mmm_model()` automatically calls `mmm.add_original_scale_contribution_variable(var=[...])` which registers `*_original_scale` pm.Deterministic variables in the model graph. After fitting, the trace will contain variables like `channel_contribution_original_scale`, `intercept_contribution_original_scale`, etc. These are required for `mmm.plot.*` and `mmm.summary.*` to return results in original (unscaled) units.

If calling `mmm.build_model()` directly instead of `build_mmm_model()`, you must also call:
```python
mmm.add_original_scale_contribution_variable(
    var=["channel_contribution", "intercept_contribution", "y"]
    # Also add "control_contribution" if control_columns are set
    # Also add "yearly_seasonality_contribution" if yearly_seasonality is set
)
```

## Data Requirements

### Required Columns

```python
data = pd.DataFrame({
    "date_week": [...],      # Time index
    "y": [...],              # Target variable (revenue, installs, etc.)
    "tv": [...],             # Channel 1 spend
    "digital": [...],        # Channel 2 spend
    "radio": [...]           # Channel 3 spend
})
```

### With Dimensions

```python
data = pd.DataFrame({
    "date_week": [...],
    "y": [...],
    "tv": [...],
    "digital": [...],
    "radio": [...],
    "country": [...],        # Dimension 1
    "region": [...],         # Dimension 2
    "product_type": [...]    # Dimension 3
})
```

## Advanced Prior Specification

### Using Custom Prior Classes

```python
from pymc_extras.prior import Prior, LogNormalPrior, MaskedPrior

# LogNormal prior with hierarchical mean/std
beta_prior = LogNormalPrior(
    mean=Prior("Normal", mu=1, sigma=2, dims="country"),
    std=Prior("Normal", mu=1, sigma=2, dims="region")
)

# Masked prior (apply prior to subset of dimensions)
masked_prior = MaskedPrior(
    prior=Prior("HalfNormal", sigma=1),
    mask=[True, False, True, False]  # Apply to channels 0 and 2 only
)
```

### Setting Dimensions for All Priors

```python
# Apply dimensions to ALL priors in a component
adstock = GeometricAdstock(l_max=6).set_dims_for_all_priors(
    ('country', 'region', 'product_type', 'channel')
)
```

**Key insight**: This method broadcasts dimension structure across all parameters in the component.

## Performance Considerations

### Sampling Performance

**Warning**: "As the model grows in size (both in parameters and data), sampling can start to take longer."

**Recommendations**:
1. Start with small models and add complexity incrementally
2. Use fewer chains during development (e.g., `chains=2`)
3. Reduce draws for exploration (e.g., `draws=200`)
4. Use `target_accept=0.84` for better convergence with complex models
5. Consider efficient sampling techniques for production models

### Model Complexity Trade-offs

**Simple models**:
- Faster sampling
- Easier to diagnose
- Less flexible

**Complex models**:
- Slower sampling
- More parameters to diagnose
- Greater flexibility
- Risk of overfitting

**Recommended workflow**: Start simple, add complexity only when justified by data.

## Common Use Cases

### Use Case 1: Standard MMM

**Scenario**: Basic marketing mix modeling with carryover and saturation

**Solution**: Pattern 2 (Standard MMM with Transformations)

### Use Case 2: Multi-Market MMM

**Scenario**: Model marketing effects across multiple countries/regions

**Solution**: Pattern 3 (Multidimensional Hierarchical Model)

### Use Case 3: MMM with Strong Seasonality

**Scenario**: Marketing effects + strong weekly/yearly patterns

**Solution**: Pattern 4 (GAM with Temporal Components)

### Use Case 4: Complex Hierarchical Structure

**Scenario**: Different saturation curves per country, different adstock per product

**Solution**: Pattern 5 (Custom Hierarchical Priors)

### Use Case 5: Custom Bayesian Model

**Scenario**: Need full control over model specification beyond MMM

**Solution**: Extend MMM class, add custom effects via `mu_effects`

## Best Practices

### 1. Start Simple

Begin with basic models before adding complexity:
```python
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation

# Start here (single region)
mmm = MMM(
    date_column="date_week",
    channel_columns=["tv", "digital"],
    adstock=GeometricAdstock(l_max=4),
    saturation=LogisticSaturation()
)
mmm.fit(X=X, y=y)

# Add complexity only if needed:
# - Add more channels
# - Increase l_max
# - Switch to MMM if you have regional data
# - Add temporal components
```

### 2. Always Check Priors

```python
# Sample and visualize prior predictive distribution
prior_pred = mmm.sample_prior_predictive(X=X, samples=1000)

# Check if priors are reasonable
import matplotlib.pyplot as plt
plt.hist(prior_pred.prior_predictive["y"].values.flatten(), bins=50)
plt.axvline(y.mean(), color='red', label='Observed mean')
plt.legend()
plt.show()
```

### 3. Use Visualization for Debugging

```python
# Visualize model graph to understand structure
mmm.model.to_graphviz()

# Check for unexpected dependencies or missing connections
```

### 4. Incremental Dimension Addition (Multidimensional MMM)

```python
from pymc_marketing.mmm.multidimensional import MMM

# Add dimensions one at a time
mmm_v1 = MMM(..., dims=("country",))  # Start with 1 dimension
mmm_v2 = MMM(..., dims=("country", "region"))  # Add 2nd
mmm_v3 = MMM(..., dims=("country", "region", "product"))  # Add 3rd
```

### 5. Validate with Posterior Predictive Checks

```python
# Always check if model fits observed data
posterior_pred = mmm.sample_posterior_predictive(X_pred=X)

# Compare predictions to observations
plt.scatter(y, posterior_pred.posterior_predictive["y"].mean(dim=["chain", "draw"]))
plt.plot([y.min(), y.max()], [y.min(), y.max()], 'r--')
plt.xlabel("Observed")
plt.ylabel("Predicted")
plt.show()
```

## Common Pitfalls

### Pitfall 1: Too Many Dimensions Too Quickly (Multidimensional MMM)

**Bad**:
```python
mmm = MMM(..., dims=("country", "region", "product", "segment", "channel_type"))
# 5 dimensions immediately = slow sampling, convergence issues
```

**Good**:
```python
mmm = MMM(..., dims=("country",))  # Start with 1
# Validate, then add more if needed
```

### Pitfall 2: Forgetting to Build Model

**Bad**:
```python
mmm = MMM(...)
mmm.fit(X=X, y=y)  # Will fail - model not built
```

**Good**:
```python
mmm = MMM(...)
mmm.build_model(X=X, y=y)  # Build first
mmm.fit(X=X, y=y)  # Then fit
```

### Pitfall 3: Unrealistic Priors

**Bad**:
```python
# Prior allows negative revenue or unrealistically large values
priors = {"intercept": Prior("Normal", mu=0, sigma=10000)}
```

**Good**:
```python
# Check prior predictive, adjust if needed
prior_pred = mmm.sample_prior_predictive(X=X, samples=1000)
# Ensure prior predictions are in reasonable range
```

### Pitfall 4: Ignoring Sampling Warnings

**Bad**:
```python
mmm.fit(X=X, y=y)
# Ignores "divergences detected" warnings
```

**Good**:
```python
mmm.fit(X=X, y=y, target_accept=0.9)  # Increase target_accept
# Or reparameterize model, adjust priors
```

## When to Use Which Pattern

| Scenario | Pattern | Key Features |
|----------|---------|--------------|
| Baseline/testing | Pattern 1 (Linear) | No transformations, fast |
| Standard MMM | Pattern 2 (Standard) | Adstock + saturation |
| Multi-market | Pattern 3 (Hierarchical) | Country/region dimensions |
| Strong seasonality | Pattern 4 (GAM) | Temporal components |
| Complex structure | Pattern 5 (Custom priors) | Full hierarchical control |

## Summary

PyMC-Marketing's GAM capabilities enable:

1. **Flexible progression** from simple linear models to complex hierarchical GAMs
2. **Composable architecture** with mix-and-match components
3. **Automatic broadcasting** across dimensions
4. **Rich temporal modeling** with trends and seasonality
5. **Full Bayesian inference** with prior/posterior predictive checks

**Key principle**: Start simple, add complexity incrementally, always validate with prior/posterior checks.

## mmm_lib Function Reference

All mmm_lib functions print their return keys with `verbose=True` (default). **Always use the EXACT key names from the output - never guess or abbreviate.**

### check_prior_predictive_coverage(mmm, y, hdi_prob=0.95)

Checks if observed data falls within prior predictive HDI. Returns coverage in ORIGINAL scale.

**Return keys:**
```python
coverage = check_prior_predictive_coverage(mmm, y)
coverage['coverage_percent']  # float: % of points within HDI (aim for 50-100%)
coverage['hdi_lower_mean']    # float: lower HDI bound (original scale) - NOT 'hdi_low'!
coverage['hdi_upper_mean']    # float: upper HDI bound (original scale) - NOT 'hdi_high'!
coverage['observed_mean']     # float: mean of y
coverage['observed_min']      # float
coverage['observed_max']      # float
```

### check_convergence(mmm)

Validates MCMC convergence: R-hat < 1.1, ESS > 200, divergences < 1%.

**Return keys:**
```python
diagnostics = check_convergence(mmm)
diagnostics['converged']       # bool: True if all checks pass
diagnostics['max_rhat']        # float: should be < 1.1
diagnostics['min_ess_bulk']    # float: bulk ESS, should be > 200
diagnostics['min_ess_tail']    # float: tail ESS
diagnostics['n_divergences']   # int: number of divergent transitions
diagnostics['divergence_pct']  # float: divergences as %
diagnostics['problem_vars_rhat']  # list: vars with R-hat > 1.1
diagnostics['low_ess_vars']    # list: vars with ESS < 200
```

### ROAS and Contributions (pymc-marketing 0.18.0 built-in API)

**Use `mmm.summary.roas()` instead of custom ROAS functions:**

```python
# All-time ROAS with HDI
roas = mmm.summary.roas(frequency="all_time")

# Monthly/quarterly breakdown
roas_monthly = mmm.summary.roas(frequency="monthly")

# Channel contributions
contrib = mmm.summary.contributions(component="channel")

# Sensitivity / marginal ROAS
results = mmm.sensitivity.run_sweep(
    var_input="channel_data", sweep_values=np.linspace(0.5, 1.5, 11),
    var_names="channel_contribution", sweep_type="multiplicative",
)
marginal = mmm.sensitivity.compute_marginal_effects(results)
```

### plot_prior_predictive(mmm, original_scale=True)

**IMPORTANT:** Always use `original_scale=True` (the default) so the prior predictive and observed data are on the same scale. Using `original_scale=False` shows data in normalized [0,1] space.

## References

- PyMC-Marketing GAM Options Documentation: https://www.pymc-marketing.io/en/latest/notebooks/mmm/mmm_gam_options.html
- PyMC-Marketing API Documentation: https://www.pymc-marketing.io/
