"""
Tests for statistical analysis functions (excluding detect_seasonality_fft,
which has its own test file).

Covers:
1. test_stationarity_adf — ADF unit root test
2. test_stationarity_kpss — KPSS stationarity test
3. analyze_trend — linear trend detection
4. analyze_multicollinearity — VIF and correlation analysis
5. detect_columns — auto-detection of date/target/channel columns
6. analyze_mmm_statistics — integration test for the main entry point
"""

import sys
sys.path.insert(0, '/home/ubuntu/decision-lab/decision-packs/mmm/docker')

import numpy as np
import pandas as pd
import pytest
from mmm_lib.statistical_analysis import (
    test_stationarity_adf as run_adf,
    test_stationarity_kpss as run_kpss,
    analyze_trend,
    analyze_multicollinearity,
    detect_columns,
    analyze_mmm_statistics,
)


# ============================================================================
# FIXTURES
# ============================================================================

def make_stationary_series(n=200, seed=42):
    """White noise — stationary by construction."""
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0, 1, n))


def make_nonstationary_series(n=200, seed=42):
    """Random walk — non-stationary by construction."""
    rng = np.random.default_rng(seed)
    return pd.Series(np.cumsum(rng.normal(0, 1, n)))


def make_trending_series(n=200, slope=0.5, noise_std=0.1, seed=42):
    """Linear trend + noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    return pd.Series(slope * t + rng.normal(0, noise_std, n))


def make_mmm_dataframe(n=100, n_channels=3, seed=42):
    """Minimal MMM-like DataFrame with date, target, channels."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="W")
    data = {"date_week": dates}
    for i in range(n_channels):
        data[f"channel_{i}_spend"] = rng.exponential(100, n)
    data["revenue"] = (
        sum(data[f"channel_{i}_spend"] * rng.uniform(0.5, 2.0)
            for i in range(n_channels))
        + rng.normal(0, 50, n)
    )
    return pd.DataFrame(data)


# ============================================================================
# ADF TEST
# ============================================================================

class TestStationarityADF:
    def test_stationary_series(self):
        result = run_adf(make_stationary_series())
        assert 'error' not in result
        assert result['is_stationary'] == True
        assert result['p_value'] < 0.05

    def test_nonstationary_series(self):
        result = run_adf(make_nonstationary_series())
        assert 'error' not in result
        assert result['is_stationary'] == False
        assert result['p_value'] >= 0.05

    def test_too_short(self):
        result = run_adf(pd.Series([1, 2, 3]))
        assert 'error' in result

    def test_with_nans(self):
        s = make_stationary_series(n=200)
        s.iloc[10] = np.nan
        s.iloc[50] = np.nan
        result = run_adf(s)
        assert 'error' not in result
        assert 'is_stationary' in result

    def test_result_keys(self):
        result = run_adf(make_stationary_series())
        expected_keys = {
            'test', 'statistic', 'p_value', 'lags_used',
            'n_obs', 'critical_values', 'is_stationary', 'interpretation',
        }
        assert expected_keys.issubset(result.keys())

    def test_trending_series_is_nonstationary(self):
        s = make_trending_series(n=200, slope=1.0, noise_std=0.1)
        result = run_adf(s)
        assert 'error' not in result
        assert result['is_stationary'] == False


# ============================================================================
# KPSS TEST
# ============================================================================

class TestStationarityKPSS:
    def test_stationary_series(self):
        result = run_kpss(make_stationary_series())
        assert 'error' not in result
        assert result['is_stationary'] == True
        assert result['p_value'] >= 0.05

    def test_nonstationary_series(self):
        result = run_kpss(make_nonstationary_series())
        assert 'error' not in result
        assert result['is_stationary'] == False

    def test_too_short(self):
        result = run_kpss(pd.Series([1, 2, 3]))
        assert 'error' in result

    def test_with_nans(self):
        s = make_stationary_series(n=200)
        s.iloc[10] = np.nan
        result = run_kpss(s)
        assert 'error' not in result
        assert 'is_stationary' in result

    def test_result_keys(self):
        result = run_kpss(make_stationary_series())
        expected_keys = {
            'test', 'statistic', 'p_value', 'lags_used',
            'critical_values', 'is_stationary', 'interpretation',
        }
        assert expected_keys.issubset(result.keys())

    def test_trending_series_is_nonstationary(self):
        s = make_trending_series(n=200, slope=1.0, noise_std=0.1)
        result = run_kpss(s)
        assert 'error' not in result
        assert result['is_stationary'] == False


