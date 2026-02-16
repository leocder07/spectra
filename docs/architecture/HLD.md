# High-Level Design (HLD)

> **Spectra** deploys 8 AI agents to analyze entire repositories across 6 dimensions in 90 seconds.
> Clean Architecture. Python 3.12+. Opus 4.6 everywhere it matters.

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
  Clone     Sonnet    6 agents   Dedup +    Opus 4.6     HTML /
  + tree     4.5      parallel   validate   thinking     JSON /
            plans     Opus 4.6   paths      validates    SARIF
```

| Stage | What Happens | Key Component | Duration |
|-------|-------------|---------------|----------|
| **1. INGEST** | Clone repo, extract file tree, read top 20 source files | `GitAdapter` | ~5s |
| **2. PLAN** | MetaPrompter analyzes file tree, allocates token budgets | `MetaPrompter` (Sonnet 4.5) | ~3s |
| **3. ANALYZE** | 6 specialist agents run in parallel via `asyncio.gather` | `orchestrate_agents` | ~45s |
| **4. MERGE** | Deduplicate findings, remove hallucinated file paths | `analyze_repository` | <1s |
| **5. CRITIQUE** | CritiqueAgent validates all findings with extended thinking | `CritiqueAgent` (Opus 4.6) | ~25s |
| **6. REPORT** | Compute ScoreCard, render output | `ReportAdapter` (Jinja2) | ~2s |

> Sequence diagram: [`diagrams/sequence-analysis-pipeline.md`](../diagrams/sequence-analysis-pipeline.md)
> Data flow: [`diagrams/lld-data-flow.md`](../diagrams/lld-data-flow.md)

---

## 8 Agents

| Agent | Model | Role | Thinking | Max Tokens |
|-------|-------|------|----------|------------|
| **MetaPrompter** | Sonnet 4.5 | Plans analysis from file tree only | Standard | 5,000 |
| **ArchitectureAgent** | Opus 4.6 | Layering, dependencies, anti-patterns | Standard | ~80,000 |
| **SecurityAgent** | Opus 4.6 | OWASP, CVEs, injection, auth | Standard | ~80,000 |
| **QualityAgent** | Opus 4.6 | Complexity, tests, duplication | Standard | ~80,000 |
| **DocumentationAgent** | Opus 4.6 | README, docstrings, ADRs | Standard | ~80,000 |
| **DependencyAgent** | Opus 4.6 | CVEs, licenses, lock files | Standard | ~80,000 |
| **PerformanceAgent** | Opus 4.6 | N+1 queries, async, caching | Standard | ~80,000 |
| **CritiqueAgent** | Opus 4.6 | Validates ALL findings, rejects false positives | **Adaptive** | 16,000 |

**Hard rules:**
- MetaPrompter receives file tree only, never source code (max 5K tokens)
- 6 specialists always run in parallel (`asyncio.gather`)
- Only CritiqueAgent uses extended thinking
- Every agent output validated against Pydantic model before merge
- 120-second timeout per agent via `asyncio.wait_for`

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
| Extended thinking for CritiqueAgent only | Adaptive reasoning is expensive; only the validation stage needs deep reasoning | [ADR-003](adr/ADR-003-extended-thinking-critique-only.md) |
| Frozen Pydantic models | Immutable domain entities ensure thread safety across parallel agents | [ADR-004](adr/ADR-004-frozen-pydantic-models.md) |
| Protocol-based ports | Structural subtyping (Python Protocols) over ABC inheritance for flexibility | [ADR-001](adr/ADR-001-clean-architecture.md) |
| Literal types over Enum | JSON serializable, no `.value` noise, direct string comparison | [ADR-004](adr/ADR-004-frozen-pydantic-models.md) |

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
| LLM API | Anthropic (Opus 4.6, Sonnet 4.5) | Best reasoning models available |
| CLI | Typer + Rich | Type-safe CLI with beautiful terminal output |
| Models | Pydantic v2 (`frozen=True`) | Validation, serialization, immutability |
| Git | GitPython | Clone + file tree extraction |
| Tokens | tiktoken (`cl100k_base`) | Accurate token counting for budget management |
| Reports | Jinja2 | HTML report templating |
| HTTP | httpx (10-connection pool) | Async HTTP for Anthropic API |
| Async | asyncio | Parallel agent execution with semaphore |
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

*See [LLD.md](LLD.md) for component-level details, data flow, and implementation specifics.*
