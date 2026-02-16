# Design Patterns Catalog — Spectra

> Every pattern documented here is traced from the actual source code.
> File:line references point to real implementations.

---

## Patterns Overview

All 11 patterns and how they connect across Spectra's Clean Architecture layers:

```mermaid
graph TB
    subgraph "Layer 1 — Entities"
        VO["Value Object<br/>(frozen Pydantic models)"]
        ET["Error Taxonomy<br/>(SpectraError + ERRORS registry)"]
    end

    subgraph "Layer 2 — Use Cases"
        FA["Facade<br/>(analyze_repository)"]
        PA["Port/Adapter<br/>(Protocol interfaces)"]
        OB["Observer<br/>(ProgressObserver)"]
        PR["Protocol<br/>(AnalysisAgent)"]
    end

    subgraph "Layer 3 — Adapters"
        OBI["Observer Impl<br/>(RichProgressReporter)"]
    end

    subgraph "Layer 4 — Infrastructure"
        TM["Template Method<br/>(BaseAgent)"]
        DE["Decorator<br/>(Logging + Retry)"]
        AD["Adapter<br/>(AnthropicAdapter)"]
        FC["Factory<br/>(AgentFactory)"]
        ST["Strategy<br/>(specialist_prompts)"]
        CR["Composition Root<br/>(main.py)"]
    end

    CR -->|"wires"| DE
    CR -->|"creates"| FC
    FC -->|"produces"| TM
    TM -->|"uses"| DE
    DE -->|"wraps"| AD
    AD -->|"implements"| PA
    TM -->|"parameterized by"| ST
    FA -->|"orchestrates"| TM
    FA -->|"notifies"| OB
    OBI -->|"implements"| OB
    TM -->|"returns"| VO
    DE -->|"throws"| ET
    PR -->|"abstracts"| TM

    classDef entities fill:#7C3AED,color:#fff,stroke:#5B21B6
    classDef usecases fill:#F59E0B,color:#000,stroke:#D97706
    classDef adapters fill:#22C55E,color:#000,stroke:#16A34A
    classDef infra fill:#3B82F6,color:#fff,stroke:#2563EB

    class VO,ET entities
    class FA,PA,OB,PR usecases
    class OBI adapters
    class TM,DE,AD,FC,ST,CR infra
```

---

## 1. Template Method

**GoF Category:** Behavioral

**Why chosen:** All 8 agents share the same lifecycle (validate, build prompt, call LLM, parse, validate output, format) but differ in specific steps. Template Method eliminates duplication while enforcing a consistent pipeline.

**Implementation:** `src/spectra/infrastructure/agents/base_agent.py:23-147`

```mermaid
classDiagram
    class BaseAgent {
        <<abstract>>
        #_role: AgentRole
        #_gateway: LLMGateway
        #_model: str
        #_system_prompt: str
        #_max_tokens: int
        +run(user_prompt: str) AgentOutput
        +validate_input(user_prompt: str)* void
        +build_prompt(user_prompt: str)* str
        +execute_llm(prompt: str) str
        +parse_output(raw: str) dict
        +validate_output(parsed: dict)* tuple~Finding~
        +format_result(...) AgentOutput
    }

    class MetaPrompter {
        +validate_input(user_prompt: str) void
        +build_prompt(user_prompt: str) str
        +validate_output(parsed: dict) tuple~Finding~
    }

    class SpecialistAgent {
        -_dimension: Dimension
        -_id_prefix: str
        +validate_input(user_prompt: str) void
        +build_prompt(user_prompt: str) str
        +validate_output(parsed: dict) tuple~Finding~
    }

    class CritiqueAgent {
        +validate_input(user_prompt: str) void
        +build_prompt(user_prompt: str) str
        +execute_llm(prompt: str) str
        +validate_output(parsed: dict) tuple~Finding~
    }

    BaseAgent <|-- MetaPrompter
    BaseAgent <|-- SpecialistAgent
    BaseAgent <|-- CritiqueAgent

    note for BaseAgent "run() is the template method:\nvalidate_input → build_prompt →\nexecute_llm → parse_output →\nvalidate_output → format_result\n(base_agent.py:58-79)"
```

