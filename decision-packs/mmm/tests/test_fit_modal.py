#!/usr/bin/env python
"""Test script for fit_model_modal.py CLI.

This script tests the Modal fitting workflow:
1. Creates a minimal test bundle (model_to_fit.pkl)
2. Runs fit_model_modal CLI
3. Verifies the output (including prior reattachment)

Requirements:
    - MODAL_TOKEN_ID and MODAL_TOKEN_SECRET in .env file or environment
    - conda env: mmm-docker (or any env with pymc-marketing + modal)

Usage:
    # From decision-packs/mmm/tests directory:
    conda activate mmm-docker
    python test_fit_modal.py

    # Or with pytest:
    pytest test_fit_modal.py -v -s

Note: Do NOT set PYTENSOR_FLAGS="cxx=" - C++ compilation is faster for deterministics.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Load .env file from project root
from dotenv import load_dotenv
_project_root = Path(__file__).parent.parent.parent.parent
load_dotenv(_project_root / ".env")

import pytest


# Path to mmm_lib
MMM_LIB_PATH = Path(__file__).parent.parent / "docker" / "mmm_lib"


def check_modal_tokens():
    """Check if Modal tokens are set."""
    token_id = os.environ.get("MODAL_TOKEN_ID")
    token_secret = os.environ.get("MODAL_TOKEN_SECRET")
    if not token_id or not token_secret:
        pytest.skip(
            "MODAL_TOKEN_ID and MODAL_TOKEN_SECRET not set. "
            "Get your tokens at: https://modal.com/settings/tokens"
        )
    return token_id, token_secret


def create_test_bundle(output_path: str) -> None:
    """Create a minimal test bundle using create_test_bundle.py.

    Parameters
    ----------
    output_path : str
        Path to save the bundle.
    """
    create_script = Path(__file__).parent / "create_test_bundle.py"
    result = subprocess.run(
        [sys.executable, str(create_script), output_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        raise RuntimeError(f"Failed to create test bundle: {result.stderr}")
    print(result.stdout)


class TestFitModelModal:
    """Test the fit_model_modal.py CLI."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.mark.slow
    def test_fit_model_modal_cli(self, temp_dir):
        """Test the complete Modal fitting workflow via CLI."""
        check_modal_tokens()

        bundle_path = temp_dir / "model_to_fit.pkl"
        output_path = temp_dir / "fitted_model.nc"

        # Create test bundle
        print("\n=== Creating test bundle ===")
        create_test_bundle(str(bundle_path))
        assert bundle_path.exists(), "Bundle file was not created"

        # Run fit_model_modal CLI
        print("\n=== Running fit_model_modal CLI ===")
        result = subprocess.run(
            [
                sys.executable,
                "-m", "mmm_lib.fit_model_modal",
                "--model-bundle", str(bundle_path),
                "--output", str(output_path),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(MMM_LIB_PATH.parent)},
            timeout=1800,  # 30 minute timeout
        )

        print("STDOUT:")
        print(result.stdout)
        if result.stderr:
            print("STDERR:")
            print(result.stderr)

        # Check result
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert output_path.exists(), "Fitted model was not created"

        # Verify fitted model can be loaded
        print("\n=== Verifying fitted model ===")
        self._verify_fitted_model(output_path)

    def _verify_fitted_model(self, model_path: Path):
        """Verify the fitted model is valid."""
        # Import here to avoid import errors when just running CLI test
        sys.path.insert(0, str(MMM_LIB_PATH.parent))
        from pymc_marketing.mmm.multidimensional import MMM

        mmm = MMM.load(str(model_path))

        print(f"Model type: {type(mmm).__name__}")
        print(f"Channels: {mmm.channel_columns}")

        # Check idata groups
        assert mmm.idata is not None, "idata is None"
        groups = list(mmm.idata.groups())
        print(f"idata groups: {groups}")

        # Should have posterior (from MCMC)
        assert "posterior" in groups, "Missing posterior group"
        posterior_vars = list(mmm.idata.posterior.data_vars)
        print(f"Posterior variables: {posterior_vars[:5]}...")  # First 5

        # Should have posterior_predictive (from local sampling)
        assert "posterior_predictive" in groups, "Missing posterior_predictive group"
        pp_vars = list(mmm.idata.posterior_predictive.data_vars)
        print(f"Posterior predictive variables: {pp_vars}")

        # Should have prior and prior_predictive (reattached)
        assert "prior" in groups, "Missing prior group (should be reattached)"
        prior_vars = list(mmm.idata.prior.data_vars)
        print(f"Prior variables: {prior_vars[:5]}...")  # First 5

        assert "prior_predictive" in groups, "Missing prior_predictive group (should be reattached)"
        prior_pred_vars = list(mmm.idata.prior_predictive.data_vars)
        print(f"Prior predictive variables: {prior_pred_vars}")

        # Verify prior has actual samples (not empty)
        prior_shape = mmm.idata.prior["intercept"].shape
        print(f"Prior 'intercept' shape: {prior_shape}")
        assert prior_shape[0] > 0, "Prior has no chains"
        assert prior_shape[1] > 0, "Prior has no samples"

        # Verify prior_predictive has actual samples
        prior_pred_shape = mmm.idata.prior_predictive["y"].shape
        print(f"Prior predictive 'y' shape: {prior_pred_shape}")
        assert prior_pred_shape[0] > 0, "Prior predictive has no chains"
        assert prior_pred_shape[1] > 0, "Prior predictive has no samples"

        print()
        print("All expected idata groups present with data!")


