"""Test the pickle workflow for MMM model fitting.

This tests the 3-phase workflow:
1. Prepare: Create MMM with hierarchical priors, build model, run prior predictive, pickle
2. Fit: Load from pickle, fit with numpyro, save with mmm.save()
3. Analyze: Load with MMM.load(), compute ROAS/contributions
"""

import os
import cloudpickle
import tempfile
from pathlib import Path

import pytest

# Add mmm_lib to path for testing outside Docker
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "docker"))

from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation
from pymc_marketing.mmm.multidimensional import MMM
from pymc_extras.prior import Prior

from mmm_lib import (
    prepare_mmm_data,
    check_convergence,
    check_prior_predictive_coverage,
)


class TestPickleWorkflow:
    """Test the complete pickle workflow for MMM."""

    def test_create_multidim_mmm_with_hierarchical_priors(
        self, multidim_market_data, channel_columns, control_columns
    ):
        """Test creating MMM with hierarchical priors."""
        df = multidim_market_data

        # Configure hierarchical priors for adstock
        # Hyperpriors at channel level, final params at (channel, geo)
        adstock = GeometricAdstock(
            l_max=8,
            priors={
                "alpha": Prior(
                    "Beta",
                    alpha=Prior("Gamma", mu=2, sigma=1, dims="channel"),
                    beta=Prior("Gamma", mu=5, sigma=2, dims="channel"),
                    dims=("channel", "geo"),
                )
            },
        )

        # Hierarchical saturation priors
        saturation = LogisticSaturation(
            priors={
                "lam": Prior(
                    "Gamma",
                    mu=Prior("HalfNormal", sigma=1, dims="channel"),
                    sigma=Prior("HalfNormal", sigma=0.5, dims="channel"),
                    dims=("channel", "geo"),
                ),
                "beta": Prior(
                    "HalfNormal",
                    sigma=Prior("HalfNormal", sigma=1, dims="channel"),
                    dims=("channel", "geo"),
                ),
            }
        )

        mmm = MMM(
            date_column="date",
            target_column="sales",
            channel_columns=channel_columns,
            control_columns=control_columns,
            dims=("geo",),
            adstock=adstock,
            saturation=saturation,
            yearly_seasonality=4,
        )

        assert mmm is not None
        assert mmm.date_column == "date"
        assert mmm.target_column == "sales"
        assert mmm.channel_columns == channel_columns

    def test_pickle_unfitted_model(
        self, multidim_market_data, channel_columns, control_columns
    ):
        """Test pickling an unfitted MMM model."""
        df = multidim_market_data

        # Create model with hierarchical priors
        adstock = GeometricAdstock(
            l_max=8,
            priors={
                "alpha": Prior(
                    "Beta",
                    alpha=Prior("Gamma", mu=2, sigma=1, dims="channel"),
                    beta=Prior("Gamma", mu=5, sigma=2, dims="channel"),
                    dims=("channel", "geo"),
                )
            },
        )

        saturation = LogisticSaturation(
            priors={
                "lam": Prior("Gamma", mu=1, sigma=0.5, dims=("channel", "geo")),
                "beta": Prior("HalfNormal", sigma=2, dims=("channel", "geo")),
            }
        )

        mmm = MMM(
            date_column="date",
            target_column="sales",
            channel_columns=channel_columns,
            control_columns=control_columns,
            dims=("geo",),
            adstock=adstock,
            saturation=saturation,
            yearly_seasonality=4,
        )

        # Prepare data
        X, y = prepare_mmm_data(df, date_column="date", y_column="sales")

        # Build model
        mmm.build_model(X=X, y=y)

        # Sample prior predictive
        mmm.sample_prior_predictive(X, samples=100)

        # Verify prior predictive samples exist
        assert mmm.idata is not None
        assert "prior_predictive" in mmm.idata.groups()

        # Pickle the unfitted model
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            cloudpickle.dump(mmm, f)
            pkl_path = f.name

        try:
            # Verify we can load it back
            with open(pkl_path, "rb") as f:
                loaded_mmm = cloudpickle.load(f)

            assert loaded_mmm is not None
            assert loaded_mmm.date_column == "date"
            assert loaded_mmm.channel_columns == channel_columns
        finally:
            os.unlink(pkl_path)

    @pytest.mark.slow
    def test_full_pickle_workflow(
        self, multidim_market_data, channel_columns, control_columns
    ):
        """Test the complete pickle workflow: pickle -> fit -> save -> load -> analyze."""
        df = multidim_market_data

        # Phase 1: Create and pickle unfitted model
        adstock = GeometricAdstock(
            l_max=4,  # Shorter for faster test
            priors={
                "alpha": Prior("Beta", alpha=2, beta=5, dims=("channel", "geo"))
            },
        )

        saturation = LogisticSaturation(
            priors={
                "lam": Prior("Gamma", mu=1, sigma=0.5, dims=("channel", "geo")),
                "beta": Prior("HalfNormal", sigma=2, dims=("channel", "geo")),
            }
        )

        mmm = MMM(
            date_column="date",
            target_column="sales",
            channel_columns=channel_columns,
            control_columns=control_columns,
            dims=("geo",),
            adstock=adstock,
            saturation=saturation,
            yearly_seasonality=2,  # Minimal for speed
        )

        X, y = prepare_mmm_data(df, date_column="date", y_column="sales")
        mmm.build_model(X=X, y=y)
        mmm.sample_prior_predictive(X, samples=50)

        with tempfile.TemporaryDirectory() as tmpdir:
            pkl_path = Path(tmpdir) / "unfitted_model.pkl"
            fitted_path = Path(tmpdir) / "fitted_model.nc"

            # Pickle unfitted model
            with open(pkl_path, "wb") as f:
                cloudpickle.dump(mmm, f)

            # Phase 2: Load from pickle and fit
            with open(pkl_path, "rb") as f:
                mmm_loaded = cloudpickle.load(f)

            # Fit with minimal samples for testing
            mmm_loaded.fit(
                X=X,
                y=y,
                nuts_sampler="numpyro",
                draws=50,
                tune=50,
                chains=2,
                target_accept=0.8,
                random_seed=42,
            )

            # Save with canonical mmm.save()
            mmm_loaded.save(str(fitted_path))

            # Verify fitted model was saved
            assert fitted_path.exists()

            # Phase 3: Load and analyze
            mmm_final = MMM.load(str(fitted_path))

            # Check convergence
            diagnostics = check_convergence(mmm_final, verbose=False)
            assert "converged" in diagnostics
            assert "max_rhat" in diagnostics

            # Compute ROAS using built-in pymc-marketing API
            roas = mmm_final.summary.roas(frequency="all_time")
            assert roas is not None
            assert len(roas) > 0

            # Verify model has posterior samples
            assert mmm_final.idata is not None
            assert "posterior" in mmm_final.idata.groups()