The `run()` method at line 58 defines the invariant algorithm. Subclasses override only what varies:
- **MetaPrompter** (`meta_prompter.py:127`) — validates plan JSON keys, never returns findings
- **SpecialistAgent** (`specialist_agent.py:17`) — filters findings by MIN_CONFIDENCE threshold
- **CritiqueAgent** (`critique_agent.py:127`) — overrides `execute_llm` to use `analyze_with_thinking`

---

## 2. Decorator (Structural)

**GoF Category:** Structural

**Why chosen:** LLM calls need retry logic and observability, but these concerns must remain separate from the API adapter itself. Decorator allows composing behaviors without modifying `AnthropicAdapter`.

**Implementation:**
- `src/spectra/infrastructure/logging_decorator.py:39-103`
- `src/spectra/infrastructure/retry_decorator.py:21-99`

```mermaid
classDiagram
    class LLMGateway {
        <<Protocol>>
        +analyze(system_prompt, user_prompt, model, max_tokens) str
        +analyze_with_thinking(system_prompt, user_prompt, model, max_tokens) str
    }

    class AnthropicAdapter {
        -_client: AsyncAnthropic
        -_last_usage: tuple~int, int~
        +analyze(...) str
        +analyze_with_thinking(...) str
        +close() void
    }

    class RetryDecorator {
        -_inner: LLMGateway
        -_max_retries: int
        -_backoff_base: float
        +analyze(...) str
        +analyze_with_thinking(...) str
        -_retry(fn, **kwargs) str
    }

    class LoggingDecorator {
        -_inner: LLMGateway
        -_observer: ProgressObserver
        +analyze(...) str
        +analyze_with_thinking(...) str
        -_log_call(model, start) void
    }

    LLMGateway <|.. AnthropicAdapter : implements
    LLMGateway <|.. RetryDecorator : implements
    LLMGateway <|.. LoggingDecorator : implements
    LoggingDecorator o--> RetryDecorator : _inner
    RetryDecorator o--> AnthropicAdapter : _inner

    note for LoggingDecorator "Outermost: logs model,\nduration, tokens\n(logging_decorator.py:39)"
    note for RetryDecorator "Middle: exponential backoff\n1s → 2s → 4s with jitter\n(retry_decorator.py:21)"
    note for AnthropicAdapter "Innermost: actual\nHTTP streaming calls\n(anthropic_adapter.py:49)"
```

The chain is wired at `main.py:108-110`:
```python
adapter = AnthropicAdapter(api_key=api_key)
retry   = RetryDecorator(adapter, max_retries=3, backoff_base=1.0)
gateway = LoggingDecorator(retry, observer=observer)
```

All three satisfy `LLMGateway` via Python's structural subtyping (Protocol compliance) — no explicit inheritance required.

---

## 3. Adapter

**GoF Category:** Structural

**Why chosen:** The Anthropic SDK has its own API surface (`AsyncAnthropic`, streaming events, exception types). The Adapter translates this into Spectra's `LLMGateway` protocol while mapping SDK exceptions to domain error codes.

**Implementation:** `src/spectra/infrastructure/anthropic_adapter.py:49-258`

```mermaid
classDiagram
    class LLMGateway {
        <<Protocol>>
        +analyze(system_prompt, user_prompt, model, max_tokens) str
        +analyze_with_thinking(system_prompt, user_prompt, model, max_tokens) str
    }

    class AnthropicAdapter {
        -_client: AsyncAnthropic
        -_closed: bool
        -_last_usage: tuple~int, int~
        +analyze(...) str
        +analyze_with_thinking(...) str
        +close() void
        -_call_streaming(...) str
        -_call_with_thinking(...) str
        -_stream_thinking(...) Message
    }

    class AsyncAnthropic {
        <<Anthropic SDK>>
        +messages: Messages
        +close() void
    }

    class SpectraRetryError {
        +error: SpectraError
    }

    LLMGateway <|.. AnthropicAdapter : implements
    AnthropicAdapter --> AsyncAnthropic : wraps
    AnthropicAdapter ..> SpectraRetryError : throws

    note for AnthropicAdapter "Maps SDK exceptions:\nAPIConnectionError → SPEC-002\nRateLimitError → SPEC-003\nAuthenticationError → ValueError\n(anthropic_adapter.py:184-192)"
```

