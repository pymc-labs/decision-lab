#!/bin/bash
# =============================================================================
# Post-run hook
# =============================================================================
# This script runs inside the Docker container AFTER the agent finishes.
# It's configured in config.yaml under hooks.post-run.
#
# Post-run hooks run even if the agent failed. A non-zero exit code from a
# post-run hook prints a WARNING but does not change the session exit code.
#
# Use cases for post-run hooks:
#   - Print or format results
#   - Upload artifacts
#   - Clean up temporary files
#   - Send notifications
#
# The agent writes its output to /workspace/ (mounted from the work directory).
# This script reads final_poem.md which the orchestrator (literary-agent.md)
# creates in Step 3 of its workflow.

echo ""
echo "========== Final Poem =========="
if [ -f /workspace/final_poem.md ]; then
    cat /workspace/final_poem.md
else
    echo "No final_poem.md found."
fi
echo ""
echo "================================"
