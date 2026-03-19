---
name: PyMC Data Handling
description: Expert on PyMC data management including pm.Data and pm.Minibatch for handling datasets, updating data containers, and mini-batch training. Use for data container errors or dataset handling issues.
---

# PyMC Data Handling Skill

You are an expert in PyMC data management, helping migrate notebook code to work with the current stable PyMC version.

## Core Data Functions

### pm.Data - Register Data Variables

`pm.Data` is the main container for registering data within a PyMC model. It enables data to be updated after model creation, which is essential for predictions and cross-validation.

```python
import pymc as pm
import numpy as np

# Basic usage
with pm.Model() as model:
    X = pm.Data("X", X_train)
    y = pm.Data("y", y_train)

    # Build model using data
    beta = pm.Normal("beta", mu=0, sigma=1)
    mu = beta * X
    likelihood = pm.Normal("likelihood", mu=mu, sigma=1, observed=y)
```

### pm.Data with Named Dimensions

```python
coords = {
    "obs": np.arange(100),
    "feature": ["age", "income", "education"]
}

with pm.Model(coords=coords) as model:
    # Data with dimensions
    X = pm.Data("X", X_train, dims=("obs", "feature"))
    y = pm.Data("y", y_train, dims="obs")

    # Model
    beta = pm.Normal("beta", mu=0, sigma=1, dims="feature")
    mu = pm.math.dot(X, beta)
    likelihood = pm.Normal("likelihood", mu=mu, sigma=1, observed=y, dims="obs")
```

## Updating Data with set_data

After fitting a model, you can update data containers for predictions:

```python
# Fit model on training data
with model:
    trace = pm.sample(1000)

# Update data for test set predictions
with model:
    pm.set_data({"X": X_test, "y": y_test})

    # Generate predictions
    posterior_predictive = pm.sample_posterior_predictive(trace)
```

### Multiple Data Updates

```python
# Update multiple data containers
with model:
    pm.set_data({
        "X": X_new,
        "y": y_new,
        "weights": new_weights
    })
```

## pm.Minibatch - Mini-batch Training

`pm.Minibatch` enables random sampling from data for stochastic training approaches.

```python
# Large dataset mini-batching
with pm.Model() as model:
    # Create mini-batch containers
    X_batch = pm.Minibatch(X_train, batch_size=32)
    y_batch = pm.Minibatch(y_train, batch_size=32)

    # Build model
    beta = pm.Normal("beta", mu=0, sigma=1)
    mu = beta * X_batch

    # Likelihood with mini-batch
    likelihood = pm.Normal("likelihood", mu=mu, sigma=1, observed=y_batch)

    # Sample with mini-batches
    trace = pm.sample(1000)
```

### Multiple Variables in Minibatch

```python
# Synchronized mini-batching across variables
with pm.Model() as model:
    X_batch, y_batch = pm.Minibatch(X_train, y_train, batch_size=64)

    # Both X and y will have same random indices
    # ensuring alignment
```

### Minibatch with Scaling

When using mini-batches, you typically need to scale the likelihood:

```python
with pm.Model() as model:
    batch_size = 32
    total_size = len(X_train)

    X_batch = pm.Minibatch(X_train, batch_size=batch_size)
    y_batch = pm.Minibatch(y_train, batch_size=batch_size)

    beta = pm.Normal("beta", mu=0, sigma=1)
    mu = beta * X_batch

    # Scale likelihood by total_size / batch_size
    likelihood = pm.Normal(
        "likelihood",
        mu=mu,
        sigma=1,
        observed=y_batch,
        total_size=total_size
    )
```

## pm.get_data - Access Package Data

Retrieves bundled package data files:

```python
# Load example datasets
data_file = pm.get_data("dataset.csv")
df = pd.read_csv(data_file)
```

## Common Patterns

### Train/Test Split Workflow

```python
# Split data
X_train, X_test, y_train, y_test = train_test_split(X, y)

# Create model with training data
coords = {"obs": np.arange(len(X_train)), "features": feature_names}
with pm.Model(coords=coords) as model:
    X_data = pm.Data("X", X_train, dims=("obs", "features"))
    y_data = pm.Data("y", y_train, dims="obs")

    # Model specification
    beta = pm.Normal("beta", 0, 1, dims="features")
    sigma = pm.HalfNormal("sigma", 1)
    mu = pm.math.dot(X_data, beta)
    likelihood = pm.Normal("y_obs", mu, sigma, observed=y_data, dims="obs")

    # Fit
    trace = pm.sample(1000)

# Predict on test set
with model:
    # Update coordinates for test set
    coords["obs"] = np.arange(len(X_test))
    pm.set_data({"X": X_test})

    # No observed data needed for prediction
    pm.set_data({"y": np.zeros(len(X_test))})  # Dummy values

    # Sample posterior predictive
    ppc = pm.sample_posterior_predictive(trace, var_names=["y_obs"])
```