Key translations:
- `anthropic.APIConnectionError` → `SpectraRetryError(ERRORS["SPEC-002"])` (line 185)
- `anthropic.RateLimitError` → `SpectraRetryError(ERRORS["SPEC-003"])` (line 187)
- Streaming events are assembled into a single string response (lines 162-183)

---

## 4. Factory

**GoF Category:** Creational

**Why chosen:** The composition root needs to create all 8 agents without knowing their concrete constructors. The Factory centralizes creation logic and ensures all agents share the same decorated gateway.

**Implementation:** `src/spectra/infrastructure/agents/agent_factory.py:39-109`

```mermaid
classDiagram
    class AgentFactory {
        -_gateway: LLMGateway
        +create(role: AgentRole) BaseAgent
        +create_specialists() list~BaseAgent~
    }

    class BaseAgent {
        <<abstract>>
    }

    class MetaPrompter {
        model = "claude-sonnet-4-5-20250929"
        max_tokens = 5000
    }

    class SpecialistAgent {
        model = "claude-opus-4-6"
        max_tokens = 80000
    }

    class CritiqueAgent {
        model = "claude-opus-4-6"
        max_tokens = 16000
    }

    AgentFactory ..> MetaPrompter : creates
    AgentFactory ..> SpecialistAgent : creates (x6)
    AgentFactory ..> CritiqueAgent : creates
    BaseAgent <|-- MetaPrompter
    BaseAgent <|-- SpecialistAgent
    BaseAgent <|-- CritiqueAgent

    note for AgentFactory "Dispatch logic (agent_factory.py:67-90):\n'meta_prompter' → MetaPrompter\n'critique' → CritiqueAgent\nany specialist → SpecialistAgent\n  parameterized via SPECIALIST_CONFIGS"
```

Factory dispatch at `agent_factory.py:55-90`:
- `"meta_prompter"` → `MetaPrompter(gateway)` (Sonnet 4.5, 5K tokens)
- `"critique"` → `CritiqueAgent(gateway)` (Opus 4.6, extended thinking)
- Any of 6 specialist roles → `SpecialistAgent(role, gateway, **config)` from `SPECIALIST_CONFIGS`

---

## 5. Strategy

**GoF Category:** Behavioral

**Why chosen:** Six specialist agents share identical execution logic but differ only in their analysis dimension and system prompt. Strategy allows parameterizing a single `SpecialistAgent` class with dimension-specific behavior.

**Implementation:** `src/spectra/infrastructure/agents/specialist_prompts.py:739-746`

```mermaid
classDiagram
    class SpecialistAgent {
        -_dimension: Dimension
        -_id_prefix: str
        -_system_prompt: str
        +validate_input(prompt) void
        +build_prompt(prompt) str
        +validate_output(parsed) tuple~Finding~
    }

    class SPECIALIST_CONFIGS {
        <<dict: AgentRole → Config>>
        architecture: (dim, prefix, prompt, model)
        security: (dim, prefix, prompt, model)
        quality: (dim, prefix, prompt, model)
        documentation: (dim, prefix, prompt, model)
        dependency: (dim, prefix, prompt, model)
        performance: (dim, prefix, prompt, model)
    }

    class ArchitecturePrompt {
        <<strategy>>
        Focus: layering, deps, anti-patterns
    }

    class SecurityPrompt {
        <<strategy>>
        Focus: OWASP, CVE, injection, ASVS
    }

    class QualityPrompt {
        <<strategy>>
        Focus: complexity, tests, duplication
    }

    class DocumentationPrompt {
        <<strategy>>
        Focus: README, docstrings, ADRs
    }

    class DependencyPrompt {
        <<strategy>>
        Focus: CVEs, licenses, lock files
    }

    class PerformancePrompt {
        <<strategy>>
        Focus: N+1, async, caching, memory
    }

    SPECIALIST_CONFIGS --> ArchitecturePrompt
    SPECIALIST_CONFIGS --> SecurityPrompt
    SPECIALIST_CONFIGS --> QualityPrompt
    SPECIALIST_CONFIGS --> DocumentationPrompt
    SPECIALIST_CONFIGS --> DependencyPrompt
    SPECIALIST_CONFIGS --> PerformancePrompt
    SpecialistAgent ..> SPECIALIST_CONFIGS : parameterized by
```

