"""Token budget management — allocation and tracking across pipeline stages.

Handles the distribution of the specialist token pool (500K tokens by
default) across the 6 analysis dimensions, using either MetaPrompter
suggestions or the default ``DIMENSION_WEIGHTS``.
"""

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
"""Default weights matching the ScoreCard dimension weights."""


def allocate_specialist_budgets(
    budget: TokenBudget,
    allocations: dict[str, int] | None = None,
) -> dict[Dimension, int]:
    """Distribute specialist token pool across dimensions.

    Uses MetaPrompter allocations if provided, otherwise falls back
    to the default ``DIMENSION_WEIGHTS``.

    Args:
        budget: Pipeline token budget with the specialist pool size.
        allocations: Optional MetaPrompter-suggested per-dimension
            token counts.

    Returns:
        Mapping of dimension to allocated token count.
    """
    pool = budget.specialists_pool

    if allocations:
        total_alloc = sum(allocations.values())
        return {dim: int(pool * allocations.get(dim, 0) / max(total_alloc, 1)) for dim in DIMENSION_WEIGHTS}

    return {dim: int(pool * weight) for dim, weight in DIMENSION_WEIGHTS.items()}


def check_budget_remaining(
    budget: TokenBudget,
    tokens_used: int,
) -> int:
    """Return remaining tokens, clamped to zero.

    Args:
        budget: Pipeline token budget.
        tokens_used: Tokens consumed so far.

    Returns:
        Non-negative remaining token count.
    """
    remaining = budget.total - tokens_used
    return max(remaining, 0)
