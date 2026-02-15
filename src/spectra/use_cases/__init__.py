"""Use-case layer — Layer 2 of Clean Architecture (imports only from entities/).

This layer contains the core business logic for Spectra's analysis pipeline.
It defines the orchestration flow, port interfaces, and token budget management.

Key modules:

- **interfaces.py** — Protocol classes (ports) defining boundaries between the
  use-case layer and infrastructure. Includes ``LLMGateway``, ``GitPort``,
  ``TokenPort``, ``ReportPort``, and ``ProgressObserver``. Infrastructure
  adapters implement these protocols via dependency inversion.
- **analyze_repository.py** — The pipeline facade that orchestrates all 6 stages:
  INGEST → PLAN → ANALYZE → MERGE → CRITIQUE → REPORT. This is the main
  entry point called by the composition root.
- **orchestrate_agents.py** — Parallel agent execution via ``asyncio.gather``
  with per-agent timeouts and a concurrency semaphore. Also provides the
  failure state machine (0-1 failures → merging, 2+ → degraded).
- **manage_token_budget.py** — Token pool allocation across 6 dimensions using
  either MetaPrompter suggestions or default ``DIMENSION_WEIGHTS``.

**Dependency rule**: This layer imports ONLY from ``spectra.entities``.
It never imports from adapters or infrastructure.
"""

from spectra.use_cases.analyze_repository import analyze_repository
from spectra.use_cases.interfaces import (
    GitPort,
    LLMGateway,
    ProgressObserver,
    ReportPort,
    TokenPort,
)
from spectra.use_cases.manage_token_budget import (
    DIMENSION_WEIGHTS,
    allocate_specialist_budgets,
    check_budget_remaining,
)
from spectra.use_cases.orchestrate_agents import (
    AnalysisAgent,
    evaluate_results,
    run_specialists,
)

__all__ = [
    # token budget
    "DIMENSION_WEIGHTS",
    # orchestration
    "AnalysisAgent",
    # interfaces (ports)
    "GitPort",
    "LLMGateway",
    "ProgressObserver",
    "ReportPort",
    "TokenPort",
    "allocate_specialist_budgets",
    "analyze_repository",
    "check_budget_remaining",
    "evaluate_results",
    "run_specialists",
]
