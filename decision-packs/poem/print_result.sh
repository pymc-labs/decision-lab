#!/bin/bash
echo ""
echo "========== Final Poem =========="
if [ -f /workspace/final_poem.md ]; then
    cat /workspace/final_poem.md
else
    echo "No final_poem.md found."
fi
echo ""
echo "================================"
