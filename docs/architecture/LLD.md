# Low-Level Design (LLD)

> Component-level implementation details for Spectra's 8-agent analysis pipeline.
> Every file:line reference points to actual source code.

---

## Component Catalog

### Layer 1 — Entities (zero spectra imports)

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `entities/models.py` | Frozen Pydantic domain models | `Finding`, `ScoreCard`, `AnalysisReport`, `Codebase`, `TokenBudget`, `AgentOutput`, `CacheEntry`, `CacheStats`, `BatchPrompt`, `BatchCacheKey`, `RepoCacheKey` |
| `entities/enums.py` | Literal type aliases | `Severity`, `Dimension`, `Grade`, `AgentRole`, `PipelineState`, `SchemaVersion` |
| `entities/errors.py` | Structured error hierarchy | `SpectraError`, `ERRORS` registry, `AgentError`, `GitError`, `SpectraRetryError` |

### Layer 2 — Use Cases (imports entities only)

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `use_cases/interfaces.py` | Protocol interfaces (ports) | `LLMGateway` (with `effort` + `task_budget_tokens` kwargs), `GitPort` (with `prepare_workspace`), `TokenPort`, `ReportPort`, `ProgressObserver` (with `on_cache_lookup`), `CachePort`. Also exports `is_local_path` classifier. |
| `use_cases/analyze_repository.py` | 6-stage pipeline facade — accepts a single `PipelineContext` value object | `analyze_repository(ctx: PipelineContext) → AnalysisReport`, `PipelineContext`, `CacheVersions`, `compute_file_hashes`, `build_batch_prompts`, `partition_by_cache` |
| `use_cases/orchestrate_agents.py` | Parallel agent execution | `run_specialists()`, `evaluate_results()` |
| `use_cases/manage_token_budget.py` | Token budget allocation | `allocate_specialist_budgets()`, `DIMENSION_WEIGHTS` |

