# Conflict Detection Report

## Models Evaluated
All 3 model instances converged successfully.

## Check 1: ROAS Variation (< 5x threshold)
| Channel | Min ROAS | Max ROAS | Ratio | Status |
|---------|----------|----------|-------|--------|
| TV | 2.18 | 2.58 | 1.18x | ✅ Pass |
| Digital | 3.62 | 3.95 | 1.09x | ✅ Pass |
| Social | 2.76 | 3.21 | 1.16x | ✅ Pass |
| Search | 3.89 | 4.28 | 1.10x | ✅ Pass |
| Print | 1.08 | 1.41 | 1.31x | ✅ Pass |

**Result**: ✅ All channels within acceptable variation range.

## Check 2: Directional Agreement
All models agree on the sign and relative magnitude of all channel effects.
- All channels show positive ROAS across all models
- No directional disagreements detected

**Result**: ✅ Full directional agreement.

## Check 3: Top 5 Channel Ranking Consistency
| Rank | Instance 1 | Instance 2 | Instance 3 |
|------|-----------|-----------|-----------|
| 1 | Search | Search | Search |
| 2 | Digital | Digital | Digital |
| 3 | Social | Social | Social |
| 4 | TV | TV | TV |
| 5 | Print | Print | Print |

**Result**: ✅ Identical ranking across all models.

## Overall Verdict
**✅ NO CONFLICTS DETECTED** — Proceeding to model selection and budget optimization.

Models show remarkable consistency despite different adstock formulations and data cleaning approaches, which strengthens confidence in the results.
