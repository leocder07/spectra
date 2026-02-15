"""Token budget management — allocation and tracking across pipeline stages.

Handles the distribution of the specialist token pool (500K tokens by
default) across the 6 analysis dimensions, using either MetaPrompter
suggestions or the default ``DIMENSION_WEIGHTS``.

Budget allocation strategy:
    - The total pipeline budget (default 1M tokens) is split between
      the MetaPrompter (fixed ~5K), specialists (variable pool), and
      CritiqueAgent (pre-allocated ~200K).
    - Each specialist gets a share of the pool proportional to its
      dimension weight (e.g., architecture=25%, documentation=10%).
    - A 5% safety margin is built into ``TokenBudget.specialists_pool``
      to absorb variable response sizes without triggering SPEC-004.
    - If the MetaPrompter provides custom allocations (from its analysis
      of the repo structure), those override the default weights while
      still respecting the total pool size.
    - Overflow handling: ``check_budget_remaining`` clamps to zero so
      the pipeline gracefully skips the critique stage rather than
      crashing when the budget is exhausted.
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
    # Pool already includes 5% safety margin for variable response sizes
    pool = budget.specialists_pool

    if allocations:
        # MetaPrompter-suggested allocations: normalize to pool size
        # to prevent over-allocation regardless of LLM output
        total_alloc = sum(allocations.values())
        return {dim: int(pool * allocations.get(dim, 0) / max(total_alloc, 1)) for dim in DIMENSION_WEIGHTS}

    # Default: allocate proportional to dimension weights
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
    # Clamp to zero: negative budget gracefully skips critique stage
    # rather than raising — the pipeline always produces a report
    remaining = budget.total - tokens_used
    return max(remaining, 0)
