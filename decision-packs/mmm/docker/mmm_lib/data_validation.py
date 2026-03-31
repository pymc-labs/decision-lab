"""Data validation utilities for MMM.

Functions for validating data against MMM configuration before model fitting.
"""

import pandas as pd
from typing import Any


def validate_data_for_mmm(
    df: pd.DataFrame,
    data_config: dict[str, Any],
) -> dict[str, Any]:
    """Validate data against MMM configuration.

    Parameters
    ----------
    df : pd.DataFrame
        Input data.
    data_config : dict
        Data configuration with column specifications:
        - date_column: str
        - target_column: str
        - channel_columns: list[str]
        - control_columns: list[str] (optional)

    Returns
    -------
    dict[str, Any]
        Validation result with keys:
        - valid: bool
        - errors: list[str]
        - warnings: list[str]
        - summary: dict with data statistics
    """
    errors: list[str] = []
    warnings: list[str] = []

    date_col = data_config.get("date_column", "date")
    target_col = data_config.get("target_column", "y")
    channel_cols = data_config.get("channel_columns", [])
    control_cols = data_config.get("control_columns", [])

    # Check required columns exist
    required = [date_col, target_col] + channel_cols
    missing = [col for col in required if col not in df.columns]
    if missing:
        errors.append(f"Missing required columns: {missing}")

    # Check optional control columns
    missing_controls = [col for col in control_cols if col not in df.columns]
    if missing_controls:
        warnings.append(f"Missing control columns (optional): {missing_controls}")

    # Check for negative values in channels (marketing spend should be non-negative)
    for col in channel_cols:
        if col in df.columns and (df[col] < 0).any():
            errors.append(f"Negative values in channel column: {col}")

    # Check for missing values in required columns
    for col in required:
        if col in df.columns:
            n_missing = df[col].isna().sum()
            if n_missing > 0:
                warnings.append(f"Missing values in column {col}: {n_missing} rows")

    # Check date column can be parsed
    if date_col in df.columns:
        try:
            pd.to_datetime(df[date_col])
        except Exception as e:
            errors.append(f"Cannot parse date column '{date_col}': {e}")

    # Check for duplicate dates (might indicate panel data)
    if date_col in df.columns:
        n_duplicates = df[date_col].duplicated().sum()
        if n_duplicates > 0:
            warnings.append(
                f"Duplicate dates found: {n_duplicates} rows. "
                "Consider using MultidimMMM for panel data."
            )

    # Summary statistics
    summary: dict[str, Any] = {
        "n_rows": len(df),
        "n_cols": len(df.columns),
        "channels": channel_cols,
        "controls": control_cols,
    }

    if target_col in df.columns:
        summary["target_mean"] = float(df[target_col].mean())
        summary["target_std"] = float(df[target_col].std())
        summary["target_min"] = float(df[target_col].min())
        summary["target_max"] = float(df[target_col].max())
        # Scaled statistics (for prior configuration)
        summary["target_scaled_mean"] = summary["target_mean"] / summary["target_max"]

    if date_col in df.columns:
        try:
            dates = pd.to_datetime(df[date_col])
            summary["date_range"] = f"{dates.min()} to {dates.max()}"
            summary["n_periods"] = len(dates.unique())
        except Exception:
            pass

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
    }
