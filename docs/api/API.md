# Spectra API Reference

Complete reference for using Spectra as a Python library. All public classes, functions, and protocols are documented here with usage examples.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Domain Models (entities/)](#domain-models)
- [Protocol Interfaces (use_cases/interfaces.py)](#protocol-interfaces)
- [Pipeline Orchestration (use_cases/)](#pipeline-orchestration)
- [CLI Controller (adapters/)](#cli-controller)
- [Infrastructure (infrastructure/)](#infrastructure)
- [Error Codes](#error-codes)
- [Constants](#constants)

---

## Quick Start

```python
import asyncio
from spectra.infrastructure.main import _run_analysis

async def main():
    report = await _run_analysis(
        repo_url="https://github.com/expressjs/express",
        output_path="spectra-report.html",
    )
    print(f"Grade: {report.score_card.overall_grade}")
    print(f"Score: {report.score_card.overall_score}/100")
    for f in report.findings:
        if f.is_critical():
            print(f"  CRITICAL: {f.title} @ {f.location.file_path}:{f.location.line_start}")

asyncio.run(main())
```

---

## Domain Models

All domain models live in `spectra.entities.models` and use `frozen=True` for immutability. They are hashable, JSON-serializable, and safe for concurrent access.

### `FileLocation`

Value object pinpointing a source code location.

```python
from spectra.entities.models import FileLocation

loc = FileLocation(
    file_path="src/auth.py",
    line_start=42,
    line_end=50,  # optional — None for single-line
)
```

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | `str` | Repository-relative path |
| `line_start` | `int` | First line of the span (1-based) |
| `line_end` | `int \| None` | Last line, or None for single-line |

### `Finding`

Core domain entity — an immutable, dedupable analysis finding. Two findings are equal when they share the same `file_path`, `line_start`, and `dimension`.

```python
from spectra.entities.models import Finding, FileLocation

finding = Finding(
    id="sec-001",
    dimension="security",
    severity="critical",
    title="SQL injection in login query",
    description="User input is concatenated directly into SQL",
    location=FileLocation(file_path="src/db.py", line_start=88),
    recommendation="Use parameterized queries with bound parameters",
    agent_role="security",
    confidence=0.95,
)

# Query methods
finding.is_critical()    # True
finding.is_actionable()  # True (critical, high, or medium)

# Immutable — use model_copy to create modified versions
adjusted = finding.model_copy(
    update={"severity": "high", "validated_by_critique": True}
)
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique identifier (e.g., `sec-001`) |
| `dimension` | `Dimension` | Analysis dimension |
| `severity` | `Severity` | `critical`, `high`, `medium`, `low`, `info` |
| `title` | `str` | Short human-readable summary |
| `description` | `str` | Detailed explanation with evidence |
| `location` | `FileLocation` | Source code location |
| `recommendation` | `str` | Actionable fix suggestion |
| `agent_role` | `AgentRole` | Agent that produced this finding |
| `confidence` | `float` | Confidence score (0.0–1.0, min 0.7 to include) |
| `validated_by_critique` | `bool` | Whether CritiqueAgent confirmed this |
| `estimated_hours` | `float` | Estimated remediation effort |

### `DimensionScore`

Score for a single analysis dimension.

```python
from spectra.entities.models import DimensionScore

score = DimensionScore(
    dimension="security",
    score=88.0,
    grade="B+",
    findings_count=5,
    weight=0.25,
)

score.is_passing()    # True (>= 60.0)
score.is_excellent()  # False (< 90.0)
```

| Field | Type | Description |
|-------|------|-------------|
| `dimension` | `Dimension` | Which dimension |
| `score` | `float` | 0–100 numeric score |
| `grade` | `Grade` | Letter grade (A+ through F) |
| `findings_count` | `int` | Number of findings |
| `weight` | `float` | Normalized weight for overall calculation |

### `ScoreCard`

Aggregate scores across all analysis dimensions.

```python
# Access the worst/best dimension
worst = score_card.worst_dimension()  # DimensionScore with lowest score
best = score_card.best_dimension()    # DimensionScore with highest score

# Look up a specific dimension's grade
grade = score_card.grade_for("security")  # e.g., "B+"
```

| Field | Type | Description |
|-------|------|-------------|
| `overall_score` | `float` | Weighted average (0–100) |
| `overall_grade` | `Grade` | Letter grade for overall |
| `dimensions` | `tuple[DimensionScore, ...]` | Per-dimension breakdown |
| `total_findings` | `int` | Sum of all findings |

### `AgentOutput`

Validated output from a single agent run.

| Field | Type | Description |
|-------|------|-------------|
| `agent_role` | `AgentRole` | Which agent produced this |
| `findings` | `tuple[Finding, ...]` | Validated findings |
| `tokens_used` | `int` | Total tokens consumed |
| `duration_seconds` | `float` | Wall-clock time |
| `raw_response` | `str` | Unprocessed LLM response |
| `dimension_score` | `float \| None` | LLM-assigned holistic score |

### `AgentContext`

Input context passed to an agent for analysis.

| Field | Type | Description |
|-------|------|-------------|
| `agent_role` | `AgentRole` | Target agent role |
| `system_prompt` | `str` | System prompt |
| `user_prompt` | `str` | User prompt with repo data |
| `model` | `str` | Anthropic model identifier |
| `max_tokens` | `int` | Maximum response tokens |
| `extended_thinking` | `bool` | Enable extended thinking (CritiqueAgent only) |

### `AnalysisReport`

Final report combining all agent results.

```python
report.critical_finding_count()  # Number of critical findings
report.is_degraded               # True if 2+ agents failed
report.score_card.overall_grade  # e.g., "B+"
```

| Field | Type | Description |
|-------|------|-------------|
| `repo_url` | `str` | Repository URL |
| `repo_name` | `str` | Short name |
| `score_card` | `ScoreCard` | Aggregate scores |
| `findings` | `tuple[Finding, ...]` | All validated findings |
| `analysis_duration_seconds` | `float` | Total pipeline time |
| `total_tokens_used` | `int` | Sum of all tokens |
| `total_cost_usd` | `float` | Estimated API cost |
| `agents_used` | `tuple[AgentRole, ...]` | Contributing agents |
| `is_degraded` | `bool` | True if 2+ agents failed |
| `degraded_dimensions` | `tuple[Dimension, ...]` | Missing dimensions |
| `cross_cutting_insights` | `tuple[str, ...]` | CritiqueAgent notes |
| `hallucination_removed_count` | `int` | Findings removed by path validation |

### `Codebase`

Representation of a cloned repository on disk.

| Field | Type | Description |
|-------|------|-------------|
| `repo_url` | `str` | Original remote URL |
| `repo_name` | `str` | Short name |
| `local_path` | `str` | Absolute path to clone |
| `file_tree` | `tuple[str, ...]` | Sorted file paths |

### `AnalysisRequest`

User-initiated analysis request.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `repo_url` | `str` | — | Git HTTPS URL |
| `quick` | `bool` | `False` | Skip CritiqueAgent |
| `output_format` | `str` | `"rich"` | `rich`, `html`, or `json` |

### `TokenBudget`

Token allocation across pipeline stages.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `total` | `int` | `800,000` | Maximum for entire pipeline |
| `meta_prompter` | `int` | `5,000` | Reserved for planning |
| `specialists_pool` | `int` | `500,000` | Shared pool for 6 specialists |
| `critique_reserved` | `int` | `200,000` | Reserved for CritiqueAgent |
| `buffer` | `int` | `95,000` | Safety margin |

### Utility Functions

#### `score_to_grade(score: float) -> Grade`

Convert a numeric score (0–100) to a letter grade.

```python
from spectra.entities.models import score_to_grade

score_to_grade(95)   # "A+"
score_to_grade(83.5) # "B+"
score_to_grade(42)   # "F"
```

#### `estimate_cost(outputs: tuple[AgentOutput, ...]) -> float`

Estimate total USD cost from agent outputs using per-1K-token pricing.

```python
from spectra.entities.models import estimate_cost

cost = estimate_cost(tuple(agent_outputs))  # e.g., 2.41
```

---

## Enums (Literal Types)

All enums use `Literal` types (not `enum.Enum`) for JSON serializability:

```python
from spectra.entities.enums import Severity, Dimension, Grade, AgentRole, PipelineState

# Type aliases — use in type hints
severity: Severity = "critical"  # "critical" | "high" | "medium" | "low" | "info"
dimension: Dimension = "security"  # 6 dimensions
grade: Grade = "B+"  # A+ through F
role: AgentRole = "security"  # 8 agent roles
state: PipelineState = "analyzing"  # 10 pipeline states
```

---

## Protocol Interfaces

Defined in `spectra.use_cases.interfaces`. These are the ports for dependency inversion.

### `LLMGateway`

Port for LLM inference calls. Implemented by `AnthropicAdapter`, wrapped by `RetryDecorator` and `LoggingDecorator`.

```python
class LLMGateway(Protocol):
    async def analyze(
        self, system_prompt: str, user_prompt: str, model: str, max_tokens: int
    ) -> str: ...

    async def analyze_with_thinking(
        self, system_prompt: str, user_prompt: str, model: str, max_tokens: int
    ) -> str: ...
```

### `GitPort`

Port for repository operations. Implemented by `GitAdapter` using GitPython.

```python
class GitPort(Protocol):
    async def clone(self, repo_url: str, target_dir: str) -> None: ...
    async def get_file_tree(self, repo_dir: str) -> list[str]: ...
    async def read_file(self, repo_dir: str, file_path: str) -> str: ...
    async def validate_repo_size(self, repo_dir: str) -> None: ...
```

### `TokenPort`

Port for token counting. Implemented by `TiktokenAdapter`.

```python
class TokenPort(Protocol):
    def count(self, text: str) -> int: ...
    def fits_budget(self, text: str, budget: int) -> bool: ...
```

### `ReportPort`

Port for rendering analysis reports. Implemented by `ReportAdapter` using Jinja2.

```python
class ReportPort(Protocol):
    def render(self, report: AnalysisReport, output_path: str) -> str: ...
```

### `ProgressObserver`

Port for pipeline progress updates. Implemented by `RichProgressReporter`.

```python
class ProgressObserver(Protocol):
    def on_stage_start(self, stage: str, message: str) -> None: ...
    def on_stage_complete(self, stage: str, message: str) -> None: ...
    def on_agent_start(self, agent: AgentRole) -> None: ...
    def on_agent_success(self, agent: AgentRole, duration: float) -> None: ...
    def on_agent_failure(self, agent: AgentRole, error: str) -> None: ...
    def on_error(self, stage: str, error: str) -> None: ...
```

---

## Pipeline Orchestration

### `analyze_repository()`

Main entry point for the use-case layer. Coordinates all 6 pipeline stages.

```python
from spectra.use_cases.analyze_repository import analyze_repository

report = await analyze_repository(
    request=request,
    codebase=codebase,
    meta_prompter=meta_prompter,
    specialists=specialists,
    critique_agent=critique_agent,
    observer=observer,
)
```

### `run_specialists()`

Run specialist agents in parallel with individual timeouts.

```python
from spectra.use_cases.orchestrate_agents import run_specialists

results = await run_specialists(
    agents=specialists,
    prompts={"security": "...", "architecture": "..."},
    timeout_seconds=120.0,
    max_concurrency=4,
)
```

### `evaluate_results()`

Apply the failure state machine: 0–1 failures → merging, 2+ → degraded.

```python
from spectra.use_cases.orchestrate_agents import evaluate_results

successes, failed_roles, state = evaluate_results(results, roles)
if state == "degraded":
    print(f"Degraded: {failed_roles}")
```

### Token Budget Management

```python
from spectra.use_cases.manage_token_budget import (
    allocate_specialist_budgets,
    check_budget_remaining,
    DIMENSION_WEIGHTS,
)

# Distribute token pool across dimensions
allocations = allocate_specialist_budgets(budget, meta_prompter_suggestions)

# Check remaining budget
remaining = check_budget_remaining(budget, tokens_used)
```

---

## CLI Controller

The CLI is built with Typer and lives in `spectra.adapters.cli_controller`.

### Entry Points

| Function | Description |
|----------|-------------|
| `cli_entry()` | Start the Typer CLI app |
| `set_analyzer_factory(factory)` | Inject the async analyzer callable |

### Composition Root

The `cli()` function in `spectra.infrastructure.main` serves as the package entry point:

```python
from spectra.infrastructure.main import cli

# This is what [project.scripts] calls:
# spectra = "spectra.infrastructure.main:cli"
cli()
```

It wires the decorator chain (Logging → Retry → Anthropic), creates agents via the factory, and injects the analyzer into the CLI controller.

---

## Infrastructure

### Decorator Chain

Every LLM call passes through a 3-layer decorator chain:

```
LoggingDecorator → RetryDecorator → AnthropicAdapter
```

```python
from spectra.infrastructure.anthropic_adapter import AnthropicAdapter
from spectra.infrastructure.retry_decorator import RetryDecorator
from spectra.infrastructure.logging_decorator import LoggingDecorator

adapter = AnthropicAdapter(api_key="sk-ant-...")
retry = RetryDecorator(adapter, max_retries=3, backoff_base=1.0)
gateway = LoggingDecorator(retry, observer=observer)
```

### Agent Factory

Creates all 8 agent configurations from the `AgentFactory`:

```python
from spectra.infrastructure.agents.agent_factory import AgentFactory

factory = AgentFactory(gateway=gateway)
meta_prompter = factory.create("meta_prompter")
specialists = factory.create_specialists()  # Returns 6 agents
critique = factory.create("critique")
```

---

## Error Codes

All errors carry a code, description, and retry metadata:

| Code | Message | Retryable | Max Retries |
|------|---------|-----------|-------------|
| `SPEC-001` | Git clone failed | Yes | 2 |
| `SPEC-002` | Anthropic API unreachable | Yes | 3 |
| `SPEC-003` | Rate limited (429) | Yes | 3 |
| `SPEC-004` | Token budget exceeded | No | 0 |
| `SPEC-005` | Agent output validation failed | Yes | 1 |
| `SPEC-006` | Agent timeout (120s) | No | 0 |
| `SPEC-007` | 2+ agents failed | No | 0 |
| `SPEC-008` | CritiqueAgent failed | No | 0 |
| `SPEC-009` | Report render failed | No | 0 |

```python
from spectra.entities.errors import ERRORS, SpectraError, AgentError

# Look up an error
err = ERRORS["SPEC-003"]  # SpectraError(code="SPEC-003", message="Rate limited (429)", retryable=True, max_retries=3)

# Raise domain errors
raise AgentError(ERRORS["SPEC-006"])
```

---

## Constants

### Scoring Constants

```python
from spectra.entities.models import (
    PASSING_SCORE,          # 60.0 — minimum passing score
    EXCELLENT_SCORE,        # 90.0 — excellent threshold
    DEFAULT_DIMENSION_SCORE, # 85.0 — score with zero findings
    MIN_CONFIDENCE,          # 0.7 — minimum finding confidence
)
```

### Dimension Weights

```python
from spectra.use_cases.manage_token_budget import DIMENSION_WEIGHTS

# {"architecture": 0.25, "security": 0.25, "quality": 0.20,
#  "documentation": 0.10, "maintainability": 0.10, "performance": 0.10}
```

### Brand Colors

```python
from spectra.adapters.brand import VIOLET, AMBER, RED, GREEN, CYAN, GRAY

# VIOLET = "#7C3AED"  (Primary — Spectrum Violet)
# AMBER  = "#F59E0B"  (Accent — Prism Amber)
# RED    = "#EF4444"  (Critical — Signal Red)
# GREEN  = "#22C55E"  (Success — Growth Green)
# CYAN   = "#06B6D4"  (Secondary — B-range grades)
# GRAY   = "#6B7280"  (Muted text)
```
