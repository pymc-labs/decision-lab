"""
Tests for detect_seasonality_fft function.

Covers:
1. Clear sinusoidal seasonality (should detect)
2. Multiple seasonality components
3. Pure noise / no seasonality (should NOT detect)
4. Short series (edge case)
5. Series with NaNs
6. Near-constant series
7. Series with trend + seasonality
8. Weekly seasonality in daily data
9. Yearly seasonality in weekly data
10. Deterministic seed reproducibility
11. Parameter variations (detrend, difference, alpha)
12. Edge cases (min_period >= max_period, all NaN)
"""

import sys
sys.path.insert(0, '/home/ubuntu/decision-lab/decision-packs/mmm/docker')

import numpy as np
import pandas as pd
import pytest
from mmm_lib.statistical_analysis import detect_seasonality_fft


# ============================================================================
# FIXTURES
# ============================================================================

def make_seasonal_series(n=200, period=52, amplitude=1.0, noise_std=0.1, seed=42):
    """Generate a sinusoidal series with optional noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    signal = amplitude * np.sin(2 * np.pi * t / period)
    noise = rng.normal(0, noise_std, n)
    return signal + noise


def make_noise_series(n=200, seed=42):
    """Generate pure white noise."""
    rng = np.random.default_rng(seed)
    return rng.normal(0, 1, n)


def make_trend_series(n=200, slope=0.05, seed=42):
    """Generate a linear trend with noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return slope * t + rng.normal(0, 0.5, n)


# ============================================================================
# 1. CLEAR SINUSOIDAL SEASONALITY
# ============================================================================

class TestClearSeasonality:
    def test_detects_period_52(self):
        """Strong period-52 sinusoid should be detected."""
        y = make_seasonal_series(n=208, period=52, amplitude=3.0, noise_std=0.3)
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True
        assert result['dominant_period'] is not None
        assert abs(result['dominant_period'] - 52) < 5, \
            f"Expected ~52, got {result['dominant_period']}"
        assert result['p_value'] < 0.05

    def test_detects_period_12(self):
        """Strong period-12 sinusoid (monthly in monthly data)."""
        y = make_seasonal_series(n=120, period=12, amplitude=3.0, noise_std=0.2)
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True
        assert abs(result['dominant_period'] - 12) < 2, \
            f"Expected ~12, got {result['dominant_period']}"

    def test_detects_period_7(self):
        """Weekly cycle in daily data."""
        y = make_seasonal_series(n=365, period=7, amplitude=2.0, noise_std=0.3)
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True
        assert abs(result['dominant_period'] - 7) < 1.5, \
            f"Expected ~7, got {result['dominant_period']}"

    def test_strong_signal_high_strength(self):
        """A very strong signal should have high strength (ratio)."""
        y = make_seasonal_series(n=200, period=26, amplitude=10.0, noise_std=0.1)
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True
        assert result['strength'] > 20, \
            f"Expected strength > 20 for strong signal, got {result['strength']}"


# ============================================================================
# 2. MULTIPLE SEASONALITY COMPONENTS
# ============================================================================

class TestMultipleSeasonality:
    def test_detects_dominant_of_two(self):
        """When two seasonal components exist, the stronger one should dominate."""
        t = np.arange(300)
        y = 5.0 * np.sin(2 * np.pi * t / 52) + 1.0 * np.sin(2 * np.pi * t / 12)
        y += np.random.default_rng(42).normal(0, 0.3, len(t))
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True
        assert abs(result['dominant_period'] - 52) < 5

    def test_non_sinusoidal_log_sin_squared_with_trend(self):
        """Detect log(sin(x) + 1.01)^2 + sqrt(t) + noise.

        A highly asymmetric periodic waveform (sharp spike near sin trough,
        flat elsewhere) buried under a concave sqrt(t) trend and stddev=1
        noise. Tests that poly detrending handles the non-linear trend and
        FFT still picks up the non-sinusoidal periodicity.
        """
        t = np.arange(300)
        x = 2 * np.pi * t / 52
        y = np.log(np.sin(x) + 1.01) ** 2 + np.sqrt(t)
        y += np.random.default_rng(34092).normal(0, 1.0, len(t))
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True
        assert abs(result['dominant_period'] - 52) < 5, \
            f"Expected ~52, got {result['dominant_period']}"
        # Non-sinusoidal waveform should produce harmonics in the peaks
        peak_periods = [p['period'] for p in result['peaks']]
        has_harmonic = any(abs(p - 26) < 3 for p in peak_periods)  # 52/2
        assert has_harmonic, f"Expected harmonic at ~26, got {peak_periods}"

    def test_peaks_contain_both_periods(self):
        """Both periods should appear in the peaks list."""
        t = np.arange(300)
        y = 3.0 * np.sin(2 * np.pi * t / 52) + 3.0 * np.sin(2 * np.pi * t / 12)
        y += np.random.default_rng(42).normal(0, 0.2, len(t))
        result = detect_seasonality_fft(y, seed=42)
        peak_periods = [p['period'] for p in result['peaks']]
        has_52 = any(abs(p - 52) < 5 for p in peak_periods)
        has_12 = any(abs(p - 12) < 2 for p in peak_periods)
        assert has_52, f"Expected ~52 in peaks, got {peak_periods}"
        assert has_12, f"Expected ~12 in peaks, got {peak_periods}"


