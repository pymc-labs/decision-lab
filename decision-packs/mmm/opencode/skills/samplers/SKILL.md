---
name: PyMC Samplers
description: Expert on PyMC MCMC sampling methods including NUTS, HMC, Metropolis variants, and pm.sample() API. Use for sampling errors, convergence issues, sampler configuration, or trace-related problems.
---

# PyMC Samplers Skill

You are an expert in PyMC sampling methods, helping migrate notebook code to work with the current stable PyMC version.

## Core Sampling Functions

### pm.sample() - Main Sampling Function

The primary function for MCMC sampling:

```python
import pymc as pm

with pm.Model() as model:
    # Define model...

    # Basic sampling
    trace = pm.sample(
        draws=1000,           # Number of samples per chain
        tune=1000,            # Number of tuning steps
        chains=4,             # Number of chains
        cores=4,              # Parallel chains
        random_seed=None  # Set for reproducibility        # Reproducibility
    )
```

### Full pm.sample() Parameters

```python
trace = pm.sample(
    draws=1000,                    # Samples to draw
    tune=1000,                     # Tuning/burn-in steps
    chains=4,                      # Number of chains
    cores=None,                    # CPU cores (None = all available)
    random_seed=None,              # Random seed for reproducibility
    step=None,                     # Custom step sampler(s)
    initvals=None,                 # Initial values
    init="auto",                   # Initialization: "auto", "jitter+adapt_diag", etc.
    n_init=200000,                 # Samples for initialization
    progressbar=True,              # Show progress bar
    return_inferencedata=True,     # Return ArviZ InferenceData
    idata_kwargs=None,             # InferenceData creation kwargs
    compute_convergence_checks=True, # Compute Rhat, ESS
    discard_tuned_samples=True,    # Exclude tuning samples
    target_accept=0.8,             # For NUTS: target acceptance rate
    callback=None,                 # Callback function per draw
)
```

## Sampling Step Methods

### NUTS (No-U-Turn Sampler)

Default and recommended for most models with continuous variables:

```python
# Automatic (default)
trace = pm.sample(1000)

# Explicit NUTS configuration
trace = pm.sample(
    1000,
    target_accept=0.95,  # Higher = slower but more accurate
    max_treedepth=10     # Maximum tree depth
)

# Manual NUTS setup
from pymc.step_methods import NUTS

with model:
    step = NUTS()
    trace = pm.sample(1000, step=step)
```

### Metropolis Samplers

For simpler models or discrete variables:

```python
from pymc.step_methods import Metropolis

with model:
    # Basic Metropolis
    step = Metropolis()
    trace = pm.sample(5000, step=step)

    # With specific proposal distribution
    step = Metropolis(proposal_dist=pm.NormalProposal)
```

### BinaryMetropolis

Optimized for binary variables:

```python
from pymc.step_methods import BinaryMetropolis

with model:
    x = pm.Bernoulli("x", p=0.5)
    step = BinaryMetropolis([x])
    trace = pm.sample(5000, step=step)
```

### Slice Sampler

For unimodal distributions:

```python
from pymc.step_methods import Slice

with model:
    step = Slice()
    trace = pm.sample(5000, step=step)
```

### HamiltonianMC

Standard Hamiltonian Monte Carlo:

```python
from pymc.step_methods import HamiltonianMC

with model:
    step = HamiltonianMC()
    trace = pm.sample(1000, step=step)
```

### CompoundStep - Multiple Samplers

Combine different samplers for different variables:

```python
from pymc.step_methods import NUTS, BinaryMetropolis, CompoundStep

with model:
    continuous_vars = [mu, sigma]
    discrete_vars = [z]

    # NUTS for continuous, Metropolis for discrete
    step1 = NUTS(vars=continuous_vars)
    step2 = BinaryMetropolis(vars=discrete_vars)

    # Compound step
    step = CompoundStep([step1, step2])
    trace = pm.sample(1000, step=step)
```

## Prior and Posterior Predictive Sampling

### Prior Predictive Checks

Sample from the prior before seeing data:

```python
with model:
    # Sample from prior
    prior_predictive = pm.sample_prior_predictive(
        samples=500,
        random_seed=None  # Set for reproducibility
    )

# Inspect prior predictions
import arviz as az
az.plot_ppc(prior_predictive, group="prior")
```

### Posterior Predictive Checks

Sample predictions after fitting:

```python
with model:
    # Fit model
    trace = pm.sample(1000)

    # Generate posterior predictions
    posterior_predictive = pm.sample_posterior_predictive(
        trace,
        var_names=None,        # Variables to sample (None = all)
        random_seed=None  # Set for reproducibility,
        progressbar=True
    )

# Check model fit
az.plot_ppc(posterior_predictive)
```

### Out-of-Sample Predictions

```python
# Update data for new predictions
with model:
    pm.set_data({"X": X_test})

    # Sample predictions
    predictions = pm.sample_posterior_predictive(
        trace,
        var_names=["y"]  # Only prediction variable
    )
```

## Initialization Methods

### Initialization Strategies

```python
# Auto (default) - usually "jitter+adapt_diag"
trace = pm.sample(1000, init="auto")

# Jitter around prior mean + adapt diagonal mass matrix
trace = pm.sample(1000, init="jitter+adapt_diag")

# Jitter around prior mean + full adaptation
trace = pm.sample(1000, init="jitter+adapt_full")

# ADVI initialization
trace = pm.sample(1000, init="adapt_diag")

# Maximum a posteriori (MAP) initialization
trace = pm.sample(1000, init="adapt_diag_grad")
```

### Custom Initial Values

```python
# Specify starting values
initvals = {
    "mu": 0.5,
    "sigma": 1.0
}

trace = pm.sample(1000, initvals=initvals)
```

