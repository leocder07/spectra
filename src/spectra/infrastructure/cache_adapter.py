"""SQLite cache adapter — Layer 4 implementation of ``CachePort``.

Caches per-file specialist findings in a single ``cache.db`` file under
``$XDG_CACHE_HOME/spectra/`` (default ``~/.cache/spectra/``). The
composite primary key — ``(file_hash, dimension, model_version,
prompt_version, schema_version)`` — makes invalidation a no-op: a stale
row simply never matches a current-context lookup, and physical deletion
is deferred to ``spectra cache prune`` (Phase 4).

WAL mode is set on connect so concurrent reads can proceed without
blocking writes. All fallible I/O is funnelled through ``_guard_io``,
which converts ``sqlite3.Error`` and ``OSError`` into ``AgentError``
carrying SPEC-010 — the use-case layer treats this as non-fatal and
degrades to no-cache.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import blake2b
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from spectra import __version__ as _SPECTRA_VERSION  # noqa: N812
from spectra.entities.enums import Dimension, SchemaVersion
from spectra.entities.errors import ERRORS, AgentError
from spectra.entities.models import CacheStats, Finding

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

# ── Module constants ──────────────────────────────────────────

SCHEMA_VERSION: SchemaVersion = "v1"
"""Current ``Finding`` schema version. Bump when shape changes."""

_REPO_SIGNATURE_HEX_LEN = 32  # blake2b digest_size=16 → 32 hex chars
_DEFAULT_MODEL_VERSION = "claude-opus-4-7"
_DEFAULT_PROMPT_VERSION = "default-v1"
_NO_REPO_SIGNATURE = "unknown"

_CREATE_FINDINGS_TABLE = """
CREATE TABLE IF NOT EXISTS findings_cache (
    file_hash         TEXT NOT NULL,
    dimension         TEXT NOT NULL,
    file_path         TEXT NOT NULL,
    findings_json     TEXT NOT NULL,
    model_version     TEXT NOT NULL,
    prompt_version    TEXT NOT NULL,
    spectra_version   TEXT NOT NULL,
    schema_version    TEXT NOT NULL,
    repo_signature    TEXT NOT NULL,
    computed_at       TIMESTAMP NOT NULL,
    PRIMARY KEY (file_hash, dimension, model_version, prompt_version, schema_version)
)
"""

_CREATE_REPO_INDEX = "CREATE INDEX IF NOT EXISTS idx_repo ON findings_cache(repo_signature)"
_CREATE_AGE_INDEX = "CREATE INDEX IF NOT EXISTS idx_age ON findings_cache(computed_at)"
_CREATE_HIT_LOG = """
CREATE TABLE IF NOT EXISTS hit_log (
    ts        TIMESTAMP NOT NULL,
    hit       INTEGER NOT NULL
)
"""


# ── Module-level helpers (single responsibility) ──────────────


class _PutCall(NamedTuple):
    """Internal value object packaging arguments to ``put_findings``.

    Keeps ``put_findings`` and ``_upsert_params`` within the
    three-parameter ceiling without bypassing the public port signature.
    """

    file_hash: str
    dimension: Dimension
    findings: tuple[Finding, ...]
    model_version: str
    prompt_version: str


def _serialize_findings(findings: tuple[Finding, ...]) -> str:
    """Serialize a tuple of findings to JSON via Pydantic."""
    items = [json.loads(f.model_dump_json()) for f in findings]
    return json.dumps(items)


def _deserialize_findings(payload: str) -> tuple[Finding, ...]:
    """Inverse of ``_serialize_findings``."""
    return tuple(Finding.model_validate(item) for item in json.loads(payload))


def _spec_010(cause: BaseException) -> AgentError:
    """Wrap any cache I/O failure as SPEC-010 (non-fatal at call sites)."""
    err = AgentError(ERRORS["SPEC-010"])
    err.__cause__ = cause
    return err


@contextmanager
def _guard_io() -> Iterator[None]:
    """Convert sqlite3/OS failures into ``AgentError`` SPEC-010."""
    try:
        yield
    except (sqlite3.Error, OSError) as exc:
        raise _spec_010(exc) from exc


# ── Adapter ───────────────────────────────────────────────────


class SqliteCacheAdapter:
    """SQLite-backed implementation of ``CachePort``.

    The adapter owns a single SQLite connection for the lifetime of the
    process. It also holds the *current-run context* — model version,
    per-dimension prompt versions, schema version, and repo signature —
    used to compose cache keys on read and write. Bumping any of these
    via the ``set_*`` methods invalidates affected rows on the next
    lookup without touching disk.
    """

    def __init__(self, db_path: Path) -> None:
        """Open ``db_path``, enable WAL, ensure schema exists."""
        self._db_path = db_path
        self._model_version = _DEFAULT_MODEL_VERSION
        self._prompt_versions: dict[str, str] = {}
        self._schema_version: SchemaVersion = SCHEMA_VERSION
        self._repo_signature = _NO_REPO_SIGNATURE
        self._conn = self._open_connection()
        self._init_schema()

    # ── Connection lifecycle ──────────────────────────────────

    def _open_connection(self) -> sqlite3.Connection:
        """Create parent dir, open SQLite, set WAL — all under SPEC-010."""
        with _guard_io():
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self._db_path),
                detect_types=sqlite3.PARSE_DECLTYPES,
                isolation_level=None,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            return conn

    def _init_schema(self) -> None:
        """Run CREATE TABLE/INDEX IF NOT EXISTS statements idempotently."""
        with _guard_io():
            self._conn.execute(_CREATE_FINDINGS_TABLE)
            self._conn.execute(_CREATE_REPO_INDEX)
            self._conn.execute(_CREATE_AGE_INDEX)
            self._conn.execute(_CREATE_HIT_LOG)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with _guard_io():
            self._conn.close()

    # ── Run-context setters (used by composition root + tests) ──

    def set_model_version(self, model_version: str) -> None:
        """Set the model identifier used for subsequent cache key lookups."""
        self._model_version = model_version

    def set_prompt_version(
        self,
        dimension: Dimension,
        prompt_version: str,
    ) -> None:
        """Set the prompt version for a specific dimension."""
        self._prompt_versions[dimension] = prompt_version

    def set_schema_version(self, schema_version: str) -> None:
        """Set the schema version (bumped when ``Finding`` shape changes)."""
        self._schema_version = schema_version  # type: ignore[assignment]

    def set_repo_signature(self, repo_signature: str) -> None:
        """Tag subsequent writes with the given repo signature."""
        self._repo_signature = repo_signature

    # ── Port methods ──────────────────────────────────────────

    def get_findings(
        self,
        file_hash: str,
        dimension: Dimension,
    ) -> tuple[Finding, ...] | None:
        """Return cached findings or ``None`` on miss."""
        params = self._lookup_key(file_hash, dimension)
        with _guard_io():
            row = self._conn.execute(_SELECT_FINDINGS_SQL, params).fetchone()
        if row is None:
            return None
        return _deserialize_findings(row[0])

    def _lookup_key(
        self,
        file_hash: str,
        dimension: Dimension,
    ) -> tuple[str, ...]:
        """Build the composite key tuple for a SELECT lookup."""
        return (
            file_hash,
            dimension,
            self._model_version,
            self._prompt_for(dimension),
            self._schema_version,
        )

    def put_findings(
        self,
        file_hash: str,
        dimension: Dimension,
        findings: tuple[Finding, ...],
        model_version: str,
        prompt_version: str,
    ) -> None:
        """Persist findings under the composite cache key."""
        params = self._upsert_params(
            _PutCall(
                file_hash=file_hash,
                dimension=dimension,
                findings=findings,
                model_version=model_version,
                prompt_version=prompt_version,
            ),
        )
        with _guard_io():
            self._conn.execute(_UPSERT_FINDINGS_SQL, params)

    def _upsert_params(self, call: _PutCall) -> tuple[object, ...]:
        """Build the parameter tuple for the upsert SQL."""
        return (
            call.file_hash,
            call.dimension,
            _first_file_path(call.findings),
            _serialize_findings(call.findings),
            call.model_version,
            call.prompt_version,
            _SPECTRA_VERSION,
            self._schema_version,
            self._repo_signature,
            datetime.now(UTC),
        )

    def clear(self, repo_signature: str | None = None) -> int:
        """Purge cache rows; return the count removed."""
        with _guard_io():
            if repo_signature is None:
                cursor = self._conn.execute("DELETE FROM findings_cache")
            else:
                cursor = self._conn.execute(
                    "DELETE FROM findings_cache WHERE repo_signature = ?",
                    (repo_signature,),
                )
            return cursor.rowcount

    def stats(self) -> CacheStats:
        """Return aggregate cache statistics."""
        with _guard_io():
            total_entries, total_repos, oldest = self._stats_row()
            db_size_bytes = self._db_path.stat().st_size if self._db_path.exists() else 0
        return CacheStats(
            total_entries=total_entries,
            total_repos=total_repos,
            db_size_bytes=db_size_bytes,
            hit_rate_last_100=self._hit_rate_last_100(),
            oldest_entry_at=oldest,
        )

    def compute_repo_signature(self, file_tree: tuple[str, ...]) -> str:
        """Deterministic blake2b signature of the file tree."""
        digest = blake2b(digest_size=16)
        for path in file_tree:
            digest.update(path.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()

    # ── Private helpers ───────────────────────────────────────

    def _prompt_for(self, dimension: Dimension) -> str:
        """Return the configured prompt version for a dimension."""
        return self._prompt_versions.get(dimension, _DEFAULT_PROMPT_VERSION)

    def _stats_row(self) -> tuple[int, int, datetime | None]:
        """Return (total_entries, total_repos, oldest_entry_at)."""
        row = self._conn.execute(_STATS_SQL).fetchone()
        if row is None or row[0] == 0:
            return 0, 0, None
        return int(row[0]), int(row[1]), row[2]

    def _hit_rate_last_100(self) -> float:
        """Return the rolling cache hit rate over the last 100 lookups."""
        rows = self._conn.execute(_HIT_LOG_SQL).fetchall()
        if not rows:
            return 0.0
        return sum(r[0] for r in rows) / len(rows)


# ── Module-level helpers (kept tiny, single-purpose) ──────────


def _first_file_path(findings: Iterable[Finding]) -> str:
    """Pick a representative file path for the cache row's ``file_path`` column."""
    for finding in findings:
        return finding.location.file_path
    return ""