### Layer 3 — Adapters (imports entities + use_cases)

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `adapters/cli_controller.py` | Typer CLI entry point | `app`, `analyze` command, `cache stats|clear|prune` subcommands (Phase 4 — in flight, see PR #19) |
| `adapters/progress_reporter.py` | Rich terminal progress | `RichProgressReporter` (implements `ProgressObserver`, including `on_cache_lookup`) |
| `adapters/analysis_presenter.py` | ScoreCard terminal display | `AnalysisPresenter` |

### Layer 4 — Infrastructure (imports all inner layers)

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `infrastructure/main.py` | Composition root (DI wiring) | `_run_analysis()`, `cli()` |
| `infrastructure/anthropic_adapter.py` | Anthropic API client | `AnthropicAdapter` (implements `LLMGateway`) |
| `infrastructure/retry_decorator.py` | Exponential backoff | `RetryDecorator` (implements `LLMGateway`) |
| `infrastructure/logging_decorator.py` | Call metrics logging | `LoggingDecorator` (implements `LLMGateway`) |
| `infrastructure/git_adapter.py` | Git operations + security | `GitAdapter` (implements `GitPort`, including `prepare_workspace`) |
| `infrastructure/tiktoken_adapter.py` | Token counting | `TiktokenAdapter` (implements `TokenPort`) |
| `infrastructure/report_adapter.py` | Jinja2 HTML rendering | `ReportAdapter` (implements `ReportPort`) |
| `infrastructure/cache_adapter.py` | SQLite cache | `SqliteCacheAdapter` (implements `CachePort`), `default_cache_path()`, `SCHEMA_VERSION` |
| `infrastructure/agents/base_agent.py` | ABC Template Method | `BaseAgent` |
| `infrastructure/agents/agent_factory.py` | Agent creation dispatch | `AgentFactory` |
| `infrastructure/agents/meta_prompter.py` | Planning agent (Opus 4.7, `effort=medium`) | `MetaPrompter` |
| `infrastructure/agents/specialist_agent.py` | Parameterized specialist (Opus 4.7, `effort=xhigh`) | `SpecialistAgent` |
| `infrastructure/agents/specialist_prompts.py` | System prompts (6 dimensions) | `SPECIALIST_CONFIGS`, `_OPUS = "claude-opus-4-7"` |
| `infrastructure/agents/critique_agent.py` | Validation agent (Opus 4.7, `effort=high`, `task_budget=80K`) | `CritiqueAgent`, `_TASK_BUDGET_TOKENS` |

> Component interaction diagram: [`diagrams/lld-component-interaction.md`](../diagrams/lld-component-interaction.md)
> Class diagram: [`diagrams/class-domain-model.md`](../diagrams/class-domain-model.md)

---

## `PipelineContext` value object

`analyze_repository(ctx: PipelineContext) → AnalysisReport` — a single frozen dataclass replaces what used to be an 8-parameter facade signature (Fowler "Replace Long Parameter List with Parameter Object"). Everything the pipeline needs is on `ctx`:

```python
@dataclass(frozen=True)
class PipelineContext:
    request: AnalysisRequest
    codebase: Codebase
    source_files: dict[str, str]
    specialists: list[AnalysisAgent]
    critique: AnalysisAgent | None
    meta_plan: AgentOutput
    observer: ProgressObserver
    token_budget: TokenBudget
    git_port: GitPort | None              # Phase 3 — needed for file hashing
    cache_port: CachePort | None          # None when --no-cache
    cache_key_factory: Callable | None    # builds RepoCacheKey from a signature
    force_cache_bypass: bool = False      # set by --force
    cache_versions: CacheVersions | None  # four-tuple for Phase 3 keys
```

Cache wiring is **optional**: `cache_port=None` (the wiring used when `--no-cache` is passed) skips both the read and the write paths cleanly. `force_cache_bypass=True` ignores any hit on read but still refreshes the cache on a successful run. This keeps every `if cache_port is not None` check at a single layer (the facade) rather than spreading through every helper.

---

## Decorator Chain

All LLM calls flow through a 3-layer decorator chain wired at `main.py:108-110`:

```
Agent.execute_llm()
    → LoggingDecorator    (timing + metrics → ProgressObserver)
        → RetryDecorator  (backoff 1s/2s/4s + jitter, max 3 retries)
            → AnthropicAdapter  (streaming HTTP via httpx, 10 connection pool)
                → Claude API (Opus 4.7)
```

| Layer | Class | File | Responsibility |
|-------|-------|------|----------------|
| Outermost | `LoggingDecorator` | `logging_decorator.py:39` | Logs model, duration, token count; sanitizes secrets |
| Middle | `RetryDecorator` | `retry_decorator.py:21` | Exponential backoff with jitter; only retries `SpectraRetryError(retryable=True)` |
| Innermost | `AnthropicAdapter` | `anthropic_adapter.py:49` | Streaming HTTP calls; sets `output_config.effort` and `task_budget` (when supplied); maps SDK exceptions to SPEC-002/003 |

All three satisfy `LLMGateway` Protocol via structural subtyping — no explicit inheritance. The factory holds a single reference to the outermost decorator. All 8 agents share this gateway instance.

**Wiring code** (`main.py:108-110`):
```python
adapter = AnthropicAdapter(api_key=api_key)
retry   = RetryDecorator(adapter, max_retries=3, backoff_base=1.0)
gateway = LoggingDecorator(retry, observer=observer)
```

### LLMGateway Protocol — Opus 4.7 surface

```python
class LLMGateway(Protocol):
    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,                # "low|medium|high|xhigh|max"
    ) -> str: ...

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        task_budget_tokens: int | None = None,    # min 20_000; activates beta header
    ) -> str: ...
```

Two breaking changes vs the pre-Opus-4.7 protocol:
- `temperature` removed entirely — Opus 4.7 rejects it (HTTP 400). Reasoning depth is steered exclusively by `effort`.
- `analyze_with_thinking` no longer takes `budget_tokens` (the deprecated per-call thinking budget); it now takes `task_budget_tokens` (the cumulative loop budget) which Anthropic gates behind the beta header `task-budgets-2026-03-13`.

`AnthropicAdapter` sets `thinking={"type": "adaptive", "display": "summarized"}` for `analyze_with_thinking` and packages `effort` / `task_budget` into `output_config` (see `anthropic_adapter.py:240-265`).

See [ADR-005](adr/ADR-005-opus-4-7-migration.md) for the migration rationale and per-agent effort tuning. See [`diagrams/lld-decorator-chain.md`](../diagrams/lld-decorator-chain.md) for the dedicated decorator-chain LLD.

---

## `CachePort` and `SqliteCacheAdapter`

### Port surface (`use_cases/interfaces.py`)

```python
class CachePort(Protocol):
    # Phase 1 — per-file row
    def get_findings(self, file_hash: str, dimension: Dimension) -> tuple[Finding, ...] | None: ...
    def put_findings(self, file_hash, dimension, findings, model_version, prompt_version) -> None: ...

    # Phase 2 — full report
    def get_full_report(self, key: RepoCacheKey) -> AnalysisReport | None: ...
    def put_full_report(self, key: RepoCacheKey, report: AnalysisReport) -> None: ...

    # Phase 3 — per-batch
    def get_batch_findings(self, key: BatchCacheKey) -> tuple[Finding, ...] | None: ...
    def put_batch_findings(self, key: BatchCacheKey, findings: tuple[Finding, ...]) -> None: ...

    # Phase 3 — run-context binding (atomic four-tuple)
    def bind_run_context(self, model_versions, prompt_versions, schema_version, spectra_version) -> None: ...
    def batch_key_for(self, batch_id: str, dimension: Dimension) -> BatchCacheKey | None: ...

    # Phase 3 — telemetry
    def record_hit(self, dimension: Dimension, batch_id: str, hit: bool) -> None: ...

    # Maintenance
    def compute_repo_signature(self, file_tree: tuple[str, ...]) -> str: ...
    def stats(self) -> CacheStats: ...
    def clear(self, repo_signature: str | None = None) -> int: ...
```

All methods are synchronous — the cache is local I/O, not networked. Lookups return `None` on miss rather than raising. Serious I/O failures raise `AgentError(SPEC-010)` so callers can degrade gracefully.

### Adapter (`infrastructure/cache_adapter.py`)

`SqliteCacheAdapter` opens a single SQLite connection at `${XDG_CACHE_HOME:-~/.cache}/spectra/cache.db`, sets `PRAGMA journal_mode=WAL`, and creates four tables idempotently (`CREATE TABLE IF NOT EXISTS`):

| Table | PK | Indexes | Notes |
|-------|----|---------|-------|
| `findings_cache` | `(file_hash, dimension, model_version, prompt_version, schema_version)` | `idx_repo`, `idx_age` | Phase 1 row format |
| `full_report_cache` | `(repo_signature, spectra_version, model_versions, prompt_versions, schema_version)` | — | Phase 2 short-circuit |
| `findings_batches` | `(batch_id, dimension, model_version, prompt_version, schema_version, spectra_version)` | — | Phase 3 per-batch |
| `hit_log` | (no PK; append-only) | — | Telemetry; Phase 4 will add `dimension`, `batch_id` columns |

Every fallible I/O is wrapped in `_guard_io()`, which converts `sqlite3.Error` and `OSError` into `AgentError(SPEC-010)`.

### Invalidation matrix

| Trigger | Detection | Tables affected | Scope |
|---------|-----------|-----------------|-------|
| `--force` | CLI: `force_cache_bypass=True` | All reads bypassed; writes still occur | Whole run |
| `--no-cache` | Composition root: `cache_port=None` | All reads + writes skipped | Whole run |
| `spectra.__version__` bump | `spectra_version` in key differs | `full_report_cache`, `findings_batches` | Whole repo |
| Model version change | `model_version` in key differs | All findings tables | Per dimension (or whole repo for full-report) |
| Prompt version bump | `prompt_version` in key differs | All findings tables | Per dimension |
| Schema version bump | `SchemaVersion` literal in key differs | All findings tables | Whole repo |
| File content change | `blake2b(file)` differs → new `file_hash` / `batch_id` | `findings_cache`, `findings_batches` | Per file (and its batch) |
| File deleted | `repo_signature` changes | `full_report_cache` | Whole repo |
| Row >N days old | `computed_at < now - N` | All findings tables | Per row (lazy GC, Phase 4 `prune`) |

Stale rows are never matched by current-context lookups; physical deletion is deferred to `spectra cache prune` (Phase 4 — in flight, see PR #19).

### Cache CLI subcommands (Phase 4 — in flight)

```bash
spectra cache stats                      # show CacheStats: total_entries, total_repos,
                                          #   db_size_bytes, hit_rate_last_100, oldest_entry_at
spectra cache clear [<repo>]             # purge one repo (by URL or signature) or all
spectra cache prune --older-than 30d     # delete rows where computed_at < now - N
```

These land with PR #19. The `hit_log` table will gain `dimension` and `batch_id` columns to support per-dimension hit-rate breakdowns. The `bind_run_context` API and `record_hit` calls already in flight on every cache lookup require no changes — Phase 4 is purely additive in scope.

> Cache subsystem deep-dive: [`diagrams/cache-architecture.md`](../diagrams/cache-architecture.md) · [`diagrams/excalidraw/cache-schema.excalidraw`](../diagrams/excalidraw/cache-schema.excalidraw)
> ADRs: [ADR-006](adr/ADR-006-cache-port-incremental-analysis.md) · [ADR-009](adr/ADR-009-batch-granularity-per-focus-area.md)

---

## `GitPort.prepare_workspace` (local-path branch)

```python
class GitPort(Protocol):
    async def prepare_workspace(self, source: str, target_dir: str) -> str:
        """Resolve source into a usable on-disk repository directory.

        For HTTPS URLs, clones into target_dir and returns it.
        For local paths, validates the directory holds a git checkout
        and returns its absolute path (target_dir is ignored).
        """
```

`is_local_path(source)` (also exported from `interfaces.py`) is the pure classifier the adapter and the CLI controller share. Local paths are anything starting with `/`, `./`, `../`, `~`, `file://`, or the literal `.`, plus relative names that resolve to existing directories. Remote schemes (`https://`, `git@`, `ssh://`, `git://`) are always classified as non-local.

`GitAdapter.prepare_workspace` rejects path-traversal segments, symlinked directories, and paths missing a `.git/` subdirectory — the same security envelope as `clone()`.

---

## Agent Template Method Lifecycle

Every agent follows the same lifecycle defined in `BaseAgent.run()` at `base_agent.py:58-79`:

```
validate_input(prompt)     →  Check non-empty input
    → build_prompt(prompt) →  Construct system + user prompts
    → execute_llm(prompt)  →  Call gateway.analyze() or analyze_with_thinking()
    → parse_output(raw)    →  Extract JSON from LLM response
    → validate_output(parsed) →  Pydantic validation of findings
    → format_result(...)   →  Build AgentOutput value object
```

Each subclass overrides specific steps:

| Agent | Overrides | Key Difference |
|-------|-----------|----------------|
| `MetaPrompter` | `validate_input`, `build_prompt`, `validate_output` | Validates plan JSON keys, never returns findings |
| `SpecialistAgent` | `validate_input`, `build_prompt`, `validate_output` | Filters findings below MIN_CONFIDENCE (0.7) |
| `CritiqueAgent` | `validate_input`, `build_prompt`, `execute_llm`, `validate_output` | Overrides `execute_llm` to use `analyze_with_thinking` |

> Agent lifecycle state diagram: [`diagrams/state-agent-lifecycle.md`](../diagrams/state-agent-lifecycle.md)

---

## Parallel Execution Model

`orchestrate_agents.py` runs the 6 specialists concurrently — but only on the **fresh** batches after `partition_by_cache` has split out the cached findings:

```python
# Simplified — full code in analyze_repository.py and orchestrate_agents.py
async def run_specialists(agents, prompts, timeout=120):
    sem = asyncio.Semaphore(4)  # max 4 concurrent API calls

    async def run_one(agent, prompt):
        async with sem:
            return await asyncio.wait_for(agent.run(prompt), timeout=timeout)

    results = await asyncio.gather(
        *[run_one(a, p) for a, p in zip(agents, prompts)],
        return_exceptions=True
    )
    return results
```

**Key constraints:**
- `Semaphore(4)` limits concurrent API calls to avoid 429 rate limits
- `wait_for(timeout=120)` per agent — individual timeout doesn't cancel siblings
- `return_exceptions=True` — failures are captured, not propagated
- `evaluate_results()` counts failures: 0-1 → merging, 2+ → degraded
- Phase 3 packs the `BatchPrompt` text into the existing prompt slot — the agent itself doesn't know about batches

> Parallel execution diagram: [`diagrams/state-agent-lifecycle.md`](../diagrams/state-agent-lifecycle.md) (Specialist Agent section)

---

## Data Flow Through Pipeline

### Stage 1: INGEST

```
source → git.prepare_workspace() → repo_dir
    → git.validate_repo_size() → git.get_file_tree()
    → _read_key_source_files(top 20 files, ≤100K tokens) → Codebase
```

`prepare_workspace` is the polymorphic entrypoint: HTTPS URLs trigger `clone(...)`, local paths get validated and returned in place.

**File selection heuristic** (`main.py`):
1. Priority files: `README.md`, `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`
2. Source files sorted by path depth (shallow first), then alphabetically
3. Each file read up to 1MB, total capped at 100K tokens
4. Maximum 20 files selected

### Stage 2: PLAN

```
Codebase.file_tree (text) → MetaPrompter.run() → AgentOutput
    → extract plan JSON: {repo_language, focus_areas[], token_allocation{}}
    → allocate_specialist_budgets() → dict[Dimension, int]
```

MetaPrompter receives **file tree only** (never source code). Max 5K tokens. Uses **Opus 4.7 with `effort=medium`** — planning is structured JSON extraction, not deep reasoning, so the medium-effort setting keeps latency and cost low while still benefiting from Opus 4.7's instruction following.

### Stage 2½: CACHE (Phase 2 short-circuit)

```
key = RepoCacheKey(
    repo_signature=cache.compute_repo_signature(file_tree),
    spectra_version=spectra.__version__,
    model_versions=...,
    prompt_versions=...,
    schema_version="v1",
)
if not force_cache_bypass:
    cached = cache.get_full_report(key)
    if cached is not None:
        return cached    # short-circuit — Stages 3-5 skipped, Stage 6 still renders
```

### Stage 3: ANALYZE (Phase 3 per-batch caching)

```
plan + source_files → build_batch_prompts(plan)
    → dict[AgentRole, list[BatchPrompt]]    # one batch per focus_area, fallback: 1 per dim

for spec in specialists:
    cached_per_role[role], fresh_per_role[role] = partition_by_cache(batches, cache, dim)

run_specialists(agents, fresh batches only, timeout=120s)
    → asyncio.gather → AgentOutput per fresh batch

for each (role, batch, fresh_findings):
    cache.put_batch_findings(BatchCacheKey, fresh_findings)

_assemble_phase3_result: merge cached + fresh findings per role
evaluate_results: → (successes, failed_roles, PipelineState)
```

Each specialist receives: filtered file tree + plan context + relevant source code. All six run **Opus 4.7 with `effort=xhigh`** (Anthropic's recommended setting for coding/agentic workloads).

### Stage 4: MERGE

```
successes → _merge_findings() → dict.fromkeys dedup via Finding.__hash__
    → _validate_finding_paths(findings, file_tree) → remove hallucinated paths
    → tuple[Finding, ...] (deduplicated, path-validated)
```

**Finding deduplication**: Two `Finding` objects are equal when they share `(file_path, line_start, dimension)`. Enforced by `Finding.__hash__` and `__eq__` at `models.py:83-95`. Dedup uses `dict.fromkeys()` for O(n) single-pass with insertion-order preservation. Cached findings and fresh findings flow through the same deduplication.

**Hallucination detection**: `_validate_finding_paths()` checks every `finding.location.file_path` against the actual file tree. Findings referencing non-existent files are removed. Count tracked in `AnalysisReport.hallucination_removed_count`.

### Stage 5: CRITIQUE

```
findings_json → _should_run_critique() → if eligible:
    CritiqueAgent.run(findings_json) → critique JSON
    → _apply_critique(): reject FPs + adjust severities
    → _extract_cross_cutting_insights()
    → (filtered_findings, insights)
```

**Skip conditions**: `--quick` flag, degraded state (2+ failures), no budget remaining.

CritiqueAgent uses **Opus 4.7 with adaptive thinking** (`thinking={"type": "adaptive", "display": "summarized"}`), `effort="high"`, `max_tokens=64_000`, and `task_budget_tokens=80_000` (beta header `task-budgets-2026-03-13`). The `task_budget` is a hard cumulative cap on thinking + output tokens — the model decides how to split between deeper reasoning and longer output, but the total cannot exceed the budget. `display: "summarized"` keeps the SDK from streaming raw chain-of-thought back to the client, so the parser only sees the final answer. Target: <5% false positive rate.

See [ADR-008](adr/ADR-008-adaptive-thinking-supersedes-extended.md) for the terminology change ("extended" → "adaptive" thinking) and the rationale for `task_budget` over the deprecated `budget_tokens`.

### Stage 6: REPORT (with Phase 2 cache write-back)

```
findings + ScoreCard → AnalysisReport
    → if cache_port: cache.put_full_report(RepoCacheKey, report)
    → HTML: ReportAdapter.render() (Jinja2 template)
    → JSON: json.dumps(report.model_dump())
    → SARIF: _build_sarif() (SARIF v2.1.0)
```

> Full data flow diagram: [`diagrams/lld-data-flow.md`](../diagrams/lld-data-flow.md)
> Full sequence diagram (with cache decision points): [`diagrams/sequence-analysis-pipeline.md`](../diagrams/sequence-analysis-pipeline.md)

---

## Error Codes

| Code | Category | Retryable | Max Retries | Description |
|------|----------|-----------|-------------|-------------|
| SPEC-001 | Git | Yes | 2 | Git clone failed |
| SPEC-002 | API | Yes | 3 | Anthropic API unreachable |
| SPEC-003 | Rate Limit | Yes | 3 | Anthropic 429 rate limited |
| SPEC-004 | Budget | No | — | Token budget exceeded |
| SPEC-005 | Validation | Yes | 1 | Agent output failed Pydantic validation |
| SPEC-006 | Timeout | No | — | Agent exceeded 120s timeout |
| SPEC-007 | Pipeline | No | — | 2+ agents failed |
| SPEC-008 | Critique | No | — | CritiqueAgent failed (fallback: raw findings) |
| SPEC-009 | Report | No | — | Template render failed |
| SPEC-010 | Cache | No (degrade) | — | Cache I/O failed — pipeline degrades to no-cache for the rest of the run |

All errors are instances of `SpectraError` (frozen dataclass) with `retryable` and `max_retries` metadata. The `RetryDecorator` at `retry_decorator.py:91-94` inspects `exc.error.retryable` before deciding to retry or propagate. Cache errors (SPEC-010) are caught at the call site and never propagate to the user.

**Error class hierarchy**:
- `AgentError(Exception)` — carries `SpectraError`, raised by agents and the cache adapter
- `GitError(Exception)` — carries `SpectraError`, raised by `GitAdapter`
- `SpectraRetryError(Exception)` — carries `SpectraError`, caught by `RetryDecorator`

> State transitions on error: [`diagrams/state-pipeline.md`](../diagrams/state-pipeline.md)
> Error path sequence: [`diagrams/sequence-analysis-pipeline.md`](../diagrams/sequence-analysis-pipeline.md) (Error Path + SPEC-010 sections)

---

## Token Budget Management

| Pool | Tokens | Allocation Strategy |
|------|--------|-------------------|
| **Total** | 800,000 | Fixed per analysis run |
| **MetaPrompter** | 5,000 | Fixed — file tree only, no source code |
| **Specialists** | 500,000 | Distributed by dimension weight |
| **Critique** | 200,000 | Reserved — used only if eligible |
| **Buffer** | 95,000 | Safety margin for overhead |

**Specialist allocation** (`manage_token_budget.py`):
```
Architecture: 500,000 × 0.25 = 125,000 tokens
Security:     500,000 × 0.25 = 125,000 tokens
Quality:      500,000 × 0.20 = 100,000 tokens
Documentation: 500,000 × 0.10 = 50,000 tokens
Maintainability: 500,000 × 0.10 = 50,000 tokens
Performance:  500,000 × 0.10 = 50,000 tokens
```

Token counting uses tiktoken's `cl100k_base` encoding via `TiktokenAdapter` with hash-based caching for O(1) repeat lookups. On a warm-cache run only the fresh batches consume specialist budget.

---

## Git Security Hardening

`GitAdapter` at `git_adapter.py` implements 8 layers of security across both `clone()` and `prepare_workspace()`:

| Layer | Protection | Limit |
|-------|-----------|-------|
| 1. Protocol | HTTPS only | Rejects `git://`, `ssh://`, `file://` |
| 2. SSRF | `_is_private_ip()` check | Blocks RFC 1918, loopback, link-local |
| 3. URL | Length cap | 2,048 characters max |
| 4. Path traversal | Path sanitization | Blocks `../`, absolute path injection in source |
| 5. Symlinks | Symlink blocking | Rejects symlinked directories (local-path branch too) |
| 6. Size | File and repo limits | 10K files, 100MB total, 1MB per file |
| 7. Clone | Hardened git clone | `depth=1`, hooks disabled, no submodules, 60s timeout |
| 8. Read | Read timeout | 5 seconds per file |

`prepare_workspace` for local paths goes through layers 4, 5, 6, 8 — protocol/SSRF/URL/clone don't apply.

---

## Report Generation

The HTML report (`templates/report.html.j2`) rendered by `ReportAdapter` includes:

| Section | Content |
|---------|---------|
| ScoreCard | Overall grade, dimension scores, weighted percentages |
| Findings | Grouped by dimension, sorted by severity, code snippets |
| Compliance | OWASP Top 10 (2021+2025), SOC 2 CC1-CC9, PCI DSS 4.0, NIST CSF 2.0 |
| ROI Calculator | Spectra cost vs manual review ($175/hr x 4hrs = $700) |
| Investment Readiness | Weighted composite of 8 due diligence metrics |
| Issue Concentration | Gini coefficient for finding distribution |
| Dependencies | License compliance, complexity indicators, risk scoring |

---

## Port/Adapter Mapping

| Port (Layer 2) | Adapter (Layer 3/4) | Protocol Methods |
|----------------|-------------------|-----------------|
| `LLMGateway` | `AnthropicAdapter` | `analyze(... effort=)`, `analyze_with_thinking(... effort=, task_budget_tokens=)` |
| `GitPort` | `GitAdapter` | `prepare_workspace()`, `clone()`, `get_file_tree()`, `read_file()`, `validate_repo_size()` |
| `TokenPort` | `TiktokenAdapter` | `count()`, `fits_budget()` |
| `ReportPort` | `ReportAdapter` | `render()` |
| `ProgressObserver` | `RichProgressReporter` | `on_stage_start()`, `on_stage_complete()`, `on_agent_*()`, `on_error()`, `on_cache_lookup()` |
| `AnalysisAgent` | `BaseAgent` subclasses | `run()`, `role` property |
| `CachePort` | `SqliteCacheAdapter` | `get/put_findings()`, `get/put_full_report()`, `get/put_batch_findings()`, `bind_run_context()`, `batch_key_for()`, `record_hit()`, `compute_repo_signature()`, `stats()`, `clear()` |

All ports use Python's `Protocol` (PEP 544) for structural subtyping — adapters satisfy ports by having matching method signatures, no explicit inheritance required.

> Class diagram: [`diagrams/class-domain-model.md`](../diagrams/class-domain-model.md)
> ER diagram: [`diagrams/er-domain-entities.md`](../diagrams/er-domain-entities.md)

---

## Domain Model

All domain entities are **frozen Pydantic models** (`frozen=True`):

| Entity | Key Fields | Hash/Eq | Notes |
|--------|-----------|---------|-------|
| `Finding` | id, dimension, severity, location, confidence | `(file_path, line_start, dimension)` | Hashable for O(n) dedup |
| `FileLocation` | file_path, line_start, line_end | Default | |
| `DimensionScore` | dimension, score, grade, weight | Default | |
| `ScoreCard` | overall_score, overall_grade, dimensions | Default | |
| `AgentOutput` | agent_role, findings, tokens_used, duration | Default | |
| `AnalysisReport` | score_card, findings, is_degraded, insights | Default | Cached as `report_json` in `full_report_cache` |
| `Codebase` | repo_url, repo_name, file_tree | Default | `local_path` is the absolute repo dir from `prepare_workspace` |
| `TokenBudget` | total=800K, meta=5K, specialists=500K, critique=200K | Default | |
| `CacheEntry` | file_hash, file_path, dimension, findings, model_version, prompt_version, spectra_version, schema_version, computed_at | Default | One row in `findings_cache` |
| `CacheStats` | total_entries, total_repos, db_size_bytes, hit_rate_last_100, oldest_entry_at | Default | Surfaced by `spectra cache stats` |
| `BatchPrompt` | batch_id, file_paths, file_hashes, prompt_text | Default | Phase 3 batch unit |
| `BatchCacheKey` | batch_id, dimension, model_version, prompt_version, schema_version, spectra_version | Default | Composite key for `findings_batches` |
| `RepoCacheKey` | repo_signature, spectra_version, model_versions, prompt_versions, schema_version | Default | Composite key for `full_report_cache` |

Immutability guarantees:
- Thread safety across parallel agent execution
- Hashable findings for O(n) deduplication
- No accidental mutation between pipeline stages
- `model_copy(update={...})` for severity adjustments in critique stage

> Domain model diagram: [`diagrams/class-domain-model.md`](../diagrams/class-domain-model.md)

---

*See [HLD.md](HLD.md) for system-level architecture, design decisions, and technology stack.*

---

*Last updated: 2026-04-29 — `CachePort` and `SqliteCacheAdapter` documented (Phases 1-3 shipped, Phase 4 in flight); `GitPort.prepare_workspace` for local paths; `PipelineContext` value object; `ProgressObserver.on_cache_lookup` hook; SPEC-010 added.*
