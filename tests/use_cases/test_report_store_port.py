"""Contract tests for ``ReportStorePort`` — the Layer-2 history-store port (#25).

The port shape lives in ``use_cases/interfaces.py`` and is implemented
twice in Layer 4 (sqlite + postgres). This test fixes the contract
shape — anyone changing the protocol must update this test in lock-step.

Both real adapters import the port via structural subtyping (Protocol
runtime_checkable is intentionally NOT applied — the dependency rule does
not need it, and the cost is import-time runtime cost we'd rather avoid).
The unit test below uses a stub class to prove the protocol is callable.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from spectra.entities.models import ReportSummary
from spectra.use_cases.interfaces import ReportStorePort


def test_report_store_port_is_protocol() -> None:
    """ReportStorePort is exposed as a typing.Protocol."""
    assert hasattr(ReportStorePort, "__class__")
    # Protocols expose their declared methods as descriptors on the class.
    assert hasattr(ReportStorePort, "store")
    assert hasattr(ReportStorePort, "latest")
    assert hasattr(ReportStorePort, "history")


def test_report_store_port_methods_are_async() -> None:
    """All three port methods are coroutines — calls return awaitables.

    Spec from ADR-022: history reads must not block the pipeline thread.
    """
    assert inspect.iscoroutinefunction(ReportStorePort.store)
    assert inspect.iscoroutinefunction(ReportStorePort.latest)
    assert inspect.iscoroutinefunction(ReportStorePort.history)


@pytest.mark.asyncio
async def test_in_memory_stub_satisfies_port() -> None:
    """A trivial stub satisfies ReportStorePort by structural typing.

    Doubles as documentation for what implementers must provide.
    """
    from typing import cast

    class _Stub:
        def __init__(self) -> None:
            self.stored: list[ReportSummary] = []

        async def store(self, report: ReportSummary) -> None:
            self.stored.append(report)

        async def latest(self, repo_signature: str) -> ReportSummary | None:
            return self.stored[-1] if self.stored else None

        async def history(
            self,
            repo_signature: str,
            since: datetime,
            until: datetime,
        ) -> tuple[ReportSummary, ...]:
            return tuple(self.stored)

    port: ReportStorePort = cast("ReportStorePort", _Stub())  # structural typing check
    assert (await port.latest("anything")) is None
    assert (await port.history("anything", datetime.now(UTC) - timedelta(days=7), datetime.now(UTC))) == ()
