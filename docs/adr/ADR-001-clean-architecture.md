# ADR-001: Clean Architecture with 4 Layers

## Status

Accepted

## Date

2025-01-15

## Context

Spectra is a code analysis tool that deploys 8 AI agents to analyze repositories. The codebase needs clear separation between domain logic, application logic, external adapters, and infrastructure concerns. Without explicit boundaries, LLM gateway details would leak into business logic, making the system hard to test and maintain.

## Decision

Adopt Clean Architecture with 4 concentric layers, each with strict import rules:

```
Layer 1: entities/        -> Imports NOTHING from spectra package
Layer 2: use_cases/       -> Imports ONLY from entities/
Layer 3: adapters/        -> Imports from entities/ + use_cases/
Layer 4: infrastructure/  -> Imports from all inner layers
```

**The Dependency Rule:** Source code dependencies ONLY point inward. No layer may import from a layer further from the center.

### Layer Responsibilities

- **entities/** — Domain models (Pydantic frozen), enums (Literal types), error taxonomy. Zero framework coupling.
- **use_cases/** — Pipeline orchestration, agent coordination, token budget management. Protocol interfaces (ports) define boundaries.
- **adapters/** — CLI (Typer), terminal display (Rich), brand constants. Translate between user interface and use cases.
- **infrastructure/** — Anthropic API client, GitPython wrapper, Jinja2 report renderer, decorator chain, agent implementations.

### Composition Root

`infrastructure/main.py` serves as the composition root — the only place where all layers are imported and wired together via dependency injection.

## Consequences

### Positive

- Domain models are testable without any infrastructure (no API keys, no network).
- LLM provider can be swapped by implementing the `LLMGateway` protocol.
- Git operations are behind the `GitPort` protocol — testable with fakes.
- Clear ownership boundaries for team collaboration.

### Negative

- More files and indirection than a flat structure.
- Protocol interfaces add a small amount of boilerplate.
- New contributors must understand the layer rules before modifying code.

### Mitigation

- Layer rules are documented in CLAUDE.md and enforced in code review.
- Barrel exports (`__init__.py` with `__all__`) make imports clean.
