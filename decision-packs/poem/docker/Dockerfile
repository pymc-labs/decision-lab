# =============================================================================
# decision-pack Dockerfile
# =============================================================================
# This defines the container environment for the agent. dlab wraps this in a
# second Dockerfile that installs opencode on top (see dlab/docker.py).
#
# The final container runs with:
#   - /workspace mounted from the session work directory
#   - /_opencode_logs mounted for log output
#   - Environment variables from --env-file
#   - All DLAB_* env vars forwarded from the host
#
# The container stays alive via "tail -f /dev/null" so dlab can run
# commands inside it with "docker exec". The CMD here is NOT used at runtime.
#
# For this simple decision-pack, we just need Python. For data science
# decision-packs, you'd add packages here:
#
#   pip:   COPY requirements.txt ... && pip install -r ...
#   conda: COPY environment.yml ... && conda env update -n base -f ...
#   uv:    COPY --from=ghcr.io/astral-sh/uv:latest ... && uv pip install --system ...
#   pixi:  COPY pixi.toml /opt/pixi/ && cd /opt/pixi && pixi install
#
# See the MMM decision-pack (decision-packs/mmm/docker/Dockerfile) for a
# full example with conda, custom libraries, and Modal serverless compute.

FROM python:3.11-slim

WORKDIR /workspace

CMD ["/bin/bash"]
