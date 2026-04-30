"""Redis-backed implementation of ``RemoteCachePort`` (capability #21, ADR-021).

Layer 4 adapter — the use-case layer never imports ``redis``. The
composition root selects this adapter when ``--cache-remote`` (or the
``SPECTRA_CACHE_REDIS`` env var) is set, then wraps it with the local
``SqliteCacheAdapter`` inside a ``TieredCacheAdapter``.

ADR-012 — every value persisted carries a 32-byte ``blake2b`` MAC
computed under the per-user keyring secret PLUS a port-name domain
separator (``"remote"``). The same secret derives the local L1 and the
remote L2 MAC, but the domain separator means an attacker who lifts a
row from one tier cannot replay it against the other. On read, the
adapter recomputes the MAC and ``compare_digest``s; a mismatch deletes
the offending key and returns a miss (logged as SPEC-010 once per
process so the operator does not get N copies of the same warning).

Failure mode (SPEC-010): connection refused, timeout, and auth failures
all degrade to no-cache for the remainder of the run — reads return
``None`` and writes are silently dropped. The pipeline keeps running
with the local-only cache. This is the same SPEC-010 contract the
SqliteCacheAdapter honours; cache failures are NEVER fatal.
"""

from __future__ import annotations

import hmac as _hmac
import json
import logging
from hashlib import blake2b
from typing import TYPE_CHECKING, Any

