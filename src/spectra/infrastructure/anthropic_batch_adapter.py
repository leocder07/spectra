"""Anthropic Batch API adapter — implements ``BatchSubmitterPort`` (ADR-024).

Submits up to 10K LLM requests as a single Batch API job and polls for
completion. Anthropic charges 50% of standard pricing for batch jobs that
return within 24h, which stacks with prompt caching: every cached token
inside a batch is billed at 0.50 * 0.10 = 0.05x the standard input rate.

Wrong fit for interactive ``spectra analyze`` (the 24h SLA breaks the
≤5-minute UX in CLAUDE.md). Right fit for the Q3 portfolio scheduler
(``spectra portfolio scan``) where 50-300 repos analyze overnight.

Architecture:
    The adapter is Layer 4 — the use case never imports anthropic SDK
    types. ``BatchRequestItem`` is the boundary entity; the adapter
    translates each one into the Anthropic ``MessageCreateParamsNonStreaming``
    shape inside ``submit`` and back into ``BatchResultItem`` inside
    ``poll``. Cache breakpoints are honored using the same
    ``cache_control: ephemeral`` markers as the streaming adapter.

Failure semantics (ADR-024 §5):
    - Connection / 5xx → SPEC-002 (retryable)
    - Rate-limit → SPEC-003 (retryable)
    - Per-slot errors do NOT fail the whole batch — they are surfaced on
      the individual ``BatchResultItem.error`` field so the orchestrator
      can decide whether to retry per-slot or accept the partial result.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast

import anthropic
import httpx
from anthropic.types.messages import batch_create_params

from spectra.entities.errors import ERRORS, SpectraRetryError
from spectra.entities.models import (
    BatchHandle,
    BatchRequestItem,
    BatchResult,
    BatchResultItem,
    CacheUsage,
)
from spectra.infrastructure.anthropic_adapter import _build_system_blocks

_log = logging.getLogger("spectra.batch")

MAX_BATCH_SIZE: int = 10_000
"""Anthropic Batch API hard limit — 10K requests per submission."""

_MAX_CONNECTIONS = 10


class AnthropicBatchAdapter:
    """Async Anthropic batch client implementing ``BatchSubmitterPort``."""

    def __init__(self, api_key: str) -> None:
        """Initialize the batch adapter.

        Args:
            api_key: Anthropic API key (``sk-ant-*``).

        Raises:
            ValueError: Empty, whitespace-only, or placeholder key.
        """
        placeholders = {"sk-ant-your-key-here", "your-key-here", ""}
        stripped = api_key.strip()
        if not stripped or stripped in placeholders:
            msg = "ANTHROPIC_API_KEY is missing or contains a placeholder value"
            raise ValueError(msg)
        self._closed = False
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            http_client=httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=_MAX_CONNECTIONS,
                    max_keepalive_connections=_MAX_CONNECTIONS,
                ),
            ),
        )

    async def submit(
        self,
        requests: tuple[BatchRequestItem, ...],
    ) -> BatchHandle:
        """Submit ``requests`` as a single batch job."""
        if not requests:
            msg = "Batch submit requires at least one request"
            raise ValueError(msg)
        if len(requests) > MAX_BATCH_SIZE:
            msg = (
                f"Batch size {len(requests)} exceeds MAX_BATCH_SIZE "
                f"({MAX_BATCH_SIZE}) — split into multiple batches"
            )
            raise ValueError(msg)
        payload = [_request_to_payload(r) for r in requests]
        # The SDK's batch_create_params.Request is a TypedDict shape; our
        # dict literals match it structurally but mypy cannot prove it
        # without an explicit cast.
        typed_payload = cast(list[batch_create_params.Request], payload)
        try:
            response = await self._client.messages.batches.create(requests=typed_payload)
        except anthropic.APIConnectionError as exc:
            raise SpectraRetryError(ERRORS["SPEC-002"]) from exc
        except anthropic.RateLimitError as exc:
            raise SpectraRetryError(ERRORS["SPEC-003"]) from exc
        return BatchHandle(
            batch_id=response.id,
            submitted_at=datetime.now(UTC),
            request_count=len(requests),
        )

    async def poll(self, handle: BatchHandle) -> BatchResult:
        """Fetch the current state of ``handle``."""
        try:
            batch = await self._client.messages.batches.retrieve(handle.batch_id)
        except anthropic.APIConnectionError as exc:
            raise SpectraRetryError(ERRORS["SPEC-002"]) from exc
        except anthropic.RateLimitError as exc:
            raise SpectraRetryError(ERRORS["SPEC-003"]) from exc
        status = batch.processing_status
        if status != "ended":
            return BatchResult(handle=handle, processing_status=status, items=())
        items = await self._collect_results(handle.batch_id)
        return BatchResult(handle=handle, processing_status="ended", items=items)

    async def _collect_results(
        self,
        batch_id: str,
    ) -> tuple[BatchResultItem, ...]:
        """Stream every result entry from a completed batch."""
        results = await self._client.messages.batches.results(batch_id)
        return tuple([_entry_to_item(entry) async for entry in results])

    async def close(self) -> None:
        """Close the underlying HTTP client and release connection pool."""
        self._closed = True
        await self._client.close()

    def __del__(self) -> None:
        """Warn if the client was not explicitly closed."""
        if not getattr(self, "_closed", True):
            _log.warning(
                "AnthropicBatchAdapter was not closed — call close() or use async with",
            )


def _request_to_payload(request: BatchRequestItem) -> dict[str, object]:
    """Translate a ``BatchRequestItem`` into Anthropic's batch request shape."""
    params: dict[str, object] = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "system": _build_system_blocks(
            request.system_prompt, request.cache_breakpoint_index,
        ),
        "messages": [{"role": "user", "content": request.user_prompt}],
    }
    if request.effort is not None:
        params["output_config"] = {"effort": request.effort}
    return {"custom_id": request.custom_id, "params": params}


def _entry_to_item(entry: object) -> BatchResultItem:
    """Translate one Anthropic batch result entry into a ``BatchResultItem``."""
    custom_id = getattr(entry, "custom_id", "")
    result = getattr(entry, "result", None)
    result_type = getattr(result, "type", "errored")
    if result_type != "succeeded":
        error_payload = getattr(result, "error", None)
        return BatchResultItem(
            custom_id=custom_id,
            error=_format_error(error_payload) or "batch slot did not succeed",
        )
    message = getattr(result, "message", None)
    text = _extract_text(message)
    usage = getattr(message, "usage", None)
    cache_usage = _read_cache_usage(usage)
    return BatchResultItem(
        custom_id=custom_id,
        text=text,
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_usage=cache_usage,
    )


def _extract_text(message: object) -> str:
    """Concatenate all ``type="text"`` content blocks on a batch message."""
    if message is None:
        return ""
    blocks = getattr(message, "content", []) or []
    parts = [
        getattr(block, "text", "")
        for block in blocks
        if getattr(block, "type", "") == "text"
    ]
    return "".join(parts)


def _read_cache_usage(usage: object) -> CacheUsage:
    """Extract Anthropic cache token counters from a batch usage block."""
    if usage is None:
        return CacheUsage()
    creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    return CacheUsage(creation_tokens=creation, read_tokens=read)


def _format_error(payload: object) -> str:
    """Render an Anthropic batch error payload to a single-line string."""
    if payload is None:
        return ""
    inner = getattr(payload, "error", payload)
    return str(getattr(inner, "message", inner))
