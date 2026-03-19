"""MMM model fitting with Modal cloud, with optional local fallback.

By default, models are fit on Modal cloud. Set DLAB_FIT_MODEL_LOCALLY=1
to fit locally instead (slower, no Modal credentials needed).

When using Modal, only MCMC sampling is done remotely; posterior predictive
sampling is done locally to avoid transferring large fitted models.

Environment variables:
    DLAB_FIT_MODEL_LOCALLY: "1" for local fitting, "0" or unset for Modal cloud
    MODAL_TOKEN_ID: Required for Modal cloud fitting
    MODAL_TOKEN_SECRET: Required for Modal cloud fitting
"""

import os
import subprocess
import time
import shutil
from pathlib import Path

import cloudpickle


# Path to Modal app inside Docker container
MODAL_APP_PATH = "/opt/modal_app/mmm_sampler.py"


def _should_fit_locally() -> bool:
    """Check whether to fit locally based on env vars."""
    if os.environ.get("DLAB_FIT_MODEL_LOCALLY", "0") == "1":
        return True
    if not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"):
        return True
    return False


def ensure_modal_deployed() -> None:
    """
    Ensure the Modal app is deployed, deploying it if necessary.

    This function checks if the mmm-sampler function exists on Modal.
    If not, it deploys the app from MODAL_APP_PATH.
    """
    import modal

    try:
        # Try to get the function - this will fail if not deployed
        modal.Function.from_name("mmm-sampler", "fit_mmm")
        print("Modal app already deployed")
        return
    except modal.exception.NotFoundError:
        print("Modal app not deployed, deploying now...")
    except Exception as e:
        # Other errors (auth, network) - try to deploy anyway
        print(f"Could not check Modal app status ({e}), attempting deploy...")

    # Deploy the Modal app
    if not os.path.exists(MODAL_APP_PATH):
        raise FileNotFoundError(
            f"Modal app not found at {MODAL_APP_PATH}. "
            "Make sure you're running inside the MMM Docker container."
        )

    result = subprocess.run(
        ["modal", "deploy", MODAL_APP_PATH],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to deploy Modal app:\n{result.stderr}\n{result.stdout}"
        )

    print("Modal app deployed successfully")
    print()