class TestPickleWorkflowUnit:
    """Unit tests for individual workflow components."""

    def test_prepare_mmm_data(self, multidim_market_data):
        """Test data preparation for MMM."""
        df = multidim_market_data
        X, y = prepare_mmm_data(df, date_column="date", y_column="sales")

        assert X is not None
        assert y is not None
        assert len(X) == len(df)
        assert len(y) == len(df)
        assert "sales" not in X.columns

    def test_prior_creation_with_dims(self, channel_columns):
        """Test creating priors with dimension specifications."""
        # Simple prior with dims
        alpha_prior = Prior("Beta", alpha=2, beta=5, dims=("channel", "geo"))
        assert alpha_prior is not None

        # Hierarchical prior
        hierarchical_prior = Prior(
            "Beta",
            alpha=Prior("Gamma", mu=2, sigma=1, dims="channel"),
            beta=Prior("Gamma", mu=5, sigma=2, dims="channel"),
            dims=("channel", "geo"),
        )
        assert hierarchical_prior is not None

    def test_adstock_saturation_creation(self):
        """Test creating adstock and saturation transformations."""
        adstock = GeometricAdstock(
            l_max=8,
            priors={"alpha": Prior("Beta", alpha=2, beta=5, dims=("channel", "geo"))},
        )
        assert adstock is not None

        saturation = LogisticSaturation(
            priors={
                "lam": Prior("Gamma", mu=1, sigma=0.5, dims=("channel", "geo")),
                "beta": Prior("HalfNormal", sigma=2, dims=("channel", "geo")),
            }
        )
        assert saturation is not None


