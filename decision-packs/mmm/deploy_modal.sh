#!/bin/bash
# MMM decision-pack prerun: deploy Modal app for cloud MCMC sampling
set -e

# Default to local fitting — skip Modal deploy
if [ "${DLAB_FIT_MODEL_LOCALLY:-1}" = "1" ]; then
    echo "Local fitting mode (DLAB_FIT_MODEL_LOCALLY=1). Skipping Modal deployment."
    exit 0
fi

# Check Modal credentials
if [ -z "$MODAL_TOKEN_ID" ] || [ -z "$MODAL_TOKEN_SECRET" ]; then
    echo "Warning: Modal tokens not set. Models will be fit locally."
    exit 0
fi

MODAL_APP="/opt/modal_app/mmm_sampler.py"

if [ -f "$MODAL_APP" ]; then
    echo "Deploying Modal app..."
    modal deploy "$MODAL_APP"
    echo "Modal app deployed."
else
    echo "Warning: Modal app not found at $MODAL_APP, skipping deploy"
fi
