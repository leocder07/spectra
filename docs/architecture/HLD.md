# High-Level Design (HLD)

> **Spectra** deploys 8 AI agents to analyze entire repositories across 6 dimensions in under 5 minutes.
> Clean Architecture. Python 3.12+. Claude Opus 4.7 everywhere it matters.

## Table of Contents

1. [System Architecture](#system-architecture)
2. [The Dependency Rule](#the-dependency-rule)
3. [6-Stage Analysis Pipeline](#6-stage-analysis-pipeline)
4. [8 Agents](#8-agents)
5. [ScoreCard Weights](#scorecard-weights)
6. [Key Design Decisions](#key-design-decisions)
7. [Design Patterns](#design-patterns)
8. [Technology Stack](#technology-stack)
9. [Failure Handling](#failure-handling)
10. [Token Budget](#token-budget)
11. [Output Formats](#output-formats)
12. [Distribution: GitHub Action](#distribution-github-action)
13. [Roadmap: Incremental Analysis (Designed, In Progress)](#roadmap-incremental-analysis-designed-in-progress)

---

## System Architecture

Spectra follows **4-layer Clean Architecture** with strict inward-only dependencies. The composition root (`main.py`) wires all dependencies at startup — no service locator, no framework magic.

```
                    ┌──────────────────────────────────┐
                    │  Layer 4 — Infrastructure         │
                    │  main.py, AnthropicAdapter,       │
                    │  AgentFactory, 8 Agents,          │
                    │  GitAdapter, ReportAdapter         │
                    ├──────────────────────────────────┤
                    │  Layer 3 — Adapters               │
                    │  cli_controller (Typer),           │
                    │  RichProgressReporter,             │
                    │  AnalysisPresenter                 │
                    ├──────────────────────────────────┤
                    │  Layer 2 — Use Cases              │
                    │  analyze_repository (Facade),      │
                    │  orchestrate_agents, interfaces    │
                    ├──────────────────────────────────┤
                    │  Layer 1 — Entities               │
                    │  models.py, enums.py, errors.py   │
                    │  ZERO imports from spectra        │
                    └──────────────────────────────────┘

            Dependencies point INWARD only. Never outward.
```

> Full Mermaid diagram: [`diagrams/hld-system-architecture.md`](../diagrams/hld-system-architecture.md)

### The Dependency Rule

| Layer | May Import From | Never Imports From |
|-------|----------------|-------------------|
| **1 — Entities** | stdlib, pydantic only | Any spectra module |
| **2 — Use Cases** | Layer 1 | Layers 3, 4 |
| **3 — Adapters** | Layers 1, 2 | Layer 4 |
| **4 — Infrastructure** | Layers 1, 2, 3 | (outermost) |

This is enforced by convention and code review. Violation = immediate rejection.

---

## 6-Stage Analysis Pipeline

Every `spectra analyze <repo-url>` runs through 6 sequential stages:

```
  INGEST ──→ PLAN ──→ ANALYZE ──→ MERGE ──→ CRITIQUE ──→ REPORT
    │          │         │           │          │            │
  Clone     Opus 4.7  6 agents   Dedup +    Opus 4.7     HTML /
  + tree     medium   parallel   validate   adaptive     JSON /
            plans     Opus 4.7   paths      thinking     SARIF
                       xhigh                + budget
```

| Stage | What Happens | Key Component | Duration |
|-------|-------------|---------------|----------|
| **1. INGEST** | Clone repo, extract file tree, read top 20 source files | `GitAdapter` | ~5s |
| **2. PLAN** | MetaPrompter analyzes file tree, allocates token budgets | `MetaPrompter` (Opus 4.7, `effort=medium`) | ~3s |
| **3. ANALYZE** | 6 specialist agents run in parallel via `asyncio.gather` | `orchestrate_agents` (Opus 4.7, `effort=xhigh`) | ~45s |
| **4. MERGE** | Deduplicate findings, remove hallucinated file paths | `analyze_repository` | <1s |
| **5. CRITIQUE** | CritiqueAgent validates all findings with adaptive thinking | `CritiqueAgent` (Opus 4.7, `effort=high`, `task_budget=80K`) | ~25s |
| **6. REPORT** | Compute ScoreCard, render output | `ReportAdapter` (Jinja2) | ~2s |

> Sequence diagram: [`diagrams/sequence-analysis-pipeline.md`](../diagrams/sequence-analysis-pipeline.md)
> Data flow: [`diagrams/lld-data-flow.md`](../diagrams/lld-data-flow.md)

---

## 8 Agents

All eight agents now run on **Claude Opus 4.7** (model id `claude-opus-4-7`). Effort and thinking modes vary by role.

| Agent | Model | Role | Effort | Thinking | Max Tokens | Task Budget |
|-------|-------|------|--------|----------|------------|-------------|
| **MetaPrompter** | Opus 4.7 | Plans analysis from file tree only | `medium` | Off | 5,000 | — |
| **ArchitectureAgent** | Opus 4.7 | Layering, dependencies, anti-patterns | `xhigh` | Off | ~80,000 | — |
| **SecurityAgent** | Opus 4.7 | OWASP, CVEs, injection, auth | `xhigh` | Off | ~80,000 | — |
| **QualityAgent** | Opus 4.7 | Complexity, tests, duplication | `xhigh` | Off | ~80,000 | — |
| **DocumentationAgent** | Opus 4.7 | README, docstrings, ADRs | `xhigh` | Off | ~80,000 | — |
| **DependencyAgent** | Opus 4.7 | CVEs, licenses, lock files | `xhigh` | Off | ~80,000 | — |
| **PerformanceAgent** | Opus 4.7 | N+1 queries, async, caching | `xhigh` | Off | ~80,000 | — |
| **CritiqueAgent** | Opus 4.7 | Validates ALL findings, rejects false positives | `high` | **Adaptive (`display: summarized`)** | 64,000 | 80,000 |

**Hard rules:**
- MetaPrompter receives file tree only, never source code (max 5K tokens)
- 6 specialists always run in parallel (`asyncio.gather`)
- Only CritiqueAgent uses adaptive thinking (`thinking={"type": "adaptive", "display": "summarized"}`)
- CritiqueAgent is the only agent that uses `task_budget` (beta header `task-budgets-2026-03-13`) — caps cumulative reasoning + output spend at 80K tokens regardless of how the model decides to allocate them
- Every agent output validated against Pydantic model before merge
- 120-second timeout per agent via `asyncio.wait_for`
- `temperature` is **never** passed — Opus 4.7 rejects it; reasoning depth is steered exclusively via `output_config.effort`

> Agent model diagram: [`diagrams/hld-system-architecture.md`](../diagrams/hld-system-architecture.md) (8 Agents section)
> Agent lifecycle: [`diagrams/state-agent-lifecycle.md`](../diagrams/state-agent-lifecycle.md)

---

## ScoreCard Weights

| Dimension | Weight | Agent |
|-----------|--------|-------|
| Architecture | 25% | ArchitectureAgent |
| Security | 25% | SecurityAgent |
| Quality | 20% | QualityAgent |
| Documentation | 10% | DocumentationAgent |
| Maintainability | 10% | DependencyAgent |
| Performance | 10% | PerformanceAgent |

**Score computation:**
```
penalty_score = 100 - min(sum(PENALTY[severity] * confidence), 55)
blended_score = 0.4 * llm_score + 0.6 * penalty_score
overall_score = sum(dimension_score * normalized_weight)
```

Penalties: critical=15, high=8, medium=3, low=1. Max penalty capped at 55 points.

Grades: A+ (95-100), A (90-94), A- (87-89), B+ (83-86), B (80-82), B- (77-79), C+ (73-76), C (70-72), C- (67-69), D (60-66), F (0-56).

---

## Key Design Decisions

| Decision | Rationale | ADR |
|----------|-----------|-----|
| 4-layer Clean Architecture | Strict dependency rule enables testability and adapter swapping | [ADR-001](adr/ADR-001-clean-architecture.md) |
| 8 agents, 6 in parallel | Parallel analysis across dimensions; MetaPrompter plans, CritiqueAgent validates | [ADR-002](adr/ADR-002-parallel-agent-pipeline.md) |
| ~~Extended thinking for CritiqueAgent only~~ | Original 2025 decision — superseded by ADR-008 | [ADR-003](adr/ADR-003-extended-thinking-critique-only.md) (superseded) |
| Adaptive thinking for CritiqueAgent only | Replaces "extended thinking" terminology; uses `display: summarized` and `task_budget` (Opus 4.7) | [ADR-008](adr/ADR-008-adaptive-thinking-supersedes-extended.md) |
| Frozen Pydantic models | Immutable domain entities ensure thread safety across parallel agents | [ADR-004](adr/ADR-004-frozen-pydantic-models.md) |
| Protocol-based ports | Structural subtyping (Python Protocols) over ABC inheritance for flexibility | [ADR-001](adr/ADR-001-clean-architecture.md) |
| Literal types over Enum | JSON serializable, no `.value` noise, direct string comparison | [ADR-004](adr/ADR-004-frozen-pydantic-models.md) |
| Migrate all agents to Opus 4.7 | Single model family; per-role `effort` tuning; `temperature` and `budget_tokens` removed | [ADR-005](adr/ADR-005-opus-4-7-migration.md) |
| `CachePort` + per-`focus_area` SQLite cache | Incremental analysis: 80–95% hit rates on typical edits; merge/score always over union | [ADR-006](adr/ADR-006-cache-port-incremental-analysis.md) |
| GitHub Action as primary distribution | Composite Action installs PyPI package on the runner; idempotent PR comment | [ADR-007](adr/ADR-007-github-action-distribution.md) |

> Design patterns catalog (11 patterns): [`diagrams/design-patterns-catalog.md`](../diagrams/design-patterns-catalog.md)

---

## Design Patterns

Spectra uses 11 documented design patterns across all 4 layers:

| Pattern | Where | Purpose |
|---------|-------|---------|
| **Template Method** | `BaseAgent.run()` | Fixed agent lifecycle, subclasses customize steps |
| **Decorator** | Logging + Retry chain | Add observability + retry without modifying adapter |
| **Adapter** | `AnthropicAdapter` | Translate Anthropic SDK to `LLMGateway` Protocol |
| **Factory** | `AgentFactory` | Centralize agent creation, hide concrete classes |
| **Strategy** | `SPECIALIST_CONFIGS` | One class serves 6 dimensions via parameterization |
| **Facade** | `analyze_repository()` | Single entry point for the 6-stage pipeline |
| **Port/Adapter** | 5 Protocol interfaces | Dependency inversion without inheritance |
| **Observer** | `ProgressObserver` | Decouple pipeline events from terminal display |
| **Value Object** | Frozen Pydantic models | Immutable, hashable domain entities |
| **Error Taxonomy** | `SpectraError` registry | Structured errors with retry metadata |
| **Composition Root** | `main.py` | Single DI wiring point at outermost layer |

---

## Technology Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.12+ | Async-first, type hints, pattern matching |
| LLM API | Anthropic Claude Opus 4.7 (all 8 agents) | One model family; per-role `effort` tunes cost/quality |
| CLI | Typer + Rich | Type-safe CLI with beautiful terminal output |
| Models | Pydantic v2 (`frozen=True`) | Validation, serialization, immutability |
| Git | GitPython | Clone + file tree extraction |
| Tokens | tiktoken (`cl100k_base`) | Accurate token counting for budget management |
| Reports | Jinja2 | HTML report templating |
| HTTP | httpx (10-connection pool) | Async HTTP for Anthropic API |
| Async | asyncio | Parallel agent execution with semaphore |
| Distribution | PyPI (`spectra-ai`) + GitHub Action (`spectra-ai/spectra@v1`) | One install path for humans, one for CI |
| Testing | pytest + pytest-asyncio | Async test support, 85%+ coverage |
| Linting | ruff + mypy (strict) | Fast linting + strict type checking |

---

## Failure Handling

```
0-1 agent failures  →  "merging" state (reweight scores, continue)
2+ agent failures   →  "degraded" state (partial report, skip critique)
```

The pipeline never crashes on individual agent failures. `asyncio.gather(return_exceptions=True)` captures exceptions, and `evaluate_results()` decides pipeline state based on failure count. See [error codes in LLD](LLD.md#error-codes).

> State diagram: [`diagrams/state-pipeline.md`](../diagrams/state-pipeline.md)

---

## Token Budget

| Pool | Tokens | Purpose |
|------|--------|---------|
| Total | 800,000 | Full analysis budget |
| MetaPrompter | 5,000 | Planning (file tree only) |
| Specialists | 500,000 | Shared across 6 agents (weighted by dimension) |
| Critique | 200,000 | Reserved for CritiqueAgent |
| Buffer | 95,000 | Safety margin |

The MetaPrompter's plan includes `token_allocation` hints. `allocate_specialist_budgets()` distributes the specialist pool using dimension weights (Architecture 25%, Security 25%, Quality 20%, Documentation 10%, Maintainability 10%, Performance 10%).

---

## Output Formats

| Format | Command | Renderer |
|--------|---------|----------|
| HTML | `spectra analyze <url>` | Jinja2 template with interactive UI |
| JSON | `spectra analyze <url> --format json` | `json.dumps(report.model_dump())` |
| SARIF | `spectra analyze <url> --format sarif` | SARIF v2.1.0 for IDE integration |

The HTML report includes: ScoreCard, findings by dimension, compliance mapping (OWASP, SOC 2, PCI DSS 4.0, NIST CSF 2.0), ROI calculator, and investment readiness score.

---

## Distribution: GitHub Action

Spectra ships two install paths from a single PyPI package:

| Audience | Install path | Purpose |
|----------|--------------|---------|
| Local developer | `pip install spectra-ai` | `spectra analyze <repo>` from a terminal |
| CI / PR review | `uses: spectra-ai/spectra@v1` (composite Action) | Runs Spectra on every PR, posts an idempotent comment |

The composite Action (defined in `action.yml` at the repo root) installs the same `spectra-ai` PyPI package on the runner, executes `spectra analyze`, parses the JSON report for `grade` and `score` outputs, and — on `pull_request` events — finds-or-creates a comment marked with the hidden `<!-- SPECTRA -->` sentinel so re-runs update one comment in place rather than spamming the timeline.

A dogfood workflow at `.github/workflows/spectra.yml` runs Spectra on Spectra itself for every PR.

See [ADR-007](adr/ADR-007-github-action-distribution.md) for the rationale and the local-path TODO that the Action currently works around by passing `https://github.com/$GITHUB_REPOSITORY.git` when the caller's `path` input is `.`.

---

## Roadmap: Incremental Analysis (Designed, In Progress)

A 462-line design doc at [`../plans/incremental-analysis.md`](../plans/incremental-analysis.md) introduces a per-`focus_area` cache that targets 80–95% hit rates on typical edit patterns. The architecture impact is additive:

- **New port (Layer 2):** `CachePort` Protocol with `get_findings`, `put_findings`, `clear`, `stats`, `compute_repo_signature`.
- **New adapter (Layer 4):** `SqliteCacheAdapter` backed by a single `~/.cache/spectra/cache.db` (WAL mode, composite primary key on `(file_hash, dimension, model_version, prompt_version, schema_version)`).
- **New entities (Layer 1):** `CacheEntry`, `CacheStats`, `BatchPrompt` (all frozen Pydantic).
- **Pipeline change:** `_build_specialist_prompts` returns `dict[AgentRole, list[BatchPrompt]]` instead of `dict[AgentRole, str]`. Merge and ScoreCard always run over the **union** of cached + fresh findings — the ScoreCard remains consistent with a full re-run.
- **CLI surface:** `--force`, `--no-cache`, `spectra cache stats|clear|prune`.

**Status as of 2026-04-29:** Phase 1 (the port + adapter, no pipeline callers yet) is being implemented in a parallel worktree. Phase 2 (repo-level shortcut) and Phase 3 (per-batch caching, the killer feature) follow.

See [ADR-006](adr/ADR-006-cache-port-incremental-analysis.md) for the architectural decision and the design doc for the implementation plan.

---

*See [LLD.md](LLD.md) for component-level details, data flow, and implementation specifics.*

---

*Last updated: 2026-04-29 — Opus 4.7 migration, GitHub Action distribution, CachePort design.*
