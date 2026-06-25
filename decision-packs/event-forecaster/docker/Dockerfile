FROM ghcr.io/prefix-dev/pixi:latest

# Install Python stack at /opt/pixi so it is NOT shadowed by the
# /workspace volume mount that dlab applies at runtime.
WORKDIR /opt/pixi
COPY pixi.toml pixi.lock ./
RUN pixi install --locked

# Verify the critical stack works — fail the build early if anything is broken
RUN pixi run python -c "import pymc; import arviz; print(f'PyMC {pymc.__version__} | ArviZ {arviz.__version__} OK')"
RUN pixi run python -c "import polars; import numpy; import scipy; print('Polars / NumPy / SciPy OK')"
RUN pixi run python -c "import jax; import numpyro; print(f'JAX {jax.__version__} | numpyro OK')"
RUN pixi run python -c "import nutpie; print('nutpie OK')"

# Set PIXI_PROJECT_MANIFEST globally so all pixi commands in the container
# (pixi run, pixi add) automatically target /opt/pixi without agents needing
# to specify the manifest path.
ENV PIXI_PROJECT_MANIFEST=/opt/pixi/pixi.toml

# Route bare python/python3 calls through the pixi environment so agents
# can write plain "python script.py" and get the full scientific stack.
# pixi is already on PATH from the base image.
RUN printf '#!/bin/bash\nexec pixi run python "$@"\n' \
    | tee /usr/local/bin/python /usr/local/bin/python3 > /dev/null \
    && chmod +x /usr/local/bin/python /usr/local/bin/python3

# Sanity-check the wrappers
RUN python --version \
    && python -c "import pymc, polars, pyarrow; print('python wrapper OK')"

# Agent sessions run in /workspace (mounted at runtime by dlab)
WORKDIR /workspace
CMD ["/bin/bash"]
