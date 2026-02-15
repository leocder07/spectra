![CI](https://github.com/leocder07/spectra/actions/workflows/ci.yml/badge.svg)
![Tests](https://img.shields.io/badge/tests-573_passed-22C55E)
![Coverage](https://img.shields.io/badge/coverage-90%25-22C55E)
![Python](https://img.shields.io/badge/python-3.12+-7C3AED)
![License](https://img.shields.io/badge/license-MIT-F59E0B)

# Spectra

**8 AI agents analyze your entire repository in 90 seconds.**

Spectra deploys 8 AI agents — 1 MetaPrompter (planner) + 6 specialists (parallel) + 1 CritiqueAgent (validator) — to score your codebase across architecture, security, quality, documentation, maintainability, and performance. You get a letter grade, a ranked list of findings, and a single-file HTML report ready for investors, auditors, or your next sprint planning.

---

## Quick Start

```bash
git clone https://github.com/leocder07/spectra.git
cd spectra
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...
spectra analyze https://github.com/expressjs/express
```

That's it. Open `spectra-report.html` when it's done.

### Options

```bash
spectra analyze <repo-url> --quick          # Skip critique pass, ~40s
spectra analyze <repo-url> --format json    # Machine-readable output
spectra analyze <repo-url> --output my.html # Custom report path
spectra analyze <repo-url> --verbose        # Debug output
```

---

## What Makes Spectra Different

**Multi-agent, not single-prompt.** Most tools send your code to one LLM call and hope for the best. Spectra runs 8 specialized agents — 6 in parallel — each trained on a single dimension. An architecture agent doesn't get distracted by security findings. A security agent doesn't water down its severity ratings to seem balanced.

**Validation built in, not bolted on.** The CritiqueAgent uses Claude Opus 4.6 with extended thinking to validate every finding from every specialist. False positives get removed. Severity ratings get adjusted. You get findings you can trust, not a wall of noise.

**VC-grade due diligence reports.** OWASP Top 10 compliance mapping, SOC 2 Trust Service Criteria coverage, investment readiness scoring, bus factor analysis, and technical debt quantification — the kind of reports that satisfy auditors and investors, not just developers.

**Premium terminal aesthetic.** Dark theme with glassmorphism, animated radar charts, interactive findings with filter/search/keyboard navigation, and file hotspot heatmaps. Reports you actually want to open.

**Clean Architecture, no shortcuts.** 4-layer dependency rule enforced across the entire codebase. Frozen Pydantic models. Zero `Any` types. 573 tests at 90% coverage. The tool that audits your architecture follows strict architecture itself.

---

## What You Get

### Terminal ScoreCard

```
┌─────────────────────────────────────────────┐
│  SPECTRA SCORECARD                          │
│  repo: expressjs/express                    │
│  Overall: B+ (83/100)                       │
├─────────────────────────────────────────────┤
│  Architecture   ████████░░  82  B           │
│  Security       █████████░  88  B+          │
│  Quality        ███████░░░  74  C+          │
│  Documentation  ██████░░░░  65  C           │
│  Maintainability████████░░  80  B           │
│  Performance    █████████░  86  B+          │
├─────────────────────────────────────────────┤
│  47 findings · 3 critical · 87s · $4.80     │
└─────────────────────────────────────────────┘
```

### HTML Report

A self-contained single-file report with:

- **Executive summary** with top strengths and concerns
- **Spectrum bar visualization** — color-coded grades per dimension
- **Radar chart** mapping scores across all 6 dimensions
- **Interactive findings** with severity/dimension filter, text search, and keyboard navigation (`j`/`k` to navigate, `o` to expand, `/` to search)
- **File hotspot heatmap** — files ranked by finding density
- **Technical debt quantification** — estimated hours and cost to remediate
- **OWASP Top 10 compliance mapping** — coverage across all 10 categories
- **SOC 2 Trust Service Criteria** — findings mapped to security, availability, processing integrity, confidentiality, privacy
- **Investment Readiness Score** — weighted composite across architecture, security, test coverage, documentation, bus factor, SOC 2 readiness
- **Bus factor analysis** — contributor concentration and single-point-of-failure hotspots
- **Dependency risk assessment** — outdated deps, license conflicts, supply chain concerns
- **Print-friendly output** — clean layout for PDF export and physical review

Works offline. No external dependencies. One HTML file.

---

## How It Works

Spectra runs a 6-stage pipeline:

```
INGEST ──→ PLAN ──→ ANALYZE ──→ MERGE ──→ CRITIQUE ──→ REPORT
  │          │         │           │          │            │
  Clone    MetaP    6 agents    Dedup     Validate     HTML +
  repo     plans    parallel   + score   findings     ScoreCard
```

### Stage 1 — Ingest

Clone the repository, extract the file tree and language breakdown.

### Stage 2 — Plan

**MetaPrompter** (Claude Sonnet 4.5) reads the file tree — never full source code — and builds an analysis plan. It decides which files each specialist should focus on and how to allocate the token budget across agents.

### Stage 3 — Analyze

Six specialist agents run in parallel via `asyncio.gather`:

| Agent | Dimension | What It Finds |
|-------|-----------|---------------|
| ArchitectureAgent | Architecture (25%) | Layer violations, circular deps, coupling |
| SecurityAgent | Security (25%) | Injection, auth flaws, secrets, OWASP top 10 |
| QualityAgent | Quality (20%) | Complexity, duplication, dead code, test gaps |
| DocumentationAgent | Documentation (10%) | Missing docs, stale comments, API coverage |
| DependencyAgent | Maintainability (10%) | Outdated deps, license conflicts, supply chain |
| PerformanceAgent | Performance (10%) | N+1 queries, memory leaks, hot paths |

All six agents use Claude Opus 4.6 with its 1M token context window.

### Stage 4 — Merge

Deduplicate findings across agents, cross-reference overlapping issues, and compute weighted dimension scores.

### Stage 5 — Critique

**CritiqueAgent** (Claude Opus 4.6 with extended thinking) validates every finding. It removes false positives, adjusts severity ratings, and ensures recommendations are actionable. This is the only agent that uses extended thinking.

### Stage 6 — Report

Render the HTML report via Jinja2 — radar charts, hotspot heatmaps, due diligence frameworks, interactive findings — and display the terminal ScoreCard.

---

## Architecture

Spectra follows **Clean Architecture** with four strict layers:

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

**The dependency rule:** source code dependencies only point inward. `entities/` imports nothing from the spectra package. `use_cases/` imports only from `entities/`. No exceptions.

### Key Design Patterns

- **Facade** — `AnalyzeRepository` orchestrates the 6-stage pipeline
- **Strategy** — Agent implementations swapped via factory
- **Decorator** — LLM call chain: Logging → Retry → Anthropic adapter
- **Observer** — `ProgressObserver` protocol for Rich terminal updates
- **Template Method** — `BaseAgent` defines the agent lifecycle
- **Composition Root** — `main.py` wires all dependencies at startup

### Error Handling

Every failure has a code, a retry strategy, and a user-facing message:

| Code | What Failed | Retryable |
|------|-------------|-----------|
| SPEC-001 | Git clone | Yes (2x) |
| SPEC-002 | Anthropic API | Yes (3x) |
| SPEC-003 | Rate limited | Yes (3x) |
| SPEC-004 | Token budget exceeded | No |
| SPEC-005 | Agent output invalid | Yes (1x) |
| SPEC-006 | Agent timeout (120s) | No |
| SPEC-007 | 2+ agents failed | No |
| SPEC-008 | CritiqueAgent failed | No |
| SPEC-009 | Report render failed | No |

If two or more agents fail, Spectra produces a partial report in DEGRADED state rather than failing silently.

---

## How Spectra Uses Claude

Spectra is built entirely on Claude's API, showcasing 3 key capabilities:

### Multi-Model Strategy

| Agent | Model | Why This Model |
|-------|-------|----------------|
| MetaPrompter | Sonnet 4.5 | Fast planning from file tree — no deep reasoning needed |
| 6 Specialists | Opus 4.6 | Deep code understanding across architecture, security, quality, docs, deps, performance |
| CritiqueAgent | Opus 4.6 + Adaptive Thinking | Meta-reasoning to validate findings, reject false positives, adjust severities |

### Adaptive Thinking (Newest Feature)

The CritiqueAgent uses Opus 4.6's adaptive thinking — Claude dynamically determines when and how much to reason. This is the most principled use of extended thinking: one dedicated agent that deeply reasons about all other agents' output.

### Parallel Execution Architecture

- 6 specialist agents run simultaneously via `asyncio.gather`
- Semaphore limits concurrent API calls to prevent rate limiting
- 120-second timeout per agent with graceful degradation
- If 2+ agents fail → degraded mode with reweighted scores

### Token Budget Management

- 800K total token budget across all agents
- Per-specialist allocation guided by MetaPrompter's plan
- Temperature 0.0 for reproducible scores
- Streaming API for all calls (avoids 10-minute timeout)

### Prompt Engineering

- Few-shot JSON examples in every prompt
- Hallucination guardrails ("only reference files in the tree")
- Score calibration guidance per dimension
- Confidence thresholds (MIN_CONFIDENCE = 0.7)
- CWE/OWASP references in security prompts
- Prompt injection sandboxing via XML delimiters

### Cost Transparency

Every analysis shows exact cost ($1-3 typical). No hidden API calls. The cost stat in the report builds trust with enterprise buyers.

### Example Output — Express.js Analysis

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

The HTML report includes every finding with severity, file path, line number, fix recommendation, and CWE/OWASP references for security issues.

---

## CI Integration

Spectra fits into any GitHub Actions pipeline. Add automated code analysis to every pull request.

### Quick Setup (3 steps)

1. Copy `.github/workflows/spectra-analyze.yml` into your repo
2. Add `ANTHROPIC_API_KEY` to your repo secrets (Settings > Secrets > Actions)
3. Open a pull request — Spectra posts a grade summary as a PR comment

### What Happens on Each PR

```
PR opened → Spectra installs → Analyzes repo → Posts comment
                                    │
                                    ├── Grade table (A+ to F)
                                    ├── Dimension breakdown
                                    ├── Top critical findings
                                    └── HTML report as artifact
```

### Example Workflow

```yaml
# .github/workflows/spectra-analyze.yml
name: Spectra Analysis
on:
  pull_request:
    branches: [main]

permissions:
  contents: read
  pull-requests: write

jobs:
  analyze:
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install spectra-cli
      - run: spectra analyze . --quick --format json --output spectra-report.json
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - uses: actions/upload-artifact@v4
        with:
          name: spectra-report
          path: spectra-report.json
```

See `.github/workflows/spectra-analyze.yml` in this repo for the full workflow with PR comments and grade thresholds.

### Options

| Flag | Effect |
|------|--------|
| `--quick` | Skip CritiqueAgent, ~40s instead of ~90s |
| `--format json` | Machine-readable output for CI parsing |
| `--output path` | Custom report file path |

### Grade Gating (Optional)

Uncomment the threshold check in the workflow to block PRs that score below a minimum grade. Set any threshold from 0-100.

---

## Development

```bash
git clone https://github.com/leocder07/spectra.git
cd spectra
pip install -e ".[dev]"

# Run
spectra analyze <repo-url>

# Test
pytest tests/ -v

# Lint
ruff check src/ tests/
mypy src/
```

Requires Python 3.12+ and an `ANTHROPIC_API_KEY`.

---

## Stats

| Metric | Value |
|--------|-------|
| Tests | 573 passed |
| Coverage | 90% |
| Agents | 8 (6 parallel specialists + MetaPrompter + CritiqueAgent) |
| Dimensions | 6 (architecture, security, quality, documentation, maintainability, performance) |
| Architecture | Clean Architecture, 4 layers, strict dependency rule |
| Source code | ~2,000 lines |
| Test code | ~4,300 lines |

---

## License

MIT
