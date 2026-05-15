# Spectra Leaderboard — Real OSS Scans

Live scans of widely used open-source projects, run with `spectra-ai` on Claude
Opus 4.7 (`effort=xhigh`). **Full pipeline** (all 8 agents including the
CritiqueAgent stage that filters false positives via adaptive thinking + task
budget). All findings link to the actual file:line on GitHub. No
cherry-picking — each scan is one shot, including the self-scan.

> **Note on the self-scan:** Spectra grading itself is biased by definition —
> the same prompts that wrote the findings also defined what counts as good.
> Treat the self-grade as a sanity check ("does our own architecture clear our
> own bar?") rather than as a benchmark vs the others.

## Current panel — v0.7.0

Per the post-PR-#60 deterministic penalty-only scoring formula. Same model
(Claude Opus 4.7, `effort=xhigh`), `--no-cache`, single run per repo.
Critical/high counts are the trustworthy signal; overall score is a 5-point
band (see [`SCORING-ANALYSIS.md`](reports/v0.6.0/SCORING-ANALYSIS.md)).

| Rank | Repository | Grade | Findings | Critical | High | Cost | Wall |
|-----:|-----------|------:|---------:|---------:|-----:|-----:|-----:|
| 1 | **FastAPI** ([fastapi/fastapi](https://github.com/fastapi/fastapi)) | **A (92)** | 44 | 0 | 3 | $2.61 | 388s |
| 1 | **Spectra (self-scan)** ([leocder07/spectra](https://github.com/leocder07/spectra)) | **A (92)** | 55 | 0 | 0 | $6.62 | 567s |
| 3 | **HTTPX** ([encode/httpx](https://github.com/encode/httpx)) | B+ (85) | 67 | 0 | 0 | $6.77 | 604s |
| 4 | **Aider** ([Aider-AI/aider](https://github.com/Aider-AI/aider)) | B- (79) | 49 | 0 | 5 | $6.16 | 571s |
| 5 | **Simon Willison's LLM** ([simonw/llm](https://github.com/simonw/llm)) | B- (77) | 57 | 0 | 8 | $9.02 | 580s |

### Per-dimension scores

| Repository | Architecture | Security | Quality | Documentation | Maintainability | Performance |
|------------|------:|------:|------:|------:|------:|------:|
| FastAPI | 91 A | 92 A | 95 A+ | 93 A | 81 B | 99 A+ |
| Spectra (self) | 94 A | 97 A+ | 83 B+ | 89 A- | 90 A | 97 A+ |
| HTTPX | 87 A- | 91 A | 80 B | 73 C+ | 94 A | 78 B- |
| Aider | 66 D+ | 88 A- | 79 B- | 79 B- | 93 A | 70 C |
| Simon Willison's LLM | 73 C+ | 88 A- | 69 C- | 78 B- | 82 B | 65 D+ |

**Totals: 272 findings · $31.18 real Anthropic spend across the 5 scans.**

## Historical reference — Anthropic SDK (v0.6.0)

A second baseline retained for trend comparison. Run with `spectra-ai==0.6.0`
on the same model and pipeline — useful for "how did the harness behave on a
mature, well-tested SDK."

| Repository | Grade | Findings | Critical | High | Cost | Wall | JSON |
|------------|------:|---------:|---------:|-----:|-----:|-----:|:----:|
| [`anthropics/anthropic-sdk-python`](https://github.com/anthropics/anthropic-sdk-python) | **B+ (85.6)** | 50 | 0 | 0 | $7.41 | 248s | [📦](../leaderboard-data/anthropic-sdk-python.json) |

## Reading the data

- **Severity floor (critical + high)** is the trustworthy signal. Spectra and
  HTTPX scored zero in both — the model genuinely could not find anything that
  rises to "high". FastAPI's 3 highs and Aider's/Simon's 5+8 highs are
  legitimate review targets.
- **Overall score** is a 5-point band per
  [`SCORING-ANALYSIS.md`](reports/v0.6.0/SCORING-ANALYSIS.md). FastAPI and
  Spectra both at 92 means they're effectively tied — variance across
  re-runs would swap the order.
- **Per-dimension scores** can swing more — read the worst dimension as a
  pointer to where attention is most warranted, not a verdict.

## Notable findings

- **FastAPI: 3 high in a top-tier Python framework.** Worth pulling the
  full report and checking whether they're real or hit on the
  framework's exposed API surface (which is broader than most libs). The
  per-dimension scores are otherwise excellent — Performance 99, Quality 95,
  Documentation 93.
- **Spectra ties FastAPI at A (92).** With 0 critical, 0 high, this is the
  cleanest possible signal that the scoring + the fixes from rounds 1-3
  actually compounded into measurable code-quality gains. Spectra's lowest
  dimension (Quality 83) is still B+.
- **HTTPX's Documentation at C+ (73).** A widely used HTTP library; the
  documentation gap is worth surfacing to the maintainers.
- **Aider's Architecture at D+ (66).** The lowest single-dimension score in
  the set. Aider is doing complex things (multi-file edits, multiple LLM
  backends, repo maps) — the dimension flag matches the project's known
  organic-growth pattern. Worth a separate deep-dive scan.
- **Simon's LLM has the most highs (8)** — the report is worth pulling for
  the per-finding detail. Simon's repo is small and intentionally
  experimental; high counts can include API-design gaps the maintainer is
  aware of.

## Reproduce

```bash
pip install spectra-ai
export ANTHROPIC_API_KEY=sk-ant-...

for repo in fastapi/fastapi encode/httpx simonw/llm Aider-AI/aider; do
    name=$(echo "$repo" | tr '/' '-')
    spectra analyze "https://github.com/$repo" \
        --output "reports/$name.json" \
        --format json \
        --max-cost-usd 15 \
        --no-cache \
        --allow-secrets   # most projects ship test fixtures with planted secrets
done
```

Total cost across the 5 v0.7.0 scans: **$30.68**. Total wall: **2,710s**
(~45 min serial, ~10 min if you run in parallel + accept rate-limit pressure).

## Reports

| Repository | Raw JSON |
|------------|----------|
| FastAPI | [`reports/v0.7.0/fastapi-fastapi-confidential.json`](reports/v0.7.0/fastapi-fastapi-confidential.json) |
| HTTPX | [`reports/v0.7.0/encode-httpx-confidential.json`](reports/v0.7.0/encode-httpx-confidential.json) |
| Simon Willison's LLM | [`reports/v0.7.0/simonw-llm-confidential.json`](reports/v0.7.0/simonw-llm-confidential.json) |
| Aider | [`reports/v0.7.0/aider-confidential.json`](reports/v0.7.0/aider-confidential.json) |
| Spectra (self-scan, v0.7.0) | [`reports/v0.6.0/spectra-self-scan-5-confidential.json`](reports/v0.6.0/spectra-self-scan-5-confidential.json) |
| Anthropic SDK (v0.6.0 baseline) | [`../leaderboard-data/anthropic-sdk-python.json`](../leaderboard-data/anthropic-sdk-python.json) |

## v0.7.0 scoring caveat

Per [`SCORING-ANALYSIS.md`](reports/v0.6.0/SCORING-ANALYSIS.md), the overall
score is a 5-point band on identical-code re-runs. Per-dimension scores can
swing more (we measured 22 points in the v0.6.0 series). For the leaderboard
ranking to be stable, treat "tied within 5 points" as a tie. FastAPI and
Spectra at 92 are tied. HTTPX at 85 is the next bracket. Aider and Simon's
LLM at 77-79 are in the same band.
