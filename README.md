# Spectra

**8 AI agents analyze your entire repository in 90 seconds.**

Spectra deploys 6 parallel specialist agents — plus a planner and a critic — to score your codebase across architecture, security, quality, documentation, maintainability, and performance. You get a letter grade, a ranked list of findings, and a single-file HTML report.

---

## Quick Start

```bash
pip install spectra-cli
export ANTHROPIC_API_KEY=sk-...
spectra analyze https://github.com/your-org/your-repo
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

- Color-coded grades per dimension
- Every finding with severity, file path, line number, and fix recommendation
- Findings grouped by dimension and sorted by severity
- Works offline — no external dependencies

---

## How It Works

Spectra runs a 6-stage pipeline:

```
INGEST ──→ PLAN ──→ ANALYZE ──→ MERGE ──→ CRITIQUE ──→ REPORT
  │          │         │           │          │            │
  Clone    MetaP    6 agents    Dedup     Validate     HTML +
  repo     plans    parallel    + score   findings     ScoreCard
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

Render the HTML report via Jinja2 and display the terminal ScoreCard.

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

- **Claude Opus 4.6** powers 7 of 8 agents, using the 1M token context window to analyze entire repositories without chunking
- **Extended thinking** is reserved for CritiqueAgent — the one agent that needs to reason deeply about finding validity
- **Claude Sonnet 4.5** powers MetaPrompter for fast planning decisions
- **6 agents run in true parallel** via `asyncio.gather`, each with a 120-second timeout
- **Token budget management** allocates 800K tokens across agents, with 200K reserved for CritiqueAgent

---

## Development

```bash
git clone https://github.com/leocder07/spectra-cli.git
cd spectra-cli
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

## License

MIT