The `SPECIALIST_CONFIGS` dict at `specialist_prompts.py:739-746` maps each `AgentRole` to a 4-tuple of `(dimension, id_prefix, system_prompt, model)`. The `AgentFactory` reads this config and passes it to `SpecialistAgent.__init__()`, making each instance behave differently based on its strategy.

---

## 6. Facade

**GoF Category:** Structural

**Why chosen:** The 6-stage analysis pipeline (Plan, Analyze, Merge, Critique, Report) involves complex coordination. The Facade provides a single entry point that hides orchestration complexity from callers.

**Implementation:** `src/spectra/use_cases/analyze_repository.py:111-166`

```mermaid
classDiagram
    class analyze_repository {
        <<Facade>>
        +analyze_repository(request, codebase, meta_prompter, specialists, critique_agent, ...) AnalysisReport
    }

    class _run_plan_stage {
        Stage 2: MetaPrompter planning
    }

    class _run_analyze_stage {
        Stage 3: 6 specialists in parallel
    }

    class _run_merge_stage {
        Stage 4: Deduplicate findings
    }

    class _run_critique_pipeline {
        Stage 5: CritiqueAgent validation
    }

    class _build_report {
        Stage 6: ScoreCard + AnalysisReport
    }

    class run_specialists {
        <<orchestrate_agents.py>>
        asyncio.gather parallel execution
    }

    analyze_repository --> _run_plan_stage
    analyze_repository --> _run_analyze_stage
    analyze_repository --> _run_merge_stage
    analyze_repository --> _run_critique_pipeline
    analyze_repository --> _build_report
    _run_analyze_stage --> run_specialists

    note for analyze_repository "Single entry point for Stages 2-6\nCallers pass agents + ports,\nget back AnalysisReport\n(analyze_repository.py:111-153)"
```

The internal pipeline at `analyze_repository.py:156-166`:
```
plan → resolve_source_files → analyze → merge → critique → build_report
```
Each stage is a pure function or async function. Callers (the composition root) never interact with individual stages.

---

## 7. Port/Adapter (Hexagonal Architecture)

**GoF Category:** Architectural (Ports and Adapters / Hexagonal)

**Why chosen:** Clean Architecture requires inner layers to define interfaces (ports) that outer layers implement (adapters). This inverts the dependency direction — use cases depend on abstractions, not on Anthropic/Git/Jinja2 specifics.

**Implementation:** `src/spectra/use_cases/interfaces.py:23-149`

```mermaid
classDiagram
    class LLMGateway {
        <<Port — interfaces.py:23>>
        +analyze(system_prompt, user_prompt, model, max_tokens) str
        +analyze_with_thinking(...) str
    }

    class GitPort {
        <<Port — interfaces.py:71>>
        +clone(repo_url, target_dir) void
        +get_file_tree(repo_dir) list~str~
        +read_file(repo_dir, file_path) str
        +validate_repo_size(repo_dir) void
    }

    class TokenPort {
        <<Port — interfaces.py:94>>
        +count(text) int
        +fits_budget(text, budget) bool
    }

    class ReportPort {
        <<Port — interfaces.py:109>>
        +render(report, output_path) str
    }

    class ProgressObserver {
        <<Port — interfaces.py:120>>
        +on_stage_start(stage, message) void
        +on_stage_complete(stage, message) void
        +on_agent_start(agent) void
        +on_agent_success(agent, duration) void
        +on_agent_failure(agent, error) void
        +on_error(stage, error) void
    }

    class AnthropicAdapter {
        <<Adapter — anthropic_adapter.py:49>>
    }

    class GitAdapter {
        <<Adapter — git_adapter.py>>
    }

    class TiktokenAdapter {
        <<Adapter — tiktoken_adapter.py>>
    }

    class ReportAdapter {
        <<Adapter — report_adapter.py>>
    }

    class RichProgressReporter {
        <<Adapter — progress_reporter.py:124>>
    }

    LLMGateway <|.. AnthropicAdapter : implements
    GitPort <|.. GitAdapter : implements
    TokenPort <|.. TiktokenAdapter : implements
    ReportPort <|.. ReportAdapter : implements
    ProgressObserver <|.. RichProgressReporter : implements

    note for LLMGateway "All 5 ports use Python Protocol\n(structural subtyping).\nNo explicit inheritance needed."
```

