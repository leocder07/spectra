<div align="center">

# SPECTRA

### The full spectrum of your codebase

**Spectra grades any repository on architecture, security, quality, docs, maintainability, and performance — in under 5 minutes.** It runs 8 specialized Claude agents in parallel (Opus 4.7) so you get a full audit instead of a single linter's opinion. Built for developers running self-checks, teams gating PRs in CI, and reviewers who need a second pair of eyes before merge.

<!-- TODO: 15-second hero GIF showing spectra analyze <repo> → grade pop -->

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-7C3AED?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1%2C096_passed-22C55E?style=for-the-badge)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-97%25-22C55E?style=for-the-badge)](tests/)
[![License: MIT](https://img.shields.io/badge/license-MIT-F59E0B?style=for-the-badge)](LICENSE)
[![Built with Claude](https://img.shields.io/badge/built_with-Claude_Opus_4.7-7C3AED?style=for-the-badge&logo=anthropic&logoColor=white)](https://anthropic.com)

[Quickstart](#quickstart) · [What You Get](#what-you-get) · [Compare](#how-spectra-compares) · [Architecture](#architecture) · [CLI Reference](#cli-reference)

</div>

---

## Quickstart

Three lines, under a minute:

```bash
pip install spectra-ai
export ANTHROPIC_API_KEY=sk-ant-...
spectra analyze https://github.com/your/repo
```

Open `spectra-report.html` when it finishes. Requires Python 3.12+ and an [Anthropic API key](https://console.anthropic.com/).

### Drop into any GitHub Action

```yaml
- uses: spectra-ai/spectra@v1
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## The Problem

AI-generated code ships faster than ever, but quality assurance hasn't kept up. One LLM call can't catch architecture drift, security flaws, and documentation gaps at the same time.

**Spectra deploys 8 AI agents — 6 parallel specialists, a planning agent, and a critique agent — to give you the full spectrum in under 5 minutes.**

---

## What You Get

A weighted ScoreCard plus a self-contained HTML report. Here's what the terminal looks like at the end of a run:

<!-- sample output, illustrative -->
```
▸ INGEST: cloned expressjs/express (1,247 files, 184K LOC)
▸ PLAN:   MetaPrompter built 6-agent plan (4.2K tokens)
▸ ANALYZE: 6 specialists running in parallel...
   ✓ Architecture     12.4s   8 findings
   ✓ Security          9.8s   14 findings (3 critical)
   ✓ Quality          11.2s   11 findings
   ✓ Documentation     7.6s   6 findings
   ✓ Maintainability   8.1s   4 findings
   ✓ Performance      10.5s   3 findings
▸ MERGE:    deduplicated 46 → 38 findings
▸ CRITIQUE: validated findings, dropped 4 false positives (Opus 4.7 + thinking)
▸ REPORT:   spectra-report.html

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
│  34 findings · 3 critical · 87s · $2.41     │
└─────────────────────────────────────────────┘

✓ Top issues: SQL injection in middleware/parser.js:142
              prototype pollution in utils/merge.js:38
              missing auth on /admin/* routes
```

> **See Spectra analyze itself:** [spectra-self-report.html](spectra-self-report.html) — B+ (86/100), 60 findings, $9.24

---

## Three Things That Set Spectra Apart

| 8 AI agents in parallel | Incremental cache | GitHub Action |
|---|---|---|
| Six specialists (architecture, security, quality, docs, maintainability, performance) plus a MetaPrompter planner and a CritiqueAgent that filters false positives. All Opus 4.7. Specialists fan out via `asyncio.gather` so the wall clock is the slowest agent, not the sum. | Re-run the same repo and finish in seconds. Composite-key cache (`content × dimension × model × prompt × schema × spectra version`) means only changed files re-analyze. Three subcommands manage it: `spectra cache stats / clear / prune`. | Drop `spectra-ai/spectra@v1` into any PR workflow with one block of YAML. The Action installs from PyPI, runs `spectra analyze`, and posts SARIF to the GitHub Security tab. Min-score gate fails the build below threshold. |

### Other things you get

- **Multi-model strategy** — Opus 4.7 (medium effort) for planning, Opus 4.7 (xhigh effort) for deep analysis, Opus 4.7 with adaptive thinking for critique
- **Self-contained HTML reports** — Radar charts, interactive findings, keyboard navigation, file hotspot heatmaps — one file, works offline
- **Due diligence frameworks** — OWASP Top 10, SOC 2 Trust Criteria, PCI DSS 4.0, NIST CSF 2.0, and Investment Readiness scoring
- **Cost transparency** — Every report shows exact token usage and dollar cost
- **Clean Architecture** — 4-layer dependency rule, frozen Pydantic models, zero `Any` types — the tool that audits architecture follows strict architecture itself

---

## How It Works

```mermaid
graph LR
    A[INGEST<br/>Clone repo] --> B[PLAN<br/>MetaPrompter<br/>Sonnet 4.5]
    B --> C[ANALYZE<br/>6 Specialists<br/>Opus 4.7]
    C --> D[MERGE<br/>Deduplicate<br/>& Score]
    D --> E[CRITIQUE<br/>CritiqueAgent<br/>Opus 4.7 + ET]
    E --> F[REPORT<br/>HTML + Charts<br/>ScoreCard]

    style A fill:#7C3AED,stroke:#7C3AED,color:#fff
    style B fill:#7C3AED,stroke:#7C3AED,color:#fff
    style C fill:#F59E0B,stroke:#F59E0B,color:#fff
    style D fill:#7C3AED,stroke:#7C3AED,color:#fff
    style E fill:#EF4444,stroke:#EF4444,color:#fff
    style F fill:#22C55E,stroke:#22C55E,color:#fff
```

The ANALYZE stage fans out to 6 parallel specialists:

```mermaid
graph TD
    MP[MetaPrompter Plan] --> ARCH[Architecture Agent]
    MP --> SEC[Security Agent]
    MP --> QUAL[Quality Agent]
    MP --> DOC[Documentation Agent]
    MP --> DEP[Dependency Agent]
    MP --> PERF[Performance Agent]

    ARCH --> MERGE[Merge & Score]
    SEC --> MERGE
    QUAL --> MERGE
    DOC --> MERGE
    DEP --> MERGE
    PERF --> MERGE

    style MP fill:#7C3AED,stroke:#7C3AED,color:#fff
    style MERGE fill:#F59E0B,stroke:#F59E0B,color:#fff
```

---

## Agent Roster

| Agent | Model | Role |
|-------|-------|------|
| **MetaPrompter** | Sonnet 4.5 | Reads file tree (never full code), builds analysis plan |
| **ArchitectureAgent** | Opus 4.7 | Layering, coupling, dependency analysis |
| **SecurityAgent** | Opus 4.7 | OWASP Top 10, CWE mapping, vulnerability detection |
| **QualityAgent** | Opus 4.7 | Code smells, complexity, test coverage gaps |
| **DocumentationAgent** | Opus 4.7 | API docs, README quality, inline comments |
| **DependencyAgent** | Opus 4.7 | Supply chain, outdated packages, license risks |
| **PerformanceAgent** | Opus 4.7 | N+1 queries, memory leaks, async anti-patterns |
| **CritiqueAgent** | Opus 4.7 + Extended Thinking | Validates all findings, removes false positives |

---

## ScoreCard

Every analysis produces a weighted ScoreCard:

| Dimension | Weight | Agent |
|-----------|--------|-------|
| Architecture | 25% | ArchitectureAgent |
| Security | 25% | SecurityAgent |
| Quality | 20% | QualityAgent |
| Documentation | 10% | DocumentationAgent |
| Maintainability | 10% | DependencyAgent |
| Performance | 10% | PerformanceAgent |

**Grades:** A+ (95-100) · A (90-94) · A- (87-89) · B+ (83-86) · B (80-82) · B- (77-79) · C+ (73-76) · C (70-72) · C- (67-69) · D+ (63-66) · D (60-62) · D- (57-59) · F (0-56)

---

## Report Features

Every analysis generates a self-contained HTML report with:

- **Executive summary** — Top strengths and concerns at a glance
- **Radar chart** — Scores across all 6 dimensions
- **Interactive findings** — Filter by severity/dimension, text search, keyboard navigation (`j`/`k`, `o`, `/`)
- **File hotspot heatmap** — Files ranked by finding density
- **Technical debt quantification** — Estimated hours and cost to remediate
- **ROI analysis** — Estimated return on fixing identified issues
- **Compliance mapping** — OWASP Top 10, SOC 2, PCI DSS 4.0, NIST CSF 2.0

Works offline. No external dependencies. One HTML file. Print-friendly for PDF export.

---

## Architecture

Clean Architecture with four strict layers:

```mermaid
graph TB
    subgraph "Layer 4 — Infrastructure"
        INF[Anthropic API · Git · Tokens · Agents]
    end
    subgraph "Layer 3 — Adapters"
        ADP[CLI · Rich Terminal · HTML Presenter]
    end
    subgraph "Layer 2 — Use Cases"
        UC[Pipeline Orchestration · Protocol Interfaces]
    end
    subgraph "Layer 1 — Entities"
        ENT[Domain Models · Enums · Errors]
    end

    INF --> ADP
    INF --> UC
    INF --> ENT
    ADP --> UC
    ADP --> ENT
    UC --> ENT

    style ENT fill:#22C55E,stroke:#22C55E,color:#fff
    style UC fill:#7C3AED,stroke:#7C3AED,color:#fff
    style ADP fill:#F59E0B,stroke:#F59E0B,color:#fff
    style INF fill:#EF4444,stroke:#EF4444,color:#fff
```

**The dependency rule:** Source code dependencies only point inward. No exceptions.

### Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Facade** | `AnalyzeRepository` | Orchestrates the 6-stage pipeline behind one call |
| **Strategy** | Agent implementations | Swap agents via factory without touching orchestrator |
| **Decorator** | LLM call chain | Logging → Retry → Anthropic adapter (composable) |
| **Observer** | `ProgressObserver` | Rich terminal updates decoupled from business logic |
| **Template Method** | `BaseAgent` | Common agent lifecycle, specialized per dimension |
| **Composition Root** | `main.py` | All dependencies wired at startup, no service locator |

---

## How Spectra Uses Claude

### Multi-Model Strategy

| Agent | Model | Why This Model |
|-------|-------|----------------|
| MetaPrompter | **Sonnet 4.5** | Fast planning from file tree — no deep reasoning needed |
| 6 Specialists | **Opus 4.7** | Deep code understanding across all 6 dimensions |
| CritiqueAgent | **Opus 4.7 + Extended Thinking** | Meta-reasoning to validate findings and reject false positives |

### Key Capabilities Used

- **Parallel execution** — 6 agents via `asyncio.gather` with semaphore rate limiting
- **Token budget management** — 800K tokens distributed by MetaPrompter's plan
- **Extended thinking** — CritiqueAgent reasons through each finding before passing judgment
- **Structured output** — Every agent returns Pydantic-validated JSON
- **Prompt engineering** — Few-shot JSON examples, hallucination guardrails, CWE/OWASP references
- **Graceful degradation** — If 2+ agents fail, partial report in DEGRADED state

---

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| AI Models | Claude Opus 4.7, Claude Sonnet 4.5 |
| AI SDK | `anthropic` Python SDK |
| CLI Framework | Typer |
| Terminal UI | Rich |
| Data Models | Pydantic v2 (frozen) |
| Git Operations | GitPython |
| Token Counting | tiktoken |
| Report Rendering | Jinja2 |
| HTTP Client | httpx |
| Testing | pytest, pytest-asyncio |
| Linting | Ruff (40+ rules), mypy (strict) |

---

## Numbers That Matter

| Metric | Value |
|--------|-------|
| Tests | 1,096 passed |
| Coverage | 97% |
| Agents | 8 (6 parallel + MetaPrompter + CritiqueAgent) |
| Dimensions | 6 |
| Cost | $1-10 per analysis |
| Speed | Under 5 minutes end-to-end |
| Architecture | Clean Architecture, 4 layers |
| Error codes | 9 typed (SPEC-001 to SPEC-009) |

---

## CI Integration

Use the official GitHub Action — one step, no Python setup needed. See [docs/github-action.md](docs/github-action.md) for the full reference.

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
      - uses: spectra-ai/spectra@v1
        with:
          min-score: 70
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## Contributing

```bash
# Clone and install
git clone https://github.com/leocder07/spectra.git
cd spectra
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/
mypy src/
```

PRs welcome. Please follow the Clean Architecture dependency rule — it's enforced.

---

<div align="center">

### Built for the Anthropic Build with Claude Hackathon

[![Anthropic Build Hackathon](https://img.shields.io/badge/Anthropic_Build-Hackathon_2025-7C3AED?style=for-the-badge&logo=anthropic&logoColor=white)](https://anthropic.com)

Built with Claude Opus 4.7, Claude Sonnet 4.5, and Claude Code.

**MIT License** · [Repository](https://github.com/leocder07/spectra)

</div>