# ============================================================================
# 3. NO SEASONALITY (NOISE)
# ============================================================================

class TestNoSeasonality:
    def test_white_noise(self):
        """Pure white noise should not be flagged as seasonal."""
        y = make_noise_series(n=200, seed=42)
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == False

    def test_random_walk(self):
        """A random walk should not be flagged as seasonal."""
        rng = np.random.default_rng(42)
        y = np.cumsum(rng.normal(0, 1, 200))
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == False

    def test_pure_trend(self):
        """A pure linear trend (no seasonality) should not trigger detection."""
        y = make_trend_series(n=200, slope=0.1, seed=42)
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == False


# ============================================================================
# 4. SHORT SERIES (EDGE CASES)
# ============================================================================

class TestShortSeries:
    def test_too_short(self):
        """Series with < 16 points should return has_seasonality=False with error."""
        y = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        result = detect_seasonality_fft(y)
        assert result['has_seasonality'] == False
        assert 'error' in result

    def test_exactly_16(self):
        """Series with exactly 16 points should run without error."""
        y = make_seasonal_series(n=16, period=4, amplitude=3.0, noise_std=0.1)
        result = detect_seasonality_fft(y, seed=42)
        assert 'has_seasonality' in result

    def test_barely_enough_for_period(self):
        """Series must be >= 2x the period to detect it."""
        y = make_seasonal_series(n=50, period=30, amplitude=5.0, noise_std=0.1)
        result = detect_seasonality_fft(y, seed=42)
        if result['has_seasonality'] and result['dominant_period'] is not None:
            assert result['dominant_period'] <= 25


# ============================================================================
# 5. NaN HANDLING
# ============================================================================

class TestNaNHandling:
    def test_scattered_nans(self):
        """Series with a few NaNs should still work via interpolation."""
        y = make_seasonal_series(n=200, period=26, amplitude=3.0, noise_std=0.2)
        y[10] = np.nan
        y[50] = np.nan
        y[100] = np.nan
        result = detect_seasonality_fft(y, seed=42)
        assert 'has_seasonality' in result
        assert result['has_seasonality'] == True

    def test_all_nan(self):
        """All-NaN series should return has_seasonality=False."""
        y = np.full(100, np.nan)
        result = detect_seasonality_fft(y)
        assert result['has_seasonality'] == False

    def test_leading_trailing_nans(self):
        """NaNs at start/end should be trimmed gracefully."""
        y = make_seasonal_series(n=200, period=20, amplitude=3.0, noise_std=0.2)
        y[:5] = np.nan
        y[-5:] = np.nan
        result = detect_seasonality_fft(y, seed=42)
        assert 'has_seasonality' in result


# ============================================================================
# 6. NEAR-CONSTANT SERIES
# ============================================================================

class TestNearConstant:
    def test_constant_series(self):
        """A perfectly constant series should not detect seasonality."""
        y = np.ones(100)
        result = detect_seasonality_fft(y)
        assert result['has_seasonality'] == False
        assert 'warning' in result

    def test_nearly_constant(self):
        """A nearly constant series (very tiny variance) should not detect seasonality."""
        y = np.ones(100) + np.random.default_rng(42).normal(0, 1e-12, 100)
        result = detect_seasonality_fft(y)
        assert result['has_seasonality'] == False


# ============================================================================
# 7. TREND + SEASONALITY
# ============================================================================

