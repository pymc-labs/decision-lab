# MMM Flavor Tests

Tests for the MMM (Marketing Mix Modeling) decision-pack, including local workflow tests and cloud MCMC execution tests.

## Prerequisites

### Python Environment

Tests require the `mmm-docker` conda environment:

```bash
cd decision-packs/mmm
conda env create -f environment.yaml
conda activate mmm-docker
```

### Cloud Credentials

#### Modal (for `test_modal_*.py`)

1. Create account at https://modal.com
2. Generate API tokens at https://modal.com/settings/tokens
3. Set environment variables:
   ```bash
   export MODAL_TOKEN_ID="ak-..."
   export MODAL_TOKEN_SECRET="as-..."
   ```
   Or add to `.env` file in project root:
   ```
   MODAL_TOKEN_ID=ak-...
   MODAL_TOKEN_SECRET=as-...
   ```

4. Deploy the Modal app (required before running tests):
   ```bash
   modal deploy ../docker/modal_app/mmm_sampler.py
   ```

#### Coiled (for `test_fit_coiled.py`)

1. Create account at https://coiled.io
2. Get API token at https://cloud.coiled.io/profile
3. Set environment variable:
   ```bash
   export DASK_COILED__TOKEN="..."
   ```

## Running Tests

### Quick Tests (no cloud)

```bash
# Run all non-slow tests
pytest -v -m "not slow"

# Run local pickle workflow test
pytest test_pickle_workflow.py -v
```

### Modal Tests

```bash
# Check Modal is configured correctly
pytest test_modal_integration.py::TestModalDeployment -v

# Run full Modal MCMC test (takes ~1-2 min)
pytest test_modal_integration.py -v -s

# Run Modal CLI workflow test
pytest test_fit_modal.py -v -s
```

### Coiled Tests

```bash
pytest test_fit_coiled.py -v -s
```

### All Tests

```bash
# Including slow cloud tests
pytest -v -s

# With timing info
pytest -v -s --durations=0
```

## Test Files

| File | Description | Cloud Required |
|------|-------------|----------------|
| `test_pickle_workflow.py` | Local 3-phase pickle workflow | No |
| `test_modal_integration.py` | Modal function tests with fixture | Yes (Modal) |
| `test_fit_modal.py` | Modal CLI workflow test | Yes (Modal) |
| `test_fit_coiled.py` | Coiled CLI workflow test | Yes (Coiled) |
| `compare_backends.py` | numpyro vs PyTensor benchmark | No |

## Test Fixtures

### `fixtures/test_bundle_minimal.pkl`

Pre-generated model bundle for integration tests. Contains:
- MMM model with 2 channels, 1 control
- 20 weeks of synthetic data
- Prior predictive samples
- Sampling params: draws=50, tune=50, chains=2

To regenerate:
```bash
python create_test_bundle.py fixtures/test_bundle_minimal.pkl
```

## Modal Deployment

### Architecture

The Modal app (`mmm_sampler.py`) parses the Dockerfile at deploy time to extract
pinned package versions. This ensures:
- Single source of truth: Dockerfile defines all versions
- Cloudpickle compatibility: Modal and Docker containers use identical packages

### First-Time Setup

```bash
# Authenticate (one-time)
export MODAL_TOKEN_ID="ak-..."
export MODAL_TOKEN_SECRET="as-..."

# Deploy the app
modal deploy ../docker/modal_app/mmm_sampler.py
```

### Automatic Redeployment (via dlab)

When using `dlab`, Modal deployment is handled automatically:

| Change | Docker | Modal |
|--------|--------|-------|
| Dockerfile or modal_app/ changes | Rebuilds | Redeploys |
| `--rebuild` flag | Rebuilds | Redeploys |
| `--rebuild-modal` flag | No change | Redeploys |
| Modal function missing | No change | Deploys |
| No changes | Cached | Skipped |

Since `modal_app/` is inside `docker/`, any change triggers Docker rebuild which forces Modal redeploy.

### Manual Redeployment

Redeploy after changing `mmm_sampler.py`:

```bash
modal deploy ../docker/modal_app/mmm_sampler.py
```

Or force rebuild of the Modal container image:

```bash
MODAL_FORCE_BUILD=1 modal deploy ../docker/modal_app/mmm_sampler.py
```

### Verify Deployment

```bash
# Check function is accessible
python -c "import modal; print(modal.Function.from_name('mmm-sampler', 'fit_mmm'))"
```

## Troubleshooting

### Modal function not found

```
modal.exception.NotFoundError: Function mmm-sampler/fit_mmm not found
```

**Solution**: Deploy the Modal app:
```bash
modal deploy ../docker/modal_app/mmm_sampler.py
```

### Modal authentication error

```
modal.exception.AuthError: No Modal credentials found
```

**Solution**: Set environment variables or add to `.env`:
```bash
export MODAL_TOKEN_ID="ak-..."
export MODAL_TOKEN_SECRET="as-..."
```

### MCMC too slow (PyTensor fallback)

If `test_numpyro_backend_used` fails with slow speed (<3 it/s), numpyro isn't working.

**Solution**: Force rebuild Modal image:
```bash
MODAL_FORCE_BUILD=1 modal deploy ../docker/modal_app/mmm_sampler.py
```

Check Modal logs for JAX/numpyro import errors.

### Test fixture not found

```
Test fixture not found: .../fixtures/test_bundle_minimal.pkl
```

**Solution**: Generate the fixture:
```bash
python create_test_bundle.py fixtures/test_bundle_minimal.pkl
```

### Coiled timeout / connection lost

Coiled uses AWS instances which may have transient network issues.

**Solution**: Retry the test. If persistent, check:
- AWS region availability
- Coiled dashboard for cluster status
- `DASK_COILED__TOKEN` is valid

## Performance Expectations

| Backend | Speed | 200 iterations |
|---------|-------|----------------|
| numpyro (Modal/Coiled) | 5-10 it/s | 20-40 seconds |
| PyTensor (fallback) | 1-2 it/s | 2-3 minutes |

Modal with numpyro is typically 4-5x faster than Coiled due to x86 vs ARM architecture differences for JAX.