### Cross-Validation

```python
from sklearn.model_selection import KFold

kf = KFold(n_splits=5)
scores = []

for train_idx, val_idx in kf.split(X):
    X_train, X_val = X[train_idx], X[val_idx]
    y_train, y_val = y[train_idx], y[val_idx]

    # First fold: create model
    if not hasattr(locals(), 'model'):
        with pm.Model() as model:
            X_data = pm.Data("X", X_train)
            y_data = pm.Data("y", y_train)

            beta = pm.Normal("beta", 0, 1)
            sigma = pm.HalfNormal("sigma", 1)
            mu = beta * X_data
            likelihood = pm.Normal("y_obs", mu, sigma, observed=y_data)

    # Update data for current fold
    with model:
        pm.set_data({"X": X_train, "y": y_train})
        trace = pm.sample(1000, tune=500)

        # Validate
        pm.set_data({"X": X_val, "y": y_val})
        ppc = pm.sample_posterior_predictive(trace)

    # Score predictions
    score = compute_score(ppc, y_val)
    scores.append(score)
```

## Common Migration Issues

### PyMC3 → latest PyMC version

1. **pm.Data replaces shared variables**
```python
# Old (PyMC3 with Theano)
import theano.shared
X_shared = theano.shared(X_train)

with pm.Model() as model:
    likelihood = pm.Normal("y", mu=X_shared, observed=y_train)

# Later update
X_shared.set_value(X_test)

# New (latest PyMC version)
with pm.Model() as model:
    X_data = pm.Data("X", X_train)
    likelihood = pm.Normal("y", mu=X_data, observed=y)

# Later update
with model:
    pm.set_data({"X": X_test})
```

2. **pm.MutableData is deprecated**
```python
# Old
X = pm.MutableData("X", X_train)

# New
X = pm.Data("X", X_train)
```

3. **Minibatch usage has changed**
```python
# Check current PyMC version for exact API
# Basic pattern remains similar
X_batch = pm.Minibatch(X_train, batch_size=32)
```

## Best Practices

1. **Always use pm.Data for data that might change** - Even if you don't plan to update it initially
2. **Named dimensions improve clarity** - Use dims parameter with pm.Data
3. **Set total_size with Minibatch** - Required for correct likelihood scaling
4. **Coordinate updates** - When changing data shape, update coords too
5. **Dummy observed values for prediction** - When using set_data for prediction, you may need placeholder values

## Troubleshooting

### Shape mismatches after set_data
- Ensure new data has compatible shape
- Update coords if number of observations changes
- Check that feature dimensions match

### Minibatch sampling issues
- Verify batch_size divides total_size reasonably
- Ensure total_size parameter is set correctly
- Check that all minibatch variables have same batch_size

### Data not updating
- Ensure you're inside model context when calling set_data
- Verify data container names match exactly
- Check that model reference is correct

## Example Usage

```python
import pymc as pm
import numpy as np
from sklearn.model_selection import train_test_split

# Generate data
np.random.seed(42)
n = 1000
X = np.random.randn(n, 2)
true_beta = np.array([1.5, -2.0])
y = X @ true_beta + np.random.randn(n) * 0.5

# Split data
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

# Build model with data containers
coords = {
    "obs": np.arange(len(X_train)),
    "features": ["x1", "x2"]
}

with pm.Model(coords=coords) as model:
    # Data containers
    X_data = pm.Data("X", X_train, dims=("obs", "features"))
    y_data = pm.Data("y", y_train, dims="obs")

    # Priors
    beta = pm.Normal("beta", mu=0, sigma=10, dims="features")
    sigma = pm.HalfNormal("sigma", sigma=1)

    # Likelihood
    mu = pm.math.dot(X_data, beta)
    likelihood = pm.Normal("likelihood", mu=mu, sigma=sigma, observed=y_data, dims="obs")

    # Sample
    trace = pm.sample(1000, tune=1000)

# Predict on test set
with model:
    # Update coordinates
    model.add_coords({"obs": np.arange(len(X_test))})

    # Update data
    pm.set_data({"X": X_test})

    # Posterior predictive
    ppc = pm.sample_posterior_predictive(trace, var_names=["likelihood"])

print(f"Test predictions shape: {ppc.posterior_predictive['likelihood'].shape}")
```

## When to Use This Skill

- Setting up data containers in models
- Implementing train/test workflows
- Converting theano.shared to pm.Data
- Implementing cross-validation
- Working with mini-batch training
- Updating data for predictions
- Fixing data-related shape errors
