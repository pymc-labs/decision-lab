#!/usr/bin/env bash
# Pre-run hook: optionally verify data and confirm the Python environment.
set -e

echo "=== setup.sh: pre-run hook ==="

# 1. Check if data was provided (optional for this pack)
if [ -d "data" ] && [ "$(find data -name '*.parquet' -o -name '*.csv' -o -name '*.json' 2>/dev/null | wc -l)" -gt 0 ]; then
    echo "  Data OK: $(find data -type f \( -name '*.parquet' -o -name '*.csv' -o -name '*.json' \) | wc -l) data files found"
else
    echo "  No data files provided — forecasters will rely on domain knowledge and skill references"
fi

# 2. Confirm the pre-installed Python environment at /opt/pixi is usable
echo "  Python env: $(python -c 'import pymc; print("PyMC", pymc.__version__)' 2>/dev/null || echo 'check manually')"

echo "=== setup.sh: done ==="
