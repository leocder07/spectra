"""Tests for AnthropicBatchAdapter — implements BatchSubmitterPort (ADR-024)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra.entities.errors import SpectraRetryError
from spectra.entities.models import BatchHandle, BatchRequestItem
from spectra.infrastructure.anthropic_batch_adapter import (
    MAX_BATCH_SIZE,
    AnthropicBatchAdapter,
)


def _make_request(custom_id: str = "req-0") -> BatchRequestItem:
    return BatchRequestItem(
        custom_id=custom_id,
        system_prompt="sys",
        user_prompt="user",
        model="claude-opus-4-7",
        max_tokens=1000,
    )


@pytest.fixture
def adapter():
    """Create adapter with mocked client."""
    with patch(
        "spectra.infrastructure.anthropic_batch_adapter.anthropic.AsyncAnthropic",
    ) as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        a = AnthropicBatchAdapter(api_key="test-key")
        a._client = mock_client
        yield a, mock_client


# ── Construction ──────────────────────────────────────────────


class TestConstruction:
    def test_rejects_empty_api_key(self):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            AnthropicBatchAdapter(api_key="")

    def test_rejects_placeholder_api_key(self):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            AnthropicBatchAdapter(api_key="sk-ant-your-key-here")

    def test_max_batch_size_constant(self):
        """Anthropic Batch API caps at 10K requests per submission."""
        assert MAX_BATCH_SIZE == 10_000


# ── submit ────────────────────────────────────────────────────


class TestSubmit:
    @pytest.mark.asyncio
    async def test_returns_handle_with_batch_id(self, adapter):
        a, client = adapter
        client.messages.batches.create = AsyncMock(
            return_value=SimpleNamespace(id="msgbatch_abc123"),
        )
        handle = await a.submit((_make_request(),))
        assert isinstance(handle, BatchHandle)
        assert handle.batch_id == "msgbatch_abc123"
        assert handle.request_count == 1

    @pytest.mark.asyncio
    async def test_records_submission_timestamp(self, adapter):
        a, client = adapter
        client.messages.batches.create = AsyncMock(
            return_value=SimpleNamespace(id="msgbatch_xyz"),
        )
        before = datetime.now(UTC)
        handle = await a.submit((_make_request(),))
        after = datetime.now(UTC)
        assert before <= handle.submitted_at <= after

    @pytest.mark.asyncio
    async def test_rejects_empty_request_tuple(self, adapter):
        a, _client = adapter
        with pytest.raises(ValueError, match="at least one request"):
            await a.submit(())

    @pytest.mark.asyncio
    async def test_rejects_oversize_batch(self, adapter):
        a, _client = adapter
        too_many = tuple(_make_request(f"r{i}") for i in range(MAX_BATCH_SIZE + 1))
        with pytest.raises(ValueError, match="MAX_BATCH_SIZE"):
            await a.submit(too_many)

    @pytest.mark.asyncio
    async def test_passes_custom_id_through(self, adapter):
        """Anthropic Batch API echoes custom_id back — adapters MUST forward it."""
        a, client = adapter
        client.messages.batches.create = AsyncMock(
            return_value=SimpleNamespace(id="msgbatch_x"),
        )
        await a.submit((_make_request("plant-001"), _make_request("plant-002")))
        sent_requests = client.messages.batches.create.call_args.kwargs["requests"]
        assert [r["custom_id"] for r in sent_requests] == ["plant-001", "plant-002"]

    @pytest.mark.asyncio
    async def test_forwards_cache_breakpoint_index(self, adapter):
        """Cached prefixes still apply inside batch (cost stacks per ADR-024)."""
        a, client = adapter
        client.messages.batches.create = AsyncMock(
            return_value=SimpleNamespace(id="msgbatch_c"),
        )
        request = BatchRequestItem(
            custom_id="r-0",
            system_prompt="cache_me_then_dynamic",
            user_prompt="u",
            model="claude-opus-4-7",
            max_tokens=1000,
            cache_breakpoint_index=len("cache_me_then_"),
        )
        await a.submit((request,))
        sent = client.messages.batches.create.call_args.kwargs["requests"][0]
        system = sent["params"]["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}
        assert system[0]["text"] == "cache_me_then_"

    @pytest.mark.asyncio
    async def test_connection_error_becomes_spec002(self, adapter):
        import anthropic

        a, client = adapter
        client.messages.batches.create = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=MagicMock()),
        )
        with pytest.raises(SpectraRetryError) as exc_info:
            await a.submit((_make_request(),))
        assert exc_info.value.error.code == "SPEC-002"


# ── poll ──────────────────────────────────────────────────────


def _handle() -> BatchHandle:
    return BatchHandle(
        batch_id="msgbatch_p",
        submitted_at=datetime.now(UTC),
        request_count=2,
    )


class TestPoll:
    @pytest.mark.asyncio
    async def test_in_progress_returns_no_items(self, adapter):
        a, client = adapter
        client.messages.batches.retrieve = AsyncMock(
            return_value=SimpleNamespace(
                processing_status="in_progress",
                results_url=None,
            ),
        )
        result = await a.poll(_handle())
        assert result.processing_status == "in_progress"
        assert result.is_complete() is False
        assert result.items == ()

    @pytest.mark.asyncio
    async def test_ended_fetches_results_and_returns_items(self, adapter):
        a, client = adapter
        client.messages.batches.retrieve = AsyncMock(
            return_value=SimpleNamespace(
                processing_status="ended",
                results_url="https://api.anthropic.com/results",
            ),
        )

        async def _aiter():
            for entry in (
                _result_entry("req-a", "alpha", 100, 50),
                _result_entry("req-b", "beta", 110, 60),
            ):
                yield entry

        client.messages.batches.results = AsyncMock(return_value=_aiter())
        result = await a.poll(_handle())
        assert result.is_complete()
        assert len(result.items) == 2
        assert {item.custom_id for item in result.items} == {"req-a", "req-b"}
        for item in result.items:
            assert item.succeeded()

    @pytest.mark.asyncio
    async def test_error_entry_marked_failed(self, adapter):
        a, client = adapter
        client.messages.batches.retrieve = AsyncMock(
            return_value=SimpleNamespace(
                processing_status="ended",
                results_url="https://x",
            ),
        )

        async def _aiter():
            yield SimpleNamespace(
                custom_id="req-err",
                result=SimpleNamespace(
                    type="errored",
                    error=SimpleNamespace(error=SimpleNamespace(message="rate limited")),
                ),
            )

        client.messages.batches.results = AsyncMock(return_value=_aiter())
        result = await a.poll(_handle())
        assert len(result.items) == 1
        item = result.items[0]
        assert not item.succeeded()
        assert "rate limited" in item.error

    @pytest.mark.asyncio
    async def test_cache_usage_threaded_through(self, adapter):
        a, client = adapter
        client.messages.batches.retrieve = AsyncMock(
            return_value=SimpleNamespace(
                processing_status="ended",
                results_url="https://x",
            ),
        )

        async def _aiter():
            yield _result_entry("req-c", "content", 200, 80, cache_creation=4000, cache_read=1500)

        client.messages.batches.results = AsyncMock(return_value=_aiter())
        result = await a.poll(_handle())
        item = result.items[0]
        assert item.cache_usage.creation_tokens == 4000
        assert item.cache_usage.read_tokens == 1500


def _result_entry(
    custom_id: str,
    text: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation: int = 0,
    cache_read: int = 0,
):
    """Build a fake batch result entry shaped like Anthropic's response."""
    text_block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
    )
    message = SimpleNamespace(content=[text_block], usage=usage)
    return SimpleNamespace(
        custom_id=custom_id,
        result=SimpleNamespace(type="succeeded", message=message),
    )


# ── close ─────────────────────────────────────────────────────


class TestClose:
    @pytest.mark.asyncio
    async def test_close_calls_client_close(self, adapter):
        a, client = adapter
        client.close = AsyncMock()
        await a.close()
        client.close.assert_called_once()
