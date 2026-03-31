"""
MMM Analysis Library

A comprehensive library for Marketing Mix Model (MMM) analysis using PyMC-Marketing.

Modules:
- data_preparation: Data loading, cleaning, exploration, and validation
- model_fitting: MMM model creation, configuration, fitting, and diagnostics
- analysis: Post-fit analysis, ROAS computation, visualization, and business insights

Example:
    >>> from mmm_lib import create_mmm_instance, fit_mmm_model
    >>>
    >>> # Create and fit model
    >>> mmm = create_mmm_instance(date_column="date", channel_columns=["tv", "digital"])
    >>> mmm = fit_mmm_model(mmm, X, y)
    >>>
    >>> # Use pymc-marketing 0.18.0 built-in APIs for analysis:
    >>> roas = mmm.summary.roas(frequency="all_time")
    >>> contributions = mmm.summary.contributions()
    >>> mmm.plot.contributions_over_time(var=["channel_contribution"])
"""

__version__ = "0.1.0"

# Data Preparation Functions
from .data_preparation import (
    # Data Loading
    load_csv_from_url,
    load_csv_or_parquet_from_file,
    load_csv_or_parquet_from_file_and_inspect,
    # Data Inspection
    inspect_dataframe_basic,
    get_missing_value_summary,
    get_duplicate_summary,
    get_descriptive_statistics,
    get_correlation_matrix,
    # Data Cleaning
    clean_column_names,
    handle_missing_values,
    remove_duplicates,
    convert_date_column,
    convert_column_types,
    merge_dataframes,
    # Data Transformation
    create_lagged_features,
    create_rolling_features,
    normalize_columns,
    # Visualization
    plot_missing_values,
    plot_correlation_heatmap,
    plot_distribution,
    plot_time_series,
    plot_scatter_matrix,
    plot_boxplot,
    # Validation
    validate_date_range,
    validate_required_columns,
    validate_no_negatives,
    # Export
    save_cleaned_data,
    # ACF & Time Series
    analyze_acf,
    check_spend_impression_consistency,
    detect_outliers,
    analyze_missing_values,
    check_time_series_continuity,
)

# Model Fitting Functions
from .model_fitting import (
    # Configuration
    create_mmm_config,
    create_custom_priors,
    validate_custom_priors,
    validate_mmm_config,
    # Data Preparation
    prepare_mmm_data,
    validate_mmm_data,
    # Model Creation
    create_mmm_instance,
    build_mmm_model,
    # Prior Predictive
    sample_prior_predictive,
    get_prior_predictive_summary,
    plot_prior_predictive,
    check_prior_predictive_coverage,
    extract_prior_predictive_summary,
    # Fitting
    create_sampler_config,
    fit_mmm_model,
    fit_mmm_with_config,
    # Diagnostics
    check_convergence,
    check_convergence_diagnostics,
    get_parameter_summary,
    check_model_fit_quality,
    # Serialization
    save_mmm_model,
    load_mmm_model,
    # ACF Utilities
    suggest_l_max_from_acf,
)

# Analysis Functions
# NOTE: Most analysis/plotting functions removed in favor of pymc-marketing 0.18.0 built-in APIs:
#   - mmm.summary.roas(), mmm.summary.contributions(), mmm.summary.saturation_curves()
#   - mmm.plot.posterior_predictive(), mmm.plot.contributions_over_time(), etc.
#   - mmm.sensitivity.run_sweep(), compute_marginal_effects(), compute_uplift_curve_respect_to_base()
from .analysis import (
    # Model Type Detection
    is_multidimensional_mmm,
    # Posterior Predictive
    sample_posterior_predictive,
    # Parameter Analysis
    plot_trace,
    # Budget Optimization
    optimize_budget_allocation,
    # Business Insights
    check_posterior_predictive,
    generate_recommendations,
)

# Re-export transformation names for documentation
from .model_fitting import (
    _adstock_transformation_names,
    _saturation_transformation_names,
)

# Statistical Analysis Functions
from .statistical_analysis import (
    # Main analysis function
    analyze_mmm_statistics,
    # Individual tests
    test_stationarity_adf,
    test_stationarity_kpss,
    analyze_trend,
    analyze_multicollinearity,
    detect_seasonality_fft,
    detect_columns,
    # Convenience functions for panel data
    analyze_per_dimension,
    analyze_aggregated,
)

# Model Config Serialization
from .model_config import (
    prior_to_dict,
    dict_to_prior,
    save_model_config,
    load_model_config,
)

# Full Model Analysis Pipeline
from .analyze_model import (
    analyze_mmm,
    budget_optimization as run_budget_optimization,
)

# Data Validation
from .data_validation import (
    validate_data_for_mmm,
)

__all__ = [
    # Version
    "__version__",

    # === Data Preparation ===
    # Loading
    "load_csv_from_url",
    "load_csv_or_parquet_from_file",
    "load_csv_or_parquet_from_file_and_inspect",
    # Inspection
    "inspect_dataframe_basic",
    "get_missing_value_summary",
    "get_duplicate_summary",
    "get_descriptive_statistics",
    "get_correlation_matrix",
    # Cleaning
    "clean_column_names",
    "handle_missing_values",
    "remove_duplicates",
    "convert_date_column",
    "convert_column_types",
    "merge_dataframes",
    # Transformation
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

    # === Model Fitting ===
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

    # === Analysis ===
    # NOTE: Most functions replaced by pymc-marketing 0.18.0 built-in APIs
    "is_multidimensional_mmm",
    "sample_posterior_predictive",
    "plot_trace",
    "optimize_budget_allocation",
    "check_posterior_predictive",
    "generate_recommendations",

    # === Metadata ===
    "_adstock_transformation_names",
    "_saturation_transformation_names",

    # === Statistical Analysis ===
    "analyze_mmm_statistics",
    "test_stationarity_adf",
    "test_stationarity_kpss",
    "analyze_trend",
    "analyze_multicollinearity",
    "detect_seasonality_fft",
    "detect_columns",
    "analyze_per_dimension",
    "analyze_aggregated",

    # === Model Config Serialization ===
    "prior_to_dict",
    "dict_to_prior",
    "save_model_config",
    "load_model_config",

    # === Data Validation ===
    "validate_data_for_mmm",

    # === Full Model Analysis Pipeline ===
    "analyze_mmm",
    "run_budget_optimization",
]