# ============================================================================
# ADF + KPSS AGREEMENT
# ============================================================================

class TestStationarityAgreement:
    """Both tests should agree on clear-cut cases."""

    def test_agree_stationary(self):
        s = make_stationary_series(n=300)
        adf = run_adf(s)
        kpss = run_kpss(s)
        assert adf['is_stationary'] == True
        assert kpss['is_stationary'] == True

    def test_agree_nonstationary(self):
        s = make_nonstationary_series(n=300)
        adf = run_adf(s)
        kpss = run_kpss(s)
        assert adf['is_stationary'] == False
        assert kpss['is_stationary'] == False


# ============================================================================
# TREND ANALYSIS
# ============================================================================

class TestAnalyzeTrend:
    def test_upward_trend(self):
        s = make_trending_series(n=200, slope=0.5, noise_std=0.1)
        result = analyze_trend(s)
        assert 'error' not in result
        assert result['trend_significant'] == True
        assert result['trend_direction'] == 'Upward'
        assert result['slope'] > 0

    def test_downward_trend(self):
        s = make_trending_series(n=200, slope=-0.5, noise_std=0.1)
        result = analyze_trend(s)
        assert 'error' not in result
        assert result['trend_significant'] == True
        assert result['trend_direction'] == 'Downward'
        assert result['slope'] < 0

    def test_no_trend(self):
        s = make_stationary_series(n=200)
        result = analyze_trend(s)
        assert 'error' not in result
        assert result['trend_significant'] == False
        assert result['trend_direction'] == 'No significant trend'

    def test_too_short(self):
        result = analyze_trend(pd.Series([1, 2, 3]))
        assert 'error' in result

    def test_result_keys(self):
        result = analyze_trend(make_trending_series())
        expected_keys = {
            'slope', 'intercept', 'r_squared', 'p_value', 'std_err',
            'trend_direction', 'trend_significant', 'total_pct_change',
        }
        assert expected_keys == set(result.keys())

    def test_r_squared_high_for_clean_trend(self):
        s = make_trending_series(n=200, slope=1.0, noise_std=0.01)
        result = analyze_trend(s)
        assert result['r_squared'] > 0.99

    def test_r_squared_low_for_noise(self):
        s = make_stationary_series(n=200)
        result = analyze_trend(s)
        assert result['r_squared'] < 0.1

    def test_with_nans(self):
        s = make_trending_series(n=200, slope=0.5, noise_std=0.1)
        s.iloc[5] = np.nan
        s.iloc[100] = np.nan
        result = analyze_trend(s)
        assert 'error' not in result
        assert result['trend_significant'] == True

    def test_pct_change_positive_for_upward(self):
        s = make_trending_series(n=100, slope=1.0, noise_std=0.01)
        result = analyze_trend(s)
        assert result['total_pct_change'] > 0

    def test_pct_change_negative_for_downward(self):
        # Start high so intercept is positive, then slope down
        rng = np.random.default_rng(42)
        t = np.arange(100, dtype=float)
        s = pd.Series(500.0 - 1.0 * t + rng.normal(0, 0.01, 100))
        result = analyze_trend(s)
        assert result['total_pct_change'] < 0


# ============================================================================
# MULTICOLLINEARITY
# ============================================================================

