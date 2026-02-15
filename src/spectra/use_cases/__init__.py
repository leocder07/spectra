"""Use cases layer — business logic orchestration."""

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
    # interfaces (ports)
    "GitPort",
    "LLMGateway",
    "ProgressObserver",
    "ReportPort",
    "TokenPort",
    # orchestration
    "AnalysisAgent",
    "analyze_repository",
    "evaluate_results",
    "run_specialists",
    # token budget
    "DIMENSION_WEIGHTS",
    "allocate_specialist_budgets",
    "check_budget_remaining",
]
