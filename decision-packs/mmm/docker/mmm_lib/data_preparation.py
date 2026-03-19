"""
Data Cleaning and Exploration Functions

This module contains all functions used for data cleaning, exploration, and preprocessing
for Marketing Mix Model analysis.

Functions are pure Python with no external tool dependencies.
"""

import io
import pandas as pd
import polars as po
import numpy as np
import matplotlib.pyplot as plt

from pathlib import Path

from typing import Optional, List, Dict, Any, Union
import warnings


# =============================================================================
# DATA LOADING FUNCTIONS
# =============================================================================

def load_csv_from_url(url: str, timeout: int = 30) -> pd.DataFrame:
    """
    Load CSV data from a remote URL.

    Args:
        url: URL to download CSV from
        timeout: Request timeout in seconds

    Returns:
        DataFrame with loaded data

    Example:
        >>> df = load_csv_from_url("https://example.com/data.csv")
    """
    return po.read_csv(url, timeout=timeout, try_parse_dates=True).to_pandas()

def load_csv_or_parquet_from_file(filepath: str, verbose: bool = True) -> pd.DataFrame:
    fileending = Path(filepath).suffix.lower()

    if fileending == '.csv':
        df = po.read_csv(filepath, try_parse_dates=True).to_pandas()
    elif fileending == '.parquet':
        df = pd.read_parquet(filepath)
    else:
        raise ValueError(f"Don't know how to open file with suffix {fileending}")

    return df


def load_csv_or_parquet_from_file_and_inspect(filepath: str) -> pd.DataFrame:
    """
    Load CSV/Parquet data from a local file path.

    Args:
        filepath: Path to CSV file
        verbose: Print loading summary (default True)

    Returns:
        DataFrame with loaded data

    Example:
        >>> df = load_csv_from_file("datasets/raw/data.csv")
    """


    df = load_csv_or_parquet_from_file(filepath)

    print(f"[load_csv_from_file] Loaded {filepath}")
    print(f"  shape: {df.shape[0]} rows x {df.shape[1]} columns")
    print(f"  columns: {list(df.columns)}")
    print(f"  Returning: pd.DataFrame")

    inspect_dataframe_basic(df)
    get_missing_value_summary(df)

    print("[duplicate row analysis]")
    dup_summary = get_duplicate_summary(df)
    print(f"   duplicate_count: {dup_summary['duplicate_count']}")
    print(f"   duplicate_percent: {dup_summary['duplicate_percent']:.2f}%")

    return df



# =============================================================================
# DATA INSPECTION FUNCTIONS
# =============================================================================

def inspect_dataframe_basic(df: pd.DataFrame, verbose: bool = True) -> Dict[str, Any]:
    """
    Get basic information about a DataFrame.

    Args:
        df: Input DataFrame
        verbose: Print inspection summary (default True)

    Returns:
        Dictionary with basic stats (shape, columns, dtypes, etc.)

    Example:
        >>> info = inspect_dataframe_basic(df)
        >>> print(f"Shape: {info['shape']}")
    """
    buffer = io.StringIO()
    df.info(buf=buffer)
    info_str = buffer.getvalue()

    result = {
        "shape": df.shape,
        "columns": list(df.columns),
        "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
        "memory_usage": {str(k): int(v) for k, v in df.memory_usage(deep=True).items()},
        "info": info_str,
        "head": df.head().to_dict('records'),
        "tail": df.tail().to_dict('records'),
    }

    if verbose:
        print(f"[inspect_dataframe_basic]")
        print(f"  shape: {result['shape']}")
        print(f"  n_columns: {len(result['columns'])}")
        print(f"  columns: {result['columns']}")
        print(f"  Returning: Dict with keys {list(result.keys())}")

    return result


