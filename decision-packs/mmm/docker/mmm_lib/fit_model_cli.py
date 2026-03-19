"""CLI entry point for fit-model tool.

This module provides a command-line interface for fitting MMM models.
It loads an unfitted model from pickle, fits it, and saves using mmm.save().

Supports both single time series and panel data (with dims).
"""

import argparse
import cloudpickle
import json
import sys
from typing import Any

# Note: Do NOT set PYTENSOR_FLAGS="cxx=" here.
# While numpyro handles MCMC, PyTensor C++ compilation is still used for
# compute_deterministics after MCMC, and C++ compilation is faster.

from .data_preparation import load_csv_or_parquet_from_file
from .model_fitting import check_convergence, prepare_mmm_data

from pymc_marketing.mmm.multidimensional import MMM


def get_convergence_diagnostics(mmm: MMM) -> dict[str, Any]:
    """Get convergence diagnostics as a JSON-serializable dict.

    Parameters
    ----------
    mmm : MMM
        Fitted model instance.

    Returns
    -------
    dict[str, Any]
        Diagnostics including converged status, r-hat, ESS, etc.
    """
    result = check_convergence(mmm, verbose=False)

    return {
        "converged": bool(result["converged"]),
        "max_rhat": float(result["max_rhat"]),
        "min_ess_bulk": int(result["min_ess_bulk"]) if result["min_ess_bulk"] is not None else None,
        "problem_vars_rhat": list(result.get("problem_vars_rhat", [])),
        "low_ess_vars": list(result.get("low_ess_vars", [])),
    }


def main() -> int:
    """Run model fitting from command line.

    Returns
    -------
    int
        Exit code (0 for success, 1 for failure).
    """
    parser = argparse.ArgumentParser(
        description="Fit MMM model using MCMC sampling"
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Path to pickled unfitted model (.pkl)",
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Path to data file (CSV or Parquet)",
    )
    parser.add_argument(
        "--output",
        default="fitted_model.nc",
        help="Path for fitted model output (default: fitted_model.nc)",
    )
    parser.add_argument(
        "--draws",
        type=int,
        default=1000,
        help="Number of MCMC draws (default: 1000)",
    )
    parser.add_argument(
        "--tune",
        type=int,
        default=1000,
        help="Number of tuning samples (default: 1000)",
    )
    parser.add_argument(
        "--chains",
        type=int,
        default=4,
        help="Number of MCMC chains (default: 4)",
    )
    parser.add_argument(
        "--target-accept",
        type=float,
        default=0.9,
        help="Target acceptance rate (default: 0.9)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (optional)",
    )

    args = parser.parse_args()

    try:
        # Load unfitted model from cloudpickle
        with open(args.model, "rb") as f:
            mmm = cloudpickle.load(f)

        if not isinstance(mmm, MMM):
            raise TypeError(f"Expected MMM instance, got {type(mmm).__name__}")

        # Determine model type
        model_type = type(mmm).__name__

        # Load data
        df = load_csv_or_parquet_from_file(args.data, verbose=False)

        # Get target column from model
        target_column = mmm.output_var
        date_column = mmm.date_column

        # Prepare X and y
        X, y = prepare_mmm_data(
            df,
            date_column=date_column,
            y_column=target_column,
        )

        # Fit model using numpyro backend
        mmm.fit(
            X=X,
            y=y,
            nuts_sampler="numpyro",
            draws=args.draws,
            tune=args.tune,
            chains=args.chains,
            target_accept=args.target_accept,
            random_seed=args.seed,
        )

        # Save fitted model using canonical mmm.save()
        mmm.save(args.output)

        # Output diagnostics as JSON to stdout
        diagnostics = get_convergence_diagnostics(mmm)
        diagnostics["output_path"] = args.output
        diagnostics["model_type"] = model_type
        print(json.dumps(diagnostics))

        return 0

    except Exception as e:
        import traceback
        error_result = {
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(error_result), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