class TestMulticollinearity:
    def test_independent_channels(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            'ch_a': rng.normal(0, 1, 100),
            'ch_b': rng.normal(0, 1, 100),
            'ch_c': rng.normal(0, 1, 100),
        })
        result = analyze_multicollinearity(df, ['ch_a', 'ch_b', 'ch_c'])
        assert 'error' not in result
        assert result['has_multicollinearity_issues'] == False
        assert result['severe_multicollinearity'] == False
        assert len(result['high_correlation_pairs']) == 0

    def test_collinear_channels(self):
        rng = np.random.default_rng(42)
        base = rng.normal(0, 1, 100)
        df = pd.DataFrame({
            'ch_a': base,
            'ch_b': base + rng.normal(0, 0.01, 100),  # nearly identical
            'ch_c': rng.normal(0, 1, 100),
        })
        result = analyze_multicollinearity(df, ['ch_a', 'ch_b', 'ch_c'])
        assert 'error' not in result
        assert result['severe_multicollinearity'] == True
        assert len(result['high_correlation_pairs']) > 0

    def test_too_few_rows(self):
        df = pd.DataFrame({
            'ch_a': [1, 2, 3],
            'ch_b': [4, 5, 6],
        })
        result = analyze_multicollinearity(df, ['ch_a', 'ch_b'])
        assert 'error' in result

    def test_vif_scores_returned(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            'ch_a': rng.normal(0, 1, 100),
            'ch_b': rng.normal(0, 1, 100),
        })
        result = analyze_multicollinearity(df, ['ch_a', 'ch_b'])
        assert 'vif_scores' in result
        assert len(result['vif_scores']) == 2
        for item in result['vif_scores']:
            assert 'channel' in item
            assert 'vif' in item
            assert 'severity' in item
            assert item['vif'] > 0


# ============================================================================
# COLUMN DETECTION
# ============================================================================

class TestDetectColumns:
    def test_detects_datetime_column(self):
        df = make_mmm_dataframe()
        result = detect_columns(df)
        assert result['date'] == 'date_week'

    def test_detects_target(self):
        df = make_mmm_dataframe()
        result = detect_columns(df)
        assert result['target'] == 'revenue'

    def test_detects_spend_channels(self):
        df = make_mmm_dataframe(n_channels=3)
        result = detect_columns(df)
        assert len(result['channels']) == 3
        for i in range(3):
            assert f'channel_{i}_spend' in result['channels']

    def test_detects_controls(self):
        df = make_mmm_dataframe()
        df['holiday_flag'] = 0
        df['temperature'] = 20.0
        result = detect_columns(df)
        assert 'holiday_flag' in result['controls']

    def test_string_date_column(self):
        df = make_mmm_dataframe()
        df['date_week'] = df['date_week'].dt.strftime('%Y-%m-%d')
        result = detect_columns(df)
        assert result['date'] == 'date_week'


# ============================================================================
# ANALYZE_MMM_STATISTICS (INTEGRATION)
# ============================================================================