class TestTrendPlusSeasonality:
    def test_linear_trend_plus_seasonality(self):
        """Seasonality should be detected even with a strong linear trend."""
        t = np.arange(200)
        trend = 2.0 * t
        seasonal = 50.0 * np.sin(2 * np.pi * t / 52)
        noise = np.random.default_rng(42).normal(0, 5, len(t))
        y = trend + seasonal + noise
        result = detect_seasonality_fft(y, detrend='linear', seed=42)
        assert result['has_seasonality'] == True
        assert abs(result['dominant_period'] - 52) < 5

    def test_quadratic_trend_plus_seasonality(self):
        """Quadratic trend + seasonality should be detected with poly detrend."""
        t = np.arange(200)
        trend = 0.01 * t ** 2
        seasonal = 30.0 * np.sin(2 * np.pi * t / 26)
        noise = np.random.default_rng(42).normal(0, 3, len(t))
        y = trend + seasonal + noise
        result = detect_seasonality_fft(y, detrend='poly', seed=42)
        assert result['has_seasonality'] == True
        assert abs(result['dominant_period'] - 26) < 3

    def test_quadratic_trend_default_detrend(self):
        """Default detrend='poly' should handle quadratic trends."""
        t = np.arange(200)
        trend = 0.01 * t ** 2
        seasonal = 30.0 * np.sin(2 * np.pi * t / 26)
        noise = np.random.default_rng(42).normal(0, 3, len(t))
        y = trend + seasonal + noise
        result = detect_seasonality_fft(y, seed=42)  # uses default detrend
        assert result['has_seasonality'] == True

    def test_linear_detrend_with_quadratic_trend(self):
        """Linear detrend + quadratic trend still works thanks to whitened bootstrap.

        The residual quadratic trend inflates phi (high autocorrelation),
        but the bootstrap whitens the PSD by the theoretical AR(1) spectrum
        before comparing ratios, so the periodic peak still stands out.
        """
        t = np.arange(200)
        trend = 0.01 * t ** 2
        seasonal = 30.0 * np.sin(2 * np.pi * t / 26)
        noise = np.random.default_rng(42).normal(0, 3, len(t))
        y = trend + seasonal + noise
        result = detect_seasonality_fft(y, detrend='linear', seed=42)
        assert result['strength'] > 1000
        assert result['has_seasonality'] == True


# ============================================================================
# 8. WEEKLY SEASONALITY IN DAILY DATA
# ============================================================================

class TestWeeklyDaily:
    def test_daily_data_weekly_cycle(self):
        """365 days of data with 7-day cycle."""
        t = np.arange(365)
        y = 3.0 * np.sin(2 * np.pi * t / 7) + np.random.default_rng(42).normal(0, 0.5, 365)
        result = detect_seasonality_fft(y, min_period=2, max_period=60, seed=42)
        assert result['has_seasonality'] == True
        assert abs(result['dominant_period'] - 7) < 1.5


# ============================================================================
# 9. YEARLY SEASONALITY IN WEEKLY DATA
# ============================================================================

class TestYearlyWeekly:
    def test_weekly_data_yearly_cycle(self):
        """4 years of weekly data (~208 weeks) with period-52 cycle."""
        y = make_seasonal_series(n=208, period=52, amplitude=5.0, noise_std=0.5)
        result = detect_seasonality_fft(y, max_period=104, seed=42)
        assert result['has_seasonality'] == True
        assert abs(result['dominant_period'] - 52) < 5


# ============================================================================
# 10. SEED REPRODUCIBILITY
# ============================================================================

class TestReproducibility:
    def test_same_seed_same_result(self):
        """Same seed should produce identical results."""
        y = make_seasonal_series(n=200, period=26, amplitude=2.0, noise_std=0.5)
        r1 = detect_seasonality_fft(y, seed=123)
        r2 = detect_seasonality_fft(y, seed=123)
        assert r1['has_seasonality'] == r2['has_seasonality']
        assert r1['p_value'] == r2['p_value']
        assert r1['strength'] == r2['strength']

    def test_different_seed_same_detection(self):
        """Different seeds may give slightly different p-values but same detection decision for strong signals."""
        y = make_seasonal_series(n=200, period=26, amplitude=5.0, noise_std=0.3)
        r1 = detect_seasonality_fft(y, seed=1)
        r2 = detect_seasonality_fft(y, seed=999)
        assert r1['has_seasonality'] == r2['has_seasonality'] == True


# ============================================================================
# 11. PARAMETER VARIATIONS
# ============================================================================

