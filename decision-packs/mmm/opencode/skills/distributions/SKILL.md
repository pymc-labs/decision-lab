---
name: PyMC Distributions
description: Expert on PyMC probability distributions including continuous (Normal, Beta, Gamma), discrete (Poisson, Binomial), multivariate (MvNormal, Dirichlet), mixture, and timeseries distributions. Use when encountering distribution errors, parameter issues, or migrating PyMC3 distribution code.
---

# PyMC Distributions Skill

You are an expert in PyMC probability distributions, helping migrate notebook code to work with the current stable PyMC version.

## Distribution Categories

### Continuous Distributions
Common distributions include:
- `pm.Normal(mu, sigma)` - Gaussian/normal distribution
- `pm.Beta(alpha, beta)` - Beta distribution (0, 1)
- `pm.Gamma(alpha, beta)` - Gamma distribution
- `pm.Exponential(lam)` - Exponential distribution
- `pm.StudentT(nu, mu, sigma)` - Student's t-distribution
- `pm.Uniform(lower, upper)` - Uniform distribution
- `pm.HalfNormal(sigma)` - Half-normal (positive only)
- `pm.LogNormal(mu, sigma)` - Log-normal distribution
- `pm.Cauchy(alpha, beta)` - Cauchy distribution
- `pm.Laplace(mu, b)` - Laplace distribution
- `pm.SkewNormal(mu, sigma, alpha)` - Skewed normal

### Discrete Distributions
- `pm.Bernoulli(p)` - Binary outcomes
- `pm.Binomial(n, p)` - Count of successes
- `pm.Poisson(mu)` - Count data
- `pm.Categorical(p)` - Categorical outcomes
- `pm.NegativeBinomial(mu, alpha)` - Overdispersed count data
- `pm.DiscreteUniform(lower, upper)` - Discrete uniform

### Multivariate Distributions
- `pm.MvNormal(mu, cov)` - Multivariate normal
- `pm.Dirichlet(a)` - Dirichlet distribution
- `pm.Wishart(nu, V)` - Wishart distribution
- `pm.LKJCorr(n, eta)` - LKJ correlation prior
- `pm.LKJCholeskyCov(n, eta, sd_dist)` - Cholesky parameterization

### Mixture Distributions
- `pm.Mixture(w, comp_dists)` - General mixture
- `pm.NormalMixture(w, mu, sigma)` - Gaussian mixture
- `pm.ZeroInflatedPoisson(psi, mu)` - Zero-inflated count
- `pm.ZeroInflatedBinomial(psi, n, p)` - Zero-inflated binomial
- `pm.HurdleGamma(psi, alpha, beta)` - Hurdle model

### Timeseries Distributions
- `pm.AR(rho, sigma)` - Autoregressive
- `pm.GaussianRandomWalk(mu, sigma)` - Random walk
- `pm.GARCH11(omega, alpha_1, beta_1)` - GARCH model
- `pm.EulerMaruyama(dt, sde_fn, sde_pars)` - SDE approximation

## Special Features

### Truncated/Censored Distributions
```python
# Truncated distribution
pm.Truncated("x", pm.Normal.dist(mu=0, sigma=1), lower=0, upper=10)

# Censored distribution
pm.Censored("y", pm.Normal.dist(mu=0, sigma=1), lower=None, upper=5)
```

### Custom Distributions
```python
# Define custom distribution
def custom_logp(value, mu):
    return -0.5 * ((value - mu) ** 2)

pm.CustomDist("custom", mu, logp=custom_logp, observed=data)
```

### Simulator Integration
```python
pm.Simulator("sim", fn=simulator_function, params=[param1, param2], observed=data)
```

## Common Parameters

Most distributions accept:
- `name` - Variable name (required for RVs in model)
- Distribution-specific parameters (mu, sigma, alpha, etc.)
- `shape` - Shape of the random variable
- `dims` - Named dimensions for the variable
- `observed` - Observed data (makes it a likelihood)
- `transform` - Transformation for parameter constraints

## Key Methods

```python
# Log-probability
dist.logp(value)

# Log cumulative distribution
dist.logcdf(value)

# Inverse CDF (quantile function)
dist.icdf(q)

# Random sampling (outside of pm.sample)
dist.random(size=100, rng=rng)
```

## Common Migration Issues

### PyMC3 → latest PyMC version

1. **Import changes**
```python
# Old (PyMC3)
import pymc3 as pm

# New (latest PyMC version)
import pymc as pm
```

2. **Distribution parameters**
```python
# Some distributions have parameter renames
# Check documentation for specific changes

# Old: sd parameter
pm.Normal('x', mu=0, sd=1)  # PyMC3

# New: sigma parameter
pm.Normal('x', mu=0, sigma=1)  # latest PyMC version
```

3. **Shape specification**
```python
# Shape handling is more explicit in latest PyMC version
# Use dims and coords for cleaner shape management

with pm.Model(coords={"subject": subjects, "time": times}) as model:
    x = pm.Normal("x", mu=0, sigma=1, dims=("subject", "time"))
```

4. **Distribution creation**
```python
# Creating distributions without adding to model
# Old
dist = pm.Normal.dist(mu=0, sd=1)

# New
dist = pm.Normal.dist(mu=0, sigma=1)
```

## Best Practices

1. **Use informative priors** - Weakly informative priors often work better than flat priors
2. **Named dimensions** - Use `dims` and `coords` for better shape management
3. **Vectorization** - Leverage broadcasting for efficient computation
4. **Prior predictive checks** - Always check priors make sense before sampling
5. **Transformations** - Let PyMC handle constraints automatically when possible

## Troubleshooting

### Shape mismatches
- Check that observed data shape matches distribution shape
- Verify broadcasting rules are applied correctly
- Use `pm.model_to_graphviz(model)` to visualize shapes

### Invalid parameter values
- Ensure positive constraints (use HalfNormal, Exponential, etc.)
- Check bounds for bounded distributions
- Verify probability parameters are in (0, 1)

### Sampling issues
- Some distributions may need specific step samplers
- Consider reparameterization for better geometry
- Use `pm.find_MAP()` to check if model is well-specified

## Example Usage

```python
import pymc as pm
import numpy as np

# Generate data
true_mu = 5
true_sigma = 2
data = np.random.normal(true_mu, true_sigma, size=100)

# Build model
with pm.Model() as model:
    # Priors
    mu = pm.Normal("mu", mu=0, sigma=10)
    sigma = pm.HalfNormal("sigma", sigma=5)

    # Likelihood
    y = pm.Normal("y", mu=mu, sigma=sigma, observed=data)

    # Sample
    trace = pm.sample(1000, tune=1000)
```

## When to Use This Skill

- Converting distribution specifications from old notebooks
- Fixing distribution parameter errors
- Implementing custom distributions
- Troubleshooting likelihood specifications
- Choosing appropriate priors
- Handling mixture models or zero-inflation
