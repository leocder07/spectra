![CI](https://github.com/leocder07/spectra/actions/workflows/ci.yml/badge.svg)
![Tests](https://img.shields.io/badge/tests-1096_passed-22C55E)
![Coverage](https://img.shields.io/badge/coverage-97%25-22C55E)
![Python](https://img.shields.io/badge/python-3.12+-7C3AED)
![License](https://img.shields.io/badge/license-MIT-F59E0B)

# Spectra

**8 AI agents analyze your entire repository in under 3 minutes.**

> **See Spectra analyze itself**: [spectra-self-report.html](spectra-self-report.html) — B+ (86/100), 60 findings, $9.24

---

## The Problem

In the age of AI-generated code, review is the bottleneck. Teams ship faster than ever, but quality assurance hasn't kept up. One LLM call can't catch architecture drift, security flaws, and documentation gaps at the same time.

**Spectra deploys 8 AI agents to give you the full spectrum in under 3 minutes.**

---

## Quick Start

```bash
pip install spectra-cli
export ANTHROPIC_API_KEY=sk-ant-...
spectra analyze https://github.com/expressjs/express
```

Open `spectra-report.html` when it's done.

```bash
spectra analyze <repo-url> --quick           # Skip critique pass, ~40s
spectra analyze <repo-url> --format json     # Machine-readable output
spectra analyze <repo-url> --format sarif    # SARIF for GitHub Security tab
spectra analyze <repo-url> --min-score 70    # Quality gate (exit 1 if below)
spectra analyze <repo-url> --output my.html  # Custom report path
```

---

## What Makes Spectra Different

- **Multi-agent, not single-prompt** — 6 specialist agents run in parallel, each focused on one dimension so nothing gets diluted
- **Validation built in** — CritiqueAgent uses Claude Opus 4.6 with extended thinking to remove false positives and adjust severity ratings
- **VC-grade due diligence** — OWASP Top 10, SOC 2 Trust Criteria, and Investment Readiness scoring in every report
- **Premium terminal aesthetic** — dark theme, animated radar charts, interactive findings with keyboard navigation
- **Strict Clean Architecture** — 4-layer dependency rule, frozen models, zero `Any` types — the tool that audits your architecture follows strict architecture itself

---

## How It Works

```
INGEST ──→ PLAN ──→ ANALYZE ──→ MERGE ──→ CRITIQUE ──→ REPORT
  │          │         │           │          │            │
  Clone    MetaP    6 agents    Dedup     Validate     HTML +
  repo     plans    parallel   + score   findings     ScoreCard
```

| Stage | Agent | Model | What Happens |
|-------|-------|-------|--------------|
| Plan | MetaPrompter | Sonnet 4.5 | Reads file tree (never full code), builds analysis plan |
| Analyze | 6 Specialists | Opus 4.6 | Architecture, Security, Quality, Docs, Deps, Performance — all parallel via `asyncio.gather` |
| Critique | CritiqueAgent | Opus 4.6 + Extended Thinking | Validates every finding, removes false positives |

### ScoreCard Output

```
┌─────────────────────────────────────────────┐
│  SPECTRA SCORECARD                          │
│  repo: expressjs/express                    │
│  Overall: B- (80/100)                       │
├─────────────────────────────────────────────┤
│  Architecture   █████████░  89  A-          │
│  Security       ██████░░░░  67  D+          │
│  Quality        █████████░  87  B+          │
│  Documentation  ██████░░░░  68  C-          │
│  Maintainability██████████  92  A           │
│  Performance    ████████░░  76  C+          │
├─────────────────────────────────────────────┤
│  46 findings · 3 critical · 87s · $2.41     │
└─────────────────────────────────────────────┘
```

---

## Report Features

Every analysis generates a self-contained HTML report with:

- **Executive summary** — top strengths and concerns at a glance
- **Radar chart** — scores across all 6 dimensions
- **Interactive findings** — filter by severity/dimension, text search, keyboard navigation (`j`/`k`, `o`, `/`)
- **File hotspot heatmap** — files ranked by finding density
- **Technical debt quantification** — estimated hours and cost to remediate

### Due Diligence Frameworks

- **OWASP Top 10** — compliance mapping across all 10 categories
- **SOC 2 Trust Service Criteria** — findings mapped to security, availability, processing integrity, confidentiality, privacy
- **Investment Readiness Score** — weighted composite across architecture, security, test coverage, documentation, bus factor, SOC 2 readiness

Works offline. No external dependencies. One HTML file. Print-friendly for PDF export.

---

## Architecture

Clean Architecture with four strict layers:

```
┌──────────────────────────────────────────────┐
│  Layer 4: infrastructure/                    │
│  Anthropic API, Git, token counting, agents  │
├──────────────────────────────────────────────┤
│  Layer 3: adapters/                          │
│  CLI (Typer), Rich terminal, HTML presenter  │
├──────────────────────────────────────────────┤
│  Layer 2: use_cases/                         │
│  Pipeline orchestration, Protocol interfaces │
├──────────────────────────────────────────────┤
│  Layer 1: entities/                          │
│  Domain models (Pydantic), enums, errors     │
└──────────────────────────────────────────────┘
```

**The dependency rule:** source code dependencies only point inward. No exceptions.

### Design Patterns

- **Facade** — `AnalyzeRepository` orchestrates the 6-stage pipeline
- **Strategy** — Agent implementations swapped via factory
- **Decorator** — LLM call chain: Logging → Retry → Anthropic adapter
- **Observer** — `ProgressObserver` protocol for Rich terminal updates
- **Template Method** — `BaseAgent` defines the agent lifecycle
- **Composition Root** — `main.py` wires all dependencies at startup

---

## How Spectra Uses Claude

### Multi-Model Strategy

| Agent | Model | Why |
|-------|-------|-----|
| MetaPrompter | Sonnet 4.5 | Fast planning from file tree — no deep reasoning needed |
| 6 Specialists | Opus 4.6 | Deep code understanding across all 6 dimensions |
| CritiqueAgent | Opus 4.6 + Extended Thinking | Meta-reasoning to validate findings and reject false positives |

### Key Capabilities

- **Parallel execution** — 6 agents via `asyncio.gather` with semaphore rate limiting
- **Token budget management** — 800K tokens distributed by MetaPrompter's plan
- **Prompt engineering** — few-shot JSON examples, hallucination guardrails, CWE/OWASP references
- **Cost transparency** — every analysis shows exact cost in the report
- **Graceful degradation** — if 2+ agents fail, partial report in DEGRADED state

---

## CI Integration

```yaml
# .github/workflows/spectra-analyze.yml
name: Spectra Analysis
on:
  pull_request:
    branches: [main]
jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install spectra-cli
      - run: spectra analyze . --quick --format json --output spectra-report.json
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## Numbers That Matter

| Metric | Value |
|--------|-------|
| Tests | 1,096 passed |
| Coverage | 97% |
| Agents | 8 (6 parallel specialists + MetaPrompter + CritiqueAgent) |
| Dimensions | 6 (architecture, security, quality, documentation, maintainability, performance) |
| Cost | $1-10 per analysis (varies by repo size) |
| Speed | 2-6 minutes end-to-end |
| Architecture | Clean Architecture, 4 layers, strict dependency rule |

---

## License

MIT