class TestParameterVariations:
    def test_detrend_none(self):
        """detrend='none' should still work."""
        y = make_seasonal_series(n=200, period=26, amplitude=3.0, noise_std=0.2)
        result = detect_seasonality_fft(y, detrend='none', seed=42)
        assert result['has_seasonality'] == True

    def test_detrend_linear(self):
        """detrend='linear' should still work."""
        y = make_seasonal_series(n=200, period=26, amplitude=3.0, noise_std=0.2)
        result = detect_seasonality_fft(y, detrend='linear', seed=42)
        assert result['has_seasonality'] == True

    def test_detrend_poly(self):
        """detrend='poly' (quadratic) should work."""
        y = make_seasonal_series(n=200, period=26, amplitude=3.0, noise_std=0.2)
        result = detect_seasonality_fft(y, detrend='poly', seed=42)
        assert result['has_seasonality'] == True

    def test_difference_true(self):
        """First differencing should still detect strong seasonality."""
        y = make_seasonal_series(n=200, period=26, amplitude=5.0, noise_std=0.2)
        result = detect_seasonality_fft(y, difference=True, seed=42)
        assert result['has_seasonality'] == True

    def test_strict_alpha(self):
        """Very strict alpha should pass for very strong signals.

        The function auto-scales n_bootstrap so that 1/(n+1) < alpha,
        ensuring the minimum achievable p-value is below the threshold.
        """
        y = make_seasonal_series(n=200, period=26, amplitude=10.0, noise_std=0.1)
        result = detect_seasonality_fft(y, alpha=0.001, seed=42)
        assert result['has_seasonality'] == True
        assert result['p_value'] < 0.001

    def test_bootstrap_auto_scales_for_alpha(self):
        """n_bootstrap should be automatically increased when alpha is very small."""
        y = make_seasonal_series(n=200, period=26, amplitude=10.0, noise_std=0.1)
        # With alpha=0.0001, function needs at least 10000 bootstrap samples
        # to achieve p < 0.0001. It should auto-scale.
        result = detect_seasonality_fft(y, alpha=0.0001, n_bootstrap=50, seed=42)
        assert result['has_seasonality'] == True
        assert result['p_value'] < 0.0001

    def test_lenient_alpha(self):
        """Lenient alpha should detect borderline seasonality more easily."""
        y = make_seasonal_series(n=200, period=26, amplitude=1.5, noise_std=1.0)
        result_strict = detect_seasonality_fft(y, alpha=0.001, seed=42)
        result_lenient = detect_seasonality_fft(y, alpha=0.10, seed=42)
        if result_strict['has_seasonality']:
            assert result_lenient['has_seasonality']

    def test_custom_period_range(self):
        """Custom min/max period should restrict detection."""
        t = np.arange(200)
        y = 5.0 * np.sin(2 * np.pi * t / 10) + np.random.default_rng(42).normal(0, 0.3, 200)
        # Look only for periods 20-100 - should NOT find period 10
        result = detect_seasonality_fft(y, min_period=20, max_period=100, seed=42)
        if result['has_seasonality'] and result['dominant_period'] is not None:
            assert result['dominant_period'] >= 20

    def test_n_bootstrap_zero(self):
        """n_bootstrap=0 should skip bootstrap and use heuristic only."""
        y = make_seasonal_series(n=200, period=26, amplitude=5.0, noise_std=0.2)
        result = detect_seasonality_fft(y, n_bootstrap=0, seed=42)
        assert 'has_seasonality' in result
        if result['has_seasonality']:
            assert result['p_value'] == 0.0


# ============================================================================
# 12. EDGE CASES
# ============================================================================

