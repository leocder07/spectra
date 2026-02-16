# Getting Started

Get a full repository analysis in under 2 minutes.

---

## 1. Install

```bash
git clone https://github.com/your-org/spectra.git
cd spectra
pip install -e ".[dev]"
```

Requires Python 3.12+ and an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## 2. Run

```bash
spectra analyze https://github.com/expressjs/express
```

That's it. Spectra clones the repo, deploys 8 AI agents, and generates an HTML report.

---

## 3. What Happens

Your analysis runs through 6 stages:

| Stage | What | Time |
|-------|------|------|
| **INGEST** | Clones repo, extracts file tree, reads top 20 source files | ~5s |
| **PLAN** | MetaPrompter (Sonnet 4.5) analyzes structure, allocates budgets | ~3s |
| **ANALYZE** | 6 specialist agents run in parallel on Opus 4.6 | ~45s |
| **MERGE** | Deduplicates findings, removes hallucinated file paths | <1s |
| **CRITIQUE** | CritiqueAgent (Opus 4.6 + thinking) validates all findings | ~25s |
| **REPORT** | Computes ScoreCard, renders HTML report | ~2s |

Total: ~90 seconds for a full analysis.

---

## 4. Output

### Terminal

You'll see a ScoreCard in your terminal:

```
  ┌─────────────────────────────────┐
  │  Spectra ScoreCard              │
  │  Overall: B+ (85/100)           │
  │                                 │
  │  Architecture   A-  87  ████▊   │
  │  Security       B+  84  ████▍   │
  │  Quality        A   91  █████   │
  │  Documentation  B   80  ████    │
  │  Maintainability B+  83  ████▍   │
  │  Performance    B   81  ████    │
  └─────────────────────────────────┘

  ✓ Report saved to spectra-report.html
```

### HTML Report

Open `spectra-report.html` in your browser. It includes:

- **ScoreCard** — Overall grade + per-dimension scores
- **Findings** — Grouped by dimension, sorted by severity, with code snippets
- **Compliance** — OWASP Top 10, SOC 2, PCI DSS 4.0, NIST CSF 2.0 mapping
- **ROI** — Cost comparison vs manual review
- **Cross-cutting insights** — Patterns across dimensions (from CritiqueAgent)

---

## 5. Useful Flags

| Flag | What It Does |
|------|-------------|
| `--quick` | Skip CritiqueAgent (saves ~25s, no finding validation) |
| `--format json` | Output raw JSON instead of HTML |
| `--format sarif` | Output SARIF v2.1.0 for IDE integration |
| `--min-score 80` | Exit with code 1 if score is below threshold (CI quality gate) |
| `--output path` | Save report to a custom path |
| `--verbose` | Show detailed progress and agent output |

### Examples

```bash
# Quick scan (skip critique, ~60s)
spectra analyze https://github.com/user/repo --quick

# CI pipeline quality gate
spectra analyze https://github.com/user/repo --min-score 80 --format json

# SARIF for VS Code / GitHub
spectra analyze https://github.com/user/repo --format sarif --output results.sarif
```

---

## 6. How It Works (30-Second Version)

1. **MetaPrompter** (Sonnet 4.5) looks at your file tree and creates an analysis plan
2. **6 Specialists** (Opus 4.6) analyze your code in parallel across architecture, security, quality, documentation, dependencies, and performance
3. **CritiqueAgent** (Opus 4.6 with extended thinking) validates every finding, rejects false positives, and adjusts severity levels
4. Results are deduplicated, scored, and rendered into your report

All agents share a token budget of 800K tokens. Findings are deduplicated by `(file_path, line_number, dimension)`. Hallucinated file paths are automatically removed.

---

## Next Steps

- Read the [HLD](../architecture/HLD.md) for system architecture
- Read the [LLD](../architecture/LLD.md) for implementation details
- Browse the [diagrams](../diagrams/) for visual architecture references
- Check the [API reference](../api/API.md) for all public interfaces
