---
name: Spectra architecture invariants
description: Stable architectural facts about Spectra that should remain true across model migrations and feature work
type: project
---

Spectra is a 4-layer Clean Architecture Python CLI:
- Layer 1 entities/ — frozen Pydantic, ZERO spectra package imports
- Layer 2 use_cases/ — Protocol ports (LLMGateway, GitPort, TokenPort, ReportPort, ProgressObserver, AnalysisAgent)
- Layer 3 adapters/ — CLI (Typer), RichProgressReporter, AnalysisPresenter
- Layer 4 infrastructure/ — main.py composition root, AnthropicAdapter, decorators, GitAdapter, agents/

8 agents: 1 MetaPrompter + 6 parallel specialists (architecture, security, quality, documentation, dependency, performance) + 1 CritiqueAgent. Specialists run via `asyncio.gather(*agents, return_exceptions=True)` with `Semaphore(4)` and `wait_for(timeout=120)`.

Decorator chain: `LoggingDecorator -> RetryDecorator -> AnthropicAdapter`, wired in main.py:108-110. All 3 satisfy `LLMGateway` Protocol via structural subtyping.

Failure policy: 0-1 specialist failures continues with reweighting; 2+ failures triggers DEGRADED state with partial report (skips critique).

**Why:** These facts shape every architecture doc and ADR. They've held across every model migration so far.
**How to apply:** When updating HLD/LLD or writing a new ADR, treat these as load-bearing — only the model identifiers and per-call kwargs change with migrations, not the layer rules or pipeline shape.
