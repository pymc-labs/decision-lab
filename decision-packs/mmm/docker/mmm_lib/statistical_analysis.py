"""
Statistical Analysis Module for MMM Data

This module provides statistical tests and analysis functions for Marketing Mix Model data.
All functions accept DataFrames directly, making them usable both from CLI tools and scripts.

Core functions:
- analyze_mmm_statistics: Main analysis function for MMM model specification decisions
- test_stationarity_adf: ADF test for stationarity
- test_stationarity_kpss: KPSS test for stationarity
- analyze_trend: Linear trend analysis
- analyze_multicollinearity: VIF and correlation analysis
- detect_seasonality_fft: FFT-based seasonality detection

Example usage in scripts:
    from mmm_analysis.statistical_analysis import analyze_mmm_statistics
    import pandas as pd

    df = pd.read_csv('data.csv')

    # Analyze single region
    results = analyze_mmm_statistics(
        df,
        date_col='date',
        target_col='sales',
        channel_cols=['tv_spend', 'radio_spend', 'digital_spend']
    )

    # Analyze multiple cases
    for brand in df['brand'].unique():
        df_brand = df[df['brand'] == brand]
        results = analyze_mmm_statistics(df_brand, ...)
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from pathlib import Path
import warnings

import pandas as pd
import numpy as np
from scipy import stats as scipy_stats

# Suppress warnings for cleaner output
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=RuntimeWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*interpolation.*')
warnings.filterwarnings('ignore', message='.*p-value.*')
warnings.filterwarnings('ignore', message='.*outside of the range.*')


# =============================================================================
# STATIONARITY TESTS
# =============================================================================

def test_stationarity_adf(series: pd.Series, name: str = "series") -> Dict[str, Any]:
    """
    Augmented Dickey-Fuller test for stationarity.

    Null hypothesis: The series has a unit root (non-stationary)
    If p-value < 0.05: Reject null -> series is stationary

    Args:
        series: Time series data (pandas Series or array-like)
        name: Name for reporting (optional)

    Returns:
        Dict with test results including 'is_stationary' boolean
    """
    try:
        from statsmodels.tsa.stattools import adfuller

        clean_series = pd.Series(series).dropna()
        if len(clean_series) < 20:
            return {'error': 'Not enough data points (need at least 20)'}

        result = adfuller(clean_series, autolag='AIC')

        return {
            'test': 'ADF (Augmented Dickey-Fuller)',
            'statistic': result[0],
            'p_value': result[1],
            'lags_used': result[2],
            'n_obs': result[3],
            'critical_values': result[4],
            'is_stationary': result[1] < 0.05,
            'interpretation': 'Stationary' if result[1] < 0.05 else 'Non-stationary (has unit root)'
        }
    except ImportError:
        return {'error': 'statsmodels not installed'}
    except Exception as e:
        return {'error': str(e)}


def test_stationarity_kpss(series: pd.Series, name: str = "series") -> Dict[str, Any]:
    """
    KPSS test for stationarity.

    Null hypothesis: The series is stationary
    If p-value < 0.05: Reject null -> series is non-stationary

    Args:
        series: Time series data (pandas Series or array-like)
        name: Name for reporting (optional)

    Returns:
        Dict with test results including 'is_stationary' boolean
    """
    try:
        from statsmodels.tsa.stattools import kpss

        clean_series = pd.Series(series).dropna()
        if len(clean_series) < 20:
            return {'error': 'Not enough data points (need at least 20)'}

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = kpss(clean_series, regression='c', nlags='auto')

        return {
            'test': 'KPSS',
            'statistic': result[0],
            'p_value': result[1],
            'lags_used': result[2],
            'critical_values': result[3],
            'is_stationary': result[1] >= 0.05,
            'interpretation': 'Stationary' if result[1] >= 0.05 else 'Non-stationary (has trend/drift)'
        }
    except ImportError:
        return {'error': 'statsmodels not installed'}
    except Exception as e:
        return {'error': str(e)}


def analyze_trend(series: pd.Series) -> Dict[str, Any]:
    """
    Analyze trend in time series using linear regression.

    Args:
        series: Time series data

    Returns:
        Dict with slope, r_squared, p_value, trend_direction, trend_significant
    """
    clean_series = pd.Series(series).dropna().reset_index(drop=True)
    n = len(clean_series)

    if n < 10:
        return {'error': 'Not enough data points'}

    t = np.arange(n)
    slope, intercept, r_value, p_value, std_err = scipy_stats.linregress(t, clean_series)

    if p_value < 0.05:
        trend_direction = 'Upward' if slope > 0 else 'Downward'
        trend_significant = True
    else:
        trend_direction = 'No significant trend'
        trend_significant = False

    start_value = intercept
    end_value = intercept + slope * (n - 1)
    pct_change = ((end_value - start_value) / abs(start_value)) * 100 if start_value != 0 else np.nan

    return {
        'slope': slope,
        'intercept': intercept,
        'r_squared': r_value ** 2,
        'p_value': p_value,
        'std_err': std_err,
        'trend_direction': trend_direction,
        'trend_significant': trend_significant,
        'total_pct_change': pct_change
    }


# =============================================================================
# MULTICOLLINEARITY ANALYSIS
# =============================================================================

def analyze_multicollinearity(df: pd.DataFrame, channel_cols: List[str]) -> Dict[str, Any]:
    """
    Analyze multicollinearity among channel variables using VIF.

    VIF > 5 indicates moderate multicollinearity
    VIF > 10 indicates severe multicollinearity

    Args:
        df: DataFrame containing channel columns
        channel_cols: List of channel column names

    Returns:
        Dict with vif_scores, high_correlation_pairs, severity flags
    """
    try:
        from statsmodels.stats.outliers_influence import variance_inflation_factor
        from statsmodels.tools.tools import add_constant

        channel_df = df[channel_cols].dropna()

        if len(channel_df) < len(channel_cols) + 10:
            return {'error': 'Not enough data points for VIF calculation'}

        X = add_constant(channel_df)

        vif_data = []
        for i, col in enumerate(channel_cols):
            vif = variance_inflation_factor(X.values, i + 1)
            vif_data.append({
                'channel': col,
                'vif': vif,
                'severity': 'Severe' if vif > 10 else ('Moderate' if vif > 5 else 'OK')
            })

        vif_data.sort(key=lambda x: x['vif'], reverse=True)

        corr_matrix = channel_df.corr()

        high_corr_pairs = []
        for i, col1 in enumerate(channel_cols):
            for col2 in channel_cols[i+1:]:
                corr = corr_matrix.loc[col1, col2]
                if abs(corr) > 0.7:
                    high_corr_pairs.append((col1, col2, corr))

        high_corr_pairs.sort(key=lambda x: abs(x[2]), reverse=True)

        return {
            'vif_scores': vif_data,
            'high_correlation_pairs': high_corr_pairs[:10],
            'has_multicollinearity_issues': any(v['vif'] > 5 for v in vif_data),
            'severe_multicollinearity': any(v['vif'] > 10 for v in vif_data)
        }
    except ImportError:
        return {'error': 'statsmodels not installed'}
    except Exception as e:
        return {'error': str(e)}


# =============================================================================
# FFT SEASONALITY DETECTION
# =============================================================================

def detect_seasonality_fft(
    y: Union[List, np.ndarray, pd.Series],
    detrend: str = 'poly',
    difference: bool = False,
    max_period: Optional[int] = None,
    min_period: int = 2,
    alpha: float = 0.01,
    n_bootstrap: int = 200,
    return_debug: bool = False,
    seed: Optional[int] = None
) -> Dict[str, Any]:
    """
    Detect seasonality using FFT-based spectral analysis.

    Args:
        y: Time series data (array-like or pandas Series)
        detrend: Detrending method - 'none', 'linear', or 'poly' (quadratic)
        difference: Whether to first-difference the series
        max_period: Maximum period to consider (default: len(y)//2)
        min_period: Minimum period to consider
        alpha: Significance threshold for statistical test
        n_bootstrap: Number of bootstrap samples for p-value
        return_debug: Whether to return debug info
        seed: Random seed for reproducibility

    Returns:
        Dict with has_seasonality, dominant_period, strength, p_value, peaks
    """
    from scipy import signal
    from scipy.interpolate import interp1d

    # Constants
    HEURISTIC_RATIO_THRESHOLD = 10.0
    MIN_PROMINENCE_RATIO = 2.0
    TOP_K_PEAKS = 5
    NOISE_EXCLUSION_BINS = 3
    BOUNDARY_EXCLUSION_RATIO = 0.9

    # Convert to numpy
    if isinstance(y, pd.Series):
        y = y.values
    y = np.asarray(y, dtype=float).flatten()
    original_length = len(y)

    if original_length < 16:
        return {
            'has_seasonality': False,
            'dominant_period': None,
            'strength': 0.0,
            'p_value': 1.0,
            'peaks': [],
            'n_significant_peaks': 0,
            'error': 'Time series too short (need at least 16 samples)'
        }

    # Set max_period
    if max_period is None:
        max_period = original_length // 2
    max_period = min(max_period, original_length // 2)
    min_period = max(min_period, 2)

    if min_period >= max_period:
        return {
            'has_seasonality': False,
            'dominant_period': None,
            'strength': 0.0,
            'p_value': 1.0,
            'peaks': [],
            'n_significant_peaks': 0,
            'error': f'Invalid period range: min_period={min_period} >= max_period={max_period}'
        }

    # Handle NaNs
    nan_mask = np.isnan(y)
    if nan_mask.any():
        if nan_mask.all():
            return {'has_seasonality': False, 'n_significant_peaks': 0, 'error': 'All values are NaN'}
        valid_idx = np.where(~nan_mask)[0]
        y = y[valid_idx[0]:valid_idx[-1] + 1]
        nan_mask = np.isnan(y)
        if nan_mask.any():
            x = np.arange(len(y))
            valid = ~nan_mask
            interpolator = interp1d(x[valid], y[valid], kind='linear',
                                    bounds_error=False, fill_value='extrapolate')
            y[nan_mask] = interpolator(x[nan_mask])

    # Detrend
    if detrend in ('linear', 'poly'):
        x = np.arange(len(y))
        deg = 2 if detrend == 'poly' else 1
        coeffs = np.polyfit(x, y, deg)
        y = y - np.polyval(coeffs, x)

    # Difference
    if difference:
        y = np.diff(y)

    # Standardize
    mean, std = np.mean(y), np.std(y)
    if std < 1e-10:
        return {'has_seasonality': False, 'n_significant_peaks': 0, 'warning': 'Near-constant series'}
    y = (y - mean) / std

    # Window
    window = signal.windows.hann(len(y))
    window_power = np.mean(window ** 2)
    y_windowed = y * window / np.sqrt(window_power)

    n = len(y_windowed)
    max_period = min(max_period, n // 2)

    # Compute PSD
    fft_vals = np.fft.rfft(y_windowed)
    psd = np.abs(fft_vals) ** 2 / n
    freqs = np.fft.rfftfreq(n, d=1.0)

    # Find peaks
    valid_mask = freqs > 0
    f_min = 1.0 / max_period if max_period > 0 else 0
    f_max = min(1.0 / min_period if min_period > 0 else 0.5, 0.5)
    valid_mask &= (freqs >= f_min) & (freqs <= f_max)

    if not valid_mask.any():
        return {'has_seasonality': False, 'n_significant_peaks': 0, 'peaks': []}

    valid_idx = np.where(valid_mask)[0]
    psd_valid = psd[valid_mask]
    freqs_valid = freqs[valid_mask]

    median_psd = np.median(psd_valid)
    if median_psd <= 0:
        median_psd = np.mean(psd_valid) + 1e-10

    min_prominence = median_psd * MIN_PROMINENCE_RATIO

    try:
        peak_indices, properties = signal.find_peaks(psd_valid, prominence=min_prominence, distance=2)
    except:
        peak_indices = []
        for i in range(1, len(psd_valid) - 1):
            if psd_valid[i] > psd_valid[i-1] and psd_valid[i] > psd_valid[i+1]:
                if psd_valid[i] > median_psd * MIN_PROMINENCE_RATIO:
                    peak_indices.append(i)
        peak_indices = np.array(peak_indices)
        properties = {}

    if len(peak_indices) == 0:
        return {'has_seasonality': False, 'n_significant_peaks': 0, 'peaks': [], 'strength': 0.0, 'p_value': 1.0}

    candidates = []
    for i, local_idx in enumerate(peak_indices):
        global_idx = valid_idx[local_idx]
        freq = freqs[global_idx]
        power = psd[global_idx]
        period = 1.0 / freq if freq > 0 else np.inf

        noise_mask = np.ones(len(psd_valid), dtype=bool)
        start = max(0, local_idx - NOISE_EXCLUSION_BINS)
        end = min(len(psd_valid), local_idx + NOISE_EXCLUSION_BINS + 1)
        noise_mask[start:end] = False

        noise_level = np.median(psd_valid[noise_mask]) if noise_mask.any() else median_psd
        if noise_level <= 0:
            noise_level = 1e-10

        ratio = power / noise_level

        candidates.append({
            'period': float(period),
            'frequency': float(freq),
            'power': float(power),
            'ratio': float(ratio)
        })

    candidates.sort(key=lambda x: x['ratio'], reverse=True)
    n_significant_peaks = sum(1 for c in candidates if c['ratio'] >= HEURISTIC_RATIO_THRESHOLD)
    candidates = candidates[:TOP_K_PEAKS]

    dominant = candidates[0]
    observed_ratio = dominant['ratio']
    dominant_period = dominant['period']

    period_ok = dominant_period <= max_period * BOUNDARY_EXCLUSION_RATIO
    has_seasonality_heuristic = (observed_ratio >= HEURISTIC_RATIO_THRESHOLD) and period_ok

    # Bootstrap p-value (simplified)
    # Ensure n_bootstrap is large enough that 1/(n+1) < alpha, otherwise
    # the minimum achievable p-value would exceed alpha and detection
    # would always fail regardless of signal strength.
    if n_bootstrap > 0 and alpha > 0:
        min_needed = int(np.ceil(1.0 / alpha))
        n_bootstrap = max(n_bootstrap, min_needed)

    if has_seasonality_heuristic and n_bootstrap > 0:
        rng = np.random.default_rng(seed)
        surrogate_ratios = []

        # Estimate AR(1) phi from the standardized series and compute the
        # theoretical AR(1) power spectrum. We whiten both the observed and
        # surrogate PSDs by dividing by this spectrum before comparing
        # max/median ratios. Without whitening, high-phi AR(1) noise has a
        # steep red spectrum whose max/median ratio is naturally large,
        # making it hard to distinguish periodic peaks from spectral slope.
        phi = np.corrcoef(y[:-1], y[1:])[0, 1] if len(y) > 1 else 0.0
        if np.isnan(phi):
            phi = 0.0
        phi = np.clip(phi, -0.99, 0.99)

        ar1_psd = 1.0 / np.abs(1 - phi * np.exp(-2j * np.pi * freqs)) ** 2
        ar1_valid = ar1_psd[valid_mask]

        # Recompute observed ratio on whitened spectrum
        whitened_valid = psd_valid / ar1_valid
        whitened_median = np.median(whitened_valid)
        if whitened_median <= 0:
            whitened_median = np.mean(whitened_valid) + 1e-10
        observed_ratio_whitened = np.max(whitened_valid) / whitened_median

        innovation_std = np.sqrt(1 - phi**2)

        for _ in range(n_bootstrap):
            surrogate = np.zeros(len(y))
            surrogate[0] = rng.normal(0, 1.0)
            for i in range(1, len(y)):
                surrogate[i] = phi * surrogate[i-1] + rng.normal(0, innovation_std)

            surrogate = (surrogate - np.mean(surrogate)) / np.std(surrogate)
            window = signal.windows.hann(len(surrogate))
            surrogate_windowed = surrogate * window / np.sqrt(np.mean(window ** 2))

            fft_s = np.fft.rfft(surrogate_windowed)
            psd_s = np.abs(fft_s) ** 2 / len(surrogate_windowed)

            psd_s_valid = psd_s[valid_mask[:len(psd_s)]] if len(psd_s) >= len(valid_mask) else psd_s
            if len(psd_s_valid) > 0:
                whitened_s = psd_s_valid / ar1_valid[:len(psd_s_valid)]
                med_s = np.median(whitened_s)
                surrogate_ratios.append(np.max(whitened_s) / med_s if med_s > 0 else 1.0)

        p_value = (np.sum(np.array(surrogate_ratios) >= observed_ratio_whitened) + 1) / (n_bootstrap + 1)
        has_seasonality = has_seasonality_heuristic and p_value < alpha
    else:
        p_value = 1.0 if not has_seasonality_heuristic else 0.0
        has_seasonality = has_seasonality_heuristic

    return {
        'has_seasonality': has_seasonality,
        'dominant_period': dominant_period if has_seasonality else None,
        'strength': observed_ratio,
        'p_value': p_value,
        'peaks': candidates,
        'n_significant_peaks': n_significant_peaks if has_seasonality else 0
    }


# =============================================================================
# COLUMN DETECTION
# =============================================================================

def detect_columns(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Auto-detect date, target, and channel columns in a DataFrame.

    Args:
        df: Input DataFrame

    Returns:
        Dict with detected column names for date, target, channels, controls
    """
    import re

    result = {
        'date': None,
        'target': None,
        'channels': [],
        'controls': []
    }

    # Date detection
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            result['date'] = col
            break
        if pd.api.types.is_string_dtype(df[col]):
            try:
                parsed = pd.to_datetime(df[col].head(100))
                if parsed.notna().all() and parsed.dt.year.min() >= 1900:
                    result['date'] = col
                    break
            except:
                pass

    # Target detection
    exact_targets = ['y', 'target', 'response', 'sales', 'revenue', 'conversions', 'outcome']
    target_patterns = ['sales', 'revenue', 'conversion', 'response', 'target', 'kpi', 'outcome']

    for col in df.columns:
        col_lower = col.lower().strip()
        if col_lower in exact_targets and pd.api.types.is_numeric_dtype(df[col]):
            result['target'] = col
            break
        if any(p in col_lower for p in target_patterns) and pd.api.types.is_numeric_dtype(df[col]):
            result['target'] = col
            break

    # Channel detection
    spend_patterns = ['spend', 'cost', 'budget', 'investment']
    media_patterns = ['tv', 'radio', 'digital', 'social', 'search', 'display',
                      'facebook', 'google', 'meta', 'youtube', 'email']
    synthetic_pattern = re.compile(r'^x\d+$|^x\d+_ch\d+$|^x\d+_\w+$|^channel_?\d+$', re.IGNORECASE)

    control_patterns = ['price', 'promo', 'discount', 'holiday', 'event', 'season',
                        'weather', 'temp', 'economic', 'index', 'trend']

    excluded = {result['date'], result['target']}

    for col in df.columns:
        if col in excluded:
            continue
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue

        col_lower = col.lower()

        if any(p in col_lower for p in control_patterns):
            result['controls'].append(col)
        elif any(p in col_lower for p in spend_patterns):
            result['channels'].append(col)
        elif any(p in col_lower for p in media_patterns):
            result['channels'].append(col)
        elif synthetic_pattern.match(col):
            result['channels'].append(col)

    return result


# =============================================================================
# MAIN ANALYSIS FUNCTION
# =============================================================================

def analyze_mmm_statistics(
    df: pd.DataFrame,
    date_col: Optional[str] = None,
    target_col: Optional[str] = None,
    channel_cols: Optional[List[str]] = None,
    control_cols: Optional[List[str]] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Statistical analysis for MMM data, focused on model specification decisions.

    Analyzes 4 key areas that inform MMM model specification:
    1. Stationarity + Trend → whether to include trend component
    2. Target Seasonality (FFT) → whether to include Fourier terms
    3. VIF/Multicollinearity → whether channels can be separated
    4. Channel-Target Correlation → which channels have signal

    Args:
        df: DataFrame with MMM data (one row per time period)
        date_col: Date column name (auto-detect if None)
        target_col: Target column name (auto-detect if None)
        channel_cols: List of channel column names (auto-detect if None)
        control_cols: List of control column names (auto-detect if None)
        verbose: Print formatted output to console

    Returns:
        Dict with analysis results including:
        - columns: detected/used columns
        - target_adf, target_kpss: stationarity test results
        - target_trend: trend analysis results
        - target_seasonality: FFT seasonality detection results
        - multicollinearity: VIF and correlation results
        - channel_correlations: correlation of each channel with target
        - stationarity_decision: 'STATIONARY', 'NON-STATIONARY', or 'MIXED'
        - vif_decision: 'OK', 'MODERATE', 'SEVERE', or 'ERROR'
        - strong_channels, moderate_channels, weak_channels: channel categorization

    Example:
        >>> results = analyze_mmm_statistics(
        ...     df,
        ...     date_col='date',
        ...     target_col='sales',
        ...     channel_cols=['tv_spend', 'radio_spend']
        ... )
        >>> print(results['stationarity_decision'])
        'STATIONARY'
    """
    results = {}
    report_lines = []

    def report(line: str = ""):
        report_lines.append(line)

    # Auto-detect columns if not provided
    if not all([date_col, target_col, channel_cols]):
        detected = detect_columns(df)
        date_col = date_col or detected['date']
        target_col = target_col or detected['target']
        channel_cols = channel_cols or detected['channels']
        control_cols = control_cols or detected.get('controls', [])

    if not date_col or not target_col or not channel_cols:
        return {'error': 'Could not detect required columns. Please specify date_col, target_col, channel_cols'}

    results['columns'] = {
        'date': date_col,
        'target': target_col,
        'channels': channel_cols,
        'controls': control_cols or []
    }

    # Convert and sort by date
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)

    n_rows = len(df)
    n_unique_dates = df[date_col].nunique()
    n_channels = len(channel_cols)

    # Check for panel data
    if n_unique_dates < n_rows:
        n_repeats = n_rows // n_unique_dates

        potential_dims = []
        for col in df.columns:
            if col in [date_col, target_col] + channel_cols + (control_cols or []):
                continue
            if df[col].dtype == 'object' or df[col].nunique() < 50:
                unique_per_date = df.groupby(date_col)[col].nunique().mean()
                if unique_per_date > 1:
                    potential_dims.append((col, df[col].nunique()))

        if verbose:
            print(f"\n{'='*80}")
            print("PANEL DATA DETECTED".center(80))
            print(f"{'='*80}")
            print(f"\nData has {n_rows} rows but only {n_unique_dates} unique dates")
            print(f"Average {n_repeats:.1f} rows per date")
            if potential_dims:
                print(f"\nLikely dimension columns:")
                for col, nunique in potential_dims[:3]:
                    print(f"  - {col}: {nunique} unique values")
            print(f"\nThis function requires one row per time period.")
            print(f"Filter or aggregate data before calling this function.")

        results['error'] = 'panel_data'
        results['n_rows'] = n_rows
        results['n_unique_dates'] = n_unique_dates
        results['potential_dimensions'] = potential_dims
        return results

    target = df[target_col]

    # Build report header
    report("# MMM Statistical Analysis Report")
    report(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report(f"**Rows:** {n_rows}, **Channels:** {n_channels}")
    report(f"\n**Date column:** {date_col}")
    report(f"**Target column:** {target_col}")
    report(f"**Channel columns:** {', '.join(channel_cols[:10])}" + (f" (+{n_channels-10} more)" if n_channels > 10 else ""))

    # 1. STATIONARITY + TREND
    report("\n---\n## 1. Stationarity & Trend Analysis\n")
    report("**Model decision:** Whether to include a trend component\n")

    adf_result = test_stationarity_adf(target)
    if 'error' not in adf_result:
        results['target_adf'] = adf_result
        report(f"### ADF Test")
        report(f"- **Result:** {adf_result['interpretation']}")
        report(f"- Statistic: {adf_result['statistic']:.4f}")
        report(f"- p-value: {adf_result['p_value']:.4f}")

    kpss_result = test_stationarity_kpss(target)
    if 'error' not in kpss_result:
        results['target_kpss'] = kpss_result
        report(f"\n### KPSS Test")
        report(f"- **Result:** {kpss_result['interpretation']}")
        report(f"- Statistic: {kpss_result['statistic']:.4f}")
        report(f"- p-value: {kpss_result['p_value']:.4f}")

    trend_result = analyze_trend(target)
    if 'error' not in trend_result:
        results['target_trend'] = trend_result
        report(f"\n### Trend Analysis")
        report(f"- **Direction:** {trend_result['trend_direction']}")
        report(f"- **Significant:** {'Yes' if trend_result['trend_significant'] else 'No'}")
        report(f"- Slope: {trend_result['slope']:.4f} per period")
        report(f"- R²: {trend_result['r_squared']:.4f}")

    # Stationarity decision
    adf_stat = adf_result.get('is_stationary', False) if 'error' not in adf_result else None
    kpss_stat = kpss_result.get('is_stationary', False) if 'error' not in kpss_result else None
    trend_sig = trend_result.get('trend_significant', False) if 'error' not in trend_result else False

    if adf_stat and kpss_stat:
        stationarity_decision = "STATIONARY"
    elif not adf_stat and not kpss_stat:
        stationarity_decision = "NON-STATIONARY"
    else:
        stationarity_decision = "MIXED"

    results['stationarity_decision'] = stationarity_decision
    results['trend_significant'] = trend_sig

    # 2. SEASONALITY (FFT)
    report("\n---\n## 2. Seasonality Detection (FFT)\n")
    report("**Model decision:** Whether to include Fourier terms\n")

    try:
        fft_result = detect_seasonality_fft(
            target.values,
            detrend='poly',
            max_period=min(len(target) // 2, 104),
            min_period=2,
            alpha=0.01,
            n_bootstrap=200,
        )
        results['target_seasonality'] = fft_result

        report(f"### FFT Spectral Analysis")
        report(f"- **Seasonality detected:** {'Yes' if fft_result.get('has_seasonality') else 'No'}")

        if fft_result.get('has_seasonality'):
            period = fft_result['dominant_period']
            report(f"- **Dominant period:** {period:.1f} samples")
            report(f"- **Significant spectral peaks:** {fft_result['n_significant_peaks']}")
            report(f"- Strength: {fft_result['strength']:.1f}")
            report(f"- p-value: {fft_result['p_value']:.4f}")
        else:
            strength = fft_result.get('strength', 0)
            p_val = fft_result.get('p_value', 1.0)
            if strength >= 10 and p_val >= 0.01:
                report(f"- Raw spectral ratio: {strength:.1f} (above heuristic threshold of 10)")
                report(f"- **But rejected by AR(1) bootstrap test** (p={p_val:.4f}, need < 0.01)")
                report(f"- Interpretation: the peak is explained by autocorrelation (red noise), not true periodicity")
            else:
                report(f"- Strength: {strength:.1f} (threshold: 10)")
    except Exception as e:
        results['target_seasonality'] = {'error': str(e), 'has_seasonality': False}

    # 3. MULTICOLLINEARITY (VIF)
    report("\n---\n## 3. Multicollinearity Analysis (VIF)\n")
    report("**Model decision:** Whether channels can be separated\n")

    if len(channel_cols) >= 2:
        multicol = analyze_multicollinearity(df, channel_cols)
        results['multicollinearity'] = multicol

        if 'error' not in multicol:
            report("| Channel | VIF | Severity |")
            report("|---------|-----|----------|")
            for item in multicol['vif_scores']:
                report(f"| {item['channel']} | {item['vif']:.2f} | {item['severity']} |")

            if multicol['high_correlation_pairs']:
                report(f"\n### Highly Correlated Pairs (|r| > 0.7)")
                for c1, c2, corr in multicol['high_correlation_pairs']:
                    report(f"- {c1} ↔ {c2}: r = {corr:.3f}")

            if multicol['severe_multicollinearity']:
                results['vif_decision'] = "SEVERE"
            elif multicol['has_multicollinearity_issues']:
                results['vif_decision'] = "MODERATE"
            else:
                results['vif_decision'] = "OK"
        else:
            results['vif_decision'] = "ERROR"
    else:
        results['vif_decision'] = "N/A"

    # 4. CHANNEL-TARGET CORRELATIONS
    report("\n---\n## 4. Channel-Target Correlations\n")
    report("**Model decision:** Which channels likely have signal\n")

    results['channel_correlations'] = {}
    correlations = []

    for col in channel_cols:
        corr = target.corr(df[col])
        results['channel_correlations'][col] = corr
        correlations.append((col, corr))

    correlations.sort(key=lambda x: abs(x[1]) if not pd.isna(x[1]) else 0, reverse=True)

    report("| Channel | Correlation | Signal Strength |")
    report("|---------|-------------|-----------------|")
    for col, corr in correlations:
        if pd.isna(corr):
            strength = "N/A"
            corr_str = "NaN"
        elif abs(corr) > 0.3:
            strength = "Strong"
            corr_str = f"{corr:+.3f}"
        elif abs(corr) > 0.1:
            strength = "Moderate"
            corr_str = f"{corr:+.3f}"
        else:
            strength = "Weak/None"
            corr_str = f"{corr:+.3f}"
        report(f"| {col} | {corr_str} | {strength} |")

    strong_channels = [c for c, r in correlations if not pd.isna(r) and abs(r) > 0.3]
    moderate_channels = [c for c, r in correlations if not pd.isna(r) and 0.1 < abs(r) <= 0.3]
    weak_channels = [c for c, r in correlations if pd.isna(r) or abs(r) <= 0.1]

    results['strong_channels'] = strong_channels
    results['moderate_channels'] = moderate_channels
    results['weak_channels'] = weak_channels

    # Store report
    results['report'] = '\n'.join(report_lines)

    # Print to console if verbose
    if verbose:
        print(f"\n{'='*80}")
        print("MMM ANALYSIS SUMMARY".center(80))
        print(f"{'='*80}")
        print(f"\nRows: {n_rows}, Channels: {n_channels}")

        print(f"\n1. Trend Component:")
        if stationarity_decision == "NON-STATIONARY" or trend_sig:
            print(f"   → Include trend (non-stationary or significant trend)")
        else:
            print(f"   → No trend needed (stationary, no significant trend)")

        print(f"\n2. Fourier Terms:")
        if results.get('target_seasonality', {}).get('has_seasonality'):
            period = results['target_seasonality']['dominant_period']
            n_peaks = results['target_seasonality']['n_significant_peaks']
            print(f"   → Seasonality detected (period ~{period:.0f}, {n_peaks} significant peaks)")
        else:
            print(f"   → No significant seasonality")

        print(f"\n3. Channel Separation:")
        vif = results.get('vif_decision', 'N/A')
        if vif == "SEVERE":
            print(f"   → Severe multicollinearity - consider grouping")
        elif vif == "MODERATE":
            print(f"   → Moderate multicollinearity - monitor stability")
        else:
            print(f"   → Channels can be modeled separately")

        print(f"\n4. Channel Signal:")
        print(f"   Strong: {len(strong_channels)}, Moderate: {len(moderate_channels)}, Weak: {len(weak_channels)}")
        if strong_channels:
            print(f"   Top: {', '.join(strong_channels[:3])}")

        print(f"\n{'─'*80}")
        print("DETAILED REPORT")
        print(f"{'─'*80}")
        print(results['report'])

    return results


# =============================================================================
# CONVENIENCE FUNCTIONS FOR SCRIPTING
# =============================================================================

def analyze_per_dimension(
    df: pd.DataFrame,
    dimension_col: str,
    date_col: str,
    target_col: str,
    channel_cols: List[str],
    verbose: bool = False
) -> Dict[str, Dict[str, Any]]:
    """
    Run statistical analysis for each unique value in a dimension column.

    Useful for panel data where you want to analyze each geo/brand separately.

    Args:
        df: DataFrame with panel data
        dimension_col: Column containing dimension values (e.g., 'brand', 'geo')
        date_col: Date column name
        target_col: Target column name
        channel_cols: List of channel column names
        verbose: Print progress

    Returns:
        Dict mapping dimension values to their analysis results

    Example:
        >>> results = analyze_per_dimension(
        ...     df, 'brand', 'date', 'sales', ['tv_spend', 'radio_spend']
        ... )
        >>> for brand, result in results.items():
        ...     print(f"{brand}: {result['stationarity_decision']}")
    """
    results = {}
    unique_values = df[dimension_col].unique()

    for value in unique_values:
        if verbose:
            print(f"\nAnalyzing {dimension_col}={value}...")

        df_filtered = df[df[dimension_col] == value].copy()

        result = analyze_mmm_statistics(
            df_filtered,
            date_col=date_col,
            target_col=target_col,
            channel_cols=channel_cols,
            verbose=False
        )

        results[value] = result

        if verbose and 'error' not in result:
            print(f"  Stationarity: {result.get('stationarity_decision', 'N/A')}")
            print(f"  Seasonality: {'Yes' if result.get('target_seasonality', {}).get('has_seasonality') else 'No'}")
            print(f"  VIF: {result.get('vif_decision', 'N/A')}")

    return results


def analyze_aggregated(
    df: pd.DataFrame,
    date_col: str,
    target_col: str,
    channel_cols: List[str],
    agg_func: str = 'sum',
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Aggregate panel data across dimensions and run statistical analysis.

    Args:
        df: DataFrame with panel data
        date_col: Date column name
        target_col: Target column name
        channel_cols: List of channel column names
        agg_func: Aggregation function ('sum' or 'mean')
        verbose: Print results

    Returns:
        Analysis results for aggregated data

    Example:
        >>> results = analyze_aggregated(
        ...     df, 'date', 'sales', ['tv_spend', 'radio_spend'], agg_func='sum'
        ... )
    """
    agg_dict = {target_col: agg_func}
    for col in channel_cols:
        agg_dict[col] = agg_func

    df_agg = df.groupby(date_col).agg(agg_dict).reset_index()

    return analyze_mmm_statistics(
        df_agg,
        date_col=date_col,
        target_col=target_col,
        channel_cols=channel_cols,
        verbose=verbose
    )