def fit_mmm_modal(
    model_bundle_path: str | Path,
    output_path: str | Path = "fitted_model.nc",
) -> dict:
    """
    Fit an MMM model using Modal cloud compute.

    Parameters
    ----------
    model_bundle_path : str | Path
        Path to model_to_fit.pkl containing the model bundle
    output_path : str | Path
        Output path for fitted model (default: fitted_model.nc)

    Returns
    -------
    dict
        Result containing elapsed_seconds, mcmc_elapsed, posterior_predictive_elapsed, model_type
    """
    import pickle

    # Load and optimize the model bundle for transfer
    # Strip prior predictive data to reduce size (51MB -> ~0.5MB)
    with open(model_bundle_path, "rb") as f:
        bundle = pickle.load(f)

    original_size = os.path.getsize(model_bundle_path) / 1024 / 1024

    # Strip prior predictive data - not needed for MCMC fitting
    # But save it to reattach after fitting
    mmm = bundle["mmm"]
    original_idata = mmm.idata  # Save for reattaching later
    mmm.idata = None
    if hasattr(mmm, "_prior"):
        mmm._prior = None
    if hasattr(mmm, "_prior_predictive"):
        mmm._prior_predictive = None

    # Store X for local posterior predictive sampling later
    X_for_posterior = bundle["X"].copy()

    # Recover y from mmm.y if bundle had y=None (old bundles).
    # Passing y=None to fit() causes fit_data to store zeros, breaking
    # target_scale after save/load.
    y = bundle.get("y")
    if y is None and hasattr(mmm, "y") and mmm.y is not None:
        y = mmm.y
        print("Recovered y from mmm.y (bundle had y=None)")

    draws: int = bundle.get("draws", 1000)
    tune: int = bundle.get("tune", 1000)
    chains: int = bundle.get("chains", 4)
    target_accept: float = bundle.get("target_accept", 0.9)

    # ---- LOCAL FITTING (default) ----
    if _should_fit_locally():
        print("Fitting locally (DLAB_FIT_MODEL_LOCALLY=1 or Modal tokens not set)")
        print(f"  draws={draws}, tune={tune}, chains={chains}, target_accept={target_accept}")
        print()

        # Reattach idata for prior data preservation
        mmm.idata = original_idata

        fit_start = time.time()
        try:
            mmm.fit(
                X=bundle["X"],
                y=y,
                nuts_sampler="numpyro",
                draws=draws,
                tune=tune,
                chains=chains,
                target_accept=target_accept,
            )
        except Exception:
            # numpyro may not be available; fall back to default sampler
            print("numpyro not available, falling back to PyMC sampler")
            mmm.fit(
                X=bundle["X"],
                y=y,
                draws=draws,
                tune=tune,
                chains=chains,
                target_accept=target_accept,
            )
        fit_elapsed = time.time() - fit_start

        # Sample posterior predictive
        pp_start = time.time()
        mmm.sample_posterior_predictive(X_for_posterior, extend_idata=True)
        pp_elapsed = time.time() - pp_start

        mmm.save(str(output_path))

        total_elapsed = fit_elapsed + pp_elapsed
        model_type = type(mmm).__name__

        return {
            "elapsed_seconds": total_elapsed,
            "mcmc_elapsed": fit_elapsed,
            "posterior_predictive_elapsed": pp_elapsed,
            "model_type": model_type,
            "output_path": str(output_path),
            "fitting_backend": "local",
        }

    # ---- MODAL CLOUD FITTING ----
    import modal

    # Re-serialize the stripped bundle for transfer
    stripped_bundle = {
        "mmm": mmm,
        "X": bundle["X"],
        "y": y,
        "draws": draws,
        "tune": tune,
        "chains": chains,
        "target_accept": target_accept,
    }
    bundle_bytes = cloudpickle.dumps(stripped_bundle)
    stripped_size = len(bundle_bytes) / 1024 / 1024

    print(f"Model bundle: {original_size:.1f} MB -> {stripped_size:.1f} MB (stripped prior data)")
    print()

    # Ensure Modal app is deployed (auto-deploys on first use)
    ensure_modal_deployed()

    print("Submitting to Modal...")

    # Call the Modal function (MCMC only)
    fit_fn = modal.Function.from_name("mmm-sampler", "fit_mmm")
    result = fit_fn.remote(model_bundle_pickle=bundle_bytes)
    mcmc_elapsed = result["elapsed_seconds"]

    # Write fitted model (without posterior predictive yet)
    with open(output_path, "wb") as f:
        f.write(result["model_netcdf"])

    # Run posterior predictive locally
    print()
    print("Running posterior predictive sampling locally...")
    pp_start = time.time()

    # Load the fitted model and run posterior predictive
    from pymc_marketing.mmm.multidimensional import MMM
    fitted_mmm = MMM.load(str(output_path))

    # Only sample posterior predictive if not already present
    # (older Modal deployments may have sampled it already)
    if "posterior_predictive" not in fitted_mmm.idata.groups():
        fitted_mmm.sample_posterior_predictive(X_for_posterior, extend_idata=True)
    else:
        print("Posterior predictive already present (from Modal)")

    # Reattach prior samples from original idata
    if original_idata is not None:
        if hasattr(original_idata, "prior"):
            fitted_mmm.idata.add_groups(prior=original_idata.prior)
        if hasattr(original_idata, "prior_predictive"):
            fitted_mmm.idata.add_groups(prior_predictive=original_idata.prior_predictive)
        print("Reattached prior samples to fitted model")

    # Save to temp file first, then rename (avoids "file already open" error)
    temp_output = str(output_path) + ".tmp"
    fitted_mmm.save(temp_output)
    shutil.move(temp_output, str(output_path))

    pp_elapsed = time.time() - pp_start
    print(f"Posterior predictive complete in {pp_elapsed:.1f}s")

    total_elapsed = mcmc_elapsed + pp_elapsed

    return {
        "elapsed_seconds": total_elapsed,
        "mcmc_elapsed": mcmc_elapsed,
        "posterior_predictive_elapsed": pp_elapsed,
        "model_type": result["model_type"],
        "output_path": str(output_path),
        "fitting_backend": "modal",
    }