# ── SQL string constants (kept at module bottom for legibility) ──

_SELECT_FINDINGS_SQL = """
SELECT findings_json
FROM findings_cache
WHERE file_hash = ?
  AND dimension = ?
  AND model_version = ?
  AND prompt_version = ?
  AND schema_version = ?
"""

_UPSERT_FINDINGS_SQL = """
INSERT OR REPLACE INTO findings_cache (
    file_hash, dimension, file_path, findings_json,
    model_version, prompt_version, spectra_version, schema_version,
    repo_signature, computed_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_STATS_SQL = """
SELECT COUNT(*), COUNT(DISTINCT repo_signature), MIN(computed_at)
FROM findings_cache
"""

_HIT_LOG_SQL = "SELECT hit FROM hit_log ORDER BY ts DESC LIMIT 100"


# ── SQLite type adapters (Python 3.12+ requires explicit registration) ──


def _adapt_datetime_iso(value: datetime) -> str:
    """Serialize datetime → ISO 8601 string for SQLite TIMESTAMP columns."""
    return value.isoformat()


def _convert_timestamp_iso(value: bytes) -> datetime:
    """Inverse of ``_adapt_datetime_iso`` for query results."""
    return datetime.fromisoformat(value.decode("utf-8"))


sqlite3.register_adapter(datetime, _adapt_datetime_iso)
sqlite3.register_converter("TIMESTAMP", _convert_timestamp_iso)


# ── Path resolution (XDG-respecting) ─────────────────────────


def default_cache_path() -> Path:
    """Return the default cache DB path under XDG_CACHE_HOME or ~/.cache."""
    base = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    return Path(base) / "spectra" / "cache.db"
