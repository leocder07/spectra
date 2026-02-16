# Low-Level Design (LLD)

> Component-level implementation details for Spectra's 8-agent analysis pipeline.
> Every file:line reference points to actual source code.

---

## Component Catalog

### Layer 1 — Entities (zero spectra imports)

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `entities/models.py` | Frozen Pydantic domain models | `Finding`, `ScoreCard`, `AnalysisReport`, `Codebase`, `TokenBudget`, `AgentOutput` |
| `entities/enums.py` | Literal type aliases | `Severity`, `Dimension`, `Grade`, `AgentRole`, `PipelineState` |
| `entities/errors.py` | Structured error hierarchy | `SpectraError`, `ERRORS` registry, `AgentError`, `GitError`, `SpectraRetryError` |

### Layer 2 — Use Cases (imports entities only)

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `use_cases/interfaces.py` | Protocol interfaces (ports) | `LLMGateway`, `GitPort`, `TokenPort`, `ReportPort`, `ProgressObserver` |
| `use_cases/analyze_repository.py` | 6-stage pipeline facade | `analyze_repository()` (~998 lines) |
| `use_cases/orchestrate_agents.py` | Parallel agent execution | `run_specialists()`, `evaluate_results()` |
| `use_cases/manage_token_budget.py` | Token budget allocation | `allocate_specialist_budgets()`, `DIMENSION_WEIGHTS` |

### Layer 3 — Adapters (imports entities + use_cases)

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `adapters/cli_controller.py` | Typer CLI entry point | `app`, `analyze` command |
| `adapters/progress_reporter.py` | Rich terminal progress | `RichProgressReporter` (implements `ProgressObserver`) |
| `adapters/analysis_presenter.py` | ScoreCard terminal display | `AnalysisPresenter` |

### Layer 4 — Infrastructure (imports all inner layers)

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `infrastructure/main.py` | Composition root (DI wiring) | `_run_analysis()`, `cli()` |
| `infrastructure/anthropic_adapter.py` | Anthropic API client | `AnthropicAdapter` (implements `LLMGateway`) |
| `infrastructure/retry_decorator.py` | Exponential backoff | `RetryDecorator` (implements `LLMGateway`) |
| `infrastructure/logging_decorator.py` | Call metrics logging | `LoggingDecorator` (implements `LLMGateway`) |
| `infrastructure/git_adapter.py` | Git operations + security | `GitAdapter` (implements `GitPort`) |
| `infrastructure/tiktoken_adapter.py` | Token counting | `TiktokenAdapter` (implements `TokenPort`) |
| `infrastructure/report_adapter.py` | Jinja2 HTML rendering | `ReportAdapter` (implements `ReportPort`) |
| `infrastructure/agents/base_agent.py` | ABC Template Method | `BaseAgent` |
| `infrastructure/agents/agent_factory.py` | Agent creation dispatch | `AgentFactory` |
| `infrastructure/agents/meta_prompter.py` | Planning agent | `MetaPrompter` |
| `infrastructure/agents/specialist_agent.py` | Parameterized specialist | `SpecialistAgent` |
| `infrastructure/agents/specialist_prompts.py` | System prompts (6 dimensions) | `SPECIALIST_CONFIGS` |
| `infrastructure/agents/critique_agent.py` | Validation agent | `CritiqueAgent` |

> Component interaction diagram: [`diagrams/lld-component-interaction.md`](../diagrams/lld-component-interaction.md)

---

## Decorator Chain

All LLM calls flow through a 3-layer decorator chain wired at `main.py:108-110`:

```
Agent.execute_llm()
    → LoggingDecorator    (timing + metrics → ProgressObserver)
        → RetryDecorator  (backoff 1s/2s/4s + jitter, max 3 retries)
            → AnthropicAdapter  (streaming HTTP via httpx, 10 connection pool)
                → Claude API
```

| Layer | Class | File | Responsibility |
|-------|-------|------|----------------|
| Outermost | `LoggingDecorator` | `logging_decorator.py:39` | Logs model, duration, token count; sanitizes secrets |
| Middle | `RetryDecorator` | `retry_decorator.py:21` | Exponential backoff with jitter; only retries `SpectraRetryError(retryable=True)` |
| Innermost | `AnthropicAdapter` | `anthropic_adapter.py:49` | Streaming HTTP calls; maps SDK exceptions to SPEC-002/003 |

All three satisfy `LLMGateway` Protocol via structural subtyping — no explicit inheritance. The factory holds a single reference to the outermost decorator. All 8 agents share this gateway instance.

**Wiring code** (`main.py:108-110`):
```python
adapter = AnthropicAdapter(api_key=api_key)
retry   = RetryDecorator(adapter, max_retries=3, backoff_base=1.0)
gateway = LoggingDecorator(retry, observer=observer)
```