class TestAnalyzeMMMStatistics:
    def test_basic_run(self):
        df = make_mmm_dataframe(n=100, n_channels=3)
        result = analyze_mmm_statistics(
            df,
            date_col='date_week',
            target_col='revenue',
            channel_cols=['channel_0_spend', 'channel_1_spend', 'channel_2_spend'],
            verbose=False,
        )
        assert 'error' not in result
        assert 'stationarity_decision' in result
        assert result['stationarity_decision'] in ('STATIONARY', 'NON-STATIONARY', 'MIXED')

    def test_has_trend_keys(self):
        df = make_mmm_dataframe(n=100)
        result = analyze_mmm_statistics(
            df,
            date_col='date_week',
            target_col='revenue',
            channel_cols=['channel_0_spend', 'channel_1_spend', 'channel_2_spend'],
            verbose=False,
        )
        assert 'target_trend' in result
        assert 'trend_significant' in result

    def test_has_seasonality_keys(self):
        df = make_mmm_dataframe(n=100)
        result = analyze_mmm_statistics(
            df,
            date_col='date_week',
            target_col='revenue',
            channel_cols=['channel_0_spend', 'channel_1_spend', 'channel_2_spend'],
            verbose=False,
        )
        assert 'target_seasonality' in result

    def test_has_channel_correlation_keys(self):
        df = make_mmm_dataframe(n=100, n_channels=3)
        channels = ['channel_0_spend', 'channel_1_spend', 'channel_2_spend']
        result = analyze_mmm_statistics(
            df,
            date_col='date_week',
            target_col='revenue',
            channel_cols=channels,
            verbose=False,
        )
        assert 'channel_correlations' in result
        for ch in channels:
            assert ch in result['channel_correlations']
        assert 'strong_channels' in result
        assert 'moderate_channels' in result
        assert 'weak_channels' in result

    def test_has_vif_decision(self):
        df = make_mmm_dataframe(n=100, n_channels=3)
        result = analyze_mmm_statistics(
            df,
            date_col='date_week',
            target_col='revenue',
            channel_cols=['channel_0_spend', 'channel_1_spend', 'channel_2_spend'],
            verbose=False,
        )
        assert 'vif_decision' in result
        assert result['vif_decision'] in ('OK', 'MODERATE', 'SEVERE', 'ERROR', 'N/A')

    def test_has_report_string(self):
        df = make_mmm_dataframe(n=100)
        result = analyze_mmm_statistics(
            df,
            date_col='date_week',
            target_col='revenue',
            channel_cols=['channel_0_spend', 'channel_1_spend', 'channel_2_spend'],
            verbose=False,
        )
        assert 'report' in result
        assert isinstance(result['report'], str)
        assert len(result['report']) > 0

    def test_auto_detects_columns(self):
        df = make_mmm_dataframe(n=100, n_channels=3)
        result = analyze_mmm_statistics(df, verbose=False)
        assert 'error' not in result
        assert 'columns' in result
        assert result['columns']['date'] == 'date_week'
        assert result['columns']['target'] == 'revenue'

    def test_panel_data_returns_error(self):
        """Panel data (repeated dates) should be detected and rejected."""
        df = make_mmm_dataframe(n=50, n_channels=2)
        # Duplicate the dataframe with a region column to simulate panel data
        df1 = df.copy()
        df1['region'] = 'north'
        df2 = df.copy()
        df2['region'] = 'south'
        panel_df = pd.concat([df1, df2], ignore_index=True)
        result = analyze_mmm_statistics(
            panel_df,
            date_col='date_week',
            target_col='revenue',
            channel_cols=['channel_0_spend', 'channel_1_spend'],
            verbose=False,
        )
        assert result.get('error') == 'panel_data'

    def test_detects_trend_in_trending_data(self):
        """If target has a strong trend, trend_significant should be True."""
        rng = np.random.default_rng(42)
        n = 100
        dates = pd.date_range("2020-01-01", periods=n, freq="W")
        t = np.arange(n, dtype=float)
        df = pd.DataFrame({
            'date_week': dates,
            'revenue': 1000 + 10 * t + rng.normal(0, 5, n),
            'tv_spend': rng.exponential(100, n),
            'radio_spend': rng.exponential(50, n),
        })
        result = analyze_mmm_statistics(
            df,
            date_col='date_week',
            target_col='revenue',
            channel_cols=['tv_spend', 'radio_spend'],
            verbose=False,
        )
        assert result['trend_significant'] == True
        assert result['target_trend']['trend_direction'] == 'Upward'

    def test_no_trend_in_flat_data(self):
        """If target is stationary noise, trend_significant should be False."""
        rng = np.random.default_rng(42)
        n = 100
        dates = pd.date_range("2020-01-01", periods=n, freq="W")
        df = pd.DataFrame({
            'date_week': dates,
            'revenue': 1000 + rng.normal(0, 5, n),
            'tv_spend': rng.exponential(100, n),
            'radio_spend': rng.exponential(50, n),
        })
        result = analyze_mmm_statistics(
            df,
            date_col='date_week',
            target_col='revenue',
            channel_cols=['tv_spend', 'radio_spend'],
            verbose=False,
        )
        assert result['trend_significant'] == False