class TestEdgeCases:
    def test_min_period_ge_max_period(self):
        """min_period >= max_period should return early with error."""
        y = make_seasonal_series(n=100, period=10)
        result = detect_seasonality_fft(y, min_period=50, max_period=50)
        assert result['has_seasonality'] == False
        assert 'error' in result

    def test_pandas_series_input(self):
        """Should accept pandas Series input."""
        y = pd.Series(make_seasonal_series(n=200, period=26, amplitude=3.0, noise_std=0.2))
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True

    def test_list_input(self):
        """Should accept plain Python list input."""
        y = list(make_seasonal_series(n=200, period=26, amplitude=3.0, noise_std=0.2))
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True

    def test_output_keys(self):
        """Output dictionary should always contain expected keys."""
        y = make_seasonal_series(n=200, period=26, amplitude=3.0, noise_std=0.2)
        result = detect_seasonality_fft(y, seed=42)
        expected_keys = {'has_seasonality', 'dominant_period', 'strength', 'p_value', 'peaks'}
        assert expected_keys.issubset(set(result.keys())), \
            f"Missing keys: {expected_keys - set(result.keys())}"

    def test_peaks_structure(self):
        """Each peak should have period, frequency, power, ratio."""
        y = make_seasonal_series(n=200, period=26, amplitude=3.0, noise_std=0.2)
        result = detect_seasonality_fft(y, seed=42)
        for peak in result['peaks']:
            assert 'period' in peak
            assert 'frequency' in peak
            assert 'power' in peak
            assert 'ratio' in peak
            assert peak['period'] > 0
            assert peak['power'] > 0

    def test_single_value_repeated(self):
        """Series of identical values should be constant - no seasonality."""
        y = np.full(100, 42.0)
        result = detect_seasonality_fft(y)
        assert result['has_seasonality'] == False

    def test_very_long_series(self):
        """Should handle a long series without error."""
        y = make_seasonal_series(n=5000, period=52, amplitude=3.0, noise_std=0.5)
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True
        assert abs(result['dominant_period'] - 52) < 5

    def test_output_keys_include_n_significant_peaks(self):
        """Output dictionary should always contain n_significant_peaks."""
        y = make_seasonal_series(n=200, period=26, amplitude=3.0, noise_std=0.2)
        result = detect_seasonality_fft(y, seed=42)
        assert 'n_significant_peaks' in result


# ============================================================================
# 13. SIGNIFICANT PEAK COUNTING
# ============================================================================

class TestSignificantPeakCounting:
    def test_pure_sinusoid_one_peak(self):
        """A pure sinusoid should have exactly 1 significant peak."""
        y = make_seasonal_series(n=208, period=52, amplitude=5.0, noise_std=0.2)
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True
        assert result['n_significant_peaks'] == 1

    def test_non_sinusoidal_many_peaks(self):
        """log(sin(x)+1.01)^2 + sqrt(t) + noise has multiple harmonics → many peaks."""
        t = np.arange(300)
        x = 2 * np.pi * t / 52
        y = np.log(np.sin(x) + 1.01) ** 2 + np.sqrt(t)
        y += np.random.default_rng(34092).normal(0, 1.0, len(t))
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True
        assert result['n_significant_peaks'] >= 3, \
            f"Expected >= 3 significant peaks for non-sinusoidal waveform, got {result['n_significant_peaks']}"

    def test_white_noise_zero_peaks(self):
        """Pure white noise should have 0 significant peaks."""
        y = make_noise_series(n=200, seed=42)
        result = detect_seasonality_fft(y, seed=42)
        assert result['n_significant_peaks'] == 0

    def test_no_seasonality_zero_peaks(self):
        """When has_seasonality is False, n_significant_peaks should be 0."""
        y = make_trend_series(n=200, slope=0.1, seed=42)
        result = detect_seasonality_fft(y, seed=42)
        assert result['n_significant_peaks'] == 0

    def test_two_unrelated_periods(self):
        """Two unrelated periods (not harmonics) should count as 2 peaks."""
        t = np.arange(300)
        y = 5.0 * np.sin(2 * np.pi * t / 52) + 5.0 * np.sin(2 * np.pi * t / 17)
        y += np.random.default_rng(42).normal(0, 0.3, len(t))
        result = detect_seasonality_fft(y, seed=42)
        assert result['has_seasonality'] == True
        assert result['n_significant_peaks'] >= 2, \
            f"Expected >= 2 significant peaks for two unrelated periods, got {result['n_significant_peaks']}"

    def test_too_short_series_zero_peaks(self):
        """Too-short series should return n_significant_peaks=0."""
        y = np.array([1, 2, 3, 4, 5])
        result = detect_seasonality_fft(y)
        assert result['n_significant_peaks'] == 0

    def test_constant_series_zero_peaks(self):
        """Constant series should return n_significant_peaks=0."""
        y = np.ones(100)
        result = detect_seasonality_fft(y)
        assert result['n_significant_peaks'] == 0

    def test_all_nan_zero_peaks(self):
        """All-NaN series should return n_significant_peaks=0."""
        y = np.full(100, np.nan)
        result = detect_seasonality_fft(y)
        assert result['n_significant_peaks'] == 0
