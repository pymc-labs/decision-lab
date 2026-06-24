#!/usr/bin/env bash
# Post-run validation hook (event-forecaster).
#
# Fails the session if any Bayesian forecaster's idata.nc is missing a predictions
# (or posterior_predictive) group. This enforces that forecasters store BOTH the
# parameter posterior AND the per-draw forecast predictions — a prompt instruction
# alone has proven insufficient.
set -uo pipefail

echo "=== validate_predictions: post-run hook check ==="

python - <<'PY'
import glob
import sys

import arviz as az

paths = sorted(glob.glob("parallel/*/instance-*/outputs/idata.nc"))
paths += sorted(glob.glob("outputs/idata.nc"))  # single (non-parallel) runs

if not paths:
    print("  no idata.nc found (no Bayesian forecasters?) — nothing to validate")
    sys.exit(0)

missing = []
for p in paths:
    try:
        groups = [g.strip("/") for g in az.from_netcdf(p).groups]
    except Exception as exc:
        print(f"  {p}: ERROR reading ({exc})")
        missing.append(p)
        continue
    ok = ("predictions" in groups) or ("posterior_predictive" in groups)
    print(f"  {p}: {'OK' if ok else 'MISSING predictions'}  groups={groups}")
    if not ok:
        missing.append(p)

if missing:
    print()
    print("FAIL: the following idata.nc lack a predictions / posterior_predictive group:")
    for m in missing:
        print(f"  - {m}")
    print()
    print("Forecasters must save the per-draw forecast with save_idata_with_predictions(...)")
    print("(see opencode/skills/event-forecasting/references/save_predictions.py and")
    print("forecaster.md Step 3a). Re-run the affected forecaster(s) so idata.nc carries")
    print("both the posterior AND the predictions group.")
    sys.exit(1)

print()
print(f"PASS: all {len(paths)} idata.nc contain a predictions group.")
PY
