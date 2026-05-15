<div align="center">

# SPECTRA

### The full spectrum of your codebase

**Spectra grades any repository on architecture, security, quality, docs, maintainability, and performance — in under 5 minutes.** It runs 8 specialized Claude agents (6 specialists in parallel, plus a planner and a critic) on Opus 4.7, so you get a full audit instead of a single linter's opinion. Built for developers running self-checks, teams gating PRs in CI, and reviewers who need a second pair of eyes before merge.

#### <a id="disclaimer"></a>Disclaimer

**Indicative analysis — not auditor-grade evidence.** Spectra runs 8 LLM agents over your code; findings are heuristic and require human verification before being treated as compliance evidence, audit input, or pass/fail signal in regulated workflows. Use Spectra as a fast directional signal — pair it with deterministic SAST/DAST tooling and a human reviewer for anything compliance-bound. The same notice ships in every HTML, JSON, and SARIF report ([source](src/spectra/entities/disclaimer.py)).

<!-- TODO: 15-second hero GIF showing spectra analyze <repo> → grade pop -->

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-7C3AED?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1%2C973_passed-22C55E?style=for-the-badge)](tests/)
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

> **At-rest cache encryption (optional).** The local SQLite cache always
> carries per-row HMAC integrity. To also encrypt cache contents at rest,
> install the opt-in extra: `pip install "spectra-ai[encryption]"`. This
> pulls `pysqlcipher3`, which source-builds against `libsqlcipher` —
> macOS users need `brew install sqlcipher` first; Debian/Ubuntu
> `apt-get install libsqlcipher-dev`. Without the extra, Spectra runs
> with plain SQLite + HMAC and emits a single WARN at startup.

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

> **See Spectra analyze itself:** [spectra-self-report.html](spectra-self-report.html) — v0.6.0 self-scan: B+ (86/100), 34 findings (0 critical), 244s wall, $5.99 real Anthropic spend

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

## How Spectra Compares

Honest tradeoffs. Spectra is built for full-repo audits — not for inline PR comments or IDE feedback. Use it alongside, not instead of, the tools your team already runs.

| | **Spectra** | CodeRabbit | DeepSource | Sourcery | Codeball |
|---|:---:|:---:|:---:|:---:|:---:|
| Whole-repo audit (one report, six dimensions) | ✓ | partial | partial | — | — |
| Multiple specialist agents in parallel | ✓ (8) | — | — | — | — |
| False-positive filtering pass | ✓ (CritiqueAgent) | — | — | — | — |
| Self-contained HTML report (offline) | ✓ | — | — | — | — |
| SARIF output for GitHub Security tab | ✓ | — | ✓ | — | — |
| Compliance scoring (OWASP / SOC 2 / PCI DSS / NIST) | ✓ | — | partial | — | — |
| Incremental cache (re-runs in seconds) | ✓ | — | ✓ | — | — |
| Inline PR comments on diffs | — | ✓ | ✓ | ✓ | ✓ |
| IDE plugin (VS Code, JetBrains) | — | — | — | ✓ | — |
| Real-time review on every push | — | ✓ | ✓ | — | ✓ |
| Pricing model | Per-run API cost ($1-10) | SaaS subscription | SaaS subscription | SaaS subscription | SaaS subscription |
| Open source (MIT) | ✓ | — | — | — | — |

If you need inline PR comments while reviewing diffs, run CodeRabbit. If you need an architecture-level audit with security and compliance scoring before a release or due-diligence review, run Spectra. They complement each other.

---

## How It Works

