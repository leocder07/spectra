"""Tests for token budget management."""

from __future__ import annotations

from spectra.entities.models import TokenBudget
from spectra.use_cases.manage_token_budget import (
    DIMENSION_WEIGHTS,
    allocate_specialist_budgets,
    check_budget_remaining,
)

# ── DIMENSION_WEIGHTS ───────────────────────────────────────────


class TestDimensionWeights:
    def test_six_dimensions(self):
        assert len(DIMENSION_WEIGHTS) == 6

    def test_weights_sum_to_one(self):
        assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9

    def test_architecture_weight(self):
        assert DIMENSION_WEIGHTS["architecture"] == 0.25

    def test_security_weight(self):
        assert DIMENSION_WEIGHTS["security"] == 0.25

    def test_quality_weight(self):
        assert DIMENSION_WEIGHTS["quality"] == 0.20

    def test_documentation_weight(self):
        assert DIMENSION_WEIGHTS["documentation"] == 0.10

    def test_maintainability_weight(self):
        assert DIMENSION_WEIGHTS["maintainability"] == 0.10

    def test_performance_weight(self):
        assert DIMENSION_WEIGHTS["performance"] == 0.10


# ── allocate_specialist_budgets ─────────────────────────────────


class TestAllocateSpecialistBudgets:
    def test_default_allocation(self):
        budget = TokenBudget()
        alloc = allocate_specialist_budgets(budget)
        assert len(alloc) == 6
        assert alloc["architecture"] == int(500_000 * 0.25)
        assert alloc["security"] == int(500_000 * 0.25)
        assert alloc["quality"] == int(500_000 * 0.20)
        assert alloc["documentation"] == int(500_000 * 0.10)

    def test_default_total_close_to_pool(self):
        budget = TokenBudget()
        alloc = allocate_specialist_budgets(budget)
        total = sum(alloc.values())
        assert total <= budget.specialists_pool
        assert total >= budget.specialists_pool - 6  # rounding tolerance

    def test_custom_allocations(self):
        budget = TokenBudget()
        custom = {
            "architecture": 50,
            "security": 50,
            "quality": 0,
            "documentation": 0,
            "maintainability": 0,
            "performance": 0,
        }
        alloc = allocate_specialist_budgets(budget, allocations=custom)
        assert alloc["architecture"] == 250_000
        assert alloc["security"] == 250_000
        assert alloc["quality"] == 0

    def test_custom_unequal_split(self):
        budget = TokenBudget()
        custom = {
            "architecture": 100,
            "security": 0,
            "quality": 0,
            "documentation": 0,
            "maintainability": 0,
            "performance": 0,
        }
        alloc = allocate_specialist_budgets(budget, allocations=custom)
        assert alloc["architecture"] == 500_000
        assert alloc["security"] == 0

    def test_custom_budget(self):
        budget = TokenBudget(specialists_pool=100_000)
        alloc = allocate_specialist_budgets(budget)
        assert alloc["architecture"] == int(100_000 * 0.25)


# ── check_budget_remaining ──────────────────────────────────────


class TestCheckBudgetRemaining:
    def test_within_budget(self):
        budget = TokenBudget()
        remaining = check_budget_remaining(budget, 100_000)
        assert remaining == 700_000

    def test_at_budget(self):
        budget = TokenBudget()
        remaining = check_budget_remaining(budget, 800_000)
        assert remaining == 0

    def test_over_budget(self):
        budget = TokenBudget()
        remaining = check_budget_remaining(budget, 900_000)
        assert remaining == 0

    def test_zero_used(self):
        budget = TokenBudget()
        remaining = check_budget_remaining(budget, 0)
        assert remaining == 800_000


# ── Edge cases for allocate_specialist_budgets ────────────────


class TestAllocateBudgetEdgeCases:
    def test_none_allocations_uses_defaults(self):
        budget = TokenBudget()
        alloc = allocate_specialist_budgets(budget, allocations=None)
        assert len(alloc) == 6
        assert alloc["architecture"] == int(500_000 * 0.25)

    def test_empty_allocations_uses_defaults(self):
        budget = TokenBudget()
        alloc = allocate_specialist_budgets(budget, allocations={})
        assert len(alloc) == 6

    def test_all_zero_allocations(self):
        budget = TokenBudget()
        custom = {
            "architecture": 0,
            "security": 0,
            "quality": 0,
            "documentation": 0,
            "maintainability": 0,
            "performance": 0,
        }
        alloc = allocate_specialist_budgets(budget, allocations=custom)
        assert all(v == 0 for v in alloc.values())

    def test_single_dimension_gets_full_pool(self):
        budget = TokenBudget()
        custom = {"architecture": 1}
        alloc = allocate_specialist_budgets(budget, allocations=custom)
        assert alloc["architecture"] == 500_000

    def test_very_small_pool(self):
        budget = TokenBudget(specialists_pool=6)
        alloc = allocate_specialist_budgets(budget)
        total = sum(alloc.values())
        assert total <= 6

    def test_allocations_proportional(self):
        budget = TokenBudget()
        custom = {"architecture": 3, "security": 1}
        alloc = allocate_specialist_budgets(budget, allocations=custom)
        assert alloc["architecture"] == int(500_000 * 3 / 4)
        assert alloc["security"] == int(500_000 * 1 / 4)


# ── Edge cases for check_budget_remaining ────────────────────


class TestCheckBudgetRemainingEdgeCases:
    def test_negative_used_not_realistic_but_handled(self):
        budget = TokenBudget()
        remaining = check_budget_remaining(budget, -100)
        assert remaining == 800_100

    def test_exactly_one_token_left(self):
        budget = TokenBudget()
        remaining = check_budget_remaining(budget, 799_999)
        assert remaining == 1

    def test_massive_overuse(self):
        budget = TokenBudget()
        remaining = check_budget_remaining(budget, 10_000_000)
        assert remaining == 0

    def test_custom_budget_remaining(self):
        budget = TokenBudget(total=100)
        remaining = check_budget_remaining(budget, 50)
        assert remaining == 50
