#!/usr/bin/env python
"""Modal integration tests using pre-generated fixture data.

These tests verify the Modal MCMC execution independently of local model building.
They use a pre-generated test bundle from fixtures/ to avoid requiring pymc-marketing
dependencies for basic test execution.

Requirements:
    - MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables
    - modal package installed
    - Pre-generated fixtures/test_bundle_minimal.pkl

Usage:
    # Run all Modal integration tests
    pytest test_modal_integration.py -v -s

    # Run only fast tests (skip MCMC)
    pytest test_modal_integration.py -v -m "not slow"

    # Run standalone
    python test_modal_integration.py
"""

import os
import time
from pathlib import Path

import pytest

# Load .env file from project root
from dotenv import load_dotenv

_project_root = Path(__file__).parent.parent.parent.parent
load_dotenv(_project_root / ".env")

# Fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def test_bundle_path() -> Path:
    """Path to pre-generated minimal test bundle."""
    path = FIXTURES_DIR / "test_bundle_minimal.pkl"
    if not path.exists():
        pytest.skip(
            f"Test fixture not found: {path}\n"
            "Generate with: python create_test_bundle.py fixtures/test_bundle_minimal.pkl"
        )
    return path


@pytest.fixture
def modal_tokens() -> tuple[str, str]:
    """Check and return Modal tokens, skip if not configured."""
    token_id = os.environ.get("MODAL_TOKEN_ID")
    token_secret = os.environ.get("MODAL_TOKEN_SECRET")
    if not token_id or not token_secret:
        pytest.skip(
            "Modal tokens not configured. Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET.\n"
            "Get tokens at: https://modal.com/settings/tokens"
        )
    return token_id, token_secret


class TestModalDeployment:
    """Tests for Modal app deployment status."""

    def test_modal_function_exists(self, modal_tokens):
        """Verify Modal app is deployed and function is accessible."""
        import modal

        try:
            fn = modal.Function.from_name("mmm-sampler", "fit_mmm")
            assert fn is not None
            print("Modal function 'mmm-sampler/fit_mmm' is accessible")
        except modal.exception.NotFoundError:
            pytest.fail(
                "Modal app not deployed. Deploy with:\n"
                "  modal deploy decision-packs/mmm/docker/modal_app/mmm_sampler.py"
            )


class TestModalMCMC:
    """Tests for Modal MCMC execution."""

    @pytest.mark.slow
    def test_modal_mcmc_with_fixture(self, modal_tokens, test_bundle_path, tmp_path):
        """Test MCMC execution on Modal with pre-generated bundle."""
        import cloudpickle
        import modal

        # Load fixture
        with open(test_bundle_path, "rb") as f:
            bundle = cloudpickle.load(f)

        print(f"\nLoaded bundle from: {test_bundle_path}")
        print(f"  X shape: {bundle['X'].shape}")
        print(f"  draws: {bundle.get('draws', 50)}, tune: {bundle.get('tune', 50)}")
        print(f"  chains: {bundle.get('chains', 2)}")

        # Strip prior data (mimics fit_model_modal.py behavior)
        mmm = bundle["mmm"]
        mmm.idata = None
        if hasattr(mmm, "_prior"):
            mmm._prior = None
        if hasattr(mmm, "_prior_predictive"):
            mmm._prior_predictive = None

        # Serialize for Modal
        bundle_bytes = cloudpickle.dumps({
            "mmm": mmm,
            "X": bundle["X"],
            "y": bundle.get("y"),
            "draws": bundle.get("draws", 50),
            "tune": bundle.get("tune", 50),
            "chains": bundle.get("chains", 2),
            "target_accept": bundle.get("target_accept", 0.8),
        })

        print(f"  Serialized bundle size: {len(bundle_bytes) / 1024:.1f} KB")
        print("\nCalling Modal function...")

        # Call Modal function
        start_time = time.time()
        fit_fn = modal.Function.from_name("mmm-sampler", "fit_mmm")
        result = fit_fn.remote(model_bundle_pickle=bundle_bytes)
        elapsed = time.time() - start_time

        print(f"\nModal MCMC completed in {elapsed:.1f}s")
        print(f"  Remote MCMC time: {result['elapsed_seconds']:.1f}s")
        print(f"  Model type: {result['model_type']}")
        print(f"  NetCDF size: {len(result['model_netcdf']) / 1024:.1f} KB")

        # Verify result structure
        assert "elapsed_seconds" in result
        assert "model_netcdf" in result
        assert "model_type" in result
        assert result["elapsed_seconds"] > 0
        assert len(result["model_netcdf"]) > 0

        # Save and verify the model can be loaded
        output_path = tmp_path / "test_fitted.nc"
        with open(output_path, "wb") as f:
            f.write(result["model_netcdf"])

        from pymc_marketing.mmm.multidimensional import MMM

        fitted_mmm = MMM.load(str(output_path))
        groups = list(fitted_mmm.idata.groups())
        print(f"  Fitted model idata groups: {groups}")

        assert "posterior" in groups, "Missing posterior group"
        assert fitted_mmm.idata.posterior["intercept"].shape[0] > 0

    @pytest.mark.slow
    def test_numpyro_backend_used(self, modal_tokens, test_bundle_path):
        """Verify numpyro backend is being used (not PyTensor fallback).

        This test checks that MCMC runs at expected numpyro speed.
        With numpyro: ~5-10 it/s (200 iterations in <60s)
        With PyTensor fallback: ~1-2 it/s (200 iterations in 2-3 min)
        """
        import cloudpickle
        import modal

        # Load fixture
        with open(test_bundle_path, "rb") as f:
            bundle = cloudpickle.load(f)

        # Strip prior data
        mmm = bundle["mmm"]
        mmm.idata = None

        # Small test: 50 draws + 50 tune x 2 chains = 200 iterations
        bundle_bytes = cloudpickle.dumps({
            "mmm": mmm,
            "X": bundle["X"],
            "y": bundle.get("y"),
            "draws": 50,
            "tune": 50,
            "chains": 2,
            "target_accept": 0.8,
        })

        print("\nRunning timing test to verify numpyro backend...")
        print("  Expected: <60s with numpyro, >120s with PyTensor")

        # Call Modal function
        start_time = time.time()
        fit_fn = modal.Function.from_name("mmm-sampler", "fit_mmm")
        result = fit_fn.remote(model_bundle_pickle=bundle_bytes)
        total_time = time.time() - start_time
        mcmc_time = result["elapsed_seconds"]

        # Calculate iterations per second
        total_iterations = (50 + 50) * 2  # (draws + tune) * chains
        it_per_sec = total_iterations / mcmc_time

        print(f"\n  Total time: {total_time:.1f}s")
        print(f"  MCMC time: {mcmc_time:.1f}s")
        print(f"  Iterations: {total_iterations}")
        print(f"  Speed: {it_per_sec:.1f} it/s")

        # numpyro should be at least 3 it/s (usually 5-10 it/s)
        # PyTensor fallback is typically 1-2 it/s
        if it_per_sec < 3:
            pytest.fail(
                f"MCMC too slow ({it_per_sec:.1f} it/s). "
                "numpyro backend may not be working. "
                "Check Modal logs for JAX/numpyro import errors."
            )

        print(f"\n  numpyro backend verified ({it_per_sec:.1f} it/s)")