def generate_time_recommendation(est_minutes: float, complexity: dict) -> str:
    """
    Generate actionable recommendation based on estimated fitting time.

    Parameters
    ----------
    est_minutes : float
        Estimated total fitting time in minutes
    complexity : dict
        Model complexity metrics from estimation

    Returns
    -------
    str
        Recommendation string for the agent
    """
    is_multidim = complexity.get("is_multidim", False)
    n_channels = complexity.get("n_channels", 0)

    if est_minutes < 10:
        return "PROCEED: Estimated time is reasonable (<10 min). Run full fit."

    elif est_minutes < 30:
        return (
            "PROCEED: Estimated 10-30 minutes. This is normal for moderately complex models.\n"
            "  If convergence issues occur, you may need to increase samples."
        )

    elif est_minutes < 60:
        if is_multidim and n_channels > 5:
            return (
                "CONSIDER_OPTIONS: Estimated 30-60 minutes.\n"
                "  Options:\n"
                "  1. Proceed if model complexity is justified\n"
                "  2. Simplify: Use pooled/hierarchical priors instead of unpooled\n"
                "  3. Simplify: Group similar channels\n"
                "  If you proceed and convergence is poor, increase samples (tune=1500, draws=1500)"
            )
        else:
            return (
                "PROCEED_LONG: Estimated 30-60 minutes. This is expected for your model complexity.\n"
                "  If convergence is close but not achieved, try tune=1500, draws=1500."
            )

    else:  # > 60 minutes
        hours = est_minutes / 60
        return (
            f"LONG_FIT_WARNING: Estimated {est_minutes:.0f} minutes ({hours:.1f} hours).\n"
            "  STRONGLY CONSIDER simplifying before fitting:\n"
            "  1. Switch from unpooled to hierarchical or pooled priors (biggest impact)\n"
            "  2. Group channels with similar behavior\n"
            "  3. Use simpler adstock (geometric instead of delayed)\n"
            "  4. For exploration: reduce to tune=500, draws=500 first\n"
            "  \n"
            "  If model must remain complex (justified by business needs):\n"
            "  - Budget 1-2+ hours for fitting\n"
            "  - If near-convergence, try tune=1500, draws=1500 or chains=6"
        )


def estimate_fit_time_modal(model_bundle_path: str | Path) -> dict:
    """
    Estimate fitting time for an MMM model without running the full fit.

    This function runs a small number of MCMC samples on Modal to estimate
    how long a full fit would take. Use this before committing to a long fit
    for complex models.

    Parameters
    ----------
    model_bundle_path : str | Path
        Path to model_to_fit.pkl containing the model bundle

    Returns
    -------
    dict
        Estimation results including:
        - success: Whether estimation completed
        - seconds_per_sample: Time per MCMC sample
        - estimated_total_minutes: Extrapolated total time
        - complexity: Model complexity metrics
        - recommendation: Suggested action
    """
    import pickle

    # Load and strip bundle (same as fit)
    with open(model_bundle_path, "rb") as f:
        bundle = pickle.load(f)

    # Strip prior data to reduce transfer size
    mmm = bundle["mmm"]
    mmm.idata = None
    if hasattr(mmm, "_prior"):
        mmm._prior = None
    if hasattr(mmm, "_prior_predictive"):
        mmm._prior_predictive = None

    y = bundle.get("y")
    if y is None and hasattr(mmm, "y") and mmm.y is not None:
        y = mmm.y
    stripped_bundle = {
        "mmm": mmm,
        "X": bundle["X"],
        "y": y,
        "draws": bundle.get("draws", 1000),
        "tune": bundle.get("tune", 1000),
        "chains": bundle.get("chains", 4),
        "target_accept": bundle.get("target_accept", 0.9),
    }
    bundle_bytes = cloudpickle.dumps(stripped_bundle)

    print("Running time estimation on Modal...")
    print("(This takes 2-5 minutes including VM startup)")
    print()

    # Ensure deployed
    ensure_modal_deployed()

    # Call estimation function
    import modal
    estimate_fn = modal.Function.from_name("mmm-sampler", "estimate_fit_time")
    result = estimate_fn.remote(model_bundle_pickle=bundle_bytes)

    if not result.get("success"):
        return result

    # Add recommendation based on estimated time
    est_minutes = result["estimated_total_minutes"]
    complexity = result["complexity"]
    result["recommendation"] = generate_time_recommendation(est_minutes, complexity)

    return result


