FROM continuumio/miniconda3:25.3.1-1

WORKDIR /workspace

# Configure conda to use conda-forge as primary channel
RUN conda config --add channels conda-forge && \
    conda config --set channel_priority strict

# Install packages from conda-forge with pinned versions
RUN conda install -y \
    python=3.11.14 \
    pandas=3.0.0 \
    scipy=1.17.0 \
    polars=1.37.1 \
    fastparquet=2025.12.0 \
    matplotlib=3.10.8 \
    seaborn=0.13.2 \
    scikit-learn=1.8.0 \
    statsmodels=0.14.6 \
    arviz=0.23.1 \
    pymc=5.26.1 \
    pytensor=2.35.1 \
    pyyaml=6.0.3 \
    && conda clean -afy

# Install pip packages with pinned versions
# numpy installed via pip to get compatible version with pymc-marketing
# JAX and numpyro required for nuts_sampler="numpyro" (faster MCMC)
# cloudpickle required for serializing MMM models with complex objects
# pyarrow via pip (not conda) so Coiled package sync works
# jax/jaxlib via pip because conda-forge doesn't have 0.9.x versions
# xarray/h5py pinned to match Modal app for cloudpickle compatibility
# modal for cloud MCMC fitting
RUN pip install --no-cache-dir \
    numpy==2.3.5 \
    pyarrow==23.0.0 \
    pymc-marketing==0.18.0 \
    cloudpickle==3.1.2 \
    jax==0.4.35 \
    jaxlib==0.4.35 \
    numpyro==0.16.1 \
    xarray==2025.12.0 \
    h5py==3.15.1 \
    modal==1.3.2

# Copy MMM library
COPY mmm_lib /opt/mmm_lib

# Copy Modal app (for deploying mmm-sampler function)
COPY modal_app /opt/modal_app

# Make library importable (set to /opt so "import mmm_lib" finds /opt/mmm_lib/)
ENV PYTHONPATH="/opt"

# Allow PyTensor C++ compilation for faster deterministics computation
# (numpyro handles MCMC, but post-MCMC compute_deterministics uses PyTensor)
# ENV PYTENSOR_FLAGS="cxx="  # Removed - C++ compilation is faster overall

# Verify critical imports work (fail build early if dependencies are broken)
RUN python -c "from pymc_marketing.mmm.multidimensional import MMM; print('MultidimensionalMMM import OK')"
RUN python -c "import mmm_lib; print('mmm_lib import OK')" || (python -c "import mmm_lib" 2>&1; exit 1)

# Verify JAX and numpyro work (required for nuts_sampler="numpyro")
RUN python -c "import jax; import jax.numpy as jnp; x = jnp.array([1.0, 2.0, 3.0]); print(f'JAX OK: {x.sum()}')"
RUN python -c "import numpyro; print('numpyro import OK')"
RUN python -c "from pymc.sampling.jax import sample_numpyro_nuts; print('PyMC numpyro sampler OK')"

CMD ["/bin/bash"]
