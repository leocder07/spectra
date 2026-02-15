![CI](https://github.com/leocder07/spectra/actions/workflows/ci.yml/badge.svg)

# Spectra

**8 AI agents analyze your entire repository in 90 seconds.**

Spectra deploys 8 AI agents — 1 MetaPrompter (planner) + 6 specialists (parallel) + 1 CritiqueAgent (validator) — to score your codebase across architecture, security, quality, documentation, maintainability, and performance. You get a letter grade, a ranked list of findings, and a single-file HTML report.

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
  Clone    MetaP   6 specialist  Dedup     Validate     HTML +
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

## License

MIT
