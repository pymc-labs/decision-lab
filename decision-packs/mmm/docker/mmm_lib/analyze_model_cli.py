"""Analyze a pre-fit pymc-marketing MMM from a saved .nc file.

Loads the model and training data from a fitted_model.nc file (saved via
mmm.save()), then runs the full analysis pipeline: diagnostics, posterior
predictive checks, channel contributions, saturation curves, sensitivity
analysis, ROAS, and budget optimization.

No ground truth config is needed — this works with any pymc-marketing MMM.

Usage:
    python -m mmm_lib.analyze_model_cli fitted_model.nc
    python -m mmm_lib.analyze_model_cli fitted_model.nc --skip-budget
    python -m mmm_lib.analyze_model_cli fitted_model.nc -o analysis_output/
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
from pymc_marketing.mmm.multidimensional import MMM

from mmm_lib.analyze_model import analyze_mmm


def main():
    parser = argparse.ArgumentParser(
        description="Load a fitted MMM from a .nc file and run full analysis."
    )
    parser.add_argument("model_path", type=Path,
                        help="Path to saved .nc file (from mmm.save())")
    parser.add_argument("-o", "--output-dir", type=Path, default=None,
                        help="Output directory for figures/CSVs "
                             "(default: same dir as model file)")
    parser.add_argument("--skip-budget", action="store_true",
                        help="Skip budget optimization")
    parser.add_argument("--no-roas", action="store_true",
                        help="Skip ROAS analysis (channels not in monetary units)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed")
    args = parser.parse_args()

    model_path = args.model_path.resolve()
    if not model_path.exists():
        print(f"Error: {model_path} not found", file=sys.stderr)
        sys.exit(1)

    output_dir = args.output_dir or model_path.parent
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load model (reconstructs MMM + idata from saved attrs)
    print(f"Loading model: {model_path}")
    mmm = MMM.load(str(model_path))

    # Reconstruct training dataframe from fit_data
    df = mmm.idata.fit_data.to_dataframe().reset_index()
    date_col = mmm.date_column
    if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        df[date_col] = pd.to_datetime(df[date_col])

    print(f"Data: {df.shape[0]} rows, {len(mmm.channel_columns)} channels")
    print(f"Target: {mmm.target_column}, Date: {date_col}")
    print(f"Output: {output_dir}")

    # Register original-scale variables (idempotent if already present)
    # Filter to vars that exist in model.named_vars_to_dims — after
    # MMM.load() some vars (e.g. intercept_contribution) may not be
    # registered depending on model config / pymc-marketing version.
    original_scale_vars = [
        "channel_contribution", "control_contribution",
        "intercept_contribution", "y",
    ]
    if mmm.yearly_seasonality:
        original_scale_vars.append("yearly_seasonality_contribution")
    registered = set(mmm.model.named_vars_to_dims)
    original_scale_vars = [v for v in original_scale_vars if v in registered]
    mmm.add_original_scale_contribution_variable(var=original_scale_vars)

    # Run analysis (no ground truth config — skips parameter recovery)
    analyze_mmm(
        mmm, df,
        idata_path=model_path,
        output_dir=output_dir,
        skip_budget=args.skip_budget,
        seed=args.seed,
        roas_applicable=not args.no_roas,
    )


if __name__ == "__main__":
    main()