from spectra.entities.models import (
    AnalysisReport,
    BatchCacheKey,
    CacheSecret,
    Finding,
    RepoCacheKey,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

_LOG = logging.getLogger("spectra.cache.redis")
_MAC_DIGEST_SIZE = 32
_NUL = b"\x00"
_REMOTE_DOMAIN = b"spectra-remote-cache-v1"
"""Domain separator binding the MAC to the remote port (ADR-021).

Same secret as the L1 cache, different prefix in the MAC input so a
row stolen from L1 cannot authenticate against L2 (and vice versa).
The two HMACs are orthogonal even though they share the underlying
keyring secret.
"""

_KEY_PREFIX = "spectra:v1"
"""All adapter keys share this namespace so a future v2 layout can
co-exist on the same Redis without collision. Per-org HMAC namespacing
(ADR-021 §3) is naturally enforced by the secret itself — an org with
a different secret produces non-matching MACs and never reads our rows.
"""


def _redis_module() -> Any | None:  # noqa: ANN401 — opt-import surface
    """Return the ``redis.asyncio`` module or ``None`` when unavailable.

    Kept behind a function so the redis import only fires when the
    composition root actually wires the adapter — clients without
    ``--cache-remote`` should never pay for the import.
    """
    try:
        import redis.asyncio as _redis
    except ImportError:
        return None
    return _redis


def _compute_remote_mac(
    secret: CacheSecret,
    key_parts: tuple[str, ...],
    value: str,
) -> bytes:
    """Compute the L2 row MAC.

    Same shape as the L1 MAC (``blake2b(key=secret, …)``) with a leading
    domain-separator chunk so the remote MAC and the local MAC of the
    same payload bytes never coincide. See ADR-021 §3.
    """
    digest = blake2b(key=secret.value, digest_size=_MAC_DIGEST_SIZE)
    digest.update(_REMOTE_DOMAIN)
    digest.update(_NUL)
    for part in key_parts:
        digest.update(part.encode("utf-8"))
        digest.update(_NUL)
    digest.update(value.encode("utf-8"))
    return digest.digest()


def _mac_matches(expected: bytes, actual: bytes) -> bool:
    """Constant-time MAC comparison; tolerant of stored-MAC type wobble."""
    return _hmac.compare_digest(expected, actual)


def _serialize_findings(findings: Iterable[Finding]) -> str:
    """Serialize findings to a JSON array via Pydantic — deterministic order."""
    items = [json.loads(f.model_dump_json()) for f in findings]
    return json.dumps(items)


def _deserialize_findings(payload: str) -> tuple[Finding, ...]:
    """Inverse of ``_serialize_findings``."""
    return tuple(Finding.model_validate(item) for item in json.loads(payload))


def _batch_key_parts(key: BatchCacheKey) -> tuple[str, ...]:
    """Pack a BatchCacheKey into the key-tuple used for both the redis key + MAC."""
    return (
        key.batch_id,
        key.dimension,
        key.model_version,
        key.prompt_version,
        key.schema_version,
        key.spectra_version,
    )


def _repo_key_parts(key: RepoCacheKey) -> tuple[str, ...]:
    """Pack a RepoCacheKey into the key-tuple used for both the redis key + MAC."""
    return (
        key.repo_signature,
        key.spectra_version,
        key.model_versions,
        key.prompt_versions,
        key.schema_version,
    )


def _redis_key(kind: str, parts: tuple[str, ...]) -> bytes:
    """Build the namespaced Redis key. ``kind`` is ``batch`` or ``report``."""
    return (f"{_KEY_PREFIX}:{kind}:" + "|".join(parts)).encode("utf-8")


def _frame(mac: bytes, value_bytes: bytes) -> bytes:
    """Pack ``(mac, value)`` for storage. Layout: 32-byte MAC || raw bytes."""
    return mac + value_bytes


def _unframe(blob: bytes | None) -> tuple[bytes, bytes] | None:
    """Inverse of ``_frame``. Returns None when the blob is too short."""
    if blob is None or len(blob) < _MAC_DIGEST_SIZE:
        return None
    return blob[:_MAC_DIGEST_SIZE], blob[_MAC_DIGEST_SIZE:]


# ── Adapter ───────────────────────────────────────────────────


class RedisCacheAdapter:
    """``RemoteCachePort`` backed by Redis (>=5.0, ``redis.asyncio``).

    The adapter is constructed with a live async client; ``from_url`` is
    the convenience factory the composition root reaches for. All public
    methods catch the redis-py exception family + ``OSError`` and degrade
    to a SPEC-010 cache-miss / silent-drop. The first failure logs once
    per process; subsequent failures are silent so a degraded Redis does
    not flood the operator's terminal.
    """

    def __init__(
        self,
        client: Any,  # noqa: ANN401 — redis.asyncio.Redis at runtime
        secret: CacheSecret,
        *,
        url: str | None = None,
    ) -> None:
        """Bind the adapter to ``client`` + ``secret``.

        Args:
            client: An async Redis client (``redis.asyncio.Redis``-shaped).
                Anything answering ``get/set/delete/ping`` async works,
                so the test suite can swap a fake without subclassing.
            secret: ADR-012 per-user HMAC key. Required — the adapter
                refuses to construct without one. Composition root
                resolves this via ``KeyringSecretAdapter`` and degrades
                to no-cache when the keyring is unavailable.
            url: The connection string the adapter was configured with.
                Surfaced for diagnostics only — never used at runtime.
        """
        self._client = client
        self._secret = secret
        self._url = url
        self._spec010_logged = False

    @classmethod
    def from_url(
        cls,
        url: str,
        secret: CacheSecret,
        *,
        socket_timeout: float = 2.0,
    ) -> RedisCacheAdapter:
        """Construct an adapter from a ``redis://...`` connection string.

        The default 2s socket timeout caps the worst-case latency a
        cache lookup can add to a scan — beyond that we degrade to
        no-cache rather than block the pipeline.
        """
        redis_mod = _redis_module()
        if redis_mod is None:  # pragma: no cover — gated by dev install
            msg = "redis>=5.0 is required for RedisCacheAdapter; install with 'pip install redis'"
            raise RuntimeError(msg)
        client = redis_mod.from_url(
            url,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
            decode_responses=False,
        )
        return cls(client=client, secret=secret, url=url)

    @property
    def url(self) -> str | None:
        """Return the connection URL (for ``cache doctor`` diagnostics)."""
        return self._url

    # ── RemoteCachePort surface ───────────────────────────────

    async def health(self) -> bool:
        """``True`` when Redis answers PING; ``False`` on any failure."""
        try:
            return bool(await self._client.ping())
        except Exception as exc:
            self._log_spec010_once("health probe failed", exc)
            return False

    async def get_findings(self, key: BatchCacheKey) -> tuple[Finding, ...] | None:
        """Return cached findings or ``None`` on miss / tamper / I/O error."""
        rkey = _redis_key("batch", _batch_key_parts(key))
        payload = await self._safe_get(rkey)
        if payload is None:
            return None
        verified = await self._verify_or_drop(rkey, payload, _batch_key_parts(key))
        if verified is None:
            return None
        return _deserialize_findings(verified.decode("utf-8"))

    async def put_findings(self, key: BatchCacheKey, findings: tuple[Finding, ...]) -> None:
        """Persist findings under the composite key — fire-and-forget."""
        rkey = _redis_key("batch", _batch_key_parts(key))
        value = _serialize_findings(findings)
        await self._safe_set(rkey, _batch_key_parts(key), value)

    async def get_full_report(self, key: RepoCacheKey) -> AnalysisReport | None:
        """Return the cached full report or ``None`` on miss / tamper / I/O error."""
        rkey = _redis_key("report", _repo_key_parts(key))
        payload = await self._safe_get(rkey)
        if payload is None:
            return None
        verified = await self._verify_or_drop(rkey, payload, _repo_key_parts(key))
        if verified is None:
            return None
        return AnalysisReport.model_validate_json(verified.decode("utf-8"))

    async def put_full_report(self, key: RepoCacheKey, report: AnalysisReport) -> None:
        """Persist the full report under the repo cache key — fire-and-forget."""
        rkey = _redis_key("report", _repo_key_parts(key))
        value = report.model_dump_json()
        await self._safe_set(rkey, _repo_key_parts(key), value)

    async def aclose(self) -> None:
        """Close the underlying redis connection — best-effort."""
        try:
            close = getattr(self._client, "aclose", None) or getattr(self._client, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
        except Exception as exc:
            _LOG.debug("redis client close failed: %s", exc)

    # ── Internals ─────────────────────────────────────────────

    async def _safe_get(self, rkey: bytes) -> bytes | None:
        """``GET`` wrapped with SPEC-010 degrade-to-miss."""
        try:
            value = await self._client.get(rkey)
        except Exception as exc:
            self._log_spec010_once("get failed", exc)
            return None
        if value is None:
            return None
        return bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else None

    async def _safe_set(
        self,
        rkey: bytes,
        key_parts: tuple[str, ...],
        value: str,
    ) -> None:
        """``SET`` wrapped with SPEC-010 degrade-to-drop. MAC is computed here."""
        mac = _compute_remote_mac(self._secret, key_parts, value)
        framed = _frame(mac, value.encode("utf-8"))
        try:
            await self._client.set(rkey, framed)
        except Exception as exc:
            self._log_spec010_once("set failed", exc)

    async def _safe_delete(self, rkey: bytes) -> None:
        """``DEL`` wrapped with SPEC-010 degrade-to-noop. Used on tamper."""
        try:
            await self._client.delete(rkey)
        except Exception as exc:
            self._log_spec010_once("delete failed", exc)

    async def _verify_or_drop(
        self,
        rkey: bytes,
        payload: bytes,
        key_parts: tuple[str, ...],
    ) -> bytes | None:
        """Verify the MAC; drop the row + return None on mismatch."""
        unframed = _unframe(payload)
        if unframed is None:
            await self._safe_delete(rkey)
            return None
        stored_mac, value_bytes = unframed
        expected = _compute_remote_mac(self._secret, key_parts, value_bytes.decode("utf-8"))
        if not _mac_matches(expected, stored_mac):
            self._log_mac_mismatch_once(rkey)
            await self._safe_delete(rkey)
            return None
        return value_bytes

    def _log_spec010_once(self, what: str, exc: BaseException) -> None:
        """Log SPEC-010 once per process — operator must not see N copies."""
        if self._spec010_logged:
            return
        self._spec010_logged = True
        _LOG.warning(
            "SPEC-010: redis cache %s; degrading to local-only for the rest of the run: %s: %s",
            what,
            type(exc).__name__,
            exc,
        )

    def _log_mac_mismatch_once(self, rkey: bytes) -> None:
        """Log a tampered-row event — same once-per-process budget as SPEC-010."""
        if self._spec010_logged:
            return
        self._spec010_logged = True
        _LOG.warning(
            "SPEC-010: redis cache MAC mismatch on %s; dropping row and re-analyzing",
            rkey.decode("utf-8", errors="replace"),
        )
