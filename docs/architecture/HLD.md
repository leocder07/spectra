# High-Level Design (HLD)

> **Spectra** deploys 8 AI agents to analyze entire repositories across 6 dimensions in under 5 minutes.
> Clean Architecture. Python 3.12+. Claude Opus 4.7 everywhere it matters. SQLite-backed incremental cache.

## Table of Contents

1. [System Architecture](#system-architecture)
2. [The Dependency Rule](#the-dependency-rule)
3. [6-Stage Analysis Pipeline (with cache)](#6-stage-analysis-pipeline-with-cache)
4. [Cache Subsystem](#cache-subsystem)
5. [8 Agents](#8-agents)
6. [ScoreCard Weights](#scorecard-weights)
7. [Key Design Decisions](#key-design-decisions)
8. [Design Patterns](#design-patterns)
9. [Technology Stack](#technology-stack)
10. [Failure Handling](#failure-handling)
11. [Token Budget](#token-budget)
12. [Output Formats](#output-formats)
13. [Distribution model](#distribution-model)

---

## System Architecture

Spectra follows **4-layer Clean Architecture** with strict inward-only dependencies. The composition root (`main.py`) wires all dependencies at startup — no service locator, no framework magic.

```
                    ┌──────────────────────────────────┐
                    │  Layer 4 — Infrastructure         │
                    │  main.py, AnthropicAdapter,       │
                    │  AgentFactory, 8 Agents,          │
                    │  GitAdapter, ReportAdapter,        │
                    │  SqliteCacheAdapter                │
                    ├──────────────────────────────────┤
                    │  Layer 3 — Adapters               │
                    │  cli_controller (Typer),           │
                    │  RichProgressReporter,             │
                    │  AnalysisPresenter                 │
                    ├──────────────────────────────────┤
                    │  Layer 2 — Use Cases              │
                    │  analyze_repository (Facade,       │
                    │  PipelineContext value object),    │
                    │  orchestrate_agents, interfaces    │
                    │  (LLMGateway, GitPort, CachePort)  │
                    ├──────────────────────────────────┤
                    │  Layer 1 — Entities               │
                    │  models.py (incl. CacheEntry,      │
                    │  CacheStats, BatchPrompt,          │
                    │  BatchCacheKey, RepoCacheKey),     │
                    │  enums.py, errors.py              │
                    │  ZERO imports from spectra        │
                    └──────────────────────────────────┘

            Dependencies point INWARD only. Never outward.
```

> System Context (C4 L1): [`diagrams/system-context.md`](../diagrams/system-context.md) · [`diagrams/excalidraw/system-context.excalidraw`](../diagrams/excalidraw/system-context.excalidraw)
> Container view (C4 L2): [`diagrams/container-view.md`](../diagrams/container-view.md)
> Full Mermaid system diagram: [`diagrams/hld-system-architecture.md`](../diagrams/hld-system-architecture.md)

### The Dependency Rule

| Layer | May Import From | Never Imports From |
|-------|----------------|-------------------|
| **1 — Entities** | stdlib, pydantic only | Any spectra module |
| **2 — Use Cases** | Layer 1 | Layers 3, 4 |
| **3 — Adapters** | Layers 1, 2 | Layer 4 |
| **4 — Infrastructure** | Layers 1, 2, 3 | (outermost) |

This is enforced by convention and code review. Violation = immediate rejection. The cache subsystem is purely additive: `CachePort` lives in Layer 2, `SqliteCacheAdapter` in Layer 4 — no inward leak.

---

## 6-Stage Analysis Pipeline (with cache)

Every `spectra analyze <source>` runs through 6 sequential stages. Two cache decision points short-circuit work when the inputs already match a cached result:

```
                                  ┌─────────────────────────┐
                                  │ PHASE 2 cache check     │
                                  │ get_full_report(...)    │
                                  │ HIT → skip Stages 3-5   │
                                  └────────────┬────────────┘
                                               │
  INGEST ──→ PLAN ──→ ━━━━━━━━━━━━━━━━━━━━━━━━━┷━━━━━━━━━━━━━ ANALYZE ──→ MERGE ──→ CRITIQUE ──→ REPORT
    │          │                                                  │           │            │            │
  Clone /   Opus 4.7                                          PHASE 3       Dedup +     Opus 4.7      HTML /
  prepare    medium                                          per-batch     validate    adaptive      JSON /
  workspace  plans                                          cache splits   paths       thinking      SARIF
                                                            into cached +              + budget
                                                            fresh batches
```

| Stage | What Happens | Key Component | Duration |
|-------|-------------|---------------|----------|
| **1. INGEST** | Resolve source via `GitPort.prepare_workspace` (HTTPS clone OR validate local path), extract file tree, read top 20 source files | `GitAdapter` | ~5s (or ~0s for local paths) |
| **2. PLAN** | MetaPrompter analyzes file tree, allocates token budgets, partitions files by `focus_areas` | `MetaPrompter` (Opus 4.7, `effort=medium`) | ~3s |
| **2½. CACHE (Phase 2)** | Compute repo signature, check `full_report_cache` — short-circuit if hit and `--force` not set | `SqliteCacheAdapter` | <100ms |
| **3. ANALYZE** | Per-batch cache lookup partitions into cached + fresh; only fresh batches go to specialists in parallel via `asyncio.gather` | `orchestrate_agents` + cache (Opus 4.7, `effort=xhigh`) | ~5–45s depending on hit rate |
| **4. MERGE** | Deduplicate findings (cached union fresh), remove hallucinated file paths | `analyze_repository` | <1s |
| **5. CRITIQUE** | CritiqueAgent validates all findings with adaptive thinking | `CritiqueAgent` (Opus 4.7, `effort=high`, `task_budget=80K`) | ~25s |
| **6. REPORT** | Compute ScoreCard, write back to `full_report_cache`, render output | `ReportAdapter` (Jinja2) | ~2s |

**Local-path branch (Stage 1).** `GitPort.prepare_workspace(source, target_dir)` is the single entrypoint that classifies `source` and either (a) clones an HTTPS URL into `target_dir` or (b) validates that the path holds a `.git/` checkout and returns its absolute path. `spectra analyze .` is the canonical local-path invocation.

**Phase 3 batch granularity.** `_build_specialist_prompts` returns `dict[AgentRole, list[BatchPrompt]]` — one batch per `focus_area` per specialist. `partition_by_cache` then splits each agent's batch list into a tuple of cached findings + a list of fresh batches. The specialist only runs on the fresh batches; cached findings are merged in directly. The MERGE and ScoreCard stages always operate over the **union** of cached + fresh, so the report is bit-identical to a full re-run modulo prompt/model identity (which are part of the cache key).

> Sequence diagram (with cache decision points): [`diagrams/sequence-analysis-pipeline.md`](../diagrams/sequence-analysis-pipeline.md)
> Cache decision flowchart: [`diagrams/sequence-analysis-pipeline.md#cache-decision-tree-extracted-from-the-sequence-above`](../diagrams/sequence-analysis-pipeline.md#cache-decision-tree-extracted-from-the-sequence-above)
> Data flow: [`diagrams/lld-data-flow.md`](../diagrams/lld-data-flow.md)

---

## Cache Subsystem

A new Layer-2 port (`CachePort`) and Layer-4 adapter (`SqliteCacheAdapter`) make Spectra incremental: re-runs after a single-file edit return in seconds at 80–95% of the original analysis cost.

### Three caching layers, one SQLite file

| Table | Phase | Granularity | Purpose |
|-------|-------|-------------|---------|
| `findings_cache` | 1 | per-`(file_hash, dimension)` row | Foundation; the original Phase 1 row format |
| `full_report_cache` | 2 | per-`(repo_signature, all version components)` | Short-circuits Stages 3-5 entirely when nothing about the repo or its version context changed |
| `findings_batches` | 3 | per-`(batch_id, dimension, version components)` | The killer feature — edit one file, invalidate exactly the batches it belongs to |
| `hit_log` | 3 | append-only `(ts, hit)` | Telemetry — feeds `CacheStats.hit_rate_last_100` and `on_cache_lookup` observer |

Single file at `${XDG_CACHE_HOME:-~/.cache}/spectra/cache.db`. WAL mode enables concurrent reads without blocking writes.

### Composite-key invalidation

The composite primary key on every findings table makes invalidation a no-op: a stale row simply never matches a current-context lookup. There is no "cache invalidation logic" to maintain. Triggers (full matrix in [`diagrams/cache-architecture.md`](../diagrams/cache-architecture.md)):

- `--force` → bypass reads, still write
- `--no-cache` → composition root passes `cache_port=None`, no R/W
- spectra version bump → `spectra_version` field mismatches
- model/prompt/schema version bump → corresponding key field mismatches
- file content change → new `blake2b(file)` → new `file_hash` → new `batch_id`
- file deleted → `repo_signature` changes → `full_report_cache` miss
- row >N days old → lazy GC via `spectra cache prune` (Phase 4 — in flight, see PR #19)

### Run-context binding (Phase 3)

`bind_run_context(model_versions, prompt_versions, schema_version, spectra_version)` is called once at composition-root startup. It atomically stores the four versions used to compose every per-batch cache key — eliminating the intermediate-inconsistent-state failure mode of the original Phase 1 setters.

### CLI surface

```bash
spectra analyze <source>          # cache-aware (default)
spectra analyze <source> --force  # bypass reads, still write
spectra analyze <source> --no-cache  # neither read nor write (CI mode)
spectra cache stats               # rolling hit rate, repos tracked, DB size  (Phase 4 — in flight)
spectra cache clear [<repo>]      # purge one repo or all                    (Phase 4 — in flight)
spectra cache prune --older-than 30d  # delete rows older than N days        (Phase 4 — in flight)
```

### Observability

`ProgressObserver.on_cache_lookup(dimension, hits, total)` fires once per dimension during ANALYZE, surfacing the "killer-feature signal" in the terminal — e.g. `security cache 7/8 hits`. The rolling cache hit rate over the last 100 lookups is exposed via `CacheStats.hit_rate_last_100` (and `spectra cache stats` once Phase 4 lands).

### Failure mode (SPEC-010)

`SqliteCacheAdapter` funnels every fallible I/O through `_guard_io`, which converts `sqlite3.Error` and `OSError` into `AgentError(SPEC-010)`. The pipeline catches this at the cache call sites and **degrades to no-cache for the rest of the run** — analysis proceeds normally, just without the cache benefit. Cache failures are never fatal.

> Cache deep-dive: [`diagrams/cache-architecture.md`](../diagrams/cache-architecture.md) · [`diagrams/excalidraw/cache-schema.excalidraw`](../diagrams/excalidraw/cache-schema.excalidraw)
> Decision: [ADR-006](adr/ADR-006-cache-port-incremental-analysis.md) · [ADR-009](adr/ADR-009-batch-granularity-per-focus-area.md)

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
> Decorator chain + LLMGateway protocol: [`diagrams/lld-decorator-chain.md`](../diagrams/lld-decorator-chain.md)

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
| Per-`focus_area` batch granularity (Phase 3) | One cache row per `focus_area` × dimension preserves intra-batch context while delivering the killer hit rate | [ADR-009](adr/ADR-009-batch-granularity-per-focus-area.md) |
| GitHub Action as primary distribution | Composite Action installs PyPI package on the runner; idempotent PR comment | [ADR-007](adr/ADR-007-github-action-distribution.md) |
| No self-dogfood on PR-triggered workflows | Token-abuse risk on forked PRs — downstream consumers wire it in their own repos | [ADR-010](adr/ADR-010-no-self-dogfooding.md) |

> Design patterns catalog (11 patterns): [`diagrams/design-patterns-catalog.md`](../diagrams/design-patterns-catalog.md)

---

## Design Patterns

Spectra uses 11+ documented design patterns across all 4 layers:

| Pattern | Where | Purpose |
|---------|-------|---------|
| **Template Method** | `BaseAgent.run()` | Fixed agent lifecycle, subclasses customize steps |
| **Decorator** | Logging + Retry chain | Add observability + retry without modifying adapter |
| **Adapter** | `AnthropicAdapter`, `SqliteCacheAdapter` | Translate external SDK/SQLite to Layer-2 Protocols |
| **Factory** | `AgentFactory` | Centralize agent creation, hide concrete classes |
| **Strategy** | `SPECIALIST_CONFIGS` | One class serves 6 dimensions via parameterization |
| **Facade** | `analyze_repository()` | Single entry point for the 6-stage pipeline |
| **Port/Adapter** | 6 Protocol interfaces | Dependency inversion without inheritance |
| **Observer** | `ProgressObserver` (incl. `on_cache_lookup`) | Decouple pipeline events from terminal display |
| **Value Object** | Frozen Pydantic models, `PipelineContext` | Immutable, hashable; replaces 8-param facade signature (Fowler) |
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
| Git | GitPython | Clone + file tree extraction (HTTPS only) |
| Tokens | tiktoken (`cl100k_base`) | Accurate token counting for budget management |
| Reports | Jinja2 | HTML report templating |
| Cache | SQLite stdlib + WAL mode | Single-file local cache, ACID, indexed lookups |
| Hashing | `hashlib.blake2b(digest_size=16)` | Fast, deterministic file/batch identifiers |
| HTTP | httpx (10-connection pool) | Async HTTP for Anthropic API |
| Async | asyncio | Parallel agent execution with `Semaphore(4)` |
| Distribution | PyPI (`spectra-ai`) + GitHub Action (`spectra-ai/spectra@v1`) | One install path for humans, one for CI |
| Testing | pytest + pytest-asyncio | Async test support, 85%+ coverage |
| Linting | ruff + mypy (strict) | Fast linting + strict type checking |

---

## Failure Handling

```
0-1 agent failures  →  "merging" state (reweight scores, continue)
2+ agent failures   →  "degraded" state (partial report, skip critique)
SPEC-010 cache I/O  →  degrade to no-cache for the run (analysis continues)
```

The pipeline never crashes on individual agent failures or cache failures. `asyncio.gather(return_exceptions=True)` captures agent exceptions, and `evaluate_results()` decides pipeline state based on failure count. Cache failures are caught at every call site and the pipeline carries on without the cache. See [error codes in LLD](LLD.md#error-codes).

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

The MetaPrompter's plan includes `token_allocation` hints. `allocate_specialist_budgets()` distributes the specialist pool using dimension weights (Architecture 25%, Security 25%, Quality 20%, Documentation 10%, Maintainability 10%, Performance 10%). On a warm-cache run, only the fresh batches consume specialist budget; the remainder stays in the pool.

---

## Output Formats

| Format | Command | Renderer |
|--------|---------|----------|
| HTML | `spectra analyze <source>` | Jinja2 template with interactive UI |
| JSON | `spectra analyze <source> --format json` | `json.dumps(report.model_dump())` |
| SARIF | `spectra analyze <source> --format sarif` | SARIF v2.1.0 for IDE integration |

The HTML report includes: ScoreCard, findings by dimension, compliance mapping (OWASP, SOC 2, PCI DSS 4.0, NIST CSF 2.0), ROI calculator, and investment readiness score.

---

## Distribution model

Spectra ships from a single PyPI artifact via two install paths:

| Audience | Install path | Purpose |
|----------|--------------|---------|
| Local developer | `pip install spectra-ai` | `spectra analyze <source>` from a terminal |
| CI / PR review | `uses: spectra-ai/spectra@v1` (composite Action) | Runs Spectra on every PR, posts an idempotent comment |

The composite Action (`action.yml` at the repo root) installs the same `spectra-ai` PyPI package on the runner, executes `spectra analyze`, parses the JSON report for `grade` and `score` outputs, and — on `pull_request` events — finds-or-creates a comment marked with the hidden `<!-- SPECTRA -->` sentinel so re-runs update one comment in place rather than spamming the timeline.

### Deliberate non-dogfood

This repo's own CI does **not** run `spectra-ai/spectra@v1` on its own pull requests. The risk is real: an attacker forks the repo, edits `.github/workflows/spectra.yml` to exfiltrate `secrets.ANTHROPIC_API_KEY` to an attacker-controlled endpoint, opens a PR, and (depending on event configuration) the publisher's API key gets leaked. Removing self-analysis workflows (`spectra.yml`, `spectra-analyze.yml`, `example-usage.yml`) eliminates the entire class of attack with no functional loss — the Action is still tested in CI on push events to maintained branches, just not on untrusted PRs. Downstream consumers wire the Action into their own repos with their own API keys.

> Action distribution flow + token-abuse scenario: [`diagrams/github-action-flow.md`](../diagrams/github-action-flow.md)
> Decisions: [ADR-007](adr/ADR-007-github-action-distribution.md) · [ADR-010](adr/ADR-010-no-self-dogfooding.md)

---

*See [LLD.md](LLD.md) for component-level details, data flow, and implementation specifics.*

---

*Last updated: 2026-04-29 — incremental cache subsystem (Phases 1-3 shipped, Phase 4 in flight); GitHub Action distribution + non-dogfood decision; PipelineContext value object; local-path branch via `prepare_workspace`.*