def main():
    """Run the test manually (not via pytest)."""
    check_modal_tokens()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        bundle_path = tmpdir / "model_to_fit.pkl"
        output_path = tmpdir / "fitted_model.nc"

        # Create test bundle
        print("=" * 60)
        print("STEP 1: Creating test bundle")
        print("=" * 60)
        create_test_bundle(str(bundle_path))

        # Run CLI
        print()
        print("=" * 60)
        print("STEP 2: Running fit_model_modal CLI")
        print("=" * 60)
        result = subprocess.run(
            [
                sys.executable,
                "-m", "mmm_lib.fit_model_modal",
                "--model-bundle", str(bundle_path),
                "--output", str(output_path),
            ],
            env={**os.environ, "PYTHONPATH": str(MMM_LIB_PATH.parent)},
        )

        if result.returncode != 0:
            print("CLI FAILED")
            sys.exit(1)

        # Verify
        print()
        print("=" * 60)
        print("STEP 3: Verifying fitted model")
        print("=" * 60)

        sys.path.insert(0, str(MMM_LIB_PATH.parent))
        from pymc_marketing.mmm.multidimensional import MMM

        mmm = MMM.load(str(output_path))
        print(f"Model type: {type(mmm).__name__}")
        print(f"Channels: {mmm.channel_columns}")
        groups = list(mmm.idata.groups())
        print(f"idata groups: {groups}")

        # Verify all required groups
        required = ["posterior", "posterior_predictive", "prior", "prior_predictive"]
        missing = [g for g in required if g not in groups]
        if missing:
            print(f"ERROR: Missing groups: {missing}")
            sys.exit(1)

        # Verify prior has samples (reattachment worked)
        prior_shape = mmm.idata.prior["intercept"].shape
        print(f"Prior 'intercept' shape: {prior_shape}")

        prior_pred_shape = mmm.idata.prior_predictive["y"].shape
        print(f"Prior predictive 'y' shape: {prior_pred_shape}")

        if prior_shape[1] == 0 or prior_pred_shape[1] == 0:
            print("ERROR: Prior samples are empty - reattachment failed")
            sys.exit(1)

        print()
        print("=" * 60)
        print("SUCCESS: All tests passed!")
        print("  - MCMC sampling on Modal: OK")
        print("  - Posterior predictive (local): OK")
        print("  - Prior reattachment: OK")
        print("=" * 60)


if __name__ == "__main__":
    main()
