# Scoring Analysis — Why "Fixing Things" Lowered the Grade

A root-cause investigation of the variance pattern observed in the
v0.6.0 self-scan series. Companion to
[`COMPARISON.md`](COMPARISON.md).

## The puzzle

Three forced (no-cache) self-scans of identical code produced wildly
different overall grades:

| | Scan #1 | Scan #2 | Scan #3 |
|--|---|---|---|
| Overall | A (92) | B+ (85) | B+ (85) |
| Critical / High | 0 / 0 | 0 / 0 | 0 / 0 |
| Total findings | 36 | 54 | 43 |

Score range: 8 points on byte-identical code. Per-dimension swings
were even worse — Security went 99 → 93 → 77 (a 22-point spread
across runs of the same source).

When we shipped fixes between scans, the overall grade went *down*,
not up. This was the symptom that started the investigation.

## What we found

### Finding 1 — Zero exact-title overlap across runs

Of the 133 raw findings emitted across the three scans, **zero** appear
in more than one scan by exact title match:

```
In all 3 scans:    0 findings
In 2 of 3 scans:   0 findings
Only in scan #1:   36 (one-shot)
Only in scan #2:   54 (one-shot)
Only in scan #3:   43 (one-shot)
```

Every finding is a "one-shot" by exact wording. The model paraphrases
the same underlying issue differently every run.

### Finding 2 — LLM-as-judge dedup ratio: 1.73x

Asked Claude (Opus 4.7) to cluster the 133 findings by semantic
identity, dimension by dimension. Result: **77 distinct issues**, of
which **38 recur in 2+ scans (real signal)** and **39 are pure
one-shot paraphrasings (stochastic noise)**.

| Dimension | Raw findings | Distinct issues | In all 3 scans (stable) | In 2 scans (partial) | Stochastic |
|-----------|-------------:|----------------:|------------------------:|---------------------:|-----------:|
| Architecture | 28 | 17 | 4 | 3 | 10 |
| Documentation | 27 | 14 | 3 | 5 | 6 |
| Maintainability | 22 | 13 | 2 | 5 | 6 |
| Performance | 16 | 7 | 3 | 3 | 1 |
| Quality | 22 | 14 | 2 | 4 | 8 |
| Security | 18 | 12 | 2 | 2 | 8 |
| **Total** | **133** | **77** | **17** | **22** | **39** |

So roughly half of every "new finding" the model produces on a re-scan
is just a different way of saying something it (or another agent) said
last time.

### Finding 3 — The variance amplifier is the LLM holistic blend

The pre-PR-#60 scoring formula was:

```
dimension_score = 0.4 * llm_holistic_score + 0.6 * penalty_score

where:
  penalty_score = max(0, 100 - sum(severity_penalty[f.severity] * f.confidence))
  severity_penalty = {critical: 15, high: 8, medium: 3, low: 1, info: 0}
```

Each agent emits a `dimension_score` field — its own holistic 0-100
take on the dimension. We blended that 40/60 with the formula. **That
LLM holistic was responsible for most of the cross-run variance.**

Decomposed against the actual scan data (penalty-only score vs
reported score):

| | Scan #1 sec | Scan #2 sec | Scan #3 sec |
|--|---:|---:|---:|
| Penalty-only | 99 | 98 | 96 |
| Reported (blended) | 99 | 93 | **77** |
| LLM contribution | 0 | -5 | **-19** |

Same handful of low-severity findings, same penalty score (96-99
range). The LLM's mood swung the *reported* score by 22 points.
Every dimension showed the same pattern.

## Root cause

LLM holistic dimension scoring **adds noise without adding signal**:

- The LLM has no privileged information about "what severity should
  this dimension hold" beyond what its own findings already encode.
  If Claude finds three low-severity issues but says "85 / 100", it's
  guessing, not reasoning from evidence the formula doesn't see.
- The LLM's holistic guess is not consistent across runs (the very
  data we're studying).
- Blending it with a deterministic formula weakens the contract users
  want from a grading tool: *if the same set of findings arrives
  twice, you get the same score twice.*

## The fix (PR #60)

Drop the LLM holistic blend entirely. The new formula:

```python
def _estimate_score(findings, llm_score=None):
    if not findings:
        return DEFAULT_DIMENSION_SCORE  # 70.0
    return round(_compute_penalty_score(findings), 1)
```

`llm_score` stays in the signature for backward compatibility but is
ignored. The agent's `dimension_score` field is still emitted and
captured (it's useful for telemetry and may anchor the LLM's own
reasoning), it just doesn't influence the user-facing grade.

## Expected impact

Predicted overall score under the new formula on the same three scans
(computed from the JSON reports):

| | Scan #1 | Scan #2 | Scan #3 |
|--|---:|---:|---:|
| Old reported | 92 | 85 | 85 |
| New (penalty-only) | ~94 | ~89 | ~92 |

Spread shrinks from 8 points (92→85) to ~5 points (94→89). The
remaining variance is honest — it lives in *which findings the model
surfaced this run*, not in how the model felt about them.

## What we did NOT change

- **Severity penalty weights** (15/8/3/1/0). These are the real signal
  and are already calibrated against the cap (critical caps at 4,
  high at 7, medium at 18+). Changing them would inflate or deflate
  every existing report.
- **The 55-point penalty cap.** Keeps the worst possible per-dimension
  score at 45, preserving the "no dimension is fully unrecoverable"
  invariant.
- **The default-to-70 rule for empty dimensions.** Same.
- **The CritiqueAgent.** It still validates findings before merge.

## What's still on the table

The LLM-as-judge analysis identified 17 issues that recur across all
three scans (high-confidence real signal). Those are the next batch
of follow-up fixes. The 39 "one-shot" findings are not fixes — they
are noise the model emits on a particular pass and shouldn't drive
work.

## Reproduce locally

```bash
# Cluster across 3 scan JSONs
python3 docs/launch/reports/v0.6.0/scripts/llm_judge.py
# Score decomposition (penalty-only vs reported)
python3 docs/launch/reports/v0.6.0/scripts/score_analysis.py
```