## NUTS Initialization Helper

```python
# Initialize NUTS sampler with specific settings
from pymc import init_nuts

with model:
    init_vals, step = init_nuts(
        init="auto",
        chains=4,
        random_seed=None  # Set for reproducibility,
        progressbar=True
    )

    trace = pm.sample(1000, step=step, initvals=init_vals)
```

## Drawing Single Samples

```python
# Draw single random sample from variable
with model:
    sample = pm.draw(mu, draws=1)

    # Multiple draws
    samples = pm.draw(mu, draws=100)

    # Draw multiple variables
    sample_dict = pm.draw([mu, sigma], draws=100)
```

## Computing Deterministics

After sampling, compute deterministic quantities:

```python
with model:
    trace = pm.sample(1000)

    # Compute deterministic variables from trace
    trace = pm.compute_deterministics(trace)
```

## JAX-Based Samplers

### BlackJAX NUTS

```python
from pymc.sampling.jax import sample_blackjax_nuts

with model:
    trace = sample_blackjax_nuts(
        draws=1000,
        tune=1000,
        chains=4,
        target_accept=0.8
    )
```

### NumPyro NUTS

```python
from pymc.sampling.jax import sample_numpyro_nuts

with model:
    trace = sample_numpyro_nuts(
        draws=1000,
        tune=1000,
        chains=4,
        target_accept=0.8
    )
```

## Common Migration Issues

### PyMC3 → latest PyMC version

1. **Return type changes**
```python
# Old (PyMC3) - returns MultiTrace
trace = pm.sample(1000)

# New (latest PyMC version) - returns InferenceData by default
idata = pm.sample(1000, return_inferencedata=True)  # default

# Access posterior samples
idata.posterior

# Get old-style trace if needed
trace = pm.sample(1000, return_inferencedata=False)
```

2. **Step method imports**
```python
# Old
from pymc3.step_methods import NUTS, Metropolis

# New
from pymc.step_methods import NUTS, Metropolis
```

3. **Tuning parameter**
```python
# Old: some versions used 'n_tune'
trace = pm.sample(draws=1000, n_tune=500)

# New: use 'tune'
trace = pm.sample(draws=1000, tune=500)
```

4. **Initialization**
```python
# Old: testval in variable definition
x = pm.Normal("x", mu=0, sigma=1, testval=0.5)

# New: use initvals in sample()
x = pm.Normal("x", mu=0, sigma=1)
trace = pm.sample(1000, initvals={"x": 0.5})
```

## Sampling Best Practices

1. **Use NUTS for continuous models** - It's efficient and robust
2. **Run multiple chains** - At least 4 chains to check convergence
3. **Check convergence** - Inspect Rhat (< 1.1) and ESS (> 200)
4. **Tune adequately** - Default 1000 steps usually sufficient
5. **Adjust target_accept if needed** - Increase if divergences occur
6. **Use random_seed** - For reproducibility
7. **Prior predictive checks** - Always check priors make sense
8. **Posterior predictive checks** - Validate model fit

## Troubleshooting Sampling Issues

### Divergences

```python
# Increase target acceptance rate
trace = pm.sample(1000, target_accept=0.95)

# Increase max tree depth
trace = pm.sample(1000, max_treedepth=15)

# Reparameterize model (non-centered → centered or vice versa)
```

### Slow Sampling

```python
# Use fewer chains on more cores
trace = pm.sample(1000, chains=2, cores=2)

# Try JAX backend
trace = sample_numpyro_nuts(1000)

# Reduce tuning steps if model is simple
trace = pm.sample(1000, tune=500)
```

### Poor Mixing

```python
# Increase tuning period
trace = pm.sample(1000, tune=2000)

# Try different initialization
trace = pm.sample(1000, init="adapt_diag")

# Reparameterize the model
# (e.g., non-centered parameterization for hierarchical models)
```

### High Rhat or Low ESS

```python
# Run longer chains
trace = pm.sample(5000, tune=2000)

# More chains
trace = pm.sample(1000, chains=8)

# Check model specification
# - Are priors appropriate?
# - Is model identified?
# - Are there correlations that need reparameterization?
```

## Example Usage

```python
import pymc as pm
import numpy as np
import arviz as az

# Generate data
np.random.seed(42)
true_mu = 3.0
true_sigma = 1.5
data = np.random.normal(true_mu, true_sigma, size=100)

# Build model
with pm.Model() as model:
    # Priors
    mu = pm.Normal("mu", mu=0, sigma=10)
    sigma = pm.HalfNormal("sigma", sigma=5)

    # Likelihood
    y = pm.Normal("y", mu=mu, sigma=sigma, observed=data)

    # Prior predictive check
    prior_pred = pm.sample_prior_predictive(samples=500)

    # Sample posterior
    trace = pm.sample(
        draws=1000,
        tune=1000,
        chains=4,
        cores=4,
        target_accept=0.9,
        random_seed=None  # Set for reproducibility
    )

    # Posterior predictive check
    post_pred = pm.sample_posterior_predictive(trace)

# Check convergence
print(az.summary(trace, var_names=["mu", "sigma"]))

# Visualize
az.plot_trace(trace, var_names=["mu", "sigma"])
az.plot_posterior(trace, var_names=["mu", "sigma"])
az.plot_ppc(post_pred)
```

## When to Use This Skill

- Configuring sampling parameters
- Fixing divergences or sampling issues
- Choosing appropriate step methods
- Converting PyMC3 sampling code
- Implementing prior/posterior predictive checks
- Troubleshooting convergence problems
- Optimizing sampling performance
- Working with mixed discrete/continuous models
