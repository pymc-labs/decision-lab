"""Run budget optimization on a fitted MMM at a specific risk appetite.

Loads the model from a .nc file, extracts metadata, and runs budget
optimization with configurable bounds (risk appetite).

Usage:
    python -m mmm_lib.optimize_budget_cli fitted_model.nc --risk-pct 0.5
    python -m mmm_lib.optimize_budget_cli fitted_model.nc --risk-pct 0.25 -o budget_conservative/
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
from pymc_marketing.mmm.multidimensional import MMM

from mmm_lib.analyze_model import budget_optimization


def main():
    parser = argparse.ArgumentParser(
        description="Run budget optimization on a fitted MMM."
    )
    parser.add_argument("model_path", type=Path,
                        help="Path to saved .nc file (from mmm.save())")
    parser.add_argument("--risk-pct", type=float, required=True,
                        help="Risk appetite (0.0-1.0): how far from historical "
                             "spend the optimizer can go. "
                             "0.25=conservative, 0.5=moderate, 0.75=aggressive")
    parser.add_argument("-o", "--output-dir", type=Path, default=None,
                        help="Output directory for results "
                             "(default: same dir as model file)")
    parser.add_argument("--no-roas", action="store_true",
                        help="Channels not in monetary units — show directional guidance only")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed")
    args = parser.parse_args()

    model_path = args.model_path.resolve()
    if not model_path.exists():
        print(f"Error: {model_path} not found", file=sys.stderr)
        sys.exit(1)

    if args.risk_pct <= 0:
        print(f"Error: --risk-pct must be > 0, got {args.risk_pct}",
              file=sys.stderr)
        sys.exit(1)

    output_dir = args.output_dir or model_path.parent
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load model
    print(f"Loading model: {model_path}")
    mmm = MMM.load(str(model_path))

    # Reconstruct training dataframe from fit_data
    df = mmm.idata.fit_data.to_dataframe().reset_index()
    date_col = mmm.date_column
    if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        df[date_col] = pd.to_datetime(df[date_col])

    target_col = mmm.target_column
    channel_columns = list(mmm.channel_columns)
    dims = list(mmm.dims) if mmm.dims else []

    print(f"Data: {df.shape[0]} rows, {len(channel_columns)} channels")
    print(f"Target: {target_col}, Date: {date_col}")
    print(f"Risk appetite: {args.risk_pct} (+/-{args.risk_pct:.0%} bounds)")
    print(f"Output: {output_dir}")

    # Register original-scale variables (needed for contribution computation)
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

    # Run budget optimization
    budget_optimization(
        mmm, df, output_dir,
        target_col=target_col,
        date_col=date_col,
        channel_columns=channel_columns,
        dims=dims,
        pct=args.risk_pct,
        seed=args.seed,
        roas_applicable=not args.no_roas,
    )

    print(f"\nAll results saved to {output_dir}")


if __name__ == "__main__":
    main()
