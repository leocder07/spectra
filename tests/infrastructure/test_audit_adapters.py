"""Tests for the JSONL / stdout / OTLP audit adapters (Layer 4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    from pathlib import Path

import httpx
import pytest

from spectra.entities.audit import AuditEvent, AuditTarget, Identity, new_event_id
from spectra.infrastructure.audit import (
    JsonLinesAuditAdapter,
    OtlpAuditAdapter,
    StdoutAuditAdapter,
)
from spectra.use_cases.audit import safe_emit
from spectra.use_cases.interfaces import AuditPort


def _event(event_type: str = "scan.started", run_id: str = "r-001") -> AuditEvent:
    return AuditEvent(
        event_id=new_event_id(),
        ts=datetime(2026, 4, 29, 12, 0, 0, tzinfo=UTC),
        event=event_type,  # type: ignore[arg-type]
        actor=Identity(actor="alice@example.com", source="git", confidence="medium"),
        target=AuditTarget(repo_signature="a" * 32, run_id=run_id),
        payload={"score": 88.0},
        spectra_version="0.6.0",
        run_id=run_id,
    )


# ── JsonLinesAuditAdapter ────────────────────────────────────


class TestJsonLinesAuditAdapter:
    @pytest.mark.asyncio
    async def test_writes_one_event_per_line(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        adapter = JsonLinesAuditAdapter(path=path)
        await adapter.emit(_event())
        await adapter.emit(_event("scan.completed"))
        await adapter.flush()
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            payload = json.loads(line)
            assert "event_id" in payload
            assert payload["spectra_version"] == "0.6.0"

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c" / "audit.jsonl"
        adapter = JsonLinesAuditAdapter(path=nested)
        await adapter.emit(_event())
        await adapter.flush()
        assert nested.exists()

    @pytest.mark.asyncio
    async def test_daily_rotation(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        adapter = JsonLinesAuditAdapter(path=path)
        # First write at one timestamp
        evt_old = _event()
        await adapter.emit(evt_old)
        await adapter.flush()
        # Force adapter to rotate: pretend a day passed
        adapter._current_date = (datetime.now(UTC) - timedelta(days=1)).date()
        evt_new = _event("scan.completed")
        await adapter.emit(evt_new)
        await adapter.flush()
        # Should have rotated the prior day's file with a date suffix
        rotated = list(tmp_path.glob("audit.jsonl.*"))
        assert len(rotated) == 1

    @pytest.mark.asyncio
    async def test_silent_fail_when_path_unwritable(self, tmp_path: Path) -> None:
        # A directory exists where the file should be — write will fail.
        bad = tmp_path / "audit.jsonl"
        bad.mkdir()
        adapter = JsonLinesAuditAdapter(path=bad)
        await safe_emit(cast("AuditPort", adapter), _event())
        # Pipeline must not have raised; nothing further to assert.

    @pytest.mark.asyncio
    async def test_serialized_event_contains_no_python_objects(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "audit.jsonl"
        adapter = JsonLinesAuditAdapter(path=path)
        await adapter.emit(_event())
        await adapter.flush()
        line = path.read_text(encoding="utf-8").strip()
        decoded = json.loads(line)
        assert decoded["event"] == "scan.started"
        assert decoded["actor"]["confidence"] == "medium"


# ── StdoutAuditAdapter ───────────────────────────────────────


class TestStdoutAuditAdapter:
    @pytest.mark.asyncio
    async def test_prints_json_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        adapter = StdoutAuditAdapter()
        await adapter.emit(_event())
        await adapter.flush()
        out = capsys.readouterr().out.strip()
        decoded = json.loads(out)
        assert decoded["event"] == "scan.started"

    @pytest.mark.asyncio
    async def test_one_line_per_event(self, capsys: pytest.CaptureFixture[str]) -> None:
        adapter = StdoutAuditAdapter()
        await adapter.emit(_event())
        await adapter.emit(_event("scan.completed"))
        out = capsys.readouterr().out
        lines = [line for line in out.split("\n") if line.strip()]
        assert len(lines) == 2


# ── OtlpAuditAdapter ─────────────────────────────────────────


class TestOtlpAuditAdapter:
    @pytest.mark.asyncio
    async def test_posts_json_to_endpoint(self) -> None:
        client = MagicMock()
        client.post = AsyncMock(return_value=MagicMock(status_code=200))
        adapter = OtlpAuditAdapter(
            endpoint="http://collector.local/v1/logs",
            client=client,
        )
        await adapter.emit(_event())
        client.post.assert_awaited_once()
        args, kwargs = client.post.call_args
        assert args[0] == "http://collector.local/v1/logs"
        assert "json" in kwargs
        assert kwargs["json"]["event"] == "scan.started"

    @pytest.mark.asyncio
    async def test_retries_on_transient_failure(self) -> None:
        client = MagicMock()
        client.post = AsyncMock(
            side_effect=[
                httpx.ConnectError("boom"),
                MagicMock(status_code=200),
            ]
        )
        adapter = OtlpAuditAdapter(
            endpoint="http://collector.local/v1/logs",
            client=client,
            max_retries=2,
            backoff_base=0.0,
        )
        await adapter.emit(_event())
        assert client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_silent_fail_after_exhausted_retries(self) -> None:
        client = MagicMock()
        client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))
        adapter = OtlpAuditAdapter(
            endpoint="http://collector.local/v1/logs",
            client=client,
            max_retries=2,
            backoff_base=0.0,
        )
        # Through safe_emit — pipeline must not raise even when adapter
        # exhausts its retries.
        await safe_emit(cast("AuditPort", adapter), _event())

    @pytest.mark.asyncio
    async def test_flush_closes_owned_client(self) -> None:
        client = MagicMock()
        client.aclose = AsyncMock()
        adapter = OtlpAuditAdapter(
            endpoint="http://x",
            client=client,
            owns_client=True,
        )
        await adapter.flush()
        client.aclose.assert_awaited_once()