def main():
    """Run tests standalone (without pytest)."""
    import cloudpickle
    import modal

    # Check tokens
    token_id = os.environ.get("MODAL_TOKEN_ID")
    token_secret = os.environ.get("MODAL_TOKEN_SECRET")
    if not token_id or not token_secret:
        print("ERROR: MODAL_TOKEN_ID and MODAL_TOKEN_SECRET not set")
        print("Get tokens at: https://modal.com/settings/tokens")
        return 1

    # Check fixture
    bundle_path = FIXTURES_DIR / "test_bundle_minimal.pkl"
    if not bundle_path.exists():
        print(f"ERROR: Fixture not found: {bundle_path}")
        print("Generate with: python create_test_bundle.py fixtures/test_bundle_minimal.pkl")
        return 1

    print("=" * 60)
    print("Modal Integration Test")
    print("=" * 60)

    # Test 1: Function exists
    print("\n[1/3] Checking Modal function exists...")
    try:
        fn = modal.Function.from_name("mmm-sampler", "fit_mmm")
        print("  OK: mmm-sampler/fit_mmm is accessible")
    except modal.exception.NotFoundError:
        print("  FAILED: Modal app not deployed")
        print("  Deploy with: modal deploy decision-packs/mmm/docker/modal_app/mmm_sampler.py")
        return 1

    # Test 2: MCMC execution
    print("\n[2/3] Testing MCMC execution...")
    with open(bundle_path, "rb") as f:
        bundle = cloudpickle.load(f)

    mmm = bundle["mmm"]
    mmm.idata = None

    bundle_bytes = cloudpickle.dumps({
        "mmm": mmm,
        "X": bundle["X"],
        "y": bundle.get("y"),
        "draws": 50,
        "tune": 50,
        "chains": 2,
        "target_accept": 0.8,
    })

    print(f"  Bundle size: {len(bundle_bytes) / 1024:.1f} KB")
    print("  Calling Modal function...")

    start = time.time()
    result = fn.remote(model_bundle_pickle=bundle_bytes)
    elapsed = time.time() - start

    print(f"  OK: MCMC completed in {result['elapsed_seconds']:.1f}s (total: {elapsed:.1f}s)")

    # Test 3: numpyro verification
    print("\n[3/3] Verifying numpyro backend...")
    total_iterations = (50 + 50) * 2
    it_per_sec = total_iterations / result["elapsed_seconds"]
    print(f"  Speed: {it_per_sec:.1f} it/s")

    if it_per_sec < 3:
        print("  WARNING: Speed suggests PyTensor fallback, not numpyro")
        print("  Check Modal logs for JAX/numpyro errors")
    else:
        print(f"  OK: numpyro backend working ({it_per_sec:.1f} it/s)")

    print()
    print("=" * 60)
    print("All tests passed!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())
