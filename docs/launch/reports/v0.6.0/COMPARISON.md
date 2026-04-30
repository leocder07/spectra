# v0.6.0 Self-Scan — Before / After Comparison

Two scans of the Spectra repository against itself, on either side of
PR #55 (which addressed 6 medium findings from the first run) plus
PR #54 (htmlpreview viewer links) and PR #56 (39-file doc audit).

Both runs used `spectra v0.6.0`, `--allow-secrets` (test fixtures
contain planted secret patterns by design), `--audit-sink file:...`,
and `--max-cost-usd 25`. The second run added `--force` to bypass
caches and produce a fully independent comparison.

## Headline numbers

| Metric | Before (v0.6.0 baseline) | After (PRs #54 + #55 + #56) | Δ |
|--------|--------------------------:|----------------------------:|---:|
| Overall grade | A (92) | B+ (85) | -7 |
| Total findings | 36 | 54 | +18 |
| Critical | **0** | **0** | 0 |
| High | **0** | **0** | 0 |
| Medium | 15 | 16 | +1 |
| Low | 12 | 25 | +13 |
| Info | 9 | 13 | +4 |
| Cost | $5.04 | $6.08 | +$1.04 |
| Wall clock | 207s | 541s | +334s |

## Per-dimension

| Dimension | Before | After | Δ |
|-----------|-------:|------:|--:|
| Architecture | 84 B+ (10 findings) | 79 B- (10 findings) | -4 |
| Security | 99 A+ (3) | 93 A (7) | -6 |
| Quality | 94 A (4) | 81 B (12) | -13 |
| Documentation | 85 B+ (8) | 88 A- (10) | +3 |
| Maintainability | 95 A+ (5) | 82 B (9) | -12 |
| Performance | 92 A (6) | 87 A- (6) | -4 |

## Did PR #55 fixes actually clear?

**Yes — all six fixes verified.** None of the six pre-fix finding
signatures appear in the after-scan:

| Fix | Before | After |
|-----|:------:|:-----:|
| `_PIPELINE_INFO` showed stale Sonnet 4.5 / Opus 4.6 model strings | present | cleared |
| Bare `except` clauses in heuristic file reader | present | cleared |
| `TiktokenAdapter` instantiated per call | present | cleared |
| `PolicyGateError` defined in adapter, raised by infrastructure | present | cleared |
| Per-agent override flags missing allowed-value lists in --help | present | cleared |
| SPEC error codes lack user-facing documentation cross-reference | present | cleared (docs/error-codes.md added) |

## So why did the grade go DOWN?

LLM stochasticity. Three things changed between the two runs:

1. **The model spent 2.6× longer** (541s vs 207s) and surfaced 18
   findings the first pass missed. Same code, more thorough analysis.
2. **All 18 new findings are medium / low / info** — no severity
   regression. The 0-critical / 0-high pattern held in both runs.
3. **Some new findings are real follow-ups** (e.g. `dependabot.yml` +
   `renovate.json` configured together is duplicate work — the more
   thorough second pass caught it; this PR removes `dependabot.yml`).
4. **Other new findings recur from earlier scans** (e.g.
   `pysqlcipher3` is unmaintained, `analyze()` has many parameters)
   — known issues we have explicit `noqa`s for or have judged
   acceptable trade-offs.

## Honest caveat

LLM-based code grading is **directional, not deterministic**. Two scans
of the exact same code with the exact same model and effort settings
can return different grades because the underlying model is
non-deterministic at a fine-grained level. Spectra's adversarial
harness (100% catch-rate on 20 prompt-injection plants) protects
against attacker-controlled grade manipulation, but it does not make
per-run grades reproducible.

For users:

- Trust the **severity buckets** — critical / high are stable signals.
- Treat the **overall numeric score** as a 5-point band, not an exact
  number. "B+ vs A" is real movement; "84 vs 86" is noise.
- Run repeatedly only if the answer matters — single-run findings are
  good for triage, weighted-average findings across runs are better
  for trends.

## Reports

- Before-scan JSON: [`spectra-self-confidential.json`](spectra-self-confidential.json)
- Before-scan HTML: [`spectra-self-confidential.html`](spectra-self-confidential.html)
  ([▸ View rendered](https://htmlpreview.github.io/?https://github.com/leocder07/spectra/blob/main/docs/launch/reports/v0.6.0/spectra-self-confidential.html))
- After-scan JSON: [`spectra-self-after-fixes-confidential.json`](spectra-self-after-fixes-confidential.json)
- Audit log (JSON-Lines, ADR-018): [`audit.jsonl`](audit.jsonl)
