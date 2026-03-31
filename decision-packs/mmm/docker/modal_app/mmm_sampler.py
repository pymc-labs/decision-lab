"""Modal app for MCMC sampling of cloudpickled pymc-marketing MMM models.

This module provides serverless cloud fitting using Modal. Only MCMC sampling
is done here; posterior predictive sampling is done locally to avoid
transferring large fitted models.

Package Versions
----------------
Packages are pinned to specific versions for cloudpickle compatibility with
the Docker container. These should be kept in sync with the Dockerfile.

Requirements:
    pip install modal

Setup:
    1. Create a Modal account at https://modal.com
    2. Run `modal setup` to authenticate
    3. Deploy with `modal deploy mmm_sampler.py`
       Or use dlab which auto-deploys when needed.
"""

import hashlib
from pathlib import Path

import modal

# Hash this file to force image rebuild when code changes
_modal_app_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]

# Conda packages - properly linked BLAS for fast matrix ops
CONDA_PACKAGES = [
    "python=3.11",
    "numpy=2.3.5",
    "pandas=3.0.0",
    "scipy=1.17.0",
    "arviz=0.23.1",
    "pymc=5.26.1",
    "pytensor=2.35.1",
    "numpyro",
    "xarray=2025.12.0",
    "h5py=3.15.1",
]

# Packages that need pip (not on conda-forge or need specific versions)
PIP_PACKAGES = [
    "pymc-marketing==0.18.0",
    "pyarrow==23.0.0",
    "cloudpickle==3.1.2",
]

cpu_image = (
    modal.Image.micromamba(python_version="3.11")
    .run_commands(f"echo 'modal_app hash: {_modal_app_hash}'")  # Cache buster
    .micromamba_install(*CONDA_PACKAGES, channels=["conda-forge"])
    .pip_install(*PIP_PACKAGES)
)

app = modal.App("mmm-sampler")


@app.function(image=cpu_image, cpu=8, memory=16384, timeout=10800)
def fit_mmm(model_bundle_pickle: bytes) -> dict:
    """
    Fit MMM model with numpyro backend (MCMC only).

    This function runs on a remote Modal container. Only MCMC sampling is done here;
    posterior predictive sampling is done locally to avoid transferring large
    fitted models back.

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
        - elapsed_seconds: Time taken for MCMC fitting
        - model_netcdf: Bytes of fitted model in NetCDF format (without posterior predictive)
        - model_type: Type name of the model
    """
    import time
    import tempfile
    import os
    import cloudpickle

    start_time = time.time()

    # Unpickle the model bundle
    bundle = cloudpickle.loads(model_bundle_pickle)

    mmm = bundle["mmm"]
    X = bundle["X"]
    y = bundle.get("y")
    # Safety net: if y is None, recover from mmm.y (set by build_model).
    # Passing y=None to fit() causes fit_data to store zeros, which breaks
    # target_scale after save/load.
    if y is None and hasattr(mmm, "y") and mmm.y is not None:
        y = mmm.y
        print("Recovered y from mmm.y (bundle had y=None)")
    draws = bundle.get("draws", 1000)
    tune = bundle.get("tune", 1000)
    chains = bundle.get("chains", 4)
    target_accept = bundle.get("target_accept", 0.9)

    # Set XLA device count for parallel chains
    os.environ["XLA_FLAGS"] = f"--xla_force_host_platform_device_count={chains}"

    print(f"Starting MCMC sampling: draws={draws}, tune={tune}, chains={chains}")

    # Verify numpyro is available
    numpyro_available = False
    try:
        import numpyro
        import jax
        print(f"numpyro version: {numpyro.__version__}")
        print(f"JAX version: {jax.__version__}")
        print(f"JAX devices: {jax.devices()}")
        numpyro_available = True
    except ImportError as e:
        print(f"ERROR: Failed to import numpyro/jax: {e}")
        print("Will fall back to PyTensor (SLOW)")

    # Fit with numpyro if available, otherwise fall back to PyTensor
    sampler = "numpyro" if numpyro_available else "pymc"
    print(f"Using sampler: {sampler}")

    sampler_used = sampler
    error_msg = None
    try:
        mmm.fit(
            X=X,
            y=y,
            nuts_sampler=sampler,
            draws=draws,
            tune=tune,
            chains=chains,
            cores=chains,
            target_accept=target_accept,
        )
    except Exception as e:
        # If numpyro fails, fall back to pymc
        error_msg = str(e)
        print(f"Sampler {sampler} failed: {e}")
        if sampler == "numpyro":
            print("Falling back to pymc sampler...")
            sampler_used = "pymc"
            mmm.fit(
                X=X,
                y=y,
                nuts_sampler="pymc",
                draws=draws,
                tune=tune,
                chains=chains,
                cores=chains,
                target_accept=target_accept,
            )
        else:
            raise

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
        "sampler_requested": sampler,
        "sampler_used": sampler_used,
        "sampler_error": error_msg,
    }