Five ports define the boundary between use cases and infrastructure. Each port has exactly one production adapter. The use-case layer (`analyze_repository.py`) depends only on port types, never on concrete adapters.

---

## 8. Observer

**GoF Category:** Behavioral

**Why chosen:** Pipeline stages and agent lifecycle events need to update the terminal display, but the orchestration logic (Layer 2) must not know about Rich Console (Layer 3). Observer decouples event production from consumption.

**Implementation:**
- Port: `src/spectra/use_cases/interfaces.py:120-149`
- Adapter: `src/spectra/adapters/progress_reporter.py:124-366`

```mermaid
classDiagram
    class ProgressObserver {
        <<Protocol — interfaces.py:120>>
        +on_stage_start(stage, message) void
        +on_stage_complete(stage, message) void
        +on_agent_start(agent) void
        +on_agent_success(agent, duration) void
        +on_agent_failure(agent, error) void
        +on_error(stage, error) void
    }

    class RichProgressReporter {
        -_console: Console
        -_progress: Progress
        -_agent_tasks: dict~AgentRole, TaskID~
        -_finished_agents: set~AgentRole~
        -_failed_agents: set~AgentRole~
        +on_stage_start(stage, message) void
        +on_stage_complete(stage, message) void
        +on_agent_start(agent) void
        +on_agent_success(agent, duration) void
        +on_agent_failure(agent, error) void
        +on_error(stage, error) void
        -_render_agent_panel() void
    }

    class analyze_repository {
        <<Subject — uses _notify() helper>>
    }

    class LoggingDecorator {
        <<Secondary subject>>
    }

    ProgressObserver <|.. RichProgressReporter : implements
    analyze_repository ..> ProgressObserver : notifies
    LoggingDecorator ..> ProgressObserver : notifies

    note for RichProgressReporter "Rich Progress bars, panels,\nbox-drawing tree view,\nhacker-aesthetic terminal output\n(progress_reporter.py:124)"
```

The `_notify()` helper at `analyze_repository.py:990-997` safely dispatches events:
```python
def _notify(observer, method, *args):
    if observer is not None:
        getattr(observer, method)(*args)
```

The `LoggingDecorator` also acts as a secondary subject, forwarding LLM call metadata (model, duration, tokens) to the same observer at `logging_decorator.py:95-102`.

---

## 9. Value Object (DDD)

**GoF Category:** Domain-Driven Design

**Why chosen:** Domain entities must be immutable and comparable by value, not identity. Frozen Pydantic models guarantee that findings, scores, and reports cannot be mutated after creation — critical for a pipeline where data flows through multiple stages.

**Implementation:** `src/spectra/entities/models.py:35-303`

```mermaid
classDiagram
    class FileLocation {
        <<frozen=True>>
        +file_path: str
        +line_start: int
        +line_end: int | None
    }

    class Finding {
        <<frozen=True>>
        +id: str
        +dimension: Dimension
        +severity: Severity
        +title: str
        +description: str
        +location: FileLocation
        +recommendation: str
        +agent_role: AgentRole
        +confidence: float
        +estimated_hours: float
        +__hash__() int
        +__eq__(other) bool
        +is_critical() bool
        +is_actionable() bool
    }

    class DimensionScore {
        <<frozen=True>>
        +dimension: Dimension
        +score: float
        +grade: Grade
        +findings_count: int
        +weight: float
        +is_passing() bool
        +is_excellent() bool
    }

    class ScoreCard {
        <<frozen=True>>
        +overall_score: float
        +overall_grade: Grade
        +dimensions: tuple~DimensionScore~
        +total_findings: int
        +worst_dimension() DimensionScore
        +best_dimension() DimensionScore
    }

    class AgentOutput {
        <<frozen=True>>
        +agent_role: AgentRole
        +findings: tuple~Finding~
        +tokens_used: int
        +duration_seconds: float
        +raw_response: str
        +dimension_score: float | None
    }

    class AnalysisReport {
        <<frozen=True>>
        +repo_url: str
        +score_card: ScoreCard
        +findings: tuple~Finding~
        +is_degraded: bool
        +critical_finding_count() int
    }

    Finding --> FileLocation : location
    ScoreCard --> DimensionScore : dimensions
    AnalysisReport --> ScoreCard : score_card
    AnalysisReport --> Finding : findings
    AgentOutput --> Finding : findings

    note for Finding "Hash by (file_path, line_start, dimension)\nfor O(n) deduplication via dict.fromkeys\n(models.py:83-95)"
```

