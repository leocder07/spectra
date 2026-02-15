# ADR-004: Pydantic Frozen Models for Domain Entities

## Status

Accepted

## Date

2025-01-15

## Context

Spectra's domain entities (Finding, ScoreCard, AnalysisReport, etc.) flow through multiple pipeline stages and are shared between agents. Mutable models risk accidental mutation, make equality checks unreliable, and complicate concurrent access in `asyncio.gather` parallel execution.

## Decision

All domain entity models use `frozen=True`:

```python
class Finding(BaseModel, frozen=True):
    """Immutable finding — hashable and safe for concurrent access."""
    ...
```

### Key Properties

1. **Immutability** — Frozen models raise `ValidationError` on attribute assignment after construction. Pipeline stages cannot accidentally modify findings.

2. **Hashability** — Frozen models with custom `__hash__` enable deduplication via `dict.fromkeys()`. Two findings are equal when they share the same file path, start line, and dimension.

3. **Thread safety** — Immutable objects are inherently safe for concurrent access in `asyncio.gather` parallel execution.

4. **Tuple fields** — Collections use `tuple[T, ...]` instead of `list[T]` to prevent mutation of nested sequences.

### Applied Models

| Model | Purpose |
|-------|---------|
| `FileLocation` | Source code location value object |
| `Finding` | Core analysis finding (dedupable) |
| `DimensionScore` | Score for one analysis dimension |
| `ScoreCard` | Aggregate scores across all dimensions |
| `AgentOutput` | Validated output from a single agent |
| `AgentContext` | Input context passed to an agent |
| `AnalysisReport` | Final report combining all results |
| `Codebase` | Cloned repository metadata |
| `AnalysisRequest` | User-initiated analysis request |
| `TokenBudget` | Token allocation across stages |
| `SpectraError` | Error descriptor (`dataclass(frozen=True)`) |

### Mutation Pattern

When a field needs to change (e.g., CritiqueAgent adjusting severity), use `model_copy(update={...})`:

```python
adjusted = finding.model_copy(
    update={"severity": "medium", "validated_by_critique": True}
)
```

This creates a new instance, preserving immutability.

## Consequences

### Positive

- No accidental mutation across pipeline stages.
- `Finding.__hash__` enables O(1) deduplication.
- Safe for parallel agent execution without locks.
- Pydantic validation runs at construction time — invalid data is caught early.

### Negative

- `model_copy()` is slightly more verbose than direct mutation.
- Tuple fields require conversion from lists: `tuple(findings_list)`.

### Mitigation

- `model_copy(update={...})` is a clean, explicit pattern.
- Tuple conversion is a one-line operation at agent boundaries.
