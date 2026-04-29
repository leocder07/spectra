# Spectra Leaderboard — Notable OSS Repos

Real Spectra v0.3.1 scans against well-known open-source projects. Each
row is a single `spectra analyze <repo> --quick --no-cache` invocation;
no cherry-picking, no rerun-until-it-looks-good.

| Rank | Repo | Grade | Score | Findings | High | Cost | Wall-clock |
|---:|---|:---:|---:|---:|---:|---:|---:|
| 1 | [anthropics/anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python) | **B** | 82.5 | 55 | 3 | $20.47 | 168s |
| 2 | [garrytan/alphaclaw](https://github.com/garrytan/alphaclaw) | **C+** | 73.2 | 63 | 9 | $14.57 | 162s |

> Mode: `--quick` (skips CritiqueAgent, ~3× faster). Fresh cache (`--no-cache`).
> Scanned 2026-04-29 with `spectra-ai==0.3.1`, all 6 specialists on Claude
> Opus 4.7 effort=xhigh. Costs are real Anthropic API spend.

## Per-dimension breakdown

### `anthropics/anthropic-sdk-python` — Grade B (82.5)

| Dimension | Grade | Score |
|---|:---:|---:|
| Security | A | 90.0 |
| Maintainability | A- | 87.2 |
| Quality | B | 82.8 |
| Performance | B | 81.6 |
| Architecture | B- | 77.4 |
| Documentation | C | 72.4 |

**Headline finding:** Strong security posture (90) and well-maintained
dependency surface (87) — what you'd expect from a vendor SDK. Documentation
is the lowest dimension (C), driven mostly by missing module-level docstrings
in helper modules and uneven inline comment density across the streaming
codepath.

**Zero critical findings.** Three high-severity items, all in the test fixture
generation code (not customer-facing).

### `garrytan/alphaclaw` — Grade C+ (73.2)

| Dimension | Grade | Score |
|---|:---:|---:|
| Security | B | 81.4 |
| Maintainability | C+ | 75.6 |
| Architecture | C+ | 73.1 |
| Documentation | C- | 69.6 |
| Performance | C- | 69.0 |
| Quality | D+ | 65.6 |

**Headline finding:** Quality (D+, 65.6) is the weakest dimension — a mix
of long functions, sparse type annotations on shell glue, and several
modules that bundle unrelated responsibilities. Security holds a respectable
B (81) given the surface area (a Claude Code harness with file-system and
shell access).

**Zero critical findings.** Nine high-severity items concentrated in the
shell-orchestration scripts.

## What's NOT here yet

- `garrytan/gstack` (86k⭐) — repository is ~95MB, would cost an estimated
  $50-100 to scan in `--quick` mode (more in full mode). Skipped pending
  explicit budget approval.
- `garrytan/gbrain` (12k⭐) — also a substantial TypeScript codebase;
  estimated $20-40 per scan.
- Any **full-mode** scans (with the CritiqueAgent stage) — `--quick`
  already gives the headline grade; full mode adds false-positive
  filtering at ~3× the cost.

## How to reproduce

```bash
pip install spectra-ai==0.3.1
export ANTHROPIC_API_KEY=sk-ant-...
spectra analyze https://github.com/<owner>/<repo> --quick --format json -o report.json
```

Raw JSON outputs for every scan above are in
[`docs/leaderboard-data/`](../leaderboard-data/) — the source of truth
for the table.

## Methodology notes

- `--quick` skips Stage 5 (CritiqueAgent), so headline grades are
  pre-validation. Critical-finding counts may include some false
  positives that the full pipeline would reject.
- `--no-cache` forces a cold run for every scan — these numbers are
  honest about cost, not optimized to look cheap.
- Per-dimension weights: Architecture 25%, Security 25%, Quality 20%,
  Documentation 10%, Maintainability 10%, Performance 10%.
- `cost` is the sum of input + output tokens × Claude Opus 4.7 pricing.

*Updated 2026-04-29 with `spectra-ai==0.3.1`.*