Key design choices:
- All models use `frozen=True` (immutability enforced by Pydantic)
- `Finding.__hash__` uses `(file_path, line_start, dimension)` for deduplication at `models.py:83-85`
- Tuples instead of lists for collection fields (immutable containers)
- `Field(ge=0.0, le=1.0)` constraints on `confidence` at `models.py:78`

---

## 10. Error Taxonomy with Retry Metadata

**GoF Category:** Domain Pattern

**Why chosen:** Fallible operations (API calls, git clone, validation) need structured error handling with retry decisions. The error taxonomy carries retry metadata so the `RetryDecorator` can make autonomous retry-or-abort decisions.

**Implementation:** `src/spectra/entities/errors.py:14-128`

```mermaid
classDiagram
    class SpectraError {
        <<frozen dataclass>>
        +code: str
        +message: str
        +retryable: bool
        +max_retries: int
    }

    class ERRORS {
        <<Registry>>
        SPEC-001: Git clone failed (retry 2x)
        SPEC-002: API unreachable (retry 3x)
        SPEC-003: Rate limited (retry 3x)
        SPEC-004: Budget exceeded (no retry)
        SPEC-005: Validation failed (retry 1x)
        SPEC-006: Agent timeout (no retry)
        SPEC-007: 2+ agents failed (no retry)
        SPEC-008: Critique failed (no retry)
        SPEC-009: Report render failed (no retry)
    }

    class AgentError {
        +error: SpectraError
    }

    class GitError {
        +error: SpectraError
    }

    class SpectraRetryError {
        +error: SpectraError
    }

    class RetryDecorator {
        <<Consumer>>
        Checks error.retryable
        before retry decision
    }

    Exception <|-- AgentError
    Exception <|-- GitError
    Exception <|-- SpectraRetryError
    AgentError --> SpectraError : carries
    GitError --> SpectraError : carries
    SpectraRetryError --> SpectraError : carries
    ERRORS --> SpectraError : contains 9 entries
    RetryDecorator ..> SpectraRetryError : catches and inspects

    note for SpectraRetryError "RetryDecorator checks exc.error.retryable\nat retry_decorator.py:93 before backing off"
```

The retry decision at `retry_decorator.py:91-94`:
```python
except SpectraRetryError as exc:
    if not exc.error.retryable:
        raise  # Non-retryable: propagate immediately
```

---

## 11. Composition Root (DI Wiring)

**GoF Category:** Architectural

**Why chosen:** Clean Architecture mandates that dependency injection occurs at a single point — the outermost layer. The composition root wires the complete object graph: decorator chain, agent factory, infrastructure adapters, and pipeline entry point.

**Implementation:** `src/spectra/infrastructure/main.py:69-195`

```mermaid
classDiagram
    class CompositionRoot {
        <<main.py:69>>
        +_run_analysis(repo_url, output_path, ...) AnalysisReport
        +cli() void
    }

    class DecoratorChain {
        LoggingDecorator
        → RetryDecorator
        → AnthropicAdapter
    }

    class AgentFactory {
        +create(role) BaseAgent
        +create_specialists() list
    }

    class InfraAdapters {
        GitAdapter
        ReportAdapter
        TiktokenAdapter
    }

    class analyze_repository {
        <<Facade entry point>>
    }

    class cli_controller {
        <<Typer CLI>>
        set_analyzer_factory()
    }

    CompositionRoot --> DecoratorChain : wires (main.py:108-110)
    CompositionRoot --> AgentFactory : creates (main.py:144)
    CompositionRoot --> InfraAdapters : creates (main.py:115-116)
    CompositionRoot --> analyze_repository : delegates (main.py:161)
    CompositionRoot --> cli_controller : injects (main.py:341)

    note for CompositionRoot "ONLY module that imports\nfrom ALL layers.\nWires DI graph at startup.\n(main.py lines 43-54)"
```

