#!/bin/bash
# MMM decision-pack prerun: deploy Modal app for cloud MCMC sampling
set -e

# Skip Modal deploy only if explicitly requested
if [ "${DLAB_FIT_MODEL_LOCALLY}" = "1" ]; then
    echo "DLAB_FIT_MODEL_LOCALLY=1. Skipping Modal deployment."
    exit 0
fi

# Check Modal credentials — fall back to local if missing
if [ -z "$MODAL_TOKEN_ID" ] || [ -z "$MODAL_TOKEN_SECRET" ]; then
    echo "Modal tokens not set. Models will be fit locally."
    echo "For faster cloud fitting, add MODAL_TOKEN_ID and MODAL_TOKEN_SECRET to your .env"
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
