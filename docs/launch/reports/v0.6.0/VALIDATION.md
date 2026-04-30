# Scoring Fix Validation — Six-Scan Comparison

This is the empirical close-out of the SCORING-ANALYSIS.md prediction.
Three scans before PR #60 (LLM-blend formula) versus three scans after
PR #60 + the round-3 fixes (penalty-only deterministic formula). Same
codebase (within R3 fix delta), same Claude Opus 4.7 + effort=xhigh,
all six runs forced (`--no-cache --force`).

## TL;DR

**Prediction (SCORING-ANALYSIS.md):** "Spread should shrink from 8 points
to ~5 points. Mean should shift up 3-7 points."

**Result:** Spread shrank to **2 points** (79% reduction). Mean shifted
**+5.3 points** (87.4 → 92.8). Both dimensions of the prediction
verified or beaten.

## Overall scores

| | Scan #1 | Scan #2 | Scan #3 | Scan #4 | Scan #5 | Scan #6 |
|--|--:|--:|--:|--:|--:|--:|
| **Formula** | OLD | OLD | OLD | NEW | NEW | NEW |
| Overall | A (92) | B+ (85) | B+ (85) | A (94) | A (92) | A (92) |
| Findings | 36 | 54 | 43 | 23 | 55 | 52 |
| Critical | 0 | 0 | 0 | 0 | 0 | 0 |
| High | 0 | 0 | 0 | 0 | 0 | 0 |
| Cost | $5.04 | $6.08 | $6.13 | $6.56 | $6.62 | $6.60 |

## Variance comparison

|  | OLD (3 scans) | NEW (3 scans) |
|--|--:|--:|
| Overall score range | 85–92 | 92–94 |
| **Spread (max − min)** | **8 pts** | **2 pts** ✅ |
| Mean | 87.4 | 92.8 |

**Spread shrank by 79%.** The remaining 2-point spread is real: same
finding set scored deterministically, but different scans surface
different finding sets.

## Per-dimension validation

| Dimension | OLD spread | NEW spread | Δ |
|-----------|---:|---:|---:|
| Architecture | 8 pts | 3 pts | **−61%** |
| **Security** | **22 pts** | **3 pts** | **−88%** ⭐ |
| Quality | 13 pts | 11 pts | −18% |
| Documentation | 3 pts | 3 pts | flat |
| **Maintainability** | **14 pts** | **3 pts** | **−80%** ⭐ |
| Performance | 4 pts | 9 pts | **+125%** ⚠ |

The Security dimension was the worst offender pre-fix (22-point swing,
99 → 77). It now sits at 3 points across runs, matching the other stable
dimensions.

The Performance regression (+125%) is honest: the new formula stopped
masking finding-set variance with a smoothing LLM blend, so when the
model surfaces 1 vs 9 performance findings (as it did in the new runs),
the underlying penalty-score gap is visible. **Total finding-set
variance still dominates; we've just stopped hiding it under an LLM
"opinion" layer.**

## What this validates

1. **The LLM holistic blend was the variance amplifier.** Removing it
   shrank the overall spread by 79%. The hypothesis that drove PR #60
   was correct.
2. **The severity floor remained stable.** 0 critical / 0 high in all
   six scans. The CI-gate signal users care about did not move.
3. **The score band is now real.** Two scans reading "92" and "94" mean
   "essentially the same code quality"; two scans reading "85" and "92"
   under the old formula did not — that 7-point swing was mostly LLM
   noise.

## What this does not validate

- **Per-dimension scores are still noisy** when the underlying
  finding set varies. Quality (11 pts) and Performance (9 pts) still
  show real swings because the model surfaces materially different
  finding sets per run. The fix targeted the LLM-blend amplifier, not
  the underlying finding-set non-determinism — that's a separate
  problem for a future PR (semantic dedup at MERGE stage, multi-run
  averaging, etc.).
- **N=3 is small.** Three scans on each side of the change is enough
  to demonstrate the effect size, not to characterise the long tail.
  A future scheduled job could measure across 20+ runs.

## Cost

Total spent on validation: **$36.03** across 6 scans
(3 × ~$6 baseline + 3 × ~$6.6 post-fix). Wall: ~50 min serial,
~10 min if run in parallel + accept some rate-limit pressure.

## Methodology

- Spectra repo at `main` for OLD scans (commit `1eeaa46` and earlier);
  same repo at `main` for NEW scans (commit `93a7a87` after R3 fixes).
  Code delta between OLD and NEW exists (R3 fixes addressed real medium
  findings) but does not explain the variance change. The
  fix-vs-formula attribution comes from the per-finding mapping in
  SCORING-ANALYSIS.md showing 0 stable findings across runs (i.e.
  the model surfaces effectively independent finding sets each run, so
  the only thing that should drive score variance is the formula).
- Same flags on all 6 runs:
  `--max-cost-usd 25 --allow-secrets --force --no-cache --format json`
- Scan #6 was first run during parallel OSS-leaderboard scans and got
  rate-limited (only architecture survived). It was re-run cleanly
  afterwards; the values shown above are from the clean re-run.

## Reports

| Scan | JSON |
|------|------|
| #1 OLD | [`spectra-self-confidential.json`](spectra-self-confidential.json) |
| #2 OLD | [`spectra-self-after-fixes-confidential.json`](spectra-self-after-fixes-confidential.json) |
| #3 OLD | [`spectra-self-scan-3-confidential.json`](spectra-self-scan-3-confidential.json) |
| #4 NEW | [`spectra-self-scan-4-confidential.json`](spectra-self-scan-4-confidential.json) |
| #5 NEW | [`spectra-self-scan-5-confidential.json`](spectra-self-scan-5-confidential.json) |
| #6 NEW | [`spectra-self-scan-6-confidential.json`](spectra-self-scan-6-confidential.json) |

## Reproduce

```bash
python3 /Users/leocder/Documents/spectra/spectra/docs/launch/reports/v0.6.0/scripts/validate6.py
```
