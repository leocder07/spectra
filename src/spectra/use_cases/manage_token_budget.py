"""Token budget management — allocation and tracking across pipeline stages."""

from __future__ import annotations

from spectra.entities.enums import Dimension
from spectra.entities.models import TokenBudget

DIMENSION_WEIGHTS: dict[Dimension, float] = {
    "architecture": 0.25,
    "security": 0.25,
    "quality": 0.20,
    "documentation": 0.10,
    "maintainability": 0.10,
    "performance": 0.10,
}


def allocate_specialist_budgets(
    budget: TokenBudget,
    allocations: dict[str, int] | None = None,
) -> dict[Dimension, int]:
    """Distribute specialist token pool across dimensions.

    Uses MetaPrompter allocations if provided, else default weights.
    """
    pool = budget.specialists_pool

    if allocations:
        total_alloc = sum(allocations.values())
        return {
            dim: int(pool * allocations.get(dim, 0) / max(total_alloc, 1))
            for dim in DIMENSION_WEIGHTS
        }

    return {
        dim: int(pool * weight)
        for dim, weight in DIMENSION_WEIGHTS.items()
    }


def check_budget_remaining(
    budget: TokenBudget,
    tokens_used: int,
) -> int:
    """Return remaining tokens, or 0 if budget exceeded."""
    remaining = budget.total - tokens_used
    return max(remaining, 0)