def get_missing_value_summary(df: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """
    Get summary of missing values in DataFrame.

    Args:
        df: Input DataFrame
        verbose: Print missing values summary (default True)

    Returns:
        DataFrame with missing value counts and percentages

    Example:
        >>> missing_summary = get_missing_value_summary(df)
        >>> print(missing_summary)
    """
    missing_count = df.isnull().sum()
    missing_percent = (missing_count / len(df)) * 100

    summary = pd.DataFrame({
        "Missing_Count": missing_count,
        "Missing_Percent": missing_percent
    })

    result = summary[summary["Missing_Count"] > 0].sort_values(
        "Missing_Count", ascending=False
    )

    if verbose:
        print(f"[get_missing_value_summary]")
        print(f"  total_rows: {len(df)}")
        print(f"  columns_with_missing: {len(result)}")
        if len(result) > 0:
            print(f"  total_missing_values: {int(result['Missing_Count'].sum())}")
            print(f"  columns_affected: {list(result.index)}")
        else:
            print(f"  No missing values found")
        print(f"  Returning: pd.DataFrame with columns ['Missing_Count', 'Missing_Percent']")

    return result


def get_duplicate_summary(df: pd.DataFrame, subset: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Get summary of duplicate rows in DataFrame.

    Args:
        df: Input DataFrame
        subset: Columns to consider for duplicates (None = all columns)

    Returns:
        Dictionary with duplicate statistics

    Example:
        >>> dup_info = get_duplicate_summary(df, subset=["date"])
        >>> print(f"Duplicates: {dup_info['duplicate_count']}")
    """
    duplicates = df.duplicated(subset=subset)
    duplicate_rows = df[duplicates]

    return {
        "duplicate_count": duplicates.sum(),
        "duplicate_percent": (duplicates.sum() / len(df)) * 100,
        "duplicate_rows": duplicate_rows,
        "total_rows": len(df),
    }


def get_descriptive_statistics(df: pd.DataFrame, include: str = "all") -> pd.DataFrame:
    """
    Get descriptive statistics for DataFrame.

    Args:
        df: Input DataFrame
        include: Types to include ("all", "number", "object", etc.)

    Returns:
        DataFrame with descriptive statistics

    Example:
        >>> stats = get_descriptive_statistics(df, include="number")
        >>> print(stats)
    """
    return df.describe(include=include)


def get_correlation_matrix(df: pd.DataFrame, method: str = "pearson", verbose: bool = True) -> pd.DataFrame:
    """
    Calculate correlation matrix for numeric columns.

    Args:
        df: Input DataFrame
        method: Correlation method ("pearson", "spearman", "kendall")
        verbose: Print correlation summary (default True)

    Returns:
        Correlation matrix

    Example:
        >>> corr = get_correlation_matrix(df, method="pearson")
        >>> print(corr)
    """
    numeric_df = df.select_dtypes(include=[np.number])
    result = numeric_df.corr(method=method)

    if verbose:
        print(f"[get_correlation_matrix]")
        print(f"  method: {method}")
        print(f"  numeric_columns: {len(numeric_df.columns)}")
        print(f"  matrix_shape: {result.shape}")
        print(f"  Returning: pd.DataFrame (correlation matrix)")

    return result


# =============================================================================
# DATA CLEANING FUNCTIONS
# =============================================================================

def clean_column_names(df: pd.DataFrame, lowercase: bool = True,
                       replace_spaces: str = "_") -> pd.DataFrame:
    """
    Clean and standardize column names.

    Args:
        df: Input DataFrame
        lowercase: Convert to lowercase
        replace_spaces: Character to replace spaces with

    Returns:
        DataFrame with cleaned column names

    Example:
        >>> df_clean = clean_column_names(df, lowercase=True)
    """
    df = df.copy()

    # Remove leading/trailing whitespace
    df.columns = df.columns.str.strip()

    # Replace spaces
    if replace_spaces:
        df.columns = df.columns.str.replace(" ", replace_spaces)

    # Convert to lowercase
    if lowercase:
        df.columns = df.columns.str.lower()

    return df


def handle_missing_values(df: pd.DataFrame,
                          strategy: str = "drop",
                          fill_value: Any = None,
                          columns: Optional[List[str]] = None,
                          verbose: bool = True) -> pd.DataFrame:
    """
    Handle missing values in DataFrame.

    Args:
        df: Input DataFrame
        strategy: "drop", "fill", "ffill", "bfill", "interpolate"
        fill_value: Value to fill (if strategy="fill")
        columns: Specific columns to process (None = all)
        verbose: Print handling summary (default True)

    Returns:
        DataFrame with missing values handled

    Example:
        >>> df_clean = handle_missing_values(df, strategy="drop")
        >>> df_filled = handle_missing_values(df, strategy="fill", fill_value=0)
    """
    rows_before = len(df)
    missing_before = df.isnull().sum().sum()

    df = df.copy()

    if columns:
        target_df = df[columns]
    else:
        target_df = df

    if strategy == "drop":
        df = df.dropna(subset=columns)
    elif strategy == "fill":
        if columns:
            df[columns] = target_df.fillna(fill_value)
        else:
            df = df.fillna(fill_value)
    elif strategy == "ffill":
        if columns:
            df[columns] = target_df.fillna(method="ffill")
        else:
            df = df.fillna(method="ffill")
    elif strategy == "bfill":
        if columns:
            df[columns] = target_df.fillna(method="bfill")
        else:
            df = df.fillna(method="bfill")
    elif strategy == "interpolate":
        if columns:
            df[columns] = target_df.interpolate()
        else:
            df = df.interpolate()
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    if verbose:
        rows_after = len(df)
        missing_after = df.isnull().sum().sum()
        print(f"[handle_missing_values]")
        print(f"  strategy: {strategy}")
        if columns:
            print(f"  columns: {columns}")
        if strategy == "fill":
            print(f"  fill_value: {fill_value}")
        print(f"  rows_before: {rows_before}")
        print(f"  rows_after: {rows_after}")
        print(f"  rows_dropped: {rows_before - rows_after}")
        print(f"  missing_before: {missing_before}")
        print(f"  missing_after: {missing_after}")
        print(f"  Returning: pd.DataFrame")

    return df


def remove_duplicates(df: pd.DataFrame,
                     subset: Optional[List[str]] = None,
                     keep: str = "first",
                     verbose: bool = True) -> pd.DataFrame:
    """
    Remove duplicate rows from DataFrame.

    Args:
        df: Input DataFrame
        subset: Columns to consider for duplicates (None = all)
        keep: Which duplicates to keep ("first", "last", False)
        verbose: Print duplicate removal summary (default True)

    Returns:
        DataFrame with duplicates removed

    Example:
        >>> df_clean = remove_duplicates(df, subset=["date"], keep="first")
    """
    rows_before = len(df)
    result = df.drop_duplicates(subset=subset, keep=keep)
    rows_after = len(result)

    if verbose:
        print(f"[remove_duplicates]")
        if subset:
            print(f"  subset: {subset}")
        print(f"  keep: {keep}")
        print(f"  rows_before: {rows_before}")
        print(f"  rows_after: {rows_after}")
        print(f"  duplicates_removed: {rows_before - rows_after}")
        print(f"  Returning: pd.DataFrame")

    return result


def convert_date_column(df: pd.DataFrame,
                       date_column: str,
                       format: Optional[str] = None,
                       errors: str = "coerce") -> pd.DataFrame:
    """
    Convert column to datetime type.

    Args:
        df: Input DataFrame
        date_column: Name of date column
        format: Date format string (None = infer)
        errors: How to handle errors ("raise", "coerce", "ignore")

    Returns:
        DataFrame with converted date column

    Example:
        >>> df = convert_date_column(df, "date")
    """
    df = df.copy()
    df[date_column] = pd.to_datetime(df[date_column], format=format, errors=errors)
    return df


def convert_column_types(df: pd.DataFrame,
                        type_map: Dict[str, str]) -> pd.DataFrame:
    """
    Convert column data types.

    Args:
        df: Input DataFrame
        type_map: Dictionary mapping column names to types

    Returns:
        DataFrame with converted types

    Example:
        >>> type_map = {"sales": "float", "channel": "category"}
        >>> df = convert_column_types(df, type_map)
    """
    df = df.copy()
    for col, dtype in type_map.items():
        if col in df.columns:
            df[col] = df[col].astype(dtype)
    return df


def merge_dataframes(df1: pd.DataFrame,
                    df2: pd.DataFrame,
                    on: Union[str, List[str]],
                    how: str = "inner",
                    suffixes: tuple = ("_left", "_right")) -> pd.DataFrame:
    """
    Merge two DataFrames.

    Args:
        df1: First DataFrame
        df2: Second DataFrame
        on: Column(s) to join on
        how: Join type ("inner", "outer", "left", "right")
        suffixes: Suffixes for overlapping columns, default = ("_left", "_right")

    Returns:
        Merged DataFrame

    Example:
        >>> merged = merge_dataframes(df1, df2, on="date", how="inner")
    """
    return pd.merge(df1, df2, on=on, how=how, suffixes=suffixes)


# =============================================================================
# DATA TRANSFORMATION FUNCTIONS
# =============================================================================

def create_lagged_features(df: pd.DataFrame,
                          columns: List[str],
                          lags: List[int],
                          lag_descriptor: str = "_lag",
                           ) -> pd.DataFrame:
    """
    Create lagged versions of columns.

    Args:
        df: Input DataFrame
        columns: Columns to lag
        lags: List of lag periods
        lag_descriptor: lagged columns will be named ``f"{col}{lag_descriptor}{lag}"``

    Returns:
        DataFrame with lagged features added

    Example:
        >>> df = create_lagged_features(df, ["sales"], lags=[1, 7, 14])
    """
    df = df.copy()

    for col in columns:
        for lag in lags:
            df[f"{col}{lag_descriptor}{lag}"] = df[col].shift(lag)

    return df


def create_rolling_features(df: pd.DataFrame,
                           columns: List[str],
                           windows: List[int],
                           functions: List[str] = ["mean"]) -> pd.DataFrame:
    """
    Create rolling window features.

    Args:
        df: Input DataFrame
        columns: Columns to compute rolling features for
        windows: List of window sizes
        functions: Aggregation functions ("mean", "std", "sum", etc.)

    Returns:
        DataFrame with rolling features added

    Example:
        >>> df = create_rolling_features(df, ["sales"], windows=[7, 14], functions=["mean", "std"])
    """
    df = df.copy()

    for col in columns:
        for window in windows:
            for func in functions:
                col_name = f"{col}_rolling{window}_{func}"
                df[col_name] = df[col].rolling(window=window).agg(func)

    return df


def normalize_columns(df: pd.DataFrame,
                     columns: List[str],
                     method: str = "minmax") -> pd.DataFrame:
    """
    Normalize numeric columns.

    Args:
        df: Input DataFrame
        columns: Columns to normalize
        method: "minmax" (0-1), "zscore" (standardize), or "max" (divide by max)

    Returns:
        DataFrame with normalized columns

    Example:
        >>> df = normalize_columns(df, ["sales", "tv_spend"], method="minmax")
        >>> df = normalize_columns(df, ["sales", "tv_spend"], method="max")
    """
    df = df.copy()

    for col in columns:
        if method == "minmax":
            min_val = df[col].min()
            max_val = df[col].max()
            df[col] = (df[col] - min_val) / (max_val - min_val)
        elif method == "zscore":
            mean_val = df[col].mean()
            std_val = df[col].std()
            df[col] = (df[col] - mean_val) / std_val
        elif method == "max":
            max_val = df[col].max()
            df[col] = df[col] / max_val
        else:
            raise ValueError(f"Unknown method: {method}")

    return df


# =============================================================================
# DATA VISUALIZATION FUNCTIONS
# =============================================================================

def plot_missing_values(df: pd.DataFrame, figsize: tuple = (12, 6)) -> plt.Figure:
    """
    Visualize missing values in DataFrame.

    Args:
        df: Input DataFrame
        figsize: Figure size

    Returns:
        Matplotlib Figure object

    Example:
        >>> fig = plot_missing_values(df)
        >>> plt.show()
    """
    missing = df.isnull().sum()
    missing = missing[missing > 0].sort_values(ascending=False)

    if len(missing) == 0:
        print("No missing values found!")
        return None

    fig, ax = plt.subplots(figsize=figsize)
    missing.plot(kind="bar", ax=ax)
    ax.set_title("Missing Values by Column")
    ax.set_xlabel("Column")
    ax.set_ylabel("Missing Count")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    return fig


def plot_correlation_heatmap(df: pd.DataFrame,
                             method: str = "pearson",
                             figsize: tuple = (10, 8),
                             annot: bool = True) -> plt.Figure:
    """
    Plot correlation heatmap for numeric columns using matplotlib.

    Args:
        df: Input DataFrame
        method: Correlation method
        figsize: Figure size
        annot: Show correlation values

    Returns:
        Matplotlib Figure object

    Example:
        >>> fig = plot_correlation_heatmap(df)
        >>> plt.show()
    """
    corr = get_correlation_matrix(df, method=method)

    fig, ax = plt.subplots(figsize=figsize)

    # Create heatmap using matplotlib's imshow
    im = ax.imshow(corr, cmap="coolwarm", aspect="auto", vmin=-1, vmax=1)

    # Set ticks and labels
    ax.set_xticks(np.arange(len(corr.columns)))
    ax.set_yticks(np.arange(len(corr.index)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right")
    ax.set_yticklabels(corr.index)

    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("Correlation", rotation=270, labelpad=15)

    # Add correlation values as text annotations
    if annot:
        for i in range(len(corr.index)):
            for j in range(len(corr.columns)):
                text = ax.text(j, i, f"{corr.iloc[i, j]:.2f}",
                             ha="center", va="center", color="black", fontsize=8)

    ax.set_title(f"Correlation Matrix ({method.capitalize()})")
    plt.tight_layout()

    return fig


def plot_distribution(df: pd.DataFrame,
                     column: str,
                     figsize: tuple = (10, 6),
                     bins: int = 30) -> plt.Figure:
    """
    Plot distribution of a column.

    Args:
        df: Input DataFrame
        column: Column to plot
        figsize: Figure size
        bins: Number of histogram bins

    Returns:
        Matplotlib Figure object

    Example:
        >>> fig = plot_distribution(df, "sales")
        >>> plt.show()
    """
    fig, ax = plt.subplots(figsize=figsize)

    df[column].hist(bins=bins, ax=ax, edgecolor="black", alpha=0.7)
    ax.set_title(f"Distribution of {column}")
    ax.set_xlabel(column)
    ax.set_ylabel("Frequency")
    ax.grid(True, alpha=0.3)

    # Add mean and median lines
    mean_val = df[column].mean()
    median_val = df[column].median()
    ax.axvline(mean_val, color="red", linestyle="--", label=f"Mean: {mean_val:.2f}")
    ax.axvline(median_val, color="green", linestyle="--", label=f"Median: {median_val:.2f}")
    ax.legend()

    plt.tight_layout()
    return fig


def plot_time_series(df: pd.DataFrame,
                    date_column: str,
                    value_columns: List[str],
                    figsize: tuple = (12, 6)) -> plt.Figure:
    """
    Plot time series data.

    Args:
        df: Input DataFrame
        date_column: Date column name
        value_columns: Columns to plot
        figsize: Figure size

    Returns:
        Matplotlib Figure object

    Example:
        >>> fig = plot_time_series(df, "date", ["sales", "tv_spend"])
        >>> plt.show()
    """
    fig, ax = plt.subplots(figsize=figsize)

    for col in value_columns:
        ax.plot(df[date_column], df[col], marker="o", label=col)

    ax.set_title("Time Series Plot")
    ax.set_xlabel("Date")
    ax.set_ylabel("Value")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()

    return fig


def plot_scatter_matrix(df: pd.DataFrame,
                       columns: List[str],
                       figsize: tuple = (12, 12)) -> plt.Figure:
    """
    Create scatter plot matrix for multiple columns.

    Args:
        df: Input DataFrame
        columns: Columns to include
        figsize: Figure size

    Returns:
        Matplotlib Figure object

    Example:
        >>> fig = plot_scatter_matrix(df, ["sales", "tv", "digital", "radio"])
        >>> plt.show()
    """
    from pandas.plotting import scatter_matrix

    fig = plt.figure(figsize=figsize)
    scatter_matrix(df[columns], alpha=0.5, diagonal="kde", fig=fig)
    plt.suptitle("Scatter Matrix")
    plt.tight_layout()

    return fig


def plot_boxplot(df: pd.DataFrame,
                columns: List[str],
                figsize: tuple = (12, 6)) -> plt.Figure:
    """
    Create box plots for columns.

    Args:
        df: Input DataFrame
        columns: Columns to plot
        figsize: Figure size

    Returns:
        Matplotlib Figure object

    Example:
        >>> fig = plot_boxplot(df, ["sales", "tv_spend", "digital_spend"])
        >>> plt.show()
    """
    fig, ax = plt.subplots(figsize=figsize)

    df[columns].boxplot(ax=ax)
    ax.set_title("Box Plot")
    ax.set_ylabel("Value")
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()

    return fig


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_date_range(df: pd.DataFrame,
                       date_column: str,
                       min_date: Optional[str] = None,
                       max_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate date range in DataFrame.

    Args:
        df: Input DataFrame
        date_column: Date column name
        min_date: Minimum expected date (optional)
        max_date: Maximum expected date (optional)

    Returns:
        Validation result dictionary

    Example:
        >>> result = validate_date_range(df, "date", min_date="2020-01-01")
    """
    df_dates = pd.to_datetime(df[date_column])

    result = {
        "valid": True,
        "min_date": df_dates.min(),
        "max_date": df_dates.max(),
        "errors": []
    }

    if min_date:
        min_date_ts = pd.to_datetime(min_date)
        if df_dates.min() < min_date_ts:
            result["valid"] = False
            result["errors"].append(f"Dates before {min_date} found")

    if max_date:
        max_date_ts = pd.to_datetime(max_date)
        if df_dates.max() > max_date_ts:
            result["valid"] = False
            result["errors"].append(f"Dates after {max_date} found")

    return result


def validate_required_columns(df: pd.DataFrame,
                              required_columns: List[str],
                              verbose: bool = True) -> Dict[str, Any]:
    """
    Validate that required columns exist.

    Args:
        df: Input DataFrame
        required_columns: List of required column names
        verbose: Print validation result (default True)

    Returns:
        Validation result dictionary

    Example:
        >>> result = validate_required_columns(df, ["date", "sales", "tv"])
    """
    missing = [col for col in required_columns if col not in df.columns]
    present = [col for col in required_columns if col in df.columns]

    result = {
        "valid": len(missing) == 0,
        "missing_columns": missing,
        "present_columns": present
    }

    if verbose:
        print(f"[validate_required_columns]")
        print(f"  required: {len(required_columns)}")
        print(f"  present: {len(present)}")
        print(f"  missing: {len(missing)}")
        if missing:
            print(f"  missing_columns: {missing}")
        print(f"  valid: {result['valid']}")
        print(f"  Returning: Dict with keys {list(result.keys())}")

    return result


def validate_no_negatives(df: pd.DataFrame,
                         columns: List[str]) -> Dict[str, Any]:
    """
    Validate that columns contain no negative values.

    Args:
        df: Input DataFrame
        columns: Columns to check

    Returns:
        Validation result dictionary

    Example:
        >>> result = validate_no_negatives(df, ["sales", "tv_spend"])
    """
    issues = {}

    for col in columns:
        if col in df.columns:
            negative_count = (df[col] < 0).sum()
            if negative_count > 0:
                issues[col] = {
                    "negative_count": int(negative_count),
                    "min_value": float(df[col].min())
                }

    return {
        "valid": len(issues) == 0,
        "issues": issues
    }


# =============================================================================
# EXPORT FUNCTIONS
# =============================================================================

def save_cleaned_data(df: pd.DataFrame,
                     filepath: str,
                     index: bool = False,
                     verbose: bool = True) -> str:
    """
    Save cleaned DataFrame to file (format inferred from file extension).

    Args:
        df: DataFrame to save
        filepath: Output file path (.parquet or .csv)
        index: Include index in output, default = False
        verbose: Print save summary (default True)

    Returns:
        Filepath where data was saved

    Example:
        >>> path = save_cleaned_data(df, "datasets/transformed/cleaned_data.parquet")
        >>> path = save_cleaned_data(df, "datasets/transformed/cleaned_data.csv")
    """
    if filepath.endswith('.csv'):
        df.to_csv(filepath, index=index)
        file_format = "csv"
    elif filepath.endswith('.parquet'):
        df.to_parquet(filepath, index=index)
        file_format = "parquet"
    else:
        raise ValueError(f"Unsupported file extension in {filepath}. Use .parquet or .csv")

    if verbose:
        print(f"[save_cleaned_data]")
        print(f"  filepath: {filepath}")
        print(f"  format: {file_format}")
        print(f"  shape: {df.shape[0]} rows x {df.shape[1]} columns")
        print(f"  include_index: {index}")
        print(f"  Returning: str (filepath)")

    return filepath


# =============================================================================
# ACF AND TIME SERIES ANALYSIS
# =============================================================================

def analyze_acf(df: pd.DataFrame, column: str, max_lag: int = 20, verbose: bool = True) -> Dict[str, Any]:
    """
    Analyze autocorrelation and suggest l_max for adstock parameter.

    Computes ACF values and identifies the lag where autocorrelation drops
    below 0.1, which is a good starting point for the adstock l_max parameter.

    Args:
        df: pandas DataFrame
        column: Column name to analyze (e.g., 'tv_spend')
        max_lag: Maximum lag to compute (default: 20)
        verbose: Print ACF analysis summary (default True)

    Returns:
        Dictionary with:
        - suggested_l_max: Recommended adstock l_max parameter
        - acf_values: List of ACF values for each lag
        - significant_lags: List of lags where |ACF| > 0.1
        - plot_data: Data for creating ACF plot
    """
    from statsmodels.tsa.stattools import acf

    # Compute ACF
    acf_values = acf(df[column], nlags=max_lag, fft=False)

    # Find where ACF drops below threshold (0.1)
    threshold = 0.1
    below_threshold = np.where(np.abs(acf_values) < threshold)[0]
    suggested_l_max = int(below_threshold[0]) if len(below_threshold) > 0 else max_lag

    # Identify significant lags
    significant_lags = np.where(np.abs(acf_values) > threshold)[0].tolist()

    result = {
        "suggested_l_max": suggested_l_max,
        "acf_values": acf_values.tolist(),
        "significant_lags": significant_lags,
        "plot_data": {
            "lags": list(range(len(acf_values))),
            "acf": acf_values.tolist()
        }
    }

    if verbose:
        print(f"[analyze_acf]")
        print(f"  column: {column}")
        print(f"  max_lag: {max_lag}")
        print(f"  threshold: {threshold}")
        print(f"  suggested_l_max: {suggested_l_max}")
        print(f"  n_significant_lags: {len(significant_lags)}")
        print(f"  significant_lags: {significant_lags}")
        print(f"  Returning: Dict with keys {list(result.keys())}")

    return result


def check_spend_impression_consistency(
    df: pd.DataFrame,
    spend_col: str,
    impression_col: str,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Check consistency between spend and impression columns.

    Analyzes the relationship between spend and impressions to identify
    potential data quality issues.

    Args:
        df: pandas DataFrame
        spend_col: Spend column name (e.g., 'tv_spend')
        impression_col: Impression column name (e.g., 'tv_impressions')
        verbose: Print consistency check summary (default True)

    Returns:
        Dictionary with:
        - cpm: Cost per mille (thousand impressions)
        - cpm_stats: Mean, std, min, max of CPM
        - outlier_indices: Indices where CPM is > 3 std from mean
        - zero_spend_nonzero_impr: Count of rows with 0 spend but >0 impressions
        - zero_impr_nonzero_spend: Count of rows with 0 impressions but >0 spend
        - issues_found: Boolean indicating if issues detected
    """
    spend = df[spend_col]
    impressions = df[impression_col]

    # Calculate CPM (cost per thousand impressions)
    cpm = np.where(impressions > 0, (spend / impressions) * 1000, np.nan)

    # Statistics
    cpm_mean = np.nanmean(cpm)
    cpm_std = np.nanstd(cpm)
    cpm_min = np.nanmin(cpm)
    cpm_max = np.nanmax(cpm)

    # Find outliers (CPM > 3 std from mean)
    outlier_mask = np.abs(cpm - cpm_mean) > 3 * cpm_std
    outlier_indices = np.where(outlier_mask)[0].tolist()

    # Check for logical inconsistencies
    zero_spend_nonzero_impr = ((spend == 0) & (impressions > 0)).sum()
    zero_impr_nonzero_spend = ((impressions == 0) & (spend > 0)).sum()

    issues_found = (
        len(outlier_indices) > 0 or
        zero_spend_nonzero_impr > 0 or
        zero_impr_nonzero_spend > 0
    )

    result = {
        "cpm_stats": {
            "mean": float(cpm_mean),
            "std": float(cpm_std),
            "min": float(cpm_min),
            "max": float(cpm_max)
        },
        "outlier_indices": outlier_indices,
        "outlier_count": len(outlier_indices),
        "zero_spend_nonzero_impressions": int(zero_spend_nonzero_impr),
        "zero_impressions_nonzero_spend": int(zero_impr_nonzero_spend),
        "issues_found": bool(issues_found)
    }

    if verbose:
        print(f"[check_spend_impression_consistency]")
        print(f"  spend_col: {spend_col}")
        print(f"  impression_col: {impression_col}")
        print(f"  cpm_mean: {cpm_mean:.4f}")
        print(f"  cpm_std: {cpm_std:.4f}")
        print(f"  cpm_min: {cpm_min:.4f}")
        print(f"  cpm_max: {cpm_max:.4f}")
        print(f"  outlier_count: {len(outlier_indices)}")
        print(f"  zero_spend_nonzero_impressions: {zero_spend_nonzero_impr}")
        print(f"  zero_impressions_nonzero_spend: {zero_impr_nonzero_spend}")
        print(f"  issues_found: {issues_found}")
        print(f"  Returning: Dict with keys {list(result.keys())}")

    return result


def detect_outliers(
    df: pd.DataFrame,
    column: str,
    method: str = "zscore",
    threshold: float = 3.0,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Detect outliers in a column using various methods.

    Args:
        df: pandas DataFrame
        column: Column name to check for outliers
        method: Detection method - 'zscore' or 'iqr'
        threshold: Z-score threshold (default: 3.0) or IQR multiplier (default: 1.5)
        verbose: Print outlier summary (default True)

    Returns:
        Dictionary with:
        - outlier_indices: List of row indices with outliers
        - outlier_count: Number of outliers found
        - outlier_percentage: Percentage of data points that are outliers
        - method_used: The detection method used
        - statistics: Relevant statistics (mean, std for zscore; Q1, Q3, IQR for iqr)
    """
    data = df[column].dropna()

    if method == "zscore":
        mean = data.mean()
        std = data.std()
        z_scores = np.abs((data - mean) / std)
        outlier_mask = z_scores > threshold

        stats = {
            "mean": float(mean),
            "std": float(std),
            "threshold": threshold
        }

    elif method == "iqr":
        Q1 = data.quantile(0.25)
        Q3 = data.quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - threshold * IQR
        upper_bound = Q3 + threshold * IQR
        outlier_mask = (data < lower_bound) | (data > upper_bound)

        stats = {
            "Q1": float(Q1),
            "Q3": float(Q3),
            "IQR": float(IQR),
            "lower_bound": float(lower_bound),
            "upper_bound": float(upper_bound)
        }
    else:
        raise ValueError(f"Unknown method: {method}. Use 'zscore' or 'iqr'")

    outlier_indices = data[outlier_mask].index.tolist()
    outlier_count = len(outlier_indices)
    outlier_percentage = (outlier_count / len(data)) * 100

    result = {
        "outlier_indices": outlier_indices,
        "outlier_count": outlier_count,
        "outlier_percentage": float(outlier_percentage),
        "method_used": method,
        "statistics": stats
    }

    if verbose:
        print(f"[detect_outliers]")
        print(f"  column: {column}")
        print(f"  method: {method}")
        print(f"  threshold: {threshold}")
        print(f"  n_values: {len(data)}")
        print(f"  outlier_count: {outlier_count}")
        print(f"  outlier_percentage: {outlier_percentage:.2f}%")
        if method == "zscore":
            print(f"  mean: {stats['mean']:.4f}")
            print(f"  std: {stats['std']:.4f}")
        else:
            print(f"  Q1: {stats['Q1']:.4f}")
            print(f"  Q3: {stats['Q3']:.4f}")
            print(f"  IQR: {stats['IQR']:.4f}")
        print(f"  Returning: Dict with keys {list(result.keys())}")

    return result


def analyze_missing_values(df: pd.DataFrame, verbose: bool = True) -> Dict[str, Any]:
    """
    Comprehensive analysis of missing values in DataFrame.

    Args:
        df: pandas DataFrame
        verbose: Print analysis summary (default True)

    Returns:
        Dictionary with:
        - total_missing: Total number of missing values
        - missing_by_column: Dict of {column: count} for columns with missing values
        - missing_percentage: Dict of {column: percentage} for columns with missing values
        - columns_with_missing: List of column names with any missing values
        - complete_rows: Number of rows with no missing values
        - has_missing: Boolean indicating if any missing values exist
    """
    total_missing = df.isnull().sum().sum()
    missing_by_column = df.isnull().sum()
    missing_by_column = missing_by_column[missing_by_column > 0].to_dict()

    missing_percentage = {}
    for col, count in missing_by_column.items():
        missing_percentage[col] = (count / len(df)) * 100

    columns_with_missing = list(missing_by_column.keys())
    complete_rows = df.dropna().shape[0]

    result = {
        "total_missing": int(total_missing),
        "missing_by_column": {str(k): int(v) for k, v in missing_by_column.items()},
        "missing_percentage": {str(k): float(v) for k, v in missing_percentage.items()},
        "columns_with_missing": columns_with_missing,
        "complete_rows": int(complete_rows),
        "total_rows": int(len(df)),
        "has_missing": bool(total_missing > 0)
    }

    if verbose:
        print(f"[analyze_missing_values]")
        print(f"  total_rows: {result['total_rows']}")
        print(f"  complete_rows: {result['complete_rows']}")
        print(f"  total_missing: {result['total_missing']}")
        print(f"  columns_with_missing: {len(columns_with_missing)}")
        if columns_with_missing:
            print(f"  affected_columns: {columns_with_missing}")
        print(f"  has_missing: {result['has_missing']}")
        print(f"  Returning: Dict with keys {list(result.keys())}")

    return result


def check_time_series_continuity(
    df: pd.DataFrame,
    date_col: str,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Check for gaps in time series data.

    Identifies missing dates in a time series to ensure data continuity.

    Args:
        df: pandas DataFrame
        date_col: Name of date column
        verbose: Print continuity check summary (default True)

    Returns:
        Dictionary with:
        - is_continuous: Boolean indicating if series has no gaps
        - expected_frequency: Inferred frequency (e.g., 'D', 'W')
        - missing_dates: List of missing dates
        - gap_count: Number of gaps found
        - date_range: Start and end dates
    """
    dates = pd.to_datetime(df[date_col]).sort_values()

    # Infer frequency
    date_diff = dates.diff().dropna()
    most_common_diff = date_diff.mode()[0] if len(date_diff) > 0 else pd.Timedelta(days=1)

    # Generate expected date range
    start_date = dates.min()
    end_date = dates.max()

    # Infer frequency string
    if most_common_diff == pd.Timedelta(days=1):
        freq = 'D'
    elif most_common_diff == pd.Timedelta(days=7):
        freq = 'W'
    elif most_common_diff >= pd.Timedelta(days=28) and most_common_diff <= pd.Timedelta(days=31):
        freq = 'M'
    else:
        freq = str(most_common_diff)

    expected_dates = pd.date_range(start=start_date, end=end_date, freq=freq)
    missing_dates = expected_dates.difference(dates)

    result = {
        "is_continuous": len(missing_dates) == 0,
        "expected_frequency": freq,
        "missing_dates": [str(d.date()) for d in missing_dates],
        "gap_count": len(missing_dates),
        "date_range": {
            "start": str(start_date.date()),
            "end": str(end_date.date())
        },
        "total_dates": len(dates),
        "expected_dates": len(expected_dates)
    }

    if verbose:
        print(f"[check_time_series_continuity]")
        print(f"  date_col: {date_col}")
        print(f"  date_range: {result['date_range']['start']} to {result['date_range']['end']}")
        print(f"  expected_frequency: {freq}")
        print(f"  total_dates: {len(dates)}")
        print(f"  expected_dates: {len(expected_dates)}")
        print(f"  gap_count: {len(missing_dates)}")
        print(f"  is_continuous: {result['is_continuous']}")
        print(f"  Returning: Dict with keys {list(result.keys())}")

    return result


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    # Data Loading
    "load_csv_from_url",
    "load_csv_or_parquet_from_file_and_inspect",
    "load_csv_or_parquet_from_file",
    # Data Inspection
    "inspect_dataframe_basic",
    "get_missing_value_summary",
    "get_duplicate_summary",
    "get_descriptive_statistics",
    "get_correlation_matrix",
    # Data Cleaning
    "clean_column_names",
    "handle_missing_values",
    "remove_duplicates",
    "convert_date_column",
    "convert_column_types",
    "merge_dataframes",
    # Data Transformation
    "create_lagged_features",
    "create_rolling_features",
    "normalize_columns",
    # Visualization
    "plot_missing_values",
    "plot_correlation_heatmap",
    "plot_distribution",
    "plot_time_series",
    "plot_scatter_matrix",
    "plot_boxplot",
    # Validation
    "validate_date_range",
    "validate_required_columns",
    "validate_no_negatives",
    # Export
    "save_cleaned_data",
    # ACF & Time Series
    "analyze_acf",
    "check_spend_impression_consistency",
    "detect_outliers",
    "analyze_missing_values",
    "check_time_series_continuity",
]
