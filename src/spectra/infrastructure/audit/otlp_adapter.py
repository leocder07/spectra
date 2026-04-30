"""OpenTelemetry-style HTTP audit adapter.

Posts each event as a single JSON object to a configured collector
endpoint. The OTLP wire format is intentionally not modelled in detail —
mature collectors accept any JSON body on a custom receiver, and the
ADR-018 trade-off was to push richer formatting to the collector layer
rather than maintain NxM adapter combinations here.

Retries: bounded exponential backoff (configurable, default 3 retries
1s/2s/4s). Once exhausted, the adapter raises and ``safe_emit`` swallows.
"""

from __future__ import annotations

import asyncio

import httpx

from spectra.entities.audit import AuditEvent

_RETRY_STATUS_THRESHOLD = 500
"""HTTP status codes >= this value count as transient and trigger a retry."""


class OtlpAuditAdapter:
    """POST audit events to an OTLP-compatible HTTP collector."""

    def __init__(
        self,
        endpoint: str,
        client: httpx.AsyncClient | None = None,
        *,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        timeout: float = 5.0,
        owns_client: bool = False,
    ) -> None:
        """Bind the adapter to a collector endpoint.

        Args:
            endpoint: Full URL to POST events to (e.g. the collector's
                ``/v1/logs`` path).
            client: Optional injected ``httpx.AsyncClient`` — wired by the
                composition root so HTTP connection pools survive across
                events. When omitted, the adapter builds its own client
                and sets ``owns_client=True`` so ``flush`` cleans it up.
            max_retries: Number of transient-error retries (network,
                timeout, 5xx) before the adapter raises.
            backoff_base: Base seconds for exponential backoff. Set to
                ``0.0`` in tests to skip the sleeps.
            timeout: Per-request timeout in seconds.
            owns_client: If ``True``, ``flush`` calls ``aclose`` on the
                injected client. Set automatically when the adapter
                constructs the client itself.
        """
        if client is None:
            client = httpx.AsyncClient(timeout=timeout)
            owns_client = True
        self._client = client
        self._endpoint = endpoint
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._owns_client = owns_client

    async def emit(self, event: AuditEvent) -> None:
        """POST ``event`` with retry on transient failures."""
        body = event.model_dump(mode="json")
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(self._endpoint, json=body)
                if response.status_code < _RETRY_STATUS_THRESHOLD:
                    return
                last_exc = httpx.HTTPStatusError(
                    f"OTLP collector returned {response.status_code}",
                    request=response.request,
                    response=response,
                )
            except (httpx.TransportError, httpx.HTTPError) as exc:
                last_exc = exc
            await self._sleep_backoff(attempt)
        if last_exc is not None:
            raise last_exc

    async def flush(self) -> None:
        """Close the owned ``httpx`` client; no-op when injected."""
        if self._owns_client:
            await self._client.aclose()

    async def _sleep_backoff(self, attempt: int) -> None:
        """Sleep ``backoff_base * 2**attempt`` seconds (zero-cost in tests)."""
        if self._backoff_base <= 0:
            return
        await asyncio.sleep(self._backoff_base * (2**attempt))
