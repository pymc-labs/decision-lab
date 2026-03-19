"""
Model Building and Fitting Functions

This module contains all functions used for MMM model building, configuration,
validation, and fitting.

Functions are pure Python with no external tool dependencies.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from typing import Optional, Dict, Any, List, Callable
from collections import defaultdict
import time
import datetime
import warnings
import pickle
import inspect

# PyMC Marketing imports
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation
from pymc_marketing.mmm.multidimensional import MMM
from pymc_marketing.model_config import parse_model_config, ModelConfigError
from pymc_marketing.mmm.components.saturation import SaturationTransformation, LogisticSaturation
from pymc_marketing.mmm.components.adstock import AdstockTransformation, GeometricAdstock
import pymc_marketing.mmm.components.adstock as _adstock
import pymc_marketing.mmm.components.saturation as _saturation
from pymc_extras.prior import Prior

import arviz as az
import pytensor.tensor as pt

# Gather names of available adstock and saturation transformations
_adstock_transformations = [cls for _, cls in inspect.getmembers(_adstock, inspect.isclass)
                          if issubclass(cls, AdstockTransformation) and cls is not AdstockTransformation]
_saturation_transformations = [cls for _, cls in inspect.getmembers(_saturation, inspect.isclass)
                          if issubclass(cls, SaturationTransformation) and cls is not SaturationTransformation]

_adstock_transformation_names = [c.__name__ for c in _adstock_transformations]
_saturation_transformation_names = [c.__name__ for c in _saturation_transformations]

_adstock_module_name = 'pymc_marketing.mmm.components.adstock'
_saturation_module_name = 'pymc_marketing.mmm.components.saturation'


# =============================================================================
# MODEL CONFIGURATION FUNCTIONS
# =============================================================================

def create_mmm_config(
    date_column: str,
    channel_columns: List[str],
    y_column: str,
    control_columns: Optional[List[str]] = None,
    adstock: type[AdstockTransformation] | pt.TensorLike = GeometricAdstock,
    adstock_max_lag: int = 8,
    saturation: type[SaturationTransformation] | pt.TensorLike = LogisticSaturation,
    yearly_seasonality: Optional[int] = 2,
    adstock_type: str = "geometric",
    saturation_type: str = "logistic",
) -> Dict[str, Any]:
    """
    Create MMM configuration dictionary.

    Args:
        date_column: Name of date column
        channel_columns: List of media channel columns
        y_column: Target variable column
        control_columns: Control variable columns
        adstock: AdstockTransformation or pt.TensorLike
                  If pt.TensorLike, it's an already initialized transformation.
                  If of type AdstockTransformation, can be any of
                  pymc_marketing.mmm.components.adstock's transformations.
        adstock_max_lag: Maximum adstock lag (applied to all channels)
        saturation: SaturationTransformation or pt.TensorLike
                  If pt.TensorLike, it's an already initialized transformation.
                  If of type SaturationTransformation, can be any of
                  pymc_marketing.mmm.components.saturation's transformations.
        yearly_seasonality: Order of Fourier seasonality (None to disable)
        adstock_type: Type of adstock ("geometric")
        saturation_type: Type of saturation ("logistic")

    Returns:
        Configuration dictionary

    Example:
        >>> config = create_mmm_config(
        ...     date_column="date",
        ...     channel_columns=["tv", "digital", "radio"],
        ...     y_column="sales",
        ...     adstock_max_lag=8
        ... )
    """
    config = {
        "date_column": date_column,
        "channel_columns": channel_columns,
        "y_column": y_column,
        "control_columns": control_columns,
        "adstock": adstock,
        "adstock_max_lag": adstock_max_lag,
        "saturation": saturation,
        "yearly_seasonality": yearly_seasonality,
        "adstock_type": adstock_type,
        "saturation_type": saturation_type,
    }

    return config


def create_custom_priors(
    intercept: Optional[Dict] = None,
    beta_channel: Optional[Dict] = None,
    alpha: Optional[Dict] = None,
    lam: Optional[Dict] = None,
    sigma: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Create custom prior configuration for MMM.

    NOTE: For channel-specific hyperparameters, use numpy arrays in the kwargs.
    PyMC-Marketing does NOT support per-channel prior distributions (dict/list format).

    Args:
        intercept: Prior for intercept {"dist": "Normal", "kwargs": {"mu": 0, "sigma": 2}}
        beta_channel: Prior for channel coefficients
        alpha: Prior for adstock parameters
        lam: Prior for saturation parameters
        sigma: Prior for observation noise

    Returns:
        Model config dictionary for PyMC-Marketing

    Example (same prior for all channels):
        >>> priors = create_custom_priors(
        ...     beta_channel={"dist": "HalfNormal", "kwargs": {"sigma": 2}},
        ...     alpha={"dist": "Beta", "kwargs": {"alpha": 1, "beta": 3}}
        ... )

    Example (channel-specific hyperparameters with numpy arrays):
        >>> import numpy as np
        >>> from pymc_extras.prior import Prior
        >>>
        >>> # Different sigma per channel (order must match channel_columns)
        >>> beta_sigma = np.array([3.0, 1.0, 2.0])  # tv, digital, radio
        >>>
        >>> priors = {
        ...     "beta_channel": Prior("HalfNormal", sigma=beta_sigma),
        ...     "alpha": Prior("Beta", alpha=np.array([3.0, 1.0, 2.0]), beta=3.0),
        ... }
        >>> mmm = create_mmm_instance(
        ...     channel_columns=["tv", "digital", "radio"],
        ...     model_config=priors
        ... )

    Note: The numpy array approach is the ONLY way to have different hyperparameter
    values per channel in PyMC-Marketing. Dict/list formats are NOT supported.
    """
    model_config = {}

    if intercept:
        model_config["intercept"] = intercept

    if beta_channel:
        model_config["beta_channel"] = beta_channel

    if alpha:
        model_config["alpha"] = alpha

    if lam:
        model_config["lam"] = lam

    if sigma:
        model_config["sigma"] = sigma

    return model_config


