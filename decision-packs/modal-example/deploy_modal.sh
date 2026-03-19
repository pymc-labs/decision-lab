#!/bin/bash
# Pre-run hook: deploy Modal app for cloud compute
set -e

# Default to local execution — skip Modal deploy
if [ "${DLAB_RUN_MODAL_TOOL_LOCALLY:-1}" = "1" ]; then
    echo "Local mode (DLAB_RUN_MODAL_TOOL_LOCALLY=1). Skipping Modal deployment."
    exit 0
fi

# Check Modal credentials
if [ -z "$MODAL_TOKEN_ID" ] || [ -z "$MODAL_TOKEN_SECRET" ]; then
    echo "Warning: Modal tokens not set. Skipping Modal deployment."
    exit 0
fi

MODAL_APP="/opt/modal_app/example.py"

if [ -f "$MODAL_APP" ]; then
    echo "Deploying Modal app..."
    modal deploy "$MODAL_APP"
    echo "Modal app deployed."
else
    echo "Warning: Modal app not found at $MODAL_APP, skipping deploy"
fi
