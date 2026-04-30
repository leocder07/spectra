"""Performance regression tests for ``infrastructure/main.py``.

Pinned fixes (from the v0.6.0 self-scan):

1. ``_read_key_source_files`` runs reads concurrently via the event loop.
2. ``shutil.rmtree`` is offloaded to a worker thread on workspace cleanup.
4. ``prioritize_source_files`` is O(N + M) on file count by prefix count.

Thresholds carry headroom so they pass on a noisy CI box while still
catching a regression that re-serializes the work.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from spectra.infrastructure.main import (
    _read_key_source_files,
    _run_analysis,
)
from spectra.use_cases.source_file_selection import prioritize_source_files


class _FakeGitPort:
    """Stand-in for ``GitPort.read_file`` with a configurable per-call latency."""

    def __init__(self, latency_seconds: float) -> None:
        self._latency = latency_seconds
        self.calls: list[str] = []

    async def read_file(self, repo_dir: str, file_path: str) -> str:
        # Simulate the I/O wait with ``asyncio.sleep`` so concurrent reads
        # actually overlap on the event loop. ``time.sleep`` would not.
        self.calls.append(file_path)
        await asyncio.sleep(self._latency)
        return f"// content of {file_path}\n"


class TestReadKeySourceFilesConcurrency:
    """Pin Fix 1 — heuristic source file pre-load runs concurrently."""

    @pytest.mark.asyncio
    async def test_reads_run_concurrently_not_sequentially(self) -> None:
        """10 reads at 50 ms each must finish well below the sequential bound.

        Sequential lower bound: 10 * 50 ms = 500 ms.
        Concurrent expectation: ~50-100 ms (single batch on the executor).
        We assert finished < 500 / 3 = ~166 ms so a regression to a
        ``for path: await read`` loop is caught immediately.
        """
        latency = 0.05  # 50 ms per read
        n_files = 10
        sequential_bound = n_files * latency
        threshold = sequential_bound / 3

        git = _FakeGitPort(latency_seconds=latency)
        file_tree = [f"src/spectra/file_{i}.py" for i in range(n_files)]

        start = time.perf_counter()
        with patch(
            "spectra.infrastructure.main.TiktokenAdapter",
        ) as mock_counter:
            mock_counter.return_value.count.return_value = 1
            await _read_key_source_files(git, "/tmp/repo", file_tree)  # noqa: S108
        elapsed = time.perf_counter() - start

        assert elapsed < threshold, (
            f"reads took {elapsed * 1000:.0f}ms; expected < {threshold * 1000:.0f}ms "
            f"(sequential bound {sequential_bound * 1000:.0f}ms)"
        )

    @pytest.mark.asyncio
    async def test_token_budget_still_capped_when_parallel(self) -> None:
        """Concurrent reads must still respect ``MAX_HEURISTIC_TOKENS``."""
        git = _FakeGitPort(latency_seconds=0.0)
        file_tree = [f"src/spectra/file_{i}.py" for i in range(20)]
        with patch("spectra.infrastructure.main.TiktokenAdapter") as mock_counter:
            # Each "file" claims to be 60K tokens; only the first should fit
            # under the 100K cap.
            mock_counter.return_value.count.return_value = 60_000
            result = await _read_key_source_files(git, "/tmp/repo", file_tree)  # noqa: S108
        # First file fits (60K < 100K). Second would push us to 120K -> stop.
        assert len(result) == 1


class TestPrioritizeSourceFilesComplexity:
    """Pin Fix 4 — ``prioritize_source_files`` is linear in file count."""

    def test_one_thousand_files_under_50ms(self) -> None:
        """Ranking 1000 files must finish in < 50 ms wall-clock.

        The ranking already uses ``str.startswith`` against a small
        constant prefix tuple, so it is effectively O(N). This test
        guards against a regression to e.g. nested ``for`` over the
        whole tree per prefix or a Path-heavy implementation that
        explodes on large repos.
        """
        # Build a realistic mix: entries, configs, src/ files, other source.
        file_tree: list[str] = []
        for i in range(250):
            file_tree.append(f"src/spectra/module_{i}.py")
            file_tree.append(f"lib/helpers/util_{i}.ts")
            file_tree.append(f"app/handlers/handler_{i}.go")
            file_tree.append(f"tests/test_{i}.py")
        # Ensure we cross 1000.
        assert len(file_tree) == 1000

        # Warm-up to settle imports + the function-local Path() constructions.
        prioritize_source_files(file_tree[:10])

        start = time.perf_counter()
        ranked = prioritize_source_files(file_tree)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.050, f"ranking 1000 files took {elapsed * 1000:.1f}ms; expected < 50ms"
        # Sanity: every file made it into the result.
        assert len(ranked) == len(file_tree)

    def test_ranking_preserves_tier_order(self) -> None:
        """Entry stems -> configs -> src/-prefixed sources -> other sources."""
        file_tree = [
            "tests/something.py",  # other source
            "src/spectra/foo.py",  # src-prefixed source
            "pyproject.toml",  # config
            "src/spectra/main.py",  # entry stem in src/
        ]
        ranked = prioritize_source_files(file_tree)
        # main.py (entry) first, then pyproject.toml (config), then
        # src/spectra/foo.py (src-prefixed), then tests/something.py.
        assert ranked[0].endswith("main.py")
        assert ranked[1] == "pyproject.toml"
        assert ranked[2] == "src/spectra/foo.py"
        assert ranked[3] == "tests/something.py"


class TestWorkspaceCleanupOffloaded:
    """Pin Fix 2 — ``shutil.rmtree`` runs via ``asyncio.to_thread`` not inline."""

    @pytest.mark.asyncio
    async def test_rmtree_called_via_to_thread(self, tmp_path: Path) -> None:
        """The cleanup path must dispatch ``shutil.rmtree`` off the event loop.

        We instrument both ``asyncio.to_thread`` and ``shutil.rmtree`` and
        assert every ``rmtree`` we observe was wrapped: i.e. ``to_thread``
        was called with ``shutil.rmtree`` as its callable. If a future
        refactor re-introduces a synchronous ``shutil.rmtree(workspace_dir,
        ...)`` directly on the event loop, this test fails.
        """
        original_to_thread = asyncio.to_thread
        observed: dict[str, int] = {"to_thread_rmtree": 0, "direct_rmtree": 0}

        async def spy_to_thread(func: object, /, *args: object, **kwargs: object) -> object:
            if func is shutil.rmtree or getattr(func, "__name__", "") == "rmtree":
                observed["to_thread_rmtree"] += 1
            return await original_to_thread(func, *args, **kwargs)  # type: ignore[arg-type]

        def spy_rmtree(*args: object, **kwargs: object) -> None:
            observed["direct_rmtree"] += 1

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
            patch("spectra.infrastructure.main.shutil.rmtree", side_effect=spy_rmtree),
            patch("spectra.infrastructure.main.asyncio.to_thread", side_effect=spy_to_thread),
            patch("spectra.infrastructure.main.AnthropicAdapter") as mock_adapter,
            patch("spectra.infrastructure.main.GitAdapter") as mock_git_cls,
            patch("spectra.infrastructure.main._provision_cache", return_value=None),
            patch("spectra.infrastructure.main._build_audit_port", return_value=None),
            patch(
                "spectra.infrastructure.main._allocate_workspace",
                return_value=(str(tmp_path), True),
            ),
            patch(
                "spectra.infrastructure.main._run_preflight_stage",
                side_effect=RuntimeError("stop here"),
            ),
        ):
            mock_adapter.return_value.close = _make_async_noop()
            mock_git = mock_git_cls.return_value
            mock_git.prepare_workspace = _make_async_return(str(tmp_path))
            mock_git.validate_repo_size = _make_async_noop()
            mock_git.get_file_tree = _make_async_return([])
            with pytest.raises(RuntimeError, match="stop here"):
                await _run_analysis(
                    "https://github.com/test/repo",
                    "/tmp/out.html",  # noqa: S108
                    no_cache=True,
                )

        assert observed["to_thread_rmtree"] >= 1, (
            "shutil.rmtree was not dispatched via asyncio.to_thread; cleanup is blocking the event loop"
        )
        assert observed["direct_rmtree"] >= 1, "test instrumentation never observed an rmtree call — wiring drift"


def _make_async_noop() -> object:
    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    return _noop


def _make_async_return(value: object) -> object:
    async def _ret(*args: object, **kwargs: object) -> object:
        return value

    return _ret