```mermaid
graph LR
    A[INGEST<br/>Clone repo] --> B[PLAN<br/>MetaPrompter<br/>Opus 4.7 medium]
    B --> C[ANALYZE<br/>6 Specialists<br/>Opus 4.7 xhigh]
    C --> D[MERGE<br/>Deduplicate<br/>& Score]
    D --> E[CRITIQUE<br/>CritiqueAgent<br/>Opus 4.7 adaptive]
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
| **MetaPrompter** | Opus 4.7 (medium effort) | Reads file tree (never full code), builds analysis plan |
| **ArchitectureAgent** | Opus 4.7 | Layering, coupling, dependency analysis |
| **SecurityAgent** | Opus 4.7 | OWASP Top 10, CWE mapping, vulnerability detection |
| **QualityAgent** | Opus 4.7 | Code smells, complexity, test coverage gaps |
| **DocumentationAgent** | Opus 4.7 | API docs, README quality, inline comments |
| **DependencyAgent** | Opus 4.7 | Supply chain, outdated packages, license risks |
| **PerformanceAgent** | Opus 4.7 | N+1 queries, memory leaks, async anti-patterns |
| **CritiqueAgent** | Opus 4.7 + Adaptive Thinking | Validates all findings, removes false positives |

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

### See sample reports

> GitHub displays `.html` files as raw source when clicked. Use the "View rendered" links to see the actual reports in your browser.

- [**Sample reports**](docs/launch/reports/) — real Spectra runs against the Anthropic SDK, FastAPI, HTTPX, Aider, Simon Willison's LLM, and the Spectra repo itself
- [**Quickstart demo reports**](examples/) — Django, Express, FastAPI, Flask + a multi-repo leaderboard
- [**v0.6.0 self-scan**](https://htmlpreview.github.io/?https://github.com/leocder07/spectra/blob/main/docs/launch/reports/v0.6.0/spectra-self-confidential.html) — Spectra grading itself, with prompt-injection isolation, encrypted cache, signed receipts, and the audit log all active

---

## Architecture

> **Full architecture reference:** [`docs/architecture/`](docs/architecture/) — 10 documents + 19 PlantUML diagrams covering the C4 model, domain entities, pipeline flow, agent orchestration, cache subsystem, security model, data flow, plugin extensibility, and the release pipeline. Status table tracks what shipped in v0.6.0 (the Q1 + Q2 capabilities) vs Q3+ designed work. Diagrams render via `plantuml -tsvg docs/architecture/diagrams/*.puml`.
>
> **Glossary:** [`docs/glossary.md`](docs/glossary.md) — at-a-glance index for the three numbering schemes that recur in code comments and audit events: roadmap capability numbers (`#1`-`#70`), `SPEC-NNN` error codes, and `ADR-NNN` architecture decisions. All 20 ADRs are now consolidated under `docs/architecture/adr/`.

### System context

Spectra in its environment — who invokes it and what it talks to. Two install paths (local pip + GitHub Action), one PyPI package. Source: [`docs/diagrams/system-context.md`](docs/diagrams/system-context.md).

```mermaid
flowchart LR
    classDef person      fill:#dbeafe,stroke:#1e3a8a,stroke-width:2px,color:#1e293b
    classDef system      fill:#ede9fe,stroke:#7C3AED,stroke-width:4px,color:#1e293b
    classDef external    fill:#fef3c7,stroke:#92400e,stroke-width:2px,color:#1e293b
    classDef storage     fill:#dcfce7,stroke:#166534,stroke-width:2px,color:#1e293b
    classDef distribution fill:#fef3c7,stroke:#92400e,stroke-width:2px,color:#1e293b

    Dev["<b>Developer</b><br/>[Person]<br/>Runs spectra analyze<br/>from a terminal"]:::person
    PR["<b>GitHub PR</b><br/>[External CI]<br/>pull_request event<br/>invokes the Action"]:::person

    Spectra(["<b>Spectra CLI</b><br/>[Software System]<br/>8 AI agents · 6 dimensions<br/>Clean Architecture · Python 3.12+<br/>6-stage pipeline + cache"]):::system

    Anthropic["<b>Anthropic API</b><br/>[External SaaS]<br/>Claude Opus 4.7<br/>all 8 agents"]:::external
    GitHub["<b>GitHub.com</b><br/>[External Service]<br/>Git clone source<br/>HTTPS only"]:::external
    PyPI["<b>PyPI</b><br/>[Distribution]<br/>pip install spectra-ai<br/>also installed by Action"]:::distribution
    FS[("<b>Local Filesystem</b><br/>[OS]<br/>~/.cache/spectra/cache.db (SQLite WAL)<br/>spectra-report.{html,json,sarif}")]:::storage

    Dev      -- "spectra analyze ."          --> Spectra
    PR       -- "uses: spectra-ai/spectra@v1" --> Spectra
    Spectra  -- "HTTPS · streaming /messages" --> Anthropic
    Spectra  -- "git clone (depth=1)"        --> GitHub
    Spectra  <-- "cache R/W · report write"  --> FS
    PyPI     -. "install (cold path)"        .-> Spectra
```

### Clean Architecture layers

Four strict layers with one rule:

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
| MetaPrompter | **Opus 4.7 (medium effort)** | Planning from file tree — fast, no deep reasoning needed |
| 6 Specialists | **Opus 4.7 (xhigh effort)** | Deep code understanding across all 6 dimensions |
| CritiqueAgent | **Opus 4.7 + Adaptive Thinking** | Meta-reasoning to validate findings and reject false positives |

### Key Capabilities Used

- **Parallel execution** — 6 agents via `asyncio.gather` with semaphore rate limiting
- **Token budget management** — 800K tokens distributed by MetaPrompter's plan
- **Adaptive thinking** — CritiqueAgent reasons through each finding before passing judgment
- **Structured output** — Every agent returns Pydantic-validated JSON
- **Prompt engineering** — Few-shot JSON examples, hallucination guardrails, CWE/OWASP references
- **Graceful degradation** — If 2+ agents fail, partial report in DEGRADED state

---

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| AI Models | Claude Opus 4.7 (all 8 agents) |
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
| Tests | 1,973 passed (+345 since v0.5.0) |
| Coverage | 97% |
| Agents | 8 (6 parallel + MetaPrompter + CritiqueAgent) |
| Dimensions | 6 |
| Cost | $5-10 per analysis (Opus 4.7, full mode, real Anthropic spend) |
| Speed | Under 5 minutes end-to-end |
| Architecture | Clean Architecture, 4 layers |
| Error codes | 14 typed (SPEC-001 to SPEC-014) — see [docs/error-codes.md](docs/error-codes.md) |

---

## See It Run on Real Repos

We scan well-known OSS projects on every release and check the results into the
repo. **Real Anthropic API spend, no cherry-picking, one shot per repo.**

| Repo | Grade | Findings | Critical | High | Cost |
|---|:---:|---:|---:|---:|---:|
| [`fastapi/fastapi`](https://github.com/fastapi/fastapi) | **A (92)** | 44 | 0 | 3 | $2.61 |
| [`leocder07/spectra`](https://github.com/leocder07/spectra) (self-scan) | **A (92)** | 55 | 0 | 0 | $6.62 |
| [`encode/httpx`](https://github.com/encode/httpx) | **B+ (85)** | 67 | 0 | 0 | $6.77 |
| [`Aider-AI/aider`](https://github.com/Aider-AI/aider) | **B- (79)** | 49 | 0 | 5 | $6.16 |
| [`simonw/llm`](https://github.com/simonw/llm) | **B- (77)** | 57 | 0 | 8 | $9.02 |
| [`anthropics/anthropic-sdk-python`](https://github.com/anthropics/anthropic-sdk-python) (v0.6.0 baseline) | **B+ (86)** | 50 | 0 | 0 | $7.41 |

Per-repo grades + per-dimension breakdown live in the canonical leaderboard ([`docs/launch/leaderboard.md`](docs/launch/leaderboard.md)). The underlying JSON artifacts are confidential-mode reports — to inspect findings at file:line resolution, reproduce the run yourself with the snippet in the leaderboard's "Reproduce" section.

---

## CI Integration

The official GitHub Action installs Spectra from PyPI and runs `spectra analyze` on every PR — no Python setup, no extra steps. See [docs/github-action.md](docs/github-action.md) for the full reference.

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

The Action also writes SARIF, which GitHub picks up under the **Security** tab — findings show inline on the PR.

### Severity gate (`fail-on`)

The Action ships with a `fail-on: critical` default — any critical finding fails the build so a regression cannot land silently. Loosen or tighten the gate per workflow:

```yaml
- uses: spectra-ai/spectra@v1
  with:
    fail-on: high   # also fail on high — protect main from anything ≥ high
```

Set `fail-on: none` on draft / preview PRs when you want the report without the gate firing. Accepted values: `critical`, `high`, `medium`, `low`, `none`.

---

## CLI Reference

Two top-level commands: `spectra analyze` and `spectra cache`.

### `spectra analyze`

```bash
spectra analyze <repo-url-or-path> [flags]
```

The argument can be an HTTPS Git URL, a local path, or `.` for the current working tree (no clone).

| Flag | Default | Purpose |
|------|---------|---------|
| `--quick` | off | Skip the CritiqueAgent pass (saves ~40s, keeps false positives) |
| `--format` | `html` | Output format: `html`, `json`, or `sarif` |
| `--output` | `spectra-report.html` | Custom report path |
| `--min-score` | none | Quality gate — exit 1 if overall score is below this number |
| `--fail-on` | none | Severity gate — exit 1 when any finding is at or above `critical\|high\|medium\|low\|none` (v0.6.0) |
| `--force` | off | Bypass cache, force a fresh analysis |
| `--no-cache` | off | Disable cache reads and writes for this run |
| `--no-gitignore` | off | Do not honor `.gitignore` (`.spectraignore` is still applied) |
| `--allow-secrets` | off | Continue past pre-flight secret detection (logs WARN) |
| `--max-cost-usd` | none | Per-run cost cap; abort with SPEC-014 when next call would cross (v0.6.0) |
| `--max-cost-per-hour` | none | Rolling 1-hour cost cap, persisted to `cost_log` (v0.6.0) |
| `--audit-sink` | `stdout` | Where audit events go: `stdout`, `file:<path>`, or `otlp:<url>` (v0.6.0) |
| `--classification` | `confidential` | Report mode: `confidential` (watermarked, full) or `public` (redacted summary) (v0.6.0) |

### Pre-flight: secret scan + workspace filtering

Spectra runs a fast pre-flight stage between INGEST and PLAN that:

1. **Honors `.gitignore`** (root + every nested `.gitignore`) so excluded files
   never reach a prompt or cache key. Use `--no-gitignore` to opt out.
2. **Honors `.spectraignore`** — same `gitwildmatch` syntax — for Spectra-only
   exclusions you don't want polluting your `.gitignore`. Always applied.
3. **Scans for hard-coded secrets** with a curated regex list (AWS keys,
   GitHub PATs, Anthropic keys, bearer tokens, Slack webhooks, RSA/OpenSSH
   private keys, plus an `.env*` heuristic). On detection, fails with
   `SPEC-011` listing every match. Override with `--allow-secrets` (CI-safe;
   the run continues but every finding is logged at WARN).

Example `.spectraignore`:

```
# Generated client SDKs we don't author
clients/generated/
# Vendored protobuf stubs
**/proto/*_pb2.py
# Large fixtures
tests/fixtures/large_repo/
```

### Per-agent model + effort

Override the default Claude Opus 4.7 wiring per agent role.

```bash
# Run all 6 specialists on Sonnet 4.6 (cheaper, slightly less accurate)
spectra analyze <repo> --model claude-sonnet-4-6

# Bump security agent's effort to max while keeping others at xhigh
spectra analyze <repo> --security-effort max

# Use Haiku for documentation only (it's cheap and docs don't need much reasoning)
spectra analyze <repo> --documentation-model claude-haiku-4-5

# Power-user JSON override
spectra analyze <repo> \
  --model-overrides '{"security":"claude-opus-4-7","documentation":"claude-haiku-4-5"}' \
  --effort-overrides '{"security":"max"}'
```

| Flag | Default | Allowed |
|---|---|---|
| `--model` | `claude-opus-4-7` (specialists) | `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5` |
| `--effort` | `xhigh` (specialists), `medium` (meta), `high` (critique) | `low`, `medium`, `high`, `xhigh`, `max` |
| `--<role>-model` | inherits `--model` | same as above |
| `--<role>-effort` | inherits `--effort` | same as above |

Roles: `meta`, `architecture`, `security`, `quality`, `documentation`, `dependency`, `performance`, `critique`.

**Constraint:** `max` effort is Opus-tier only (Sonnet 4.6 and Haiku 4.5 reject it).

JSON overrides win over per-flag overrides when both are present.

### `spectra cache`

Spectra writes a SQLite cache to `${XDG_CACHE_HOME:-~/.cache}/spectra/$UID/cache.db` (WAL mode, AES-256 via SQLCipher in v0.6.0). Five subcommands manage it:

| Subcommand | What it does |
|------------|--------------|
| `spectra cache stats` | Show entry count, on-disk size, per-dimension hit rate (rolling last 100 lookups) |
| `spectra cache clear` | Drop all cache entries (full reset) |
| `spectra cache prune` | Physically delete stale rows that no current key matches — safe to run anytime |
| `spectra cache doctor` | Verify per-row HMAC integrity, encryption status, keyring backend (v0.5.0+) |
| `spectra cache shred [-y]` | Overwrite cache.db (and WAL/SHM siblings) with random bytes (3 passes) then delete; also drops the per-user keyring entry (v0.6.0) |

Cache I/O failures are never fatal — the pipeline degrades to no-cache for the rest of the run (see SPEC-010).

### Error codes

Every fallible operation in Spectra raises a typed `SpectraError` — `SPEC-001` through `SPEC-014`. The full reference (when each fires, what to do, retryable yes/no, max retries) lives in [`docs/error-codes.md`](docs/error-codes.md). The CLI surfaces the code in every brand-voice ✗ message so CI logs are searchable.

---

## Verifying releases

Every release ships with two independent supply-chain attestations: SLSA L3 build provenance (via GitHub's attest-build-provenance) and a Sigstore keyless signature on every wheel. Both are produced inside the publish workflow and bound to the tag commit.

### 1. Verify SLSA build provenance

Confirms the artifact was built by `leocder07/spectra`'s publish workflow on the expected tag commit — defeats the tag-move attack class.

```bash
# Install once
brew install gh   # or: see https://cli.github.com/

# Download the wheel from PyPI (or the release page)
pip download --no-deps spectra-ai==0.6.0 -d /tmp/spectra-verify

# Verify provenance
gh attestation verify /tmp/spectra-verify/spectra_ai-0.6.0-py3-none-any.whl \
  --repo leocder07/spectra
```

Expected output: `Loaded digest sha256:... ✓ Verification succeeded!`

### 2. Verify Sigstore signature

Confirms the wheel was signed by the publish workflow's OIDC identity. Bundles are attached to each GitHub Release as `*.sigstore` assets.

```bash
# Install once
pip install "sigstore>=3.0,<4.0"

# Download wheel + bundle
VER=0.6.0
gh release download "v${VER}" --repo leocder07/spectra \
  --pattern "spectra_ai-${VER}*.sigstore*"
pip download --no-deps "spectra-ai==${VER}" -d .

# Verify
python -m sigstore verify identity \
  --bundle "spectra_ai-${VER}-py3-none-any.whl.sigstore" \
  --cert-identity "https://github.com/leocder07/spectra/.github/workflows/publish.yml@refs/tags/v${VER}" \
  --cert-oidc-issuer "https://token.actions.githubusercontent.com" \
  "spectra_ai-${VER}-py3-none-any.whl"
```

Expected output: `OK: spectra_ai-0.6.0-py3-none-any.whl`

If either check fails, do not install — open an issue at https://github.com/leocder07/spectra/security/advisories/new.

---

## Privacy & Data Processing

Spectra runs on the Customer's machine; the only outbound data flow is to Anthropic's API for inference, governed by the Customer's own Anthropic agreement. We publish a template Data Processing Addendum, an authoritative sub-processor list, and a per-edge data flow diagram so procurement and legal teams have a starting position rather than a blank page.

- [`docs/legal/DPA.md`](docs/legal/DPA.md) — GDPR Art. 28 — compatible Data Processing Addendum (template — requires legal review)
- [`docs/legal/SUBPROCESSORS.md`](docs/legal/SUBPROCESSORS.md) — Sub-processor declaration (Anthropic only)
- [`docs/legal/DATA_FLOW.md`](docs/legal/DATA_FLOW.md) — Per-edge data flow diagram, v0.6.0 baseline (audit sink + receipt edges)
- [`SECURITY.md`](SECURITY.md) — Vulnerability reporting, supported versions, hardening already shipped

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

Built with Claude Opus 4.7 and Claude Code.

**MIT License** · [Repository](https://github.com/leocder07/spectra)

</div>