@app.function(image=cpu_image, cpu=8, memory=16384, timeout=600)
def estimate_fit_time(model_bundle_pickle: bytes) -> dict:
    """
    Run a small number of samples to estimate total MCMC fitting time.

    Uses two-phase timing to separate JIT compilation from pure sampling:
    - Phase 1: Tiny fit (5 tune + 1 draw) triggers JAX JIT compilation
    - Phase 2: Larger fit (50 tune + 10 draws) with JIT cached = pure sampling speed

    The Phase 2 time gives accurate it/s for extrapolation.

    Parameters
    ----------
    model_bundle_pickle : bytes
        Cloudpickled dictionary containing:
        - mmm: The MMM model (with build_model already called, prior data stripped)
        - X: Feature DataFrame
        - y: Target Series (always pass y, never None)
        - draws: Requested number of MCMC draws (for estimation)
        - tune: Requested number of tuning samples (for estimation)
        - chains: Number of MCMC chains
        - target_accept: Target acceptance rate

    Returns
    -------
    dict
        - success: Whether estimation completed successfully
        - seconds_per_sample: Average time per MCMC sample (from Phase 2, excludes JIT)
        - jit_seconds: Time spent on JIT compilation (Phase 1)
        - sampling_seconds: Time spent on pure sampling (Phase 2)
        - estimated_total_seconds: Extrapolated time for full fit (JIT + sampling)
        - estimated_total_minutes: Extrapolated time in minutes
        - complexity: Model complexity metrics
        - error: Error message if success=False
    """
    import os
    import time
    import cloudpickle

    # Unpickle the model bundle
    bundle = cloudpickle.loads(model_bundle_pickle)

    mmm = bundle["mmm"]
    X = bundle["X"]
    y = bundle.get("y")
    if y is None and hasattr(mmm, "y") and mmm.y is not None:
        y = mmm.y
    chains = bundle.get("chains", 4)
    target_accept = bundle.get("target_accept", 0.9)

    # Requested parameters for extrapolation
    requested_tune = bundle.get("tune", 1000)
    requested_draws = bundle.get("draws", 1000)

    # Phase 1: Tiny fit to trigger JIT compilation
    JIT_TUNE = 5
    JIT_DRAWS = 1

    # Phase 2: Larger fit with JIT cached for accurate timing
    ESTIMATE_TUNE = 50
    ESTIMATE_DRAWS = 10

    # Set XLA device count
    os.environ["XLA_FLAGS"] = f"--xla_force_host_platform_device_count={chains}"

    # Compute model complexity metrics
    n_observations = len(X)
    n_channels = len(mmm.channel_columns) if hasattr(mmm, "channel_columns") else 0
    is_multidim = hasattr(mmm, "dims") and mmm.dims is not None and len(mmm.dims) > 0
    model_type = type(mmm).__name__

    print(f"Estimating fit time for {model_type}")
    print(f"  Observations: {n_observations}, Channels: {n_channels}, MultiDim: {is_multidim}")

    # Verify numpyro
    numpyro_available = False
    try:
        import numpyro
        import jax
        numpyro_available = True
        print(f"  Using numpyro backend (version {numpyro.__version__}, JAX {jax.__version__})")
    except ImportError:
        print("  WARNING: numpyro not available, using PyTensor (estimates will be slower)")

    sampler = "numpyro" if numpyro_available else "pymc"

    # Phase 1: JIT compilation
    print(f"  Phase 1: JIT warmup ({JIT_TUNE} tune + {JIT_DRAWS} draws)...")
    jit_start = time.time()

    try:
        mmm.fit(
            X=X,
            y=y,
            nuts_sampler=sampler,
            draws=JIT_DRAWS,
            tune=JIT_TUNE,
            chains=chains,
            cores=chains,
            target_accept=target_accept,
        )
    except Exception as e:
        return {
            "success": False,
            "error": f"Phase 1 (JIT) failed: {e}",
        }

    jit_elapsed = time.time() - jit_start
    print(f"  Phase 1 complete: {jit_elapsed:.1f}s (includes JIT compilation)")

    # Phase 2: Pure sampling (JIT cached)
    # Clear fitted state but keep model structure. JAX JIT cache persists at process level.
    print(f"  Phase 2: Pure sampling ({ESTIMATE_TUNE} tune + {ESTIMATE_DRAWS} draws)...")
    mmm.idata = None

    sampling_start = time.time()

    try:
        mmm.fit(
            X=X,
            y=y,
            nuts_sampler=sampler,
            draws=ESTIMATE_DRAWS,
            tune=ESTIMATE_TUNE,
            chains=chains,
            cores=chains,
            target_accept=target_accept,
        )
    except Exception as e:
        return {
            "success": False,
            "error": f"Phase 2 (sampling) failed: {e}",
        }

    sampling_elapsed = time.time() - sampling_start
    print(f"  Phase 2 complete: {sampling_elapsed:.1f}s (pure sampling)")

    # Calculate it/s from Phase 2 (excludes JIT)
    phase2_samples = chains * (ESTIMATE_TUNE + ESTIMATE_DRAWS)
    seconds_per_sample = sampling_elapsed / phase2_samples
    samples_per_second = phase2_samples / sampling_elapsed

    # Extrapolate for requested configuration
    # Total time = JIT (one-time) + sampling (scales with samples)
    total_requested_samples = chains * (requested_tune + requested_draws)
    estimated_sampling_seconds = seconds_per_sample * total_requested_samples
    estimated_total_seconds = jit_elapsed + estimated_sampling_seconds

    print()
    print(f"  Results:")
    print(f"    JIT compilation:    {jit_elapsed:.1f}s (one-time)")
    print(f"    Sampling speed:     {samples_per_second:.1f} samples/sec")
    print(f"    Seconds per sample: {seconds_per_sample:.4f}s")
    print()
    print(f"  Extrapolation for {requested_tune} tune + {requested_draws} draws x {chains} chains:")
    print(f"    JIT:      {jit_elapsed:.1f}s")
    print(f"    Sampling: {estimated_sampling_seconds:.1f}s ({total_requested_samples} samples)")
    print(f"    TOTAL:    {estimated_total_seconds:.1f}s ({estimated_total_seconds / 60:.1f} minutes)")

    return {
        "success": True,
        "seconds_per_sample": seconds_per_sample,
        "samples_per_second": samples_per_second,
        "jit_seconds": jit_elapsed,
        "sampling_seconds": sampling_elapsed,
        "estimation_samples": phase2_samples,
        "estimated_total_seconds": estimated_total_seconds,
        "estimated_total_minutes": estimated_total_seconds / 60,
        "complexity": {
            "n_observations": n_observations,
            "n_channels": n_channels,
            "chains": chains,
            "is_multidim": is_multidim,
            "model_type": model_type,
            "requested_tune": requested_tune,
            "requested_draws": requested_draws,
        },
    }