def validate_custom_priors(model_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate custom priors using PyMC-Marketing's validation.

    Args:
        model_config: Model config with custom priors

    Returns:
        Validation result

    Example:
        >>> priors = {"beta_channel": {"dist": "HalfNormal", "kwargs": {"sigma": 2}}}
        >>> result = validate_custom_priors(priors)
    """
    try:
        parsed_config = parse_model_config(model_config)
        return {
            "valid": True,
            "parsed_config": parsed_config,
            "message": "Model configuration is valid"
        }
    except ModelConfigError as e:
        return {
            "valid": False,
            "error": str(e),
            "message": f"Validation error: {e}"
        }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
            "message": f"Unexpected error: {e}"
        }


# =============================================================================
# DATA PREPARATION FUNCTIONS
# =============================================================================

def prepare_mmm_data(
    df: pd.DataFrame,
    date_column: str,
    y_column: str,
    ensure_datetime: bool = True,
    ensure_numeric_y: bool = True,
) -> tuple:
    """
    Prepare data for MMM model fitting.

    Args:
        df: Input DataFrame
        date_column: Date column name
        y_column: Target variable column
        ensure_datetime: Convert date column to datetime
        ensure_numeric_y: Convert y to float

    Returns:
        Tuple of (X, y) where X is features, y is target

    Example:
        >>> X, y = prepare_mmm_data(df, "date", "sales")
    """
    df = df.copy()

    # Convert date column
    if ensure_datetime:
        df[date_column] = pd.to_datetime(df[date_column])

    # Prepare X (all columns except y)
    X = df.drop(y_column, axis=1)

    # Prepare y
    y = df[y_column]
    if ensure_numeric_y:
        y = y.astype(float)

    return X, y


def validate_mmm_data(
    X: pd.DataFrame,
    y: pd.Series,
    channel_columns: List[str],
    date_column: str,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Validate data for MMM model fitting.

    Args:
        X: Features DataFrame
        y: Target Series
        channel_columns: Channel column names
        date_column: Date column name
        verbose: Print validation results (default: True)

    Returns:
        Validation result dictionary

    Example:
        >>> result = validate_mmm_data(X, y, ["tv", "digital"], "date")
    """
    errors = []
    warnings_list = []

    # Check date column exists
    if date_column not in X.columns:
        errors.append(f"Date column '{date_column}' not found in X")

    # Check channel columns exist
    missing_channels = [ch for ch in channel_columns if ch not in X.columns]
    if missing_channels:
        errors.append(f"Channel columns not found: {missing_channels}")

    # Check for missing values
    if X.isnull().any().any():
        missing_cols = X.columns[X.isnull().any()].tolist()
        warnings_list.append(f"Missing values in columns: {missing_cols}")

    if y.isnull().any():
        errors.append(f"Missing values in target variable (count: {y.isnull().sum()})")

    # Check for negative values in channels
    for ch in channel_columns:
        if ch in X.columns:
            if (X[ch] < 0).any():
                warnings_list.append(f"Negative values in channel '{ch}'")

    # Check for negative target
    if (y < 0).any():
        warnings_list.append(f"Negative values in target variable")

    # Check length match
    if len(X) != len(y):
        errors.append(f"Length mismatch: X has {len(X)} rows, y has {len(y)}")

    result = {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings_list,
        "n_samples": len(X),
        "n_features": len(X.columns),
    }

    if verbose:
        print("DATA VALIDATION")
        print(f"  n_samples = {result['n_samples']}")
        print(f"  n_features = {result['n_features']}")
        print(f"  n_errors = {len(errors)}")
        print(f"  n_warnings = {len(warnings_list)}")
        if errors:
            for e in errors:
                print(f"  ERROR: {e}")
        if warnings_list:
            for w in warnings_list:
                print(f"  WARNING: {w}")
        print(f"  returns: Dict with keys {list(result.keys())}")

    return result


# =============================================================================
# MODEL CREATION FUNCTIONS
# =============================================================================

def create_mmm_instance(
    date_column: str,
    channel_columns: List[str],
    target_column: str = "y",
    dims: Optional[tuple] = None,
    control_columns: Optional[List[str]] = None,
    adstock: type[AdstockTransformation] | pt.TensorLike = GeometricAdstock,
    adstock_max_lag: int = 8,
    saturation: type[SaturationTransformation] | pt.TensorLike = LogisticSaturation,
    yearly_seasonality: Optional[int] = 2,
    model_config: Optional[Dict[str, Any]] = None,
    sampler_config: Optional[Dict[str, Any]] = None,
) -> MMM:
    """
    Create MMM model instance.

    Uses pymc_marketing.mmm.multidimensional.MMM which handles both
    single-dimensional (dims=None) and multi-dimensional (e.g. dims=("geo",))
    data.

    Args:
        date_column: Date column name
        channel_columns: Media channel columns
        target_column: Target variable column name (default: "y")
        dims: Dimension names tuple for panel data, e.g., ("geo",).
              None for single time series data.
        control_columns: Control variable columns
        adstock: AdstockTransformation or pt.TensorLike
                  If of type AdstockTransformation, can be any of
                  pymc_marketing.mmm.components.adstock's transformations.
        adstock_max_lag: Maximum adstock lag (applied to all channels)
        saturation: SaturationTransformation or pt.TensorLike
                  If of type SaturationTransformation, can be any of
                  pymc_marketing.mmm.components.saturation's transformations.
        yearly_seasonality: Fourier seasonality order
        model_config: Custom priors configuration (supports per-channel priors!)
        sampler_config: MCMC sampler configuration

    Returns:
        MMM model instance

    Example:
        >>> mmm = create_mmm_instance(
        ...     date_column="date",
        ...     channel_columns=["tv", "digital", "radio"],
        ...     adstock_max_lag=8,
        ...     yearly_seasonality=10
        ... )

    Example with panel data:
        >>> mmm = create_mmm_instance(
        ...     date_column="date",
        ...     channel_columns=["tv", "digital"],
        ...     target_column="sales",
        ...     dims=("geo",),
        ... )
    """

    if inspect.isclass(adstock) and issubclass(adstock, AdstockTransformation):
        adstock = adstock(l_max=adstock_max_lag)
    if inspect.isclass(saturation) and issubclass(saturation, SaturationTransformation):
        saturation = saturation()

    mmm_kwargs = {
        "adstock": adstock,
        "saturation": saturation,
        "date_column": date_column,
        "channel_columns": channel_columns,
        "target_column": target_column,
        "control_columns": control_columns,
        "yearly_seasonality": yearly_seasonality,
    }

    # Add dims if provided (for panel data)
    if dims is not None:
        mmm_kwargs["dims"] = dims

    # Add custom priors if provided
    if model_config is not None:
        mmm_kwargs["model_config"] = model_config

    # Add sampler config if provided
    if sampler_config is not None:
        mmm_kwargs["sampler_config"] = sampler_config

    mmm = MMM(**mmm_kwargs)

    return mmm



def build_mmm_model(
    mmm: MMM,
    X: pd.DataFrame,
    y: pd.Series,
    verbose: bool = True,
) -> MMM:
    """
    Build MMM model (creates PyMC model graph).

    Args:
        mmm: MMM instance
        X: Features DataFrame
        y: Target Series
        verbose: Print model building info (default: True)

    Returns:
        MMM instance with built model

    Example:
        >>> mmm = build_mmm_model(mmm, X, y)
    """
    if verbose:
        print("BUILDING MMM MODEL")
        print(f"  n_observations = {len(X)}")
        print(f"  n_channels = {len(mmm.channel_columns)}")
        print(f"  channels = {mmm.channel_columns}")
        if mmm.control_columns:
            print(f"  n_controls = {len(mmm.control_columns)}")
            print(f"  controls = {mmm.control_columns}")
        print(f"  date_column = {mmm.date_column}")

    mmm.build_model(X, y)

    # Register original-scale contribution variables so they appear in traces.
    # Required for mmm.plot.* and mmm.summary.* to return original-scale results.
    original_scale_vars: list[str] = ["channel_contribution", "intercept_contribution", "y"]
    if mmm.control_columns:
        original_scale_vars.append("control_contribution")
    if mmm.yearly_seasonality is not None:
        original_scale_vars.append("yearly_seasonality_contribution")
    # Filter to vars that exist in model.named_vars_to_dims — some vars
    # (e.g. intercept_contribution) may not be registered depending on
    # model config / pymc-marketing version.
    registered = set(mmm.model.named_vars_to_dims)
    original_scale_vars = [v for v in original_scale_vars if v in registered]
    mmm.add_original_scale_contribution_variable(var=original_scale_vars)

    if verbose:
        print(f"  model built successfully (original-scale vars: {original_scale_vars})")
        print(f"  returns: MMM (pymc_marketing.mmm.multidimensional.MMM instance)")

    return mmm


# =============================================================================
# PRIOR PREDICTIVE CHECKING FUNCTIONS
# =============================================================================

def sample_prior_predictive(
    mmm: MMM,
    X: pd.DataFrame,
    samples: int = 1000,
    random_seed: int | None = None,
    extend_idata: bool = True,
):
    """
    Sample from prior predictive distribution.

    Args:
        mmm: MMM instance with built model
        X: Features DataFrame (must include date column!)
        samples: Number of samples
        random_seed: Random seed for reproducibility
        extend_idata: If True, stores samples in mmm.prior_predictive

    Returns:
        xarray Dataset with prior predictive samples.
        Access samples directly: result['y'] (NOT result.prior_predictive['y'])

    Note:
        After calling with extend_idata=True, you can also access via:
        mmm.prior_predictive['y']  # Direct access, NOT mmm.prior_predictive.prior_predictive

    Example:
        >>> sample_prior_predictive(mmm, X, samples=1000)
        >>> # Access via mmm attribute:
        >>> prior_y = mmm.prior_predictive['y'].values
        >>> print(f"Prior mean: {prior_y.mean():.2f}")
    """
    return mmm.sample_prior_predictive(
        X,
        samples=samples,
        random_seed=random_seed,
        extend_idata=extend_idata
    )


def get_prior_predictive_summary(mmm: MMM, verbose: bool = True) -> Dict[str, Any]:
    """
    Get summary statistics from prior predictive samples.

    Use this instead of manually extracting samples to avoid AttributeError.

    Args:
        mmm: MMM instance with prior_predictive samples (call sample_prior_predictive first)
        verbose: Print summary statistics (default: True)

    Returns:
        Dictionary with:
        - mean: float (mean of prior predictive)
        - std: float (standard deviation)
        - min: float
        - max: float
        - median: float
        - samples_shape: tuple

    Example:
        >>> sample_prior_predictive(mmm, X)
        >>> summary = get_prior_predictive_summary(mmm)
    """
    if not hasattr(mmm, 'prior_predictive') or mmm.prior_predictive is None:
        raise ValueError("No prior predictive samples found. Call sample_prior_predictive(mmm, X) first.")

    # Access samples directly from the Dataset (NOT .prior_predictive.prior_predictive)
    prior_y = mmm.prior_predictive['y'].values

    result = {
        "mean": float(prior_y.mean()),
        "std": float(prior_y.std()),
        "min": float(prior_y.min()),
        "max": float(prior_y.max()),
        "median": float(np.median(prior_y)),
        "samples_shape": prior_y.shape,
    }

    if verbose:
        print("PRIOR PREDICTIVE SUMMARY")
        print(f"  mean = {result['mean']:.4f}")
        print(f"  std = {result['std']:.4f}")
        print(f"  min = {result['min']:.4f}")
        print(f"  max = {result['max']:.4f}")
        print(f"  median = {result['median']:.4f}")
        print(f"  samples_shape = {result['samples_shape']}")
        print(f"  returns: Dict with keys {list(result.keys())}")

    return result


def plot_prior_predictive(
    mmm: MMM,
    original_scale: bool = True,
    hdi_list: List[float] = [0.5, 0.8, 0.95],
    add_mean: bool = True,
    figsize: tuple = (12, 6),
) -> plt.Figure:
    """
    Plot prior predictive distribution.

    Args:
        mmm: MMM instance with prior predictive samples
        original_scale: Plot in original scale
        hdi_list: HDI levels to plot
        add_mean: Add mean prediction line
        figsize: Figure size

    Returns:
        Matplotlib Figure

    Example:
        >>> fig = plot_prior_predictive(mmm, hdi_list=[0.5, 0.94])
        >>> plt.show()
    """
    fig = mmm.plot_prior_predictive(
        original_scale=original_scale,
        hdi_list=hdi_list,
        add_mean=add_mean,
        figsize=figsize,
    )
    return fig


def check_prior_predictive_coverage(
    mmm: MMM,
    y_observed: pd.Series,
    hdi_prob: float = 0.95,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Check if observed data falls within prior predictive HDI.

    IMPORTANT: Prior predictive samples are in SCALED space (0-1 range).
    This function converts to original scale for comparison with y_observed.

    Supports both single time series and panel data (with dims).

    Args:
        mmm: MMM with prior predictive samples
        y_observed: Observed target values (in ORIGINAL scale)
        hdi_prob: HDI probability level
        verbose: Print coverage statistics (default: True)

    Returns:
        Coverage statistics including:
        - coverage_percent: Percentage of observed points within HDI
        - hdi_lower_mean, hdi_upper_mean: Mean HDI bounds (in ORIGINAL scale)
        - observed_mean: Mean of observed data (in ORIGINAL scale)

    Example:
        >>> coverage = check_prior_predictive_coverage(mmm, y, hdi_prob=0.95)
    """
    import arviz as az
    import xarray as xr

    # Check if panel data model (MMM with dims)
    is_multidim = hasattr(mmm, 'dims') and mmm.dims is not None and len(mmm.dims) > 0

    # Get prior predictive samples (in SCALED space)
    prior_pred = mmm.idata.prior_predictive[mmm.output_var]

    # For panel data, flatten all samples for global coverage check
    # Prior predictive shape: (chain, draw, date, geo) for MMM with dims
    # Prior predictive shape: (chain, draw, date) for single time series MMM
    if is_multidim:
        # Flatten all samples to compute global HDI
        prior_samples_flat = prior_pred.values.flatten()
        hdi_lower_scaled = np.percentile(prior_samples_flat, (1 - hdi_prob) / 2 * 100)
        hdi_upper_scaled = np.percentile(prior_samples_flat, (1 + hdi_prob) / 2 * 100)
    else:
        # Calculate HDI per time point (still in SCALED space)
        hdi = az.hdi(prior_pred, hdi_prob=hdi_prob)
        if isinstance(hdi, xr.Dataset):
            hdi = hdi[mmm.output_var]
        hdi_lower_scaled = hdi.sel(hdi="lower").values
        hdi_upper_scaled = hdi.sel(hdi="higher").values

    # Get scale factor to convert from scaled space to original scale
    # PyMC-Marketing uses MaxAbsScaler which divides by max(abs(y))
    scale_factor = None

    # Method 1: Try get_target_transformer (regular MMM only)
    if not is_multidim and hasattr(mmm, 'get_target_transformer'):
        try:
            target_transformer = mmm.get_target_transformer()
            scaler = target_transformer.named_steps.get('scaler')
            if scaler is not None and hasattr(scaler, 'scale_'):
                scale_factor = scaler.scale_[0]
            elif scaler is not None and hasattr(scaler, 'max_abs_'):
                scale_factor = scaler.max_abs_[0]
        except Exception:
            pass

    # Method 2: Use max of observed y (works for both MMM types)
    if scale_factor is None:
        scale_factor = float(y_observed.max())
        if verbose and not is_multidim:
            print(f"  Using y_max={scale_factor:,.0f} as scale factor")

    # Convert HDI bounds to original scale
    lower = hdi_lower_scaled * scale_factor if not isinstance(hdi_lower_scaled, np.ndarray) else hdi_lower_scaled * scale_factor
    upper = hdi_upper_scaled * scale_factor if not isinstance(hdi_upper_scaled, np.ndarray) else hdi_upper_scaled * scale_factor

    # Calculate coverage
    if is_multidim:
        # For panel data: check if observed values (scaled) fall within global HDI
        y_scaled = y_observed.values / scale_factor
        within_hdi = (y_scaled >= hdi_lower_scaled) & (y_scaled <= hdi_upper_scaled)
        coverage = within_hdi.sum() / len(within_hdi)
        # Convert bounds to arrays for consistency
        lower = np.array([lower])
        upper = np.array([upper])
    else:
        # For regular MMM: check point-by-point
        if len(y_observed) == len(lower):
            within_hdi = (y_observed.values >= lower) & (y_observed.values <= upper)
            coverage = within_hdi.sum() / len(within_hdi)
        else:
            coverage = np.nan
            within_hdi = np.array([])

    result = {
        "coverage_percent": coverage * 100 if not np.isnan(coverage) else np.nan,
        "points_within_hdi": int(within_hdi.sum()) if not np.isnan(coverage) else None,
        "total_points": len(y_observed),
        "hdi_prob": hdi_prob,
        "hdi_lower_mean": float(np.mean(lower)),
        "hdi_upper_mean": float(np.mean(upper)),
        "observed_mean": float(y_observed.mean()),
        "observed_min": float(y_observed.min()),
        "observed_max": float(y_observed.max()),
        "is_multidim": is_multidim,
    }

    if verbose:
        model_type = "MMM with dims" if is_multidim else "MMM"
        print(f"PRIOR PREDICTIVE COVERAGE ({model_type}, Original Scale)")
        print(f"  HDI probability: {hdi_prob:.0%}")
        print(f"  Coverage: {result['coverage_percent']:.1f}% ({result['points_within_hdi']} / {result['total_points']} points within HDI)")
        print(f"  HDI bounds (mean): [{result['hdi_lower_mean']:,.0f}, {result['hdi_upper_mean']:,.0f}]")
        print(f"  Observed range: [{result['observed_min']:,.0f}, {result['observed_max']:,.0f}]")
        print(f"  Observed mean: {result['observed_mean']:,.0f}")
        print(f"  Returning: Dict with keys {list(result.keys())}")

    return result


# =============================================================================
# MODEL FITTING FUNCTIONS
# =============================================================================

def create_sampler_config(
    draws: int = 1000,
    tune: int = 1000,
    chains: int = 4,
    sampler_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create sampler configuration for MCMC.

    Args:
        draws: Number of samples to draw
        tune: Number of tuning samples
        chains: Number of chains
        sampler_mode: "numba" for JIT compilation, None for default

    Returns:
        Sampler config dictionary

    Example:
        >>> sampler_config = create_sampler_config(draws=2000, chains=4)
    """
    config = {
        "draws": draws,
        "chains": chains,
        "nuts_sampler": "pymc",
        "tune": tune,
    }

    if sampler_mode == "numba":
        config["compile_kwargs"] = {"mode": "NUMBA"}

    return config


def fit_mmm_model(
    mmm: MMM,
    X: pd.DataFrame,
    y: pd.Series,
    callback: Optional[Callable] = None,
    verbose: bool = True,
) -> MMM:
    """
    Fit MMM model using MCMC sampling.

    Args:
        mmm: MMM instance with built model
        X: Features DataFrame
        y: Target Series
        callback: Progress callback function
        verbose: Print fitting info (default: True)

    Returns:
        Fitted MMM instance

    Example:
        >>> mmm = fit_mmm_model(mmm, X, y)
    """
    if verbose:
        print("FITTING MMM MODEL")
        print(f"  n_observations = {len(X)}")
        sampler_config = mmm.sampler_config if hasattr(mmm, 'sampler_config') else {}
        draws = sampler_config.get('draws', 1000)
        tune = sampler_config.get('tune', 1000)
        chains = sampler_config.get('chains', 4)
        print(f"  draws = {draws}")
        print(f"  tune = {tune}")
        print(f"  chains = {chains}")
        start_time = time.time()

    if callback is not None:
        mmm.fit(X, y, callback=callback)
    else:
        mmm.fit(X, y)

    if verbose:
        elapsed = time.time() - start_time
        print(f"  fitting completed in {elapsed:.1f}s")
        print(f"  returns: MMM (fitted, access results via mmm.idata, mmm.fit_result, mmm.posterior_predictive)")

    return mmm


def fit_mmm_with_config(
    X: pd.DataFrame,
    y: pd.Series,
    date_column: str,
    channel_columns: List[str],
    control_columns: Optional[List[str]] = None,
    adstock: type[AdstockTransformation] | pt.TensorLike = GeometricAdstock,
    adstock_max_lag: int = 8,
    saturation: type[SaturationTransformation] | pt.TensorLike = LogisticSaturation,
    yearly_seasonality: Optional[int] = 2,
    model_config: Optional[Dict[str, Any]] = None,
    draws: int = 1000,
    tune: int = 1000,
    chains: int = 4,
    sampler_mode: Optional[str] = None,
    callback: Optional[Callable] = None,
) -> MMM:
    """
    Complete workflow to create and fit MMM model.

    Args:
        X: Features DataFrame
        y: Target Series
        date_column: Date column name
        channel_columns: Channel columns
        control_columns: Control columns
        adstock: AdstockTransformation or pt.TensorLike
                  If pt.TensorLike, it's an already initialized transformation.
                  If of type AdstockTransformation, can be any of
                  pymc_marketing.mmm.components.adstock's transformations.
        adstock_max_lag: Maximum adstock lag, only applied if adstock is uninitialized
        saturation: SaturationTransformation or pt.TensorLike
                  If pt.TensorLike, it's an already initialized transformation.
                  If of type SaturationTransformation, can be any of
                  pymc_marketing.mmm.components.saturation's transformations.
        yearly_seasonality: Seasonality order
        model_config: Custom priors
        draws: MCMC draws
        tune: MCMC tuning steps
        chains: Number of chains
        sampler_mode: Sampler mode
        callback: Progress callback

    Returns:
        Fitted MMM instance

    Example:
        >>> mmm = fit_mmm_with_config(
        ...     X, y,
        ...     date_column="date",
        ...     channel_columns=["tv", "digital"],
        ...     draws=2000,
        ...     chains=4
        ... )
    """
    # Create sampler config
    sampler_config = create_sampler_config(
        draws=draws,
        tune=tune,
        chains=chains,
        sampler_mode=sampler_mode
    )

    # Create MMM instance
    mmm = create_mmm_instance(
        date_column=date_column,
        channel_columns=channel_columns,
        control_columns=control_columns,
        adstock=adstock,
        adstock_max_lag=adstock_max_lag,
        saturation=saturation,
        yearly_seasonality=yearly_seasonality,
        model_config=model_config,
        sampler_config=sampler_config,
    )

    # Build model
    mmm = build_mmm_model(mmm, X, y)

    # Fit model
    mmm = fit_mmm_model(mmm, X, y, callback=callback)

    return mmm


# =============================================================================
# MODEL DIAGNOSTICS FUNCTIONS
# =============================================================================

def check_convergence(
    mmm: MMM,
    var_names: Optional[List[str]] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Check MCMC convergence diagnostics including R-hat, ESS, and divergences.

    Args:
        mmm: Fitted MMM instance
        var_names: Variable names to check (None = all)
        verbose: Print diagnostic results (default: True)

    Returns:
        Dictionary with:
        - converged: bool (all checks pass)
        - max_rhat: float
        - min_ess_bulk: float
        - min_ess_tail: float
        - n_divergences: int
        - divergence_pct: float
        - problem_vars_rhat: list
        - low_ess_vars: list
        - summary: DataFrame

    Example:
        >>> diagnostics = check_convergence(mmm)
        >>> print(f"Max R-hat: {diagnostics['max_rhat']:.3f}")
        >>> print(f"Divergences: {diagnostics['n_divergences']} ({diagnostics['divergence_pct']:.1%})")
    """
    if var_names is None:
        var_names = ["intercept", "beta_channel", "alpha", "lam", "sigma"]

    # Get summary
    summary = az.summary(mmm.fit_result, var_names=var_names, filter_vars="like")

    # Check R-hat
    rhats = summary["r_hat"]
    max_rhat = rhats.max()
    problem_vars = summary[rhats > 1.1].index.tolist()

    # Check ESS (bulk and tail)
    ess_bulk = summary["ess_bulk"]
    ess_tail = summary["ess_tail"]
    min_ess_bulk = ess_bulk.min()
    min_ess_tail = ess_tail.min()
    low_ess_vars = summary[ess_bulk < 200].index.tolist()

    # Check divergences - use mmm.idata (InferenceData), not mmm.fit_result (Dataset)
    n_divergences = 0
    divergence_pct = 0.0
    total_samples = 0
    try:
        if hasattr(mmm, 'idata') and mmm.idata is not None:
            if hasattr(mmm.idata, 'sample_stats') and 'diverging' in mmm.idata.sample_stats:
                diverging = mmm.idata.sample_stats['diverging']
                n_divergences = int(diverging.sum().item())
                total_samples = diverging.size
                divergence_pct = n_divergences / total_samples if total_samples > 0 else 0.0
    except Exception:
        pass  # If we can't get divergences, continue with other checks

    # Convergence passes if: R-hat < 1.1, ESS >= 200, divergences < 1%
    converged = max_rhat < 1.1 and min_ess_bulk >= 200 and divergence_pct < 0.01

    result = {
        "converged": converged,
        "max_rhat": float(max_rhat),
        "min_ess_bulk": float(min_ess_bulk),
        "min_ess_tail": float(min_ess_tail),
        "n_divergences": n_divergences,
        "divergence_pct": divergence_pct,
        "problem_vars_rhat": problem_vars,
        "low_ess_vars": low_ess_vars,
        "summary": summary,
    }

    if verbose:
        print("=" * 50)
        print("CONVERGENCE DIAGNOSTICS")
        print("=" * 50)
        print(f"max_rhat = {max_rhat:.4f}")
        print(f"min_ess_bulk = {min_ess_bulk:.0f}")
        print(f"min_ess_tail = {min_ess_tail:.0f}")
        print(f"n_divergences = {n_divergences} / {total_samples} ({divergence_pct:.2%})")
        if problem_vars:
            print(f"vars with r_hat > 1.1: {problem_vars}")
        if low_ess_vars:
            print(f"vars with ess_bulk < 200: {low_ess_vars}")
        print(f"returns: Dict with keys {list(result.keys())}")
        print("=" * 50)

    return result


def get_parameter_summary(
    mmm: MMM,
    var_names: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Get parameter summary statistics.

    Args:
        mmm: Fitted MMM instance
        var_names: Variables to summarize

    Returns:
        Summary DataFrame

    Example:
        >>> summary = get_parameter_summary(mmm)
        >>> print(summary)
    """

    if var_names is None:
        var_names = [
            "intercept", "beta_channel", "alpha", "lam",
            "sigma", "gamma_control", "gamma_fourier"
        ]

    summary = az.summary(
        mmm.fit_result,
        var_names=var_names,
        filter_vars="like"
    )

    return summary


def check_model_fit_quality(
    mmm: MMM,
    y_observed: pd.Series,
    verbose: bool = True,
) -> Dict[str, float]:
    """
    Check model fit quality metrics.

    Args:
        mmm: Fitted MMM instance
        y_observed: Observed target values
        verbose: Print fit quality metrics (default: True)

    Returns:
        Fit quality metrics

    Example:
        >>> quality = check_model_fit_quality(mmm, y)
    """
    # Get posterior predictive mean
    posterior_pred = mmm.idata.posterior_predictive[mmm.output_var]
    y_pred_mean = posterior_pred.mean(dim=["chain", "draw"]).values

    # Calculate metrics
    ss_res = np.sum((y_observed.values - y_pred_mean) ** 2)
    ss_tot = np.sum((y_observed.values - y_observed.mean()) ** 2)
    r_squared = 1 - (ss_res / ss_tot)

    mae = np.mean(np.abs(y_observed.values - y_pred_mean))
    rmse = np.sqrt(np.mean((y_observed.values - y_pred_mean) ** 2))
    mape = np.mean(np.abs((y_observed.values - y_pred_mean) / y_observed.values)) * 100

    result = {
        "r_squared": float(r_squared),
        "mae": float(mae),
        "rmse": float(rmse),
        "mape": float(mape),
    }

    if verbose:
        print("MODEL FIT QUALITY")
        print(f"  r_squared = {result['r_squared']:.4f}")
        print(f"  mae = {result['mae']:.4f}")
        print(f"  rmse = {result['rmse']:.4f}")
        print(f"  mape = {result['mape']:.2f}%")
        print(f"  returns: Dict with keys {list(result.keys())}")

    return result


# =============================================================================
# MODEL SERIALIZATION FUNCTIONS
# =============================================================================

def save_mmm_model(mmm: MMM, filepath: str) -> str:
    """
    Save MMM model to NetCDF file using the model's native save method.

    This avoids pickle serialization issues with PyMC models that contain
    local functions that can't be pickled.

    Args:
        mmm: Fitted MMM instance
        filepath: Output file path (should end in .nc for NetCDF format)

    Returns:
        Filepath where model was saved

    Example:
        >>> path = save_mmm_model(mmm, "model/fitted_model.nc")
    """
    # Use MMM's native save method which handles PyMC serialization correctly
    mmm.save(filepath)
    return filepath


def load_mmm_model(filepath: str) -> MMM:
    """
    Load MMM model from NetCDF file using the class's native load method.

    Args:
        filepath: Path to saved model (.nc file)

    Returns:
        Loaded MMM instance

    Example:
        >>> mmm = load_mmm_model("model/fitted_model.nc")
    """
    # Use MMM's native load method
    mmm = MMM.load(filepath)
    return mmm


# =============================================================================
# ACF-BASED L_MAX SUGGESTION
# =============================================================================

def suggest_l_max_from_acf(
    df: pd.DataFrame,
    channel_columns: List[str],
    max_lag: int = 20,
    threshold: float = 0.1,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Analyze ACF for multiple channels and suggest l_max for each.

    This is useful for setting adstock parameters before model fitting.

    Args:
        df: pandas DataFrame with channel data
        channel_columns: List of channel column names
        max_lag: Maximum lag to compute (default: 20)
        threshold: ACF threshold for cutoff (default: 0.1)
        verbose: Print ACF analysis results (default: True)

    Returns:
        Dictionary with:
        - suggestions: Dict of {channel: suggested_l_max}
        - acf_results: Dict of {channel: acf_values}
        - max_suggested: Maximum suggested l_max across all channels
        - min_suggested: Minimum suggested l_max across all channels
    """
    from statsmodels.tsa.stattools import acf

    suggestions = {}
    acf_results = {}

    for channel in channel_columns:
        # Compute ACF
        acf_values = acf(df[channel], nlags=max_lag, fft=False)

        # Find cutoff
        below_threshold = np.where(np.abs(acf_values) < threshold)[0]
        suggested_l_max = int(below_threshold[0]) if len(below_threshold) > 0 else max_lag

        suggestions[channel] = suggested_l_max
        acf_results[channel] = acf_values.tolist()

    result = {
        "suggestions": suggestions,
        "acf_results": acf_results,
        "max_suggested": max(suggestions.values()) if suggestions else max_lag,
        "min_suggested": min(suggestions.values()) if suggestions else 0,
        "channels_analyzed": len(channel_columns)
    }

    if verbose:
        print("ACF ANALYSIS FOR L_MAX SUGGESTION")
        print(f"  threshold = {threshold}")
        print(f"  max_lag = {max_lag}")
        for ch, l_max in suggestions.items():
            print(f"  {ch}: suggested_l_max = {l_max}")
        print(f"  overall_max_suggested = {result['max_suggested']}")
        print(f"  overall_min_suggested = {result['min_suggested']}")
        print(f"  returns: Dict with keys {list(result.keys())}")

    return result


def validate_mmm_config(
    config: Dict[str, Any],
    min_l_max: int = 1,
    max_l_max: int = 52
) -> Dict[str, Any]:
    """
    Validate MMM configuration before fitting.

    Checks for common configuration errors and API compatibility issues.

    Args:
        config: Dictionary with MMM configuration (adstock, saturation, channels, etc.)
        min_l_max: Minimum acceptable l_max value (default: 1)
        max_l_max: Maximum acceptable l_max value (default: 52)

    Returns:
        Dictionary with:
        - valid: Boolean indicating if configuration is valid (also includes is_valid for backwards compat)
        - errors: List of error messages
        - warnings: List of warning messages (optional)
        - recommendations: List of recommended changes (optional)
    """
    errors = []
    warnings_list = []
    recommendations = []

    # Check required fields - support both y_column and target_column
    required_base = ["date_column", "channel_columns"]
    for field in required_base:
        if field not in config:
            errors.append(f"Missing required field: {field}")

    # Check for y_column OR target_column
    if 'y_column' not in config and 'target_column' not in config:
        errors.append("Missing required field: 'y_column' or 'target_column'")

    # Check adstock and saturation
    if 'adstock' not in config:
        errors.append("Missing required field: 'adstock'")
    if 'saturation' not in config:
        errors.append("Missing required field: 'saturation'")

    # Channel columns validation
    if "channel_columns" in config:
        if not isinstance(config["channel_columns"], list):
            errors.append("channel_columns must be a list")
        elif len(config["channel_columns"]) == 0:
            errors.append("channel_columns cannot be empty")
        elif not all(isinstance(col, str) for col in config['channel_columns']):
            errors.append("All channel columns must be strings")

    # Numeric validations
    if "adstock_max_lag" in config:
        if not isinstance(config["adstock_max_lag"], int) or config["adstock_max_lag"] < 1:
            errors.append("adstock_max_lag must be positive integer")

    if "yearly_seasonality" in config and config["yearly_seasonality"] is not None:
        if not isinstance(config["yearly_seasonality"], int) or config["yearly_seasonality"] < 1:
            errors.append("yearly_seasonality must be positive integer or None")

    # Check adstock configuration for l_max
    if 'adstock' in config:
        adstock = config['adstock']
        if hasattr(adstock, 'l_max'):
            if adstock.l_max < min_l_max:
                warnings_list.append(f"Adstock l_max is {adstock.l_max}, should be >= {min_l_max}")
            if adstock.l_max > max_l_max:
                warnings_list.append(f"Adstock l_max is {adstock.l_max}, very high value (>{max_l_max}) might cause issues")

    # Build return dict with both "valid" and "is_valid" for backwards compatibility
    is_valid = len(errors) == 0
    result = {
        "valid": is_valid,
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings_list,
        "recommendations": recommendations,
    }

    return result


def check_convergence_diagnostics(
    idata,
    var_names: Optional[List[str]] = None,
    rhat_threshold: float = 1.1,
    ess_threshold: int = 200,
    high_divergence_threshold: int = 100
) -> Dict[str, Any]:
    """
    Check MCMC convergence diagnostics.

    Analyzes R-hat, ESS, and divergences to assess model convergence.

    Args:
        idata: ArviZ InferenceData object from model.fit()
        var_names: Optional list of variable names to check (default: all)
        rhat_threshold: R-hat threshold for convergence (default: 1.1)
        ess_threshold: Minimum acceptable effective sample size (default: 200)
        high_divergence_threshold: Threshold for "many" divergences (default: 100)

    Returns:
        Dictionary with:
        - converged: Boolean indicating if model converged
        - rhat_summary: Dict of {var: max_rhat_across_chains}
        - ess_summary: Dict of {var: min_ess_across_chains}
        - divergences: Number of divergent transitions
        - max_rhat: Maximum R-hat across all variables
        - min_ess: Minimum ESS across all variables
        - issues: List of convergence issues found
    """
    # Extract R-hat
    rhat = az.rhat(idata, var_names=var_names)
    rhat_dict = {}
    max_rhat = 0

    for var_name in rhat.data_vars:
        var_rhat = float(rhat[var_name].max())
        rhat_dict[var_name] = var_rhat
        max_rhat = max(max_rhat, var_rhat)

    # Extract ESS
    ess = az.ess(idata, var_names=var_names)
    ess_dict = {}
    min_ess = float('inf')

    for var_name in ess.data_vars:
        var_ess = float(ess[var_name].min())
        ess_dict[var_name] = var_ess
        min_ess = min(min_ess, var_ess)

    # Check divergences
    divergences = 0
    if hasattr(idata, 'sample_stats') and 'diverging' in idata.sample_stats:
        divergences = int(idata.sample_stats.diverging.sum())

    # Identify issues
    issues = []
    if max_rhat > rhat_threshold:
        issues.append(f"Poor convergence: max R-hat = {max_rhat:.4f} (should be < {rhat_threshold})")

    if min_ess < ess_threshold:
        issues.append(f"Low effective sample size: min ESS = {min_ess:.0f} (should be > {ess_threshold})")

    if divergences > 0:
        issues.append(f"Found {divergences} divergent transitions")

    # Variables with poor R-hat
    poor_rhat_vars = [var for var, rhat_val in rhat_dict.items() if rhat_val > rhat_threshold]
    if poor_rhat_vars:
        issues.append(f"Variables with R-hat > {rhat_threshold}: {', '.join(poor_rhat_vars)}")

    # Variables with low ESS
    low_ess_vars = [var for var, ess_val in ess_dict.items() if ess_val < ess_threshold]
    if low_ess_vars:
        issues.append(f"Variables with ESS < {ess_threshold}: {', '.join(low_ess_vars)}")

    converged = max_rhat < rhat_threshold and min_ess >= ess_threshold and divergences == 0

    return {
        "converged": converged,
        "rhat_summary": rhat_dict,
        "ess_summary": ess_dict,
        "divergences": divergences,
        "max_rhat": float(max_rhat),
        "min_ess": float(min_ess),
        "issues": issues,
        "recommendations": _generate_convergence_recommendations(
            max_rhat, min_ess, divergences,
            rhat_threshold, ess_threshold, high_divergence_threshold
        )
    }


def _generate_convergence_recommendations(
    max_rhat: float,
    min_ess: float,
    divergences: int,
    rhat_threshold: float = 1.1,
    ess_threshold: int = 200,
    high_divergence_threshold: int = 100
) -> List[str]:
    """Generate recommendations based on convergence diagnostics."""
    recommendations = []

    if max_rhat > rhat_threshold:
        recommendations.append("Increase number of tuning steps or sampling draws")

    if min_ess < ess_threshold:
        recommendations.append("Increase number of draws to improve effective sample size")

    if divergences > 0:
        if divergences > high_divergence_threshold:
            recommendations.append("Many divergences detected - consider reparameterizing model or adjusting priors")
        else:
            recommendations.append("Some divergences detected - monitor but may be acceptable if count is low")

    if not recommendations:
        recommendations.append("Convergence looks good!")

    return recommendations


def extract_prior_predictive_summary(
    prior_pred,
    target_column: str = "y",
    variance_ratio_threshold: float = 10.0,
    percentile_ratio_threshold: float = 100.0
) -> Dict[str, Any]:
    """
    Summarize prior predictive checks.

    Args:
        prior_pred: Prior predictive samples from model.sample_prior_predictive()
        target_column: Name of target variable (default: "y")
        variance_ratio_threshold: Threshold for std/mean ratio (default: 10.0)
        percentile_ratio_threshold: Threshold for 95th/50th percentile ratio (default: 100.0)

    Returns:
        Dictionary with:
        - mean_prediction: Mean of prior predictions
        - std_prediction: Std of prior predictions
        - percentiles: Dict with 5th, 50th, 95th percentiles
        - seems_reasonable: Boolean heuristic check
        - issues: List of potential issues
    """
    # Extract prior predictions
    if hasattr(prior_pred, 'prior_predictive'):
        predictions = prior_pred.prior_predictive[target_column].values.flatten()
    else:
        predictions = prior_pred[target_column].values.flatten()

    mean_pred = float(np.mean(predictions))
    std_pred = float(np.std(predictions))
    percentiles = {
        "5th": float(np.percentile(predictions, 5)),
        "50th": float(np.percentile(predictions, 50)),
        "95th": float(np.percentile(predictions, 95))
    }

    # Heuristic checks
    issues = []

    # Check for negative predictions (shouldn't happen for sales/revenue)
    if np.any(predictions < 0):
        neg_count = int(np.sum(predictions < 0))
        issues.append(f"Prior generates {neg_count} negative predictions")

    # Check if variance is too extreme
    variance_ratio = std_pred / (mean_pred + 1e-10)
    if variance_ratio > variance_ratio_threshold:
        issues.append(f"Prior predictions have very high variance relative to mean (ratio: {variance_ratio:.1f} > {variance_ratio_threshold})")

    # Check if predictions are unrealistically large
    percentile_ratio = percentiles["95th"] / (percentiles["50th"] + 1e-10)
    if percentile_ratio > percentile_ratio_threshold:
        issues.append(f"Prior allows for extremely large values (95th/50th ratio: {percentile_ratio:.1f} > {percentile_ratio_threshold})")

    seems_reasonable = len(issues) == 0

    return {
        "mean_prediction": mean_pred,
        "std_prediction": std_pred,
        "percentiles": percentiles,
        "min_prediction": float(np.min(predictions)),
        "max_prediction": float(np.max(predictions)),
        "seems_reasonable": seems_reasonable,
        "issues": issues
    }


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    # Configuration
    "create_mmm_config",
    "create_custom_priors",
    "validate_custom_priors",
    "validate_mmm_config",
    # Data Preparation
    "prepare_mmm_data",
    "validate_mmm_data",
    # Model Creation
    "create_mmm_instance",
    "build_mmm_model",
    # Prior Predictive
    "sample_prior_predictive",
    "get_prior_predictive_summary",
    "plot_prior_predictive",
    "check_prior_predictive_coverage",
    "extract_prior_predictive_summary",
    # Fitting
    "create_sampler_config",
    "fit_mmm_model",
    "fit_mmm_with_config",
    # Diagnostics
    "check_convergence",
    "check_convergence_diagnostics",
    "get_parameter_summary",
    "check_model_fit_quality",
    # Serialization
    "save_mmm_model",
    "load_mmm_model",
    # ACF Utilities
    "suggest_l_max_from_acf",
    # Transformation names (for documentation)
    "_adstock_transformation_names",
    "_saturation_transformation_names",
]
