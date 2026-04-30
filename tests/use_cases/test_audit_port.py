"""Tests for AuditPort protocol surface (Layer 2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from spectra.entities.audit import AuditEvent, AuditTarget, Identity, new_event_id
from spectra.use_cases.audit import (
    NoopAuditAdapter,
    safe_emit,
)
from spectra.use_cases.interfaces import AuditPort


def _event(event_type: str = "scan.started") -> AuditEvent:
    return AuditEvent(
        event_id=new_event_id(),
        ts=datetime.now(UTC),
        event=event_type,  # type: ignore[arg-type]
        actor=Identity(actor="alice@example.com", source="git", confidence="medium"),
        target=AuditTarget(repo_signature="a" * 32, run_id="r-1"),
        payload={},
        spectra_version="0.6.0",
    )


class _FailingAdapter:
    async def emit(self, event: AuditEvent) -> None:  # noqa: ARG002
        msg = "kaboom"
        raise RuntimeError(msg)

    async def flush(self) -> None:
        msg = "kaboom-flush"
        raise RuntimeError(msg)


class _RecordingAdapter:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def emit(self, event: AuditEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
class TestSafeEmit:
    async def test_silently_swallows_emit_error(self) -> None:
        port = cast("AuditPort", _FailingAdapter())
        # Must not raise — pipeline contract.
        await safe_emit(port, _event())

    async def test_propagates_to_adapter_on_success(self) -> None:
        adapter = _RecordingAdapter()
        await safe_emit(cast("AuditPort", adapter), _event())
        assert len(adapter.events) == 1

    async def test_handles_none_port(self) -> None:
        # Allowed: composition root may pass None when audit is disabled.
        await safe_emit(None, _event())


@pytest.mark.asyncio
class TestNoopAdapter:
    async def test_emit_and_flush_are_noops(self) -> None:
        adapter = NoopAuditAdapter()
        await adapter.emit(_event())
        await adapter.flush()