> Decorator diagrams: [`diagrams/design-patterns-catalog.md`](../diagrams/design-patterns-catalog.md) (Pattern #2)

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

`orchestrate_agents.py` runs 6 specialists concurrently:

```python
# orchestrate_agents.py — simplified
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

> Parallel execution diagram: [`diagrams/state-agent-lifecycle.md`](../diagrams/state-agent-lifecycle.md) (Specialist Agent section)

---

## Data Flow Through Pipeline

### Stage 1: INGEST

```
repo_url → git.clone() → git.validate_repo_size() → git.get_file_tree()
    → _read_key_source_files(top 20 files, ≤100K tokens) → Codebase
```

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

MetaPrompter receives **file tree only** (never source code). Max 5K tokens. Uses Sonnet 4.5 for cost efficiency since planning doesn't need deep reasoning.

### Stage 3: ANALYZE

```
plan + source_files → _build_specialist_prompts() → 6 prompts
    → orchestrate_agents.run_specialists() → 6x AgentOutput (or Exception)
    → evaluate_results() → (successes[], failed_roles[], PipelineState)
```

Each specialist receives: filtered file tree + plan context + relevant source code. All use Opus 4.6.

### Stage 4: MERGE

```
successes → _merge_findings() → dict.fromkeys dedup via Finding.__hash__
    → _validate_finding_paths(findings, file_tree) → remove hallucinated paths
    → tuple[Finding, ...] (deduplicated, path-validated)
```

**Finding deduplication**: Two `Finding` objects are equal when they share `(file_path, line_start, dimension)`. Enforced by `Finding.__hash__` and `__eq__` at `models.py:83-95`. Dedup uses `dict.fromkeys()` for O(n) single-pass with insertion-order preservation.

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

CritiqueAgent uses adaptive thinking (Opus 4.6). Target: <5% false positive rate. Returns: `validated_findings[]`, `rejected_findings[]`, `severity_adjustments[]`, `cross_cutting_insights[]`.

### Stage 6: REPORT

```
findings + ScoreCard → AnalysisReport
    → HTML: ReportAdapter.render() (Jinja2 template)
    → JSON: json.dumps(report.model_dump())
    → SARIF: _build_sarif() (SARIF v2.1.0)
```

> Full data flow diagram: [`diagrams/lld-data-flow.md`](../diagrams/lld-data-flow.md)
> Full sequence diagram: [`diagrams/sequence-analysis-pipeline.md`](../diagrams/sequence-analysis-pipeline.md)

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

All errors are instances of `SpectraError` (frozen dataclass) with `retryable` and `max_retries` metadata. The `RetryDecorator` at `retry_decorator.py:91-94` inspects `exc.error.retryable` before deciding to retry or propagate.

**Error class hierarchy**:
- `AgentError(Exception)` — carries `SpectraError`, raised by agents
- `GitError(Exception)` — carries `SpectraError`, raised by `GitAdapter`
- `SpectraRetryError(Exception)` — carries `SpectraError`, caught by `RetryDecorator`

> State transitions on error: [`diagrams/state-pipeline.md`](../diagrams/state-pipeline.md)
> Error path sequence: [`diagrams/sequence-analysis-pipeline.md`](../diagrams/sequence-analysis-pipeline.md) (Error Path section)

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

Token counting uses tiktoken's `cl100k_base` encoding via `TiktokenAdapter` with hash-based caching for O(1) repeat lookups.

---

## Git Security Hardening

`GitAdapter` at `git_adapter.py` implements 8 layers of security:

| Layer | Protection | Limit |
|-------|-----------|-------|
| 1. Protocol | HTTPS only | Rejects `git://`, `ssh://`, `file://` |
| 2. SSRF | `_is_private_ip()` check | Blocks RFC 1918, loopback, link-local |
| 3. URL | Length cap | 2,048 characters max |
| 4. Path traversal | Path sanitization | Blocks `../`, absolute paths |
| 5. Symlinks | Symlink blocking | Rejects symlinked files |
| 6. Size | File and repo limits | 10K files, 100MB total, 1MB per file |
| 7. Clone | Hardened git clone | `depth=1`, hooks disabled, no submodules, 60s timeout |
| 8. Read | Read timeout | 5 seconds per file |

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
| `LLMGateway` | `AnthropicAdapter` | `analyze()`, `analyze_with_thinking()` |
| `GitPort` | `GitAdapter` | `clone()`, `get_file_tree()`, `read_file()`, `validate_repo_size()` |
| `TokenPort` | `TiktokenAdapter` | `count()`, `fits_budget()` |
| `ReportPort` | `ReportAdapter` | `render()` |
| `ProgressObserver` | `RichProgressReporter` | `on_stage_start()`, `on_stage_complete()`, `on_agent_*()`, `on_error()` |
| `AnalysisAgent` | `BaseAgent` subclasses | `run()`, `role` property |

All ports use Python's `Protocol` (PEP 544) for structural subtyping — adapters satisfy ports by having matching method signatures, no explicit inheritance required.

> Class diagram: [`diagrams/class-domain-model.md`](../diagrams/class-domain-model.md)
> ER diagram: [`diagrams/er-domain-entities.md`](../diagrams/er-domain-entities.md)

---

## Domain Model

All domain entities are **frozen Pydantic models** (`frozen=True`):

| Entity | Key Fields | Hash/Eq |
|--------|-----------|---------|
| `Finding` | id, dimension, severity, location, confidence | `(file_path, line_start, dimension)` |
| `FileLocation` | file_path, line_start, line_end | Default |
| `DimensionScore` | dimension, score, grade, weight | Default |
| `ScoreCard` | overall_score, overall_grade, dimensions | Default |
| `AgentOutput` | agent_role, findings, tokens_used, duration | Default |
| `AnalysisReport` | score_card, findings, is_degraded, insights | Default |
| `Codebase` | repo_url, repo_name, file_tree | Default |
| `TokenBudget` | total=800K, meta=5K, specialists=500K, critique=200K | Default |

Immutability guarantees:
- Thread safety across parallel agent execution
- Hashable findings for O(n) deduplication
- No accidental mutation between pipeline stages
- `model_copy(update={...})` for severity adjustments in critique stage

> Domain model diagram: [`diagrams/class-domain-model.md`](../diagrams/class-domain-model.md)

---

*See [HLD.md](HLD.md) for system-level architecture, design decisions, and technology stack.*
