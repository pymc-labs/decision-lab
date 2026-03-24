# Data Exploration Summary

## Dataset Overview
- **File**: `marketing_spend_weekly.csv`
- **Rows**: 156 (3 years of weekly data, 2023-01 to 2025-12)
- **Columns**: 12

## Target Variable
- **`revenue`**: Weekly revenue in USD
  - Mean: $8.2M | Median: $7.9M | Std: $2.1M
  - No missing values
  - Mild right skew (0.34)

## Channel Spend Columns (5 channels)
| Channel | Weekly Mean | Weekly Median | % Zero Weeks | Correlation w/ Revenue |
|---------|-----------|--------------|-------------|----------------------|
| tv_spend | $680K | $720K | 2.6% | 0.61 |
| digital_spend | $520K | $510K | 0% | 0.73 |
| social_spend | $380K | $360K | 0% | 0.58 |
| search_spend | $440K | $430K | 0% | 0.69 |
| print_spend | $180K | $170K | 8.3% | 0.31 |

## Control Variables
| Variable | Description | Type |
|----------|-------------|------|
| `price_index` | Relative price vs competitors | Continuous (0.85–1.15) |
| `seasonality_index` | Holiday/seasonal multiplier | Continuous (0.7–1.4) |
| `competitor_spend` | Estimated competitor total spend | Continuous ($1.2M–$3.8M) |
| `trend` | Linear time trend | Integer (1–156) |

## Data Quality
- **Missing values**: 3 missing in `competitor_spend` (weeks 45, 89, 112) — interpolated
- **Outliers**: Week 52 (Christmas) shows 2.3x typical revenue — legitimate seasonal spike
- **Stationarity**: Revenue is trend-stationary after detrending (ADF p=0.003)
- **Multicollinearity**: VIF < 3 for all channels after removing trend. TV and Digital show moderate correlation (r=0.42)

## Parameter Count Assessment
- With 5 channels × (alpha + lmax + lambda + beta) = 20 channel params + 4 control betas + intercept + sigma = 26 parameters
- 156 observations → ~6:1 ratio — sufficient but tight. Recommend informative priors.

## Recommendation
Data is suitable for MMM analysis. Recommend two data preparation approaches:
1. **Minimal cleaning**: Interpolate missing competitor_spend, keep all 156 weeks
2. **Conservative cleaning**: Drop first 8 weeks (potential cold-start), cap outliers at 95th percentile
