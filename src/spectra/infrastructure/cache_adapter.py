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
from spectra.entities.models import (
    AnalysisReport,
    BatchCacheKey,
    CacheStats,
    Finding,
    RepoCacheKey,
)

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
    hit       INTEGER NOT NULL,
    dimension TEXT NOT NULL DEFAULT '',
    batch_id  TEXT NOT NULL DEFAULT ''
)
"""

_HIT_LOG_LEGACY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("dimension", "ALTER TABLE hit_log ADD COLUMN dimension TEXT NOT NULL DEFAULT ''"),
    ("batch_id", "ALTER TABLE hit_log ADD COLUMN batch_id TEXT NOT NULL DEFAULT ''"),
)
"""Phase 4 hit_log migration steps. Each tuple is (column, ALTER stmt)."""

_CREATE_FULL_REPORT_TABLE = """
CREATE TABLE IF NOT EXISTS full_report_cache (
    repo_signature   TEXT NOT NULL,
    spectra_version  TEXT NOT NULL,
    model_versions   TEXT NOT NULL,
    prompt_versions  TEXT NOT NULL,
    schema_version   TEXT NOT NULL,
    report_json      TEXT NOT NULL,
    computed_at      TIMESTAMP NOT NULL,
    PRIMARY KEY (
        repo_signature,
        spectra_version,
        model_versions,
        prompt_versions,
        schema_version
    )
)
"""

_CREATE_BATCH_FINDINGS_TABLE = """
CREATE TABLE IF NOT EXISTS findings_batches (
    batch_id         TEXT NOT NULL,
    dimension        TEXT NOT NULL,
    model_version    TEXT NOT NULL,
    prompt_version   TEXT NOT NULL,
    schema_version   TEXT NOT NULL,
    spectra_version  TEXT NOT NULL,
    findings_json    TEXT NOT NULL,
    computed_at      TIMESTAMP NOT NULL,
    PRIMARY KEY (
        batch_id,
        dimension,
        model_version,
        prompt_version,
        schema_version,
        spectra_version
    )
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
        self._run_versions: tuple[str, str, str, str] | None = None
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
            self._conn.execute(_CREATE_FULL_REPORT_TABLE)
            self._conn.execute(_CREATE_BATCH_FINDINGS_TABLE)
            self._migrate_hit_log_columns()

    def _migrate_hit_log_columns(self) -> None:
        """Phase 4 ALTER TABLE: add dimension/batch_id to legacy hit_log rows."""
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(hit_log)")}
        for column, stmt in _HIT_LOG_LEGACY_COLUMNS:
            if column not in existing:
                self._conn.execute(stmt)

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

    # ── Phase 3: atomic run-context binding ───────────────────

    def bind_run_context(
        self,
        model_versions: str,
        prompt_versions: str,
        schema_version: str,
        spectra_version: str,
    ) -> None:
        """Atomically set the four versions used by every Phase 3 cache key.

        Eliminates the intermediate-inconsistent-state failure mode of
        the Phase 1 set_* setters: composition-root callers configure the
        cache exactly once at startup. Stored as a tuple so subsequent
        get/put inherit the four versions atomically.
        """
        self._run_versions = (
            model_versions,
            prompt_versions,
            schema_version,
            spectra_version,
        )

    def batch_key_for(
        self,
        batch_id: str,
        dimension: Dimension,
    ) -> BatchCacheKey | None:
        """Build a BatchCacheKey from the bound run context, or None."""
        if self._run_versions is None:
            return None
        return BatchCacheKey(
            batch_id=batch_id,
            dimension=dimension,
            model_version=self._run_versions[0],
            prompt_version=self._run_versions[1],
            schema_version=self._run_versions[2],
            spectra_version=self._run_versions[3],
        )

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
        """Return aggregate cache statistics with Phase 4 breakdowns."""
        with _guard_io():
            return self._build_stats()

    def _build_stats(self) -> CacheStats:
        """Compose the CacheStats payload — runs inside ``_guard_io``."""
        total_entries, total_repos, oldest = self._stats_row()
        return CacheStats(
            total_entries=total_entries,
            total_repos=total_repos,
            db_size_bytes=self._db_size_bytes(),
            hit_rate_last_100=self._hit_rate_last_100(),
            oldest_entry_at=oldest,
            full_report_entries=self._row_count("full_report_cache"),
            batch_entries=self._row_count("findings_batches"),
            hit_log_entries=self._row_count("hit_log"),
            hit_rate_by_dimension=self._hit_rate_by_dimension(),
            most_recent_activity_at=self._most_recent_activity(),
        )

    def _db_size_bytes(self) -> int:
        """Return the on-disk size of cache.db, 0 if the file is missing."""
        return self._db_path.stat().st_size if self._db_path.exists() else 0

    def compute_repo_signature(self, file_tree: tuple[str, ...]) -> str:
        """Deterministic blake2b signature of the file tree."""
        digest = blake2b(digest_size=16)
        for path in file_tree:
            digest.update(path.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()

    # ── Phase 2: full-report storage ──────────────────────────

    def get_full_report(self, key: RepoCacheKey) -> AnalysisReport | None:
        """Return the full ``AnalysisReport`` cached under ``key``, or ``None`` on miss."""
        with _guard_io():
            row = self._conn.execute(
                _SELECT_FULL_REPORT_SQL,
                _full_report_key_params(key),
            ).fetchone()
        if row is None:
            return None
        return AnalysisReport.model_validate_json(row[0])

    def put_full_report(self, key: RepoCacheKey, report: AnalysisReport) -> None:
        """Persist ``report`` under ``key`` for the Phase 2 short-circuit."""
        params = _full_report_upsert_params(key, report)
        with _guard_io():
            self._conn.execute(_UPSERT_FULL_REPORT_SQL, params)

    # ── Phase 3: per-batch findings storage ───────────────────

    def get_batch_findings(self, key: BatchCacheKey) -> tuple[Finding, ...] | None:
        """Return cached findings for ``key`` or ``None`` on miss."""
        with _guard_io():
            row = self._conn.execute(
                _SELECT_BATCH_FINDINGS_SQL,
                _batch_key_params(key),
            ).fetchone()
        if row is None:
            return None
        return _deserialize_findings(row[0])

    def put_batch_findings(
        self,
        key: BatchCacheKey,
        findings: tuple[Finding, ...],
    ) -> None:
        """Persist ``findings`` under the composite ``key`` (latest write wins)."""
        params = _batch_upsert_params(key, findings)
        with _guard_io():
            self._conn.execute(_UPSERT_BATCH_FINDINGS_SQL, params)

    def record_hit(
        self,
        dimension: Dimension,
        batch_id: str,
        hit: bool,
    ) -> None:
        """Append a row to ``hit_log`` — non-blocking telemetry."""
        with _guard_io():
            self._conn.execute(
                "INSERT INTO hit_log (ts, hit, dimension, batch_id) VALUES (?, ?, ?, ?)",
                (datetime.now(UTC), 1 if hit else 0, dimension, batch_id),
            )

    # ── Phase 4: cache-management operations ──────────────────

    def clear_all(self) -> int:
        """Purge every cache table including hit_log; return rows deleted."""
        with _guard_io():
            return sum(self._delete_all(table) for table in _ALL_TABLES_WITH_HIT_LOG)

    def clear_by_repo(self, repo_signature: str) -> int:
        """Purge rows tagged with ``repo_signature``; return rows deleted."""
        with _guard_io():
            return self._delete_by_repo(repo_signature)

    def prune_older_than(
        self,
        cutoff: datetime,
        include_hit_log: bool = False,
    ) -> dict[str, int]:
        """GC rows older than ``cutoff``; return per-table delete counts."""
        with _guard_io():
            return self._prune_tables(cutoff, include_hit_log=include_hit_log)

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

    def _row_count(self, table: str) -> int:
        """Return the row count for ``table`` (table name validated by allow-list)."""
        if table not in _ALL_TABLES_WITH_HIT_LOG:
            return 0
        sql = f"SELECT COUNT(*) FROM {table}"  # noqa: S608 — table is allow-listed above
        row = self._conn.execute(sql).fetchone()
        return int(row[0]) if row else 0

    def _most_recent_activity(self) -> datetime | None:
        """Return the latest computed_at across all data tables, or None."""
        candidates: list[datetime] = []
        for table in _ALL_TABLES:
            sql = f"SELECT MAX(computed_at) FROM {table}"  # noqa: S608 — _ALL_TABLES is a literal allow-list
            row = self._conn.execute(sql).fetchone()
            if row and row[0] is not None:
                candidates.append(row[0])
        return max(candidates) if candidates else None

    def _hit_rate_by_dimension(self) -> dict[Dimension, float]:
        """Return rolling per-dimension hit rates over the last 100 lookups each."""
        rows = self._conn.execute(_DIMENSIONS_IN_HIT_LOG_SQL).fetchall()
        result: dict[Dimension, float] = {}
        for (dim,) in rows:
            if dim not in _DIMENSION_VALUES:
                continue  # skip legacy '' rows from the migration
            result[dim] = self._dimension_hit_rate(dim)
        return result

    def _dimension_hit_rate(self, dimension: str) -> float:
        """Return the hit rate for one dimension over its last 100 lookups."""
        rows = self._conn.execute(_HIT_LOG_BY_DIM_SQL, (dimension,)).fetchall()
        if not rows:
            return 0.0
        return float(sum(int(r[0]) for r in rows)) / len(rows)

    def _delete_all(self, table: str) -> int:
        """Issue ``DELETE FROM <table>`` and return the row count."""
        if table not in _ALL_TABLES_WITH_HIT_LOG:
            return 0
        sql = f"DELETE FROM {table}"  # noqa: S608 — table is allow-listed above
        cursor = self._conn.execute(sql)
        return cursor.rowcount

    def _delete_by_repo(self, repo_signature: str) -> int:
        """Delete from findings_cache + full_report_cache by repo signature."""
        c1 = self._conn.execute(
            "DELETE FROM findings_cache WHERE repo_signature = ?",
            (repo_signature,),
        )
        c2 = self._conn.execute(
            "DELETE FROM full_report_cache WHERE repo_signature = ?",
            (repo_signature,),
        )
        return c1.rowcount + c2.rowcount

    def _prune_tables(
        self,
        cutoff: datetime,
        *,
        include_hit_log: bool,
    ) -> dict[str, int]:
        """Delete data-table rows older than cutoff; optionally hit_log too."""
        deleted = {table: self._prune_table(table, cutoff) for table in _ALL_TABLES}
        if include_hit_log:
            deleted["hit_log"] = self._prune_hit_log(cutoff)
        return deleted

    def _prune_table(self, table: str, cutoff: datetime) -> int:
        """Delete rows from ``table`` whose computed_at is older than cutoff."""
        if table not in _ALL_TABLES:
            return 0
        sql = f"DELETE FROM {table} WHERE computed_at < ?"  # noqa: S608 — _ALL_TABLES is a literal allow-list
        cursor = self._conn.execute(sql, (cutoff,))
        return cursor.rowcount

    def _prune_hit_log(self, cutoff: datetime) -> int:
        """Delete hit_log rows whose ts is older than cutoff."""
        cursor = self._conn.execute(
            "DELETE FROM hit_log WHERE ts < ?",
            (cutoff,),
        )
        return cursor.rowcount

    @property
    def db_path(self) -> Path:
        """Return the on-disk cache.db path (used by ``cache stats`` CLI)."""
        return self._db_path


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

_HIT_LOG_BY_DIM_SQL = """
SELECT hit FROM hit_log
WHERE dimension = ?
ORDER BY ts DESC
LIMIT 100
"""

_DIMENSIONS_IN_HIT_LOG_SQL = "SELECT DISTINCT dimension FROM hit_log WHERE dimension != ''"

# Tables that store user-data rows with a computed_at timestamp.
_ALL_TABLES: tuple[str, ...] = (
    "findings_cache",
    "full_report_cache",
    "findings_batches",
)
# All cache tables including telemetry — used for clear_all + counts.
_ALL_TABLES_WITH_HIT_LOG: tuple[str, ...] = (*_ALL_TABLES, "hit_log")
# Valid Dimension Literal values, used to filter legacy '' rows from
# hit_rate_by_dimension. Inlined to keep entities/ Layer 1 free of imports.
_DIMENSION_VALUES: frozenset[str] = frozenset(
    {
        "architecture",
        "security",
        "quality",
        "documentation",
        "maintainability",
        "performance",
    }
)

_SELECT_FULL_REPORT_SQL = """
SELECT report_json
FROM full_report_cache
WHERE repo_signature = ?
  AND spectra_version = ?
  AND model_versions = ?
  AND prompt_versions = ?
  AND schema_version = ?
"""

_UPSERT_FULL_REPORT_SQL = """
INSERT OR REPLACE INTO full_report_cache (
    repo_signature, spectra_version, model_versions,
    prompt_versions, schema_version, report_json, computed_at
) VALUES (?, ?, ?, ?, ?, ?, ?)
"""


def _full_report_key_params(key: RepoCacheKey) -> tuple[str, ...]:
    """Pack a RepoCacheKey into the lookup parameter tuple."""
    return (
        key.repo_signature,
        key.spectra_version,
        key.model_versions,
        key.prompt_versions,
        key.schema_version,
    )


def _full_report_upsert_params(
    key: RepoCacheKey,
    report: AnalysisReport,
) -> tuple[object, ...]:
    """Pack key + report into the upsert parameter tuple."""
    return (
        key.repo_signature,
        key.spectra_version,
        key.model_versions,
        key.prompt_versions,
        key.schema_version,
        report.model_dump_json(),
        datetime.now(UTC),
    )


_SELECT_BATCH_FINDINGS_SQL = """
SELECT findings_json
FROM findings_batches
WHERE batch_id = ?
  AND dimension = ?
  AND model_version = ?
  AND prompt_version = ?
  AND schema_version = ?
  AND spectra_version = ?
"""

_UPSERT_BATCH_FINDINGS_SQL = """
INSERT OR REPLACE INTO findings_batches (
    batch_id, dimension, model_version, prompt_version,
    schema_version, spectra_version, findings_json, computed_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


def _batch_key_params(key: BatchCacheKey) -> tuple[str, ...]:
    """Pack a BatchCacheKey into the lookup parameter tuple."""
    return (
        key.batch_id,
        key.dimension,
        key.model_version,
        key.prompt_version,
        key.schema_version,
        key.spectra_version,
    )


def _batch_upsert_params(
    key: BatchCacheKey,
    findings: tuple[Finding, ...],
) -> tuple[object, ...]:
    """Pack key + findings into the upsert parameter tuple."""
    return (
        key.batch_id,
        key.dimension,
        key.model_version,
        key.prompt_version,
        key.schema_version,
        key.spectra_version,
        _serialize_findings(findings),
        datetime.now(UTC),
    )


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
