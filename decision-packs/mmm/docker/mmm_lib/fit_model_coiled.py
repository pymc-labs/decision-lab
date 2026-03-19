"""Coiled-based cloud fitting for MMM models.

This module provides serverless cloud fitting using Coiled, which runs
on dedicated EC2 instances in your AWS account. Much faster than
Modal's shared infrastructure for CPU-bound MCMC sampling.

Requirements:
    pip install coiled

Setup:
    1. Create a Coiled account at https://coiled.io
    2. Run `coiled login` to authenticate
    3. Connect your AWS account in Coiled dashboard (Settings -> Cloud Provider)
    4. Create an API token at https://cloud.coiled.io/profile
    5. Add to your .env file: DASK_COILED__TOKEN=your-token-here

The DASK_COILED__TOKEN environment variable is used for authentication
in Docker containers and CI/CD environments (no browser login needed).

Note: For Coiled package sync to work from Docker, packages like pyarrow
must be installed via pip (not conda). Conda packages don't sync properly.
"""

import os
import time
import tempfile
import uuid
from pathlib import Path

import cloudpickle

# Coiled is optional - only imported when cloud fitting is used
try:
    import coiled
    COILED_AVAILABLE = True
except ImportError:
    COILED_AVAILABLE = False


# VM type mapping for different workload sizes
# Using ARM Graviton3 instances for better price/performance
VM_TYPES = {
    "small": "c7g.xlarge",     # 4 vCPU, 8 GiB - quick tests
    "medium": "c7g.2xlarge",   # 8 vCPU, 16 GiB - standard MMM
    "large": "c7g.4xlarge",    # 16 vCPU, 32 GiB - complex models
}


def _fit_mmm_remote(model_bundle_pickle: bytes) -> dict:
    """
    Fit MMM model with numpyro backend.

    This function runs on a remote Coiled VM. Only MCMC sampling is done here;
    posterior predictive sampling is done locally to avoid transferring large
    fitted models back through the scheduler.

    Parameters
    ----------
    model_bundle_pickle : bytes
        Cloudpickled dictionary containing:
        - mmm: The MMM model (with build_model already called, prior data stripped)
        - X: Feature DataFrame
        - y: Target Series (always pass y, never None)
        - draws: Number of MCMC draws
        - tune: Number of tuning samples
        - chains: Number of MCMC chains
        - target_accept: Target acceptance rate

    Returns
    -------
    dict
        - elapsed_seconds: Time taken for fitting
        - model_netcdf: Bytes of fitted model in NetCDF format
        - model_type: Type name of the model
    """
    import os
    import time
    import tempfile
    import cloudpickle

    start_time = time.time()

    # Unpickle the model bundle
    bundle = cloudpickle.loads(model_bundle_pickle)

    mmm = bundle["mmm"]
    X = bundle["X"]
    y = bundle.get("y")
    # Safety net: recover y from mmm.y if bundle had y=None
    if y is None and hasattr(mmm, "y") and mmm.y is not None:
        y = mmm.y
        print("Recovered y from mmm.y (bundle had y=None)")
    draws = bundle.get("draws", 1000)
    tune = bundle.get("tune", 1000)
    chains = bundle.get("chains", 4)
    target_accept = bundle.get("target_accept", 0.9)

    print(f"Starting MCMC sampling: draws={draws}, tune={tune}, chains={chains}")

    # Fit with numpyro (MCMC only - posterior predictive done locally)
    mmm.fit(
        X=X,
        y=y,
        nuts_sampler="numpyro",
        draws=draws,
        tune=tune,
        chains=chains,
        target_accept=target_accept,
    )

    elapsed = time.time() - start_time

    # Save to NetCDF (without posterior predictive)
    with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as f:
        temp_path = f.name
    mmm.save(temp_path)
    with open(temp_path, "rb") as f:
        nc_bytes = f.read()
    os.unlink(temp_path)

    print(f"MCMC fitting complete in {elapsed:.1f}s")

    return {
        "elapsed_seconds": elapsed,
        "model_netcdf": nc_bytes,
        "model_type": type(mmm).__name__,
    }