class TestMMMLibFunctions:
    """Test mmm_lib functions work correctly with MMM."""

    def test_check_prior_predictive_coverage_multidim(
        self, multidim_market_data, channel_columns, control_columns
    ):
        """Test check_prior_predictive_coverage works with MMM."""
        df = multidim_market_data

        adstock = GeometricAdstock(
            l_max=4,
            priors={"alpha": Prior("Beta", alpha=2, beta=5, dims=("channel", "geo"))},
        )
        saturation = LogisticSaturation(
            priors={
                "lam": Prior("Gamma", mu=1, sigma=0.5, dims=("channel", "geo")),
                "beta": Prior("HalfNormal", sigma=2, dims=("channel", "geo")),
            }
        )

        mmm = MMM(
            date_column="date",
            target_column="sales",
            channel_columns=channel_columns,
            control_columns=control_columns,
            dims=("geo",),
            adstock=adstock,
            saturation=saturation,
            yearly_seasonality=2,
        )

        X, y = prepare_mmm_data(df, date_column="date", y_column="sales")
        mmm.build_model(X=X, y=y)
        mmm.sample_prior_predictive(X, samples=50)

        # This should work without errors for MMM
        coverage = check_prior_predictive_coverage(mmm, y, verbose=False)

        assert "coverage_percent" in coverage
        assert "is_multidim" in coverage
        assert coverage["is_multidim"] is True
        assert coverage["total_points"] == len(y)

    @pytest.mark.slow
    def test_contributions_multidim(
        self, multidim_market_data, channel_columns, control_columns
    ):
        """Test mmm.summary.contributions() works with MMM."""
        df = multidim_market_data

        adstock = GeometricAdstock(
            l_max=4,
            priors={"alpha": Prior("Beta", alpha=2, beta=5, dims=("channel", "geo"))},
        )
        saturation = LogisticSaturation(
            priors={
                "lam": Prior("Gamma", mu=1, sigma=0.5, dims=("channel", "geo")),
                "beta": Prior("HalfNormal", sigma=2, dims=("channel", "geo")),
            }
        )

        mmm = MMM(
            date_column="date",
            target_column="sales",
            channel_columns=channel_columns,
            control_columns=control_columns,
            dims=("geo",),
            adstock=adstock,
            saturation=saturation,
            yearly_seasonality=2,
        )

        X, y = prepare_mmm_data(df, date_column="date", y_column="sales")

        # Fit with minimal samples
        mmm.fit(
            X=X,
            y=y,
            nuts_sampler="numpyro",
            draws=50,
            tune=50,
            chains=2,
            random_seed=42,
        )

        # Test built-in contributions API
        contrib_df = mmm.summary.contributions(component="channel")

        assert contrib_df is not None
        assert len(contrib_df) > 0

    @pytest.mark.slow
    def test_roas_summary_multidim(
        self, multidim_market_data, channel_columns, control_columns
    ):
        """Test mmm.summary.roas() works with MMM."""
        df = multidim_market_data

        adstock = GeometricAdstock(
            l_max=4,
            priors={"alpha": Prior("Beta", alpha=2, beta=5, dims=("channel", "geo"))},
        )
        saturation = LogisticSaturation(
            priors={
                "lam": Prior("Gamma", mu=1, sigma=0.5, dims=("channel", "geo")),
                "beta": Prior("HalfNormal", sigma=2, dims=("channel", "geo")),
            }
        )

        mmm = MMM(
            date_column="date",
            target_column="sales",
            channel_columns=channel_columns,
            control_columns=control_columns,
            dims=("geo",),
            adstock=adstock,
            saturation=saturation,
            yearly_seasonality=2,
        )

        X, y = prepare_mmm_data(df, date_column="date", y_column="sales")

        # Fit with minimal samples
        mmm.fit(
            X=X,
            y=y,
            nuts_sampler="numpyro",
            draws=50,
            tune=50,
            chains=2,
            random_seed=42,
        )

        # Test built-in ROAS summary API
        roas = mmm.summary.roas(frequency="all_time")

        assert roas is not None
        assert len(roas) > 0
