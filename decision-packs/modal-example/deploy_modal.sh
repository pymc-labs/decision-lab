#!/bin/bash
# Pre-run hook: deploy Modal app for cloud compute
set -e

# Activate the conda environment where modal is installed.
# docker exec does not activate conda envs automatically — the container's
# SHELL directive and CMD are overridden by dlab's "tail -f /dev/null" keepalive.
eval "$(conda shell.bash hook 2> /dev/null)"
conda activate dlab-modal-example

MODAL_APP="/opt/modal_app/example.py"

if [ -f "$MODAL_APP" ]; then
    echo "Deploying Modal app..."
    modal deploy "$MODAL_APP"
    echo "Modal app deployed."
else
    echo "Warning: Modal app not found at $MODAL_APP, skipping deploy"
fi