def fit_mmm_coiled(
    model_bundle_path: str | Path,
    output_path: str | Path = "fitted_model.nc",
    vm_type: str = "c7g.2xlarge",
    region: str = "us-east-1",
) -> dict:
    """
    Fit an MMM model using Coiled cloud compute.

    Parameters
    ----------
    model_bundle_path : str | Path
        Path to model_to_fit.pkl containing the model bundle
    output_path : str | Path
        Output path for fitted model (default: fitted_model.nc)
    vm_type : str
        EC2 instance type (default: c7g.2xlarge = 8 vCPU, 16 GiB ARM)
        Options: small, medium, large, or any EC2 instance type
    region : str
        AWS region (default: us-east-1)

    Returns
    -------
    dict
        Result containing elapsed_seconds, model_type
    """
    if not COILED_AVAILABLE:
        raise ImportError(
            "Coiled is not installed. Install with: pip install coiled\n"
            "Then set DASK_COILED__TOKEN environment variable."
        )

    # Check for API token (required in Docker/CI environments)
    token = os.environ.get("DASK_COILED__TOKEN")
    if not token:
        raise EnvironmentError(
            "DASK_COILED__TOKEN environment variable not set.\n"
            "Get your token at: https://cloud.coiled.io/profile\n"
            "Add to .env file: DASK_COILED__TOKEN=your-token-here"
        )

    # Resolve VM type aliases
    resolved_vm_type = VM_TYPES.get(vm_type, vm_type)

    # Load and optimize the model bundle for transfer
    # Strip prior predictive data to reduce size (51MB -> ~0.5MB)
    import pickle
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

    # Re-serialize the stripped bundle
    stripped_bundle = {
        "mmm": mmm,
        "X": bundle["X"],
        "y": bundle.get("y"),
        "draws": bundle.get("draws", 1000),
        "tune": bundle.get("tune", 1000),
        "chains": bundle.get("chains", 4),
        "target_accept": bundle.get("target_accept", 0.9),
    }
    bundle_bytes = cloudpickle.dumps(stripped_bundle)
    stripped_size = len(bundle_bytes) / 1024 / 1024

    print(f"Model bundle: {original_size:.1f} MB -> {stripped_size:.1f} MB (stripped prior data)")
    print(f"Coiled config: vm_type={resolved_vm_type}, region={region}")
    print()
    print("Submitting to Coiled (first run may take ~1-2 min for VM startup)...")

    # Create the Coiled function dynamically
    # Uses automatic package sync from local environment
    # Unique name ensures each parallel call gets its own VM
    unique_name = f"mmm-fit-{uuid.uuid4().hex[:8]}"
    print(f"Coiled function name: {unique_name}")
    print()
    @coiled.function(
        name=unique_name,
        vm_type=resolved_vm_type,
        region=region,
        # Removed PYTENSOR_FLAGS="cxx=" - C++ compilation is faster for deterministics
        keepalive="5 minutes",  # Keep VM warm for subsequent calls
    )
    def remote_fit(bundle_bytes: bytes) -> dict:
        return _fit_mmm_remote(bundle_bytes)

    # Call the remote function (MCMC only)
    result = remote_fit(bundle_bytes)
    mcmc_elapsed = result["elapsed_seconds"]

    # Write fitted model (without posterior predictive yet)
    with open(output_path, "wb") as f:
        f.write(result["model_netcdf"])

    # Run posterior predictive locally
    print()
    print("Running posterior predictive sampling locally...")
    import time as time_module
    import shutil
    pp_start = time_module.time()

    # Load the fitted model and run posterior predictive
    from pymc_marketing.mmm.multidimensional import MMM
    fitted_mmm = MMM.load(str(output_path))

    fitted_mmm.sample_posterior_predictive(X_for_posterior, extend_idata=True)

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

    pp_elapsed = time_module.time() - pp_start
    print(f"Posterior predictive complete in {pp_elapsed:.1f}s")

    total_elapsed = mcmc_elapsed + pp_elapsed

    return {
        "elapsed_seconds": total_elapsed,
        "mcmc_elapsed": mcmc_elapsed,
        "posterior_predictive_elapsed": pp_elapsed,
        "model_type": result["model_type"],
        "output_path": str(output_path),
    }


def main():
    """CLI entry point for Coiled fitting."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Fit MMM model on Coiled cloud compute"
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
        "--vm-type",
        default="c7g.2xlarge",
        help="EC2 instance type or alias: small, medium, large (default: c7g.2xlarge = 8 vCPU ARM)",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1)",
    )
    args = parser.parse_args()

    result = fit_mmm_coiled(
        model_bundle_path=args.model_bundle,
        output_path=args.output,
        vm_type=args.vm_type,
        region=args.region,
    )

    elapsed = result["elapsed_seconds"]
    mcmc_elapsed = result.get("mcmc_elapsed", elapsed)
    pp_elapsed = result.get("posterior_predictive_elapsed", 0)
    model_type = result["model_type"]

    def fmt_time(secs):
        return f"{int(secs // 60)}m {int(secs % 60)}s"

    print()
    print("=" * 60)
    print("SUCCESS: Model fitting complete!")
    print("=" * 60)
    print()
    print(f"  Model type:    {model_type}")
    print(f"  MCMC (Coiled): {fmt_time(mcmc_elapsed)} ({mcmc_elapsed:.1f}s)")
    print(f"  Post. pred.:   {fmt_time(pp_elapsed)} ({pp_elapsed:.1f}s)")
    print(f"  Total time:    {fmt_time(elapsed)} ({elapsed:.1f}s)")
    print(f"  Output file:   {args.output}")
    print()
    print("Proceed with Phase 3.")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
