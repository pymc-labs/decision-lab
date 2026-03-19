#!/bin/bash
# =============================================================================
# Pre-run hook
# =============================================================================
# This script runs inside the Docker container BEFORE the agent starts.
# It's configured in config.yaml under hooks.pre-run.
#
# Use cases for pre-run hooks:
#   - Deploy Modal serverless apps (see decision-packs/mmm/deploy_modal.sh)
#   - Download data or models
#   - Set up environment
#   - Validate prerequisites
#
# If this script exits non-zero, the session aborts.
# The script runs via: docker exec <container> bash -c "/workspace/_hooks/say_hi.sh"
#
# Note: If using a named conda env, you'd need to activate it here.
# But the recommended pattern is to install into the base env instead.
# See: docs/decision-packs.md (section: Conda Named Environments in Hooks)

echo "Let's go"
