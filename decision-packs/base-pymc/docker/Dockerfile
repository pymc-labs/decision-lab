# =============================================================================
# base-pymc Dockerfile — pixi environment
# =============================================================================
# Installs the pixi environment to /opt/pixi/ (NOT /workspace/).
# /workspace is volume-mounted at runtime — installing there would shadow
# the environment on every dlab run.
#
# Build flow:
#   1. Install pixi binary
#   2. Copy pixi.toml to /opt/pixi/ and resolve the environment
#   3. Add the resolved env to PATH
#   4. Verify imports at build time (fail fast if deps are broken)
#
# dlab wraps this in a second Dockerfile that installs opencode on top.
# See: dlab/docker.py

FROM debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install pixi
RUN curl -fsSL https://pixi.sh/install.sh | bash
ENV PATH="/root/.pixi/bin:$PATH"

# Resolve environment into /opt/pixi/ — separate from the /workspace mount
COPY pixi.toml /opt/pixi/pixi.toml
RUN cd /opt/pixi && pixi install

# Activate the resolved environment for all subsequent layers and runtime
ENV PATH="/opt/pixi/.pixi/envs/default/bin:$PATH"

# Fail the build early if critical packages are broken
RUN python -c "import pymc, arviz, seaborn; print('PyMC', pymc.__version__, '| arviz', arviz.__version__, '| OK')"

WORKDIR /workspace

CMD ["/bin/bash"]