The wiring sequence at `main.py:107-147`:
1. Create `AnthropicAdapter` (innermost)
2. Wrap with `RetryDecorator` (exponential backoff)
3. Wrap with `LoggingDecorator` (outermost, observability)
4. Create `AgentFactory` with the fully-decorated gateway
5. Factory creates MetaPrompter + 6 specialists + CritiqueAgent
6. Delegate to `analyze_repository()` facade

---

## Pattern Interaction Map

How all 11 patterns interact during a single analysis run:

```mermaid
sequenceDiagram
    participant CR as Composition Root
    participant F as AgentFactory
    participant TM as BaseAgent (Template)
    participant ST as Strategy (Prompts)
    participant LD as LoggingDecorator
    participant RD as RetryDecorator
    participant AA as AnthropicAdapter
    participant OB as RichProgressReporter
    participant FA as Facade (analyze_repo)
    participant VO as Value Objects

    CR->>F: create("meta_prompter")
    F->>TM: new MetaPrompter(gateway)

    CR->>F: create_specialists()
    F->>ST: lookup SPECIALIST_CONFIGS[role]
    F->>TM: new SpecialistAgent(role, config)

    CR->>FA: analyze_repository(agents, ports)

    FA->>OB: on_stage_start("PLAN")
    FA->>TM: meta_prompter.run(file_tree)
    TM->>TM: validate_input()
    TM->>TM: build_prompt()
    TM->>LD: analyze(system, user, model, tokens)
    LD->>RD: analyze(...)
    RD->>AA: analyze(...)
    AA-->>RD: response (or SpectraRetryError)
    RD-->>LD: response
    LD->>OB: on_stage_complete("llm_call", metadata)
    LD-->>TM: response
    TM->>TM: parse_output()
    TM->>TM: validate_output()
    TM->>VO: format_result() → AgentOutput
    TM-->>FA: AgentOutput

    FA->>OB: on_stage_start("ANALYZE")
    FA->>TM: 6x specialist.run() [parallel]
    FA->>OB: on_agent_success / on_agent_failure
    FA->>VO: merge_findings() → tuple[Finding]
    FA->>VO: compute_scorecard() → ScoreCard
    FA->>VO: AnalysisReport (frozen)
    FA-->>CR: AnalysisReport
```

---

## Summary Table

| # | Pattern | GoF Category | Spectra Class(es) | File:Line |
|---|---------|-------------|-------------------|-----------|
| 1 | Template Method | Behavioral | `BaseAgent.run()` | `base_agent.py:58` |
| 2 | Decorator | Structural | `LoggingDecorator`, `RetryDecorator` | `logging_decorator.py:39`, `retry_decorator.py:21` |
| 3 | Adapter | Structural | `AnthropicAdapter` | `anthropic_adapter.py:49` |
| 4 | Factory | Creational | `AgentFactory` | `agent_factory.py:39` |
| 5 | Strategy | Behavioral | `SPECIALIST_CONFIGS` + `SpecialistAgent` | `specialist_prompts.py:739` |
| 6 | Facade | Structural | `analyze_repository()` | `analyze_repository.py:111` |
| 7 | Port/Adapter | Architectural | `LLMGateway`, `GitPort`, `TokenPort`, `ReportPort`, `ProgressObserver` | `interfaces.py:23-149` |
| 8 | Observer | Behavioral | `ProgressObserver` / `RichProgressReporter` | `interfaces.py:120`, `progress_reporter.py:124` |
| 9 | Value Object | DDD | `Finding`, `ScoreCard`, `AgentOutput`, et al. | `models.py:35-303` |
| 10 | Error Taxonomy | Domain | `SpectraError`, `ERRORS` registry | `errors.py:14-51` |
| 11 | Composition Root | Architectural | `main.py._run_analysis()` | `main.py:69` |
