"""Performance regression tests for cache key composition.

Pins Fix 3 from the v0.6.0 self-scan: the per-process composite version
strings are computed exactly once and reused for every cache key.
"""

from __future__ import annotations

import time

from spectra.infrastructure.main import (
    _composite_model_versions,
    _composite_prompt_versions,
)


class TestCompositeVersionsAreMemoized:
    """The version composition is deterministic per process — call it once."""

    def setup_method(self) -> None:
        # Each test starts with a clean cache so misses are observable.
        _composite_model_versions.cache_clear()
        _composite_prompt_versions.cache_clear()

    def test_one_thousand_calls_yield_one_miss(self) -> None:
        """1000 lookups must hit the lru_cache 999 times and miss exactly once."""
        for _ in range(1000):
            _composite_model_versions()
            _composite_prompt_versions()
        assert _composite_model_versions.cache_info().misses == 1
        assert _composite_model_versions.cache_info().hits == 999
        assert _composite_prompt_versions.cache_info().misses == 1
        assert _composite_prompt_versions.cache_info().hits == 999

    def test_hot_path_is_under_one_microsecond_per_call(self) -> None:
        """Hot calls should be ~lru_cache lookup speed, not full recompute."""
        # Warm up.
        _composite_model_versions()
        _composite_prompt_versions()

        start = time.perf_counter()
        for _ in range(10_000):
            _composite_model_versions()
            _composite_prompt_versions()
        elapsed = time.perf_counter() - start

        # 10K pairs in under 50 ms = under 5 us per pair (very generous;
        # lru_cache hits are typically <100 ns each on modern CPUs).
        assert elapsed < 0.050, (
            f"10K cache-key composition pairs took {elapsed * 1000:.1f}ms; expected < 50ms — memoization regressed?"
        )

    def test_repeated_calls_return_identical_strings(self) -> None:
        """Two separate calls must return identical strings (deterministic).

        This is the contract that justifies the memoization: if either
        function ever became non-deterministic we would silently miss the
        cache. The test catches that regression.
        """
        first_model = _composite_model_versions()
        first_prompt = _composite_prompt_versions()
        for _ in range(50):
            assert _composite_model_versions() == first_model
            assert _composite_prompt_versions() == first_prompt