def main():
    """CLI entry point for Modal fitting."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Fit MMM model on Modal cloud compute"
    )
    parser.add_argument(
        "--model-bundle",
        required=True,
        help="Path to model_to_fit.pkl",
    )
    parser.add_argument(
        "--output",
        default="fitted_model.nc",
        help="Output path for fitted model (default: fitted_model.nc)",
    )
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="Only estimate fitting time, don't run full fit",
    )
    args = parser.parse_args()

    if args.estimate_only:
        if _should_fit_locally():
            print("Modal is unavailable at the moment, so there's no time estimation possible. Proceed with fit-model-modal, it will fall back to a local execution of the fit routine.")
            return

        result = estimate_fit_time_modal(model_bundle_path=args.model_bundle)

        if not result.get("success"):
            print(f"ERROR: Estimation failed: {result.get('error')}")
            return

        print()
        print("=" * 60)
        print("TIME ESTIMATION RESULTS")
        print("=" * 60)
        print()
        print("  Timing breakdown:")
        print(f"    JIT compilation:      {result.get('jit_seconds', 0):.1f}s (one-time)")
        print(f"    Sampling speed:       {result.get('samples_per_second', 0):.1f} samples/sec")
        print(f"    Seconds per sample:   {result['seconds_per_sample']:.4f}s")
        print()
        print("  Extrapolation:")
        c = result["complexity"]
        total_samples = c['chains'] * (c['requested_tune'] + c['requested_draws'])
        print(f"    Target: {c['requested_tune']} tune + {c['requested_draws']} draws x {c['chains']} chains = {total_samples} samples")
        print(f"    Estimated total time: {result['estimated_total_minutes']:.1f} minutes")
        print()
        print("  Model complexity:")
        print(f"    Model type:           {c['model_type']}")
        print(f"    Observations:         {c['n_observations']}")
        print(f"    Channels:             {c['n_channels']}")
        print(f"    MultiDim:             {c['is_multidim']}")
        print()
        print("  RECOMMENDATION:")
        for line in result["recommendation"].split("\n"):
            print(f"    {line}")
        print()
        print("=" * 60)
        return

    result = fit_mmm_modal(
        model_bundle_path=args.model_bundle,
        output_path=args.output,
    )

    elapsed = result["elapsed_seconds"]
    mcmc_elapsed = result.get("mcmc_elapsed", elapsed)
    pp_elapsed = result.get("posterior_predictive_elapsed", 0)
    model_type = result["model_type"]
    backend = result.get("fitting_backend", "modal")

    def fmt_time(secs):
        return f"{int(secs // 60)}m {int(secs % 60)}s"

    print()
    print("=" * 60)
    print("SUCCESS: Model fitting complete!")
    print("=" * 60)
    print()
    print(f"  Backend:       {backend}")
    print(f"  Model type:    {model_type}")
    print(f"  MCMC:          {fmt_time(mcmc_elapsed)} ({mcmc_elapsed:.1f}s)")
    print(f"  Post. pred.:   {fmt_time(pp_elapsed)} ({pp_elapsed:.1f}s)")
    print(f"  Total time:    {fmt_time(elapsed)} ({elapsed:.1f}s)")
    print(f"  Output file:   {args.output}")
    print()
    print("Proceed with Phase 3.")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
