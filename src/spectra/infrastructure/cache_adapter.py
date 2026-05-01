"""SQLite cache adapter — Layer 4 implementation of ``CachePort``.

Caches per-file specialist findings in a single ``cache.db`` file under
``$XDG_CACHE_HOME/spectra/$UID/`` (default ``~/.cache/spectra/$UID/``).
The composite primary key — ``(file_hash, dimension, model_version,
prompt_version, schema_version)`` — makes invalidation a no-op: a stale
row simply never matches a current-context lookup, and physical deletion
is deferred to ``spectra cache prune`` (Phase 4).

WAL mode is set on connect so concurrent reads can proceed without
blocking writes. All fallible I/O is funnelled through ``_guard_io``,
which converts ``sqlite3.Error`` and ``OSError`` into ``AgentError``
carrying SPEC-010 — the use-case layer treats this as non-fatal and
degrades to no-cache.

ADR-012 — every persisted row carries a 32-byte ``blake2b`` HMAC over
the full cache-key tuple, the row payload, and the bound version tuple.
On read the adapter recomputes and constant-time-compares the MAC; a
mismatch drops the row and returns a cache miss. Combined with the
per-``$UID`` directory layout, this defends against cache poisoning on
shared dev hosts and CI runner images.

ADR references in this module: ADR-006 (cache port), ADR-012 (cache HMAC
+ per-user namespace). See ``docs/architecture/adr/`` and
``docs/glossary.md`` for the at-a-glance ADR index.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
import os
import secrets as _secrets
import sqlite3 as _stdlib_sqlite3
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from hashlib import blake2b
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from spectra import __version__ as _SPECTRA_VERSION  # noqa: N812
from spectra.entities.enums import Dimension, SchemaVersion
from spectra.entities.errors import ERRORS, AgentError
from spectra.entities.models import (
    AnalysisReport,
    BatchCacheKey,
    CacheSecret,
    CacheStats,
    Finding,
    RepoCacheKey,
)
from spectra.infrastructure.history.sqlite_repo_registry import (
    CREATE_PORTFOLIO_REPOS_SQL,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

# ── SQLCipher backend selection (Roadmap #13) ─────────────────
#
# pysqlcipher3 ships SQLCipher-flavoured ``sqlite3`` API symbols. When
# unavailable (no system libsqlcipher, Windows wheel gap, etc.) we fall
# back to the stdlib ``sqlite3`` module + log SPEC-010 once. The cache
# still works; HMAC still authenticates; only at-rest encryption is
# disabled. This degradation is documented in CHANGELOG and surfaced
# by ``spectra cache doctor`` so users see it.

try:
    from pysqlcipher3 import dbapi2 as _sqlcipher  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — exercised on platforms without SQLCipher
    _sqlcipher = None  # type: ignore[assignment, unused-ignore]


def is_sqlcipher_available() -> bool:
    """Return True when ``pysqlcipher3`` imports cleanly on this platform.

    Used by ``spectra cache doctor`` and the test suite's xfail marker so
    CI without SQLCipher still passes the rest of the cache tests.
    """
    return _sqlcipher is not None


_SQLCIPHER_FALLBACK_LOGGED = False

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
    mac               BLOB NOT NULL DEFAULT x'',
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
    mac              BLOB NOT NULL DEFAULT x'',
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
    mac              BLOB NOT NULL DEFAULT x'',
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

# ADR-012: tables that gain a per-row HMAC. (table, ALTER stmt) tuples
# applied at startup for caches created before the mac column existed.
_MAC_LEGACY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("findings_cache", "ALTER TABLE findings_cache ADD COLUMN mac BLOB NOT NULL DEFAULT x''"),
    ("full_report_cache", "ALTER TABLE full_report_cache ADD COLUMN mac BLOB NOT NULL DEFAULT x''"),
    ("findings_batches", "ALTER TABLE findings_batches ADD COLUMN mac BLOB NOT NULL DEFAULT x''"),
)
"""ADR-012 ALTER TABLE migration steps for legacy tables missing ``mac``."""

_LOG = logging.getLogger("spectra.cache")
_MAC_DIGEST_SIZE = 32
_NUL = b"\x00"

# ── SQLCipher key derivation (HKDF-SHA256) ────────────────────
#
# The encryption key is derived from the SAME per-user keyring secret
# that anchors the HMAC, but with a DIFFERENT HKDF info string so the
# two keys can never coincide. Reusing the HMAC bytes verbatim as a
# cipher key would weaken both: a single key compromise would break
# both authenticity AND confidentiality. HKDF-SHA256 with a 32-byte
# output gives a uniform AES-256-class key for SQLCipher.

_HKDF_INFO_ENCRYPTION = b"spectra-cache-encryption-v1"
_HKDF_OUT_LEN = 32  # 256-bit key — SQLCipher 4 default cipher is AES-256-CBC
_SQLCIPHER_PRAGMA_SALT = b"spectra-sqlcipher-salt-v1"
_SQLITE_HEADER_MAGIC = b"SQLite format 3\x00"


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


# ── ADR-012: HMAC helpers ─────────────────────────────────────


def _compute_mac(secret: CacheSecret, key_parts: tuple[str, ...], value: str) -> bytes:
    """Return ``blake2b`` MAC over the cache key tuple and serialized value.

    The MAC binds every persisted row to the per-user secret. Bumping any
    cache-key component, the value, or the secret produces a different
    MAC; ``compare_digest`` then rejects the row at lookup time.
    """
    digest = blake2b(key=secret.value, digest_size=_MAC_DIGEST_SIZE)
    for part in key_parts:
        digest.update(part.encode("utf-8"))
        digest.update(_NUL)
    digest.update(value.encode("utf-8"))
    return digest.digest()


def _mac_matches(expected: bytes, actual: object) -> bool:
    """Constant-time MAC comparison; tolerant of stored-MAC type wobble."""
    if not isinstance(actual, (bytes, bytearray, memoryview)):
        return False
    return _hmac.compare_digest(expected, bytes(actual))


# Per-table column lists for MAC re-computation during migration.
# Each entry maps table → (key_columns_in_order, payload_column).
_MAC_RECOMPUTE_KEYS: dict[str, tuple[tuple[str, ...], str]] = {
    "findings_cache": (
        ("file_hash", "dimension", "model_version", "prompt_version", "schema_version"),
        "findings_json",
    ),
    "full_report_cache": (
        ("repo_signature", "spectra_version", "model_versions", "prompt_versions", "schema_version"),
        "report_json",
    ),
    "findings_batches": (
        (
            "batch_id",
            "dimension",
            "model_version",
            "prompt_version",
            "schema_version",
            "spectra_version",
        ),
        "findings_json",
    ),
}


def _rekey_row(
    row: tuple[object, ...],
    col_names: tuple[str, ...],
    spec: tuple[tuple[str, ...], str],
    rekey_secret: CacheSecret,
) -> tuple[object, ...]:
    """Replace the ``mac`` column of ``row`` with one computed under ``rekey_secret``."""
    by_name = dict(zip(col_names, row, strict=True))
    key_cols, payload_col = spec
    key_parts = tuple(str(by_name[c]) for c in key_cols)
    payload = str(by_name[payload_col])
    by_name["mac"] = _compute_mac(rekey_secret, key_parts, payload)
    return tuple(by_name[c] for c in col_names)


def _sqlite_error_types() -> tuple[type[BaseException], ...]:
    """Return both stdlib ``sqlite3.Error`` and pysqlcipher3's flavour.

    pysqlcipher3 ships its own ``Error`` class hierarchy that does NOT
    inherit from ``sqlite3.Error`` (separate ``_sqlite3`` C ext build).
    We catch both so the same ``_guard_io`` works for both backends.
    """
    types: list[type[BaseException]] = [_stdlib_sqlite3.Error, OSError]
    if _sqlcipher is not None:
        types.append(_sqlcipher.Error)
    return tuple(types)


_SQLITE_ERROR_TYPES = _sqlite_error_types()


@contextmanager
def _guard_io() -> Iterator[None]:
    """Convert sqlite3/SQLCipher/OS failures into ``AgentError`` SPEC-010."""
    try:
        yield
    except _SQLITE_ERROR_TYPES as exc:
        raise _spec_010(exc) from exc


def _derive_encryption_key(secret: CacheSecret) -> str:
    """HKDF-derive a 32-byte SQLCipher key from the per-user HMAC secret.

    HKDF-SHA256(IKM=secret.value, salt=PRAGMA_SALT, info=ENCRYPTION_INFO,
    L=32). The output is rendered as a hex string so it can be passed
    through ``PRAGMA key='x"<hex>"'`` (SQLCipher's "raw key" form, which
    skips the built-in PBKDF2 derivation step — we already did the
    derivation, we don't want SQLCipher running PBKDF2 over our 32-byte
    HKDF output).
    """
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        secret.value,
        _SQLCIPHER_PRAGMA_SALT,
        iterations=4096,
        dklen=_HKDF_OUT_LEN,
    )
    # HKDF expand step would be cleaner here but pbkdf2_hmac is in
    # stdlib hashlib without needing ``cryptography``. Output is
    # equivalently uniform for our purpose: a 32-byte key derived from
    # an already-uniform 32-byte secret with a domain-separated salt.
    # Bind a final HKDF-style info-tagging round so the encryption key
    # cannot collide with any future HMAC output even if the underlying
    # PBKDF2 is reused.
    info_tagged = _hmac.new(derived, _HKDF_INFO_ENCRYPTION, hashlib.sha256).digest()
    return info_tagged.hex()


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

    def __init__(
        self,
        db_path: Path,
        secret: CacheSecret | None = None,
        *,
        _force_plaintext: bool = False,
    ) -> None:
        """Open ``db_path``, enable WAL, ensure schema exists.

        Roadmap #13 — when ``secret`` is supplied AND pysqlcipher3 is
        importable, the connection issues ``PRAGMA key=...`` immediately
        after open. The encryption key is derived from the same per-user
        keyring secret as the HMAC, but with a different HKDF info string
        so the two keys cannot collide.

        Backward-compat — if the on-disk file is a plaintext v0.5.0 cache
        (SQLite header magic present), the adapter migrates it into a
        fresh encrypted DB before continuing. The legacy file is shredded
        on success. Migration is one-shot and logs an INFO event.

        Failure mode — when pysqlcipher3 is unavailable we degrade to
        plain SQLite and log a one-time WARN. Cache still works; HMAC
        still active. Surfaced via ``encryption_status`` for ``cache
        doctor``.

        Args:
            db_path: SQLite cache file location (parent dirs auto-created).
            secret: Optional ADR-012 HMAC + roadmap-#13 encryption key.
                When ``None`` the adapter runs in legacy no-MAC mode.
            _force_plaintext: Internal flag — bypasses SQLCipher even when
                available. Used by backward-compat tests to seed a
                v0.5.0-shape cache, and by the SQLCipher-unavailable
                degradation path. Never set by application code.
        """
        self._db_path = db_path
        self._secret = secret
        self._model_version = _DEFAULT_MODEL_VERSION
        self._prompt_versions: dict[str, str] = {}
        self._schema_version: SchemaVersion = SCHEMA_VERSION
        self._repo_signature = _NO_REPO_SIGNATURE
        self._run_versions: tuple[str, str, str, str] | None = None
        self._mac_failures = 0
        self._encryption_status = self._select_encryption_status(
            secret=secret,
            force_plaintext=_force_plaintext,
        )
        self._maybe_migrate_unencrypted()
        self._conn = self._open_connection()
        self._init_schema()

    # ── Connection lifecycle ──────────────────────────────────

    def _select_encryption_status(
        self,
        *,
        secret: CacheSecret | None,
        force_plaintext: bool,
    ) -> str:
        """Pick one of ``sqlcipher`` / ``plain`` based on platform + caller intent."""
        if force_plaintext or secret is None:
            return "plain"
        if not is_sqlcipher_available():
            self._log_sqlcipher_fallback_once()
            return "plain"
        return "sqlcipher"

    @staticmethod
    def _log_sqlcipher_fallback_once() -> None:
        """Emit a single WARN per process when pysqlcipher3 is missing."""
        global _SQLCIPHER_FALLBACK_LOGGED  # noqa: PLW0603
        if _SQLCIPHER_FALLBACK_LOGGED:
            return
        _LOG.warning(
            "SPEC-010: pysqlcipher3 unavailable; cache falling back to plain SQLite "
            "(HMAC still active). Install pysqlcipher3 to enable at-rest encryption.",
        )
        _SQLCIPHER_FALLBACK_LOGGED = True

    def _open_connection(self) -> Any:  # noqa: ANN401 — backend type varies
        """Create parent dir 0700, open SQLite/SQLCipher, chmod 0600, set WAL.

        ADR-012 — the parent directory is restricted to the owning user
        and the cache file (plus its WAL/SHM siblings) are tightened to
        owner read/write only. Permission tightening is best-effort on
        platforms where ``chmod`` is a no-op (Windows).

        Roadmap #13 — when ``encryption_status == 'sqlcipher'`` the
        connection is opened via pysqlcipher3 and ``PRAGMA key`` is
        applied immediately. A canary ``SELECT count(*) FROM
        sqlite_master`` confirms the key matches the on-disk DB; a
        mismatch raises SPEC-010 so the caller can decide whether to
        degrade or surface.
        """
        with _guard_io():
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._tighten_dir_perms()
            conn = self._connect_for_status()
            conn.execute("PRAGMA journal_mode=WAL")
            self._tighten_db_perms()
            return conn

    def _connect_for_status(self) -> Any:  # noqa: ANN401 — backend type varies
        """Dispatch to the SQLCipher or plain connector based on status."""
        if self._encryption_status == "sqlcipher":
            return self._connect_encrypted()
        return self._connect_plain()

    def _connect_plain(self) -> Any:  # noqa: ANN401 — sqlite3.Connection
        """Open the cache via stdlib ``sqlite3``."""
        return _stdlib_sqlite3.connect(
            str(self._db_path),
            detect_types=_stdlib_sqlite3.PARSE_DECLTYPES,
            isolation_level=None,
        )

    def _connect_encrypted(self) -> Any:  # noqa: ANN401 — pysqlcipher3 connection
        """Open the cache via pysqlcipher3 and apply ``PRAGMA key``.

        Raises SPEC-010 when the supplied key does not decrypt the file.
        """
        assert _sqlcipher is not None  # status check guards this  # noqa: S101
        assert self._secret is not None  # noqa: S101
        conn = _sqlcipher.connect(
            str(self._db_path),
            detect_types=_sqlcipher.PARSE_DECLTYPES,
            isolation_level=None,
        )
        key_hex = _derive_encryption_key(self._secret)
        # ``x"<hex>"`` is the SQLCipher raw-key form: pass our HKDF
        # output through verbatim, skipping SQLCipher's internal PBKDF2.
        conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        # Force the cipher header to load — wrong key surfaces here.
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn

    def _maybe_migrate_unencrypted(self) -> None:
        """Detect a v0.5.0 plaintext cache and migrate it into encrypted form.

        Heuristic: file exists, encryption is requested, and the first
        16 bytes match the SQLite magic header (``SQLite format 3\\x00``).
        SQLCipher-encrypted files start with random bytes (the salt), so
        any header match is a strong signal we are looking at a legacy
        unencrypted cache, not a corrupted encrypted one.
        """
        if self._encryption_status != "sqlcipher":
            return
        if not self._db_path.exists():
            return
        try:
            header = self._db_path.read_bytes()[:16]
        except OSError:
            return
        if header != _SQLITE_HEADER_MAGIC:
            return  # already encrypted (or empty); nothing to do

        _LOG.info(
            "Migrating plaintext cache %s to SQLCipher (one-time, lossless)",
            self._db_path,
        )
        self._migrate_plaintext_to_encrypted()

    def _migrate_plaintext_to_encrypted(self) -> None:
        """Copy every row from a plaintext DB into a fresh encrypted DB.

        We read the source via stdlib ``sqlite3`` (the source IS plain
        SQLite) and write into a freshly created encrypted SQLCipher DB
        opened by pysqlcipher3 with our HKDF-derived key. The encrypted
        target is created at ``<db>.migrating``, atomically swapped into
        place via ``Path.replace``, and the plaintext is shredded
        post-swap so a partial migration cannot leave both files visible.

        MAC re-computation: rows in a v0.5.0 cache were either MAC-less
        (no secret bound) or MAC'd under a *previous* secret. After
        migration, every row carries a MAC computed under the *current*
        per-user secret — otherwise the first read would HMAC-fail and
        drop the row. The migration is the intentional re-key boundary.
        """
        assert _sqlcipher is not None  # noqa: S101
        assert self._secret is not None  # noqa: S101
        target = self._db_path.with_name(self._db_path.name + ".migrating")
        if target.exists():
            target.unlink()  # stale half-migration from a prior crash

        plain_conn = _stdlib_sqlite3.connect(str(self._db_path), isolation_level=None)
        encrypted_conn = self._open_encrypted_target(target)
        try:
            self._copy_user_tables(
                src=plain_conn,
                dst=encrypted_conn,
                rekey_secret=self._secret,
            )
        finally:
            encrypted_conn.close()
            plain_conn.close()

        # Atomic swap: target → db_path. Plaintext shredded on success.
        plaintext_backup = self._db_path.with_name(self._db_path.name + ".plain.bak")
        self._db_path.replace(plaintext_backup)
        target.replace(self._db_path)
        shred_cache_file(plaintext_backup, passes=3)

    def _open_encrypted_target(self, target: Path) -> Any:  # noqa: ANN401
        """Create + key a fresh encrypted SQLCipher DB at ``target``."""
        assert _sqlcipher is not None  # noqa: S101
        assert self._secret is not None  # noqa: S101
        conn = _sqlcipher.connect(
            str(target),
            detect_types=_sqlcipher.PARSE_DECLTYPES,
            isolation_level=None,
        )
        key_hex = _derive_encryption_key(self._secret)
        conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _copy_user_tables(
        *,
        src: Any,  # noqa: ANN401
        dst: Any,  # noqa: ANN401
        rekey_secret: CacheSecret,
    ) -> None:
        """Recreate every user table on ``dst`` and stream rows from ``src``.

        Every row in a MAC-bearing table has its MAC re-computed under
        ``rekey_secret`` so the migrated cache reads cleanly under the
        current per-user keyring secret.
        """
        rows = src.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        ).fetchall()
        for name, ddl in rows:
            dst.execute(ddl)
            SqliteCacheAdapter._copy_one_table(
                src=src,
                dst=dst,
                table=name,
                rekey_secret=rekey_secret,
            )

    @staticmethod
    def _copy_one_table(
        *,
        src: Any,  # noqa: ANN401
        dst: Any,  # noqa: ANN401
        table: str,
        rekey_secret: CacheSecret,
    ) -> None:
        """Stream rows from ``src.<table>`` into ``dst.<table>``, re-MACing if needed."""
        # Table name is from sqlite_master — never user input — safe to interpolate.
        cursor = src.execute(f"SELECT * FROM {table}")  # noqa: S608
        descriptions = cursor.description or ()
        col_count = len(descriptions)
        if col_count == 0:
            return
        col_names = tuple(d[0] for d in descriptions)
        placeholders = ",".join("?" * col_count)
        insert_sql = f"INSERT INTO {table} VALUES ({placeholders})"  # noqa: S608
        recompute = _MAC_RECOMPUTE_KEYS.get(table)
        for row in cursor.fetchall():
            new_row = _rekey_row(row, col_names, recompute, rekey_secret) if recompute is not None else row
            dst.execute(insert_sql, new_row)

    def _tighten_dir_perms(self) -> None:
        """``chmod 0700`` the cache parent directory; ignore if unsupported."""
        with suppress(OSError, NotImplementedError):
            self._db_path.parent.chmod(0o700)

    def _tighten_db_perms(self) -> None:
        """``chmod 0600`` the cache.db (and WAL/SHM if present)."""
        for suffix in ("", "-wal", "-shm"):
            target = self._db_path.with_name(self._db_path.name + suffix)
            if target.exists():
                with suppress(OSError, NotImplementedError):
                    target.chmod(0o600)

    def _init_schema(self) -> None:
        """Run CREATE TABLE/INDEX IF NOT EXISTS statements idempotently."""
        with _guard_io():
            self._conn.execute(_CREATE_FINDINGS_TABLE)
            self._conn.execute(_CREATE_REPO_INDEX)
            self._conn.execute(_CREATE_AGE_INDEX)
            self._conn.execute(_CREATE_HIT_LOG)
            self._conn.execute(_CREATE_FULL_REPORT_TABLE)
            self._conn.execute(_CREATE_BATCH_FINDINGS_TABLE)
            # #26 — co-locate the portfolio registry table on cache.db so
            # one backup/encryption story covers both. The DDL is owned by
            # ``sqlite_repo_registry``; we just apply it here for the
            # composition-root path that opens the cache connection first.
            self._conn.execute(CREATE_PORTFOLIO_REPOS_SQL)
            self._migrate_hit_log_columns()
            self._migrate_mac_columns()

    def _migrate_hit_log_columns(self) -> None:
        """Phase 4 ALTER TABLE: add dimension/batch_id to legacy hit_log rows."""
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(hit_log)")}
        for column, stmt in _HIT_LOG_LEGACY_COLUMNS:
            if column not in existing:
                self._conn.execute(stmt)

    def _migrate_mac_columns(self) -> None:
        """ADR-012 ALTER TABLE: add ``mac BLOB`` to pre-HMAC cache tables."""
        for table, stmt in _MAC_LEGACY_COLUMNS:
            # PRAGMA accepts unquoted identifiers only — table names come
            # from the literal allow-list ``_MAC_LEGACY_COLUMNS`` above.
            cols = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if "mac" not in cols:
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
        """Return cached findings or ``None`` on miss.

        ADR-012 — when a per-user secret is bound, the row's MAC is
        recomputed from the cache key plus stored payload and compared
        with ``hmac.compare_digest``. A mismatch deletes the row and
        returns a miss; the run proceeds with a fresh analysis.
        """
        params = self._lookup_key(file_hash, dimension)
        with _guard_io():
            row = self._conn.execute(_SELECT_FINDINGS_SQL, params).fetchone()
        if row is None:
            return None
        if not self._verify_findings_mac(params, row):
            return None
        return _deserialize_findings(row[0])

    def _verify_findings_mac(
        self,
        params: tuple[str, ...],
        row: tuple[object, ...],
    ) -> bool:
        """Validate the per-row HMAC; drop the row + log on mismatch."""
        if self._secret is None:
            return True
        expected = _compute_mac(self._secret, params, str(row[0]))
        if _mac_matches(expected, row[1]):
            return True
        self._drop_tampered_row(_DELETE_FINDINGS_BY_KEY_SQL, params, table="findings_cache")
        return False

    def _drop_tampered_row(
        self,
        delete_sql: str,
        params: tuple[str, ...],
        *,
        table: str,
    ) -> None:
        """Delete a row that failed MAC verification + log SPEC-010."""
        self._mac_failures += 1
        _LOG.warning(
            "SPEC-010: cache MAC mismatch on %s; dropping row and re-analyzing",
            table,
        )
        with _guard_io():
            self._conn.execute(delete_sql, params)

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
        """Build the parameter tuple for the upsert SQL (incl. ADR-012 mac)."""
        payload = _serialize_findings(call.findings)
        key = (
            call.file_hash,
            call.dimension,
            call.model_version,
            call.prompt_version,
            self._schema_version,
        )
        mac = _compute_mac(self._secret, key, payload) if self._secret else b""
        return (
            call.file_hash,
            call.dimension,
            _first_file_path(call.findings),
            payload,
            call.model_version,
            call.prompt_version,
            _SPECTRA_VERSION,
            self._schema_version,
            self._repo_signature,
            datetime.now(UTC),
            mac,
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
            return int(cursor.rowcount)

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
        params = _full_report_key_params(key)
        with _guard_io():
            row = self._conn.execute(_SELECT_FULL_REPORT_SQL, params).fetchone()
        if row is None:
            return None
        if not self._verify_full_report_mac(params, row):
            return None
        return AnalysisReport.model_validate_json(row[0])

    def _verify_full_report_mac(
        self,
        params: tuple[str, ...],
        row: tuple[object, ...],
    ) -> bool:
        """Validate the per-row HMAC for full_report_cache; drop on mismatch."""
        if self._secret is None:
            return True
        expected = _compute_mac(self._secret, params, str(row[0]))
        if _mac_matches(expected, row[1]):
            return True
        self._drop_tampered_row(_DELETE_FULL_REPORT_BY_KEY_SQL, params, table="full_report_cache")
        return False

    def put_full_report(self, key: RepoCacheKey, report: AnalysisReport) -> None:
        """Persist ``report`` under ``key`` for the Phase 2 short-circuit."""
        params = _full_report_upsert_params(key, report, self._secret)
        with _guard_io():
            self._conn.execute(_UPSERT_FULL_REPORT_SQL, params)

    # ── Phase 3: per-batch findings storage ───────────────────

    def get_batch_findings(self, key: BatchCacheKey) -> tuple[Finding, ...] | None:
        """Return cached findings for ``key`` or ``None`` on miss."""
        params = _batch_key_params(key)
        with _guard_io():
            row = self._conn.execute(_SELECT_BATCH_FINDINGS_SQL, params).fetchone()
        if row is None:
            return None
        if not self._verify_batch_findings_mac(params, row):
            return None
        return _deserialize_findings(row[0])

    def _verify_batch_findings_mac(
        self,
        params: tuple[str, ...],
        row: tuple[object, ...],
    ) -> bool:
        """Validate the per-row HMAC for findings_batches; drop on mismatch."""
        if self._secret is None:
            return True
        expected = _compute_mac(self._secret, params, str(row[0]))
        if _mac_matches(expected, row[1]):
            return True
        self._drop_tampered_row(_DELETE_BATCH_FINDINGS_BY_KEY_SQL, params, table="findings_batches")
        return False

    def put_batch_findings(
        self,
        key: BatchCacheKey,
        findings: tuple[Finding, ...],
    ) -> None:
        """Persist ``findings`` under the composite ``key`` (latest write wins)."""
        params = _batch_upsert_params(key, findings, self._secret)
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
        return sum(int(r[0]) for r in rows) / len(rows)

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
        return int(cursor.rowcount)

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
        return int(c1.rowcount) + int(c2.rowcount)

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
        return int(cursor.rowcount)

    def _prune_hit_log(self, cutoff: datetime) -> int:
        """Delete hit_log rows whose ts is older than cutoff."""
        cursor = self._conn.execute(
            "DELETE FROM hit_log WHERE ts < ?",
            (cutoff,),
        )
        return int(cursor.rowcount)

    @property
    def db_path(self) -> Path:
        """Return the on-disk cache.db path (used by ``cache stats`` CLI)."""
        return self._db_path

    @property
    def has_secret(self) -> bool:
        """True when ADR-012 HMAC enforcement is active for this adapter."""
        return self._secret is not None

    @property
    def encryption_status(self) -> str:
        """Return ``sqlcipher`` or ``plain`` for ``cache doctor`` (Roadmap #13)."""
        return self._encryption_status

    # ── ADR-012: cache doctor diagnostics ─────────────────────

    def count_rows(self) -> dict[str, dict[str, int]]:
        """Return per-table totals + verified/failed MAC counts.

        Powers ``spectra cache doctor``. When no secret is bound (legacy
        mode) every row counts as ``verified`` since MAC is not enforced.
        """
        with _guard_io():
            return {table: self._count_table(table) for table in _ALL_TABLES}

    def _count_table(self, table: str) -> dict[str, int]:
        """Walk one cache table, classifying each row by MAC verification."""
        if table == "findings_cache":
            return self._count_findings_cache()
        if table == "full_report_cache":
            return self._count_full_report_cache()
        if table == "findings_batches":
            return self._count_findings_batches()
        return {"total": 0, "verified": 0, "failed": 0}

    def _count_findings_cache(self) -> dict[str, int]:
        """Verify every row in findings_cache against its stored MAC."""
        rows = self._conn.execute(
            "SELECT file_hash, dimension, model_version, prompt_version, "
            "schema_version, findings_json, mac FROM findings_cache",
        ).fetchall()
        return self._tally_rows(rows, key_width=5)

    def _count_full_report_cache(self) -> dict[str, int]:
        """Verify every row in full_report_cache against its stored MAC."""
        rows = self._conn.execute(
            "SELECT repo_signature, spectra_version, model_versions, "
            "prompt_versions, schema_version, report_json, mac FROM full_report_cache",
        ).fetchall()
        return self._tally_rows(rows, key_width=5)

    def _count_findings_batches(self) -> dict[str, int]:
        """Verify every row in findings_batches against its stored MAC."""
        rows = self._conn.execute(
            "SELECT batch_id, dimension, model_version, prompt_version, "
            "schema_version, spectra_version, findings_json, mac FROM findings_batches",
        ).fetchall()
        return self._tally_rows(rows, key_width=6)

    def _tally_rows(
        self,
        rows: list[tuple[object, ...]],
        *,
        key_width: int,
    ) -> dict[str, int]:
        """Bucket ``rows`` into total / verified / failed by MAC verification."""
        verified = sum(1 for r in rows if self._row_mac_ok(r, key_width=key_width))
        return {"total": len(rows), "verified": verified, "failed": len(rows) - verified}

    def _row_mac_ok(self, row: tuple[object, ...], *, key_width: int) -> bool:
        """Recompute the MAC for one row and compare to the stored value."""
        if self._secret is None:
            return True
        key_parts = tuple(str(p) for p in row[:key_width])
        payload = str(row[key_width])
        stored_mac = row[key_width + 1]
        expected = _compute_mac(self._secret, key_parts, payload)
        return _mac_matches(expected, stored_mac)


# ── Module-level helpers (kept tiny, single-purpose) ──────────


def _first_file_path(findings: Iterable[Finding]) -> str:
    """Pick a representative file path for the cache row's ``file_path`` column."""
    for finding in findings:
        return finding.location.file_path
    return ""


# ── SQL string constants (kept at module bottom for legibility) ──

_SELECT_FINDINGS_SQL = """
SELECT findings_json, mac
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
    repo_signature, computed_at, mac
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_DELETE_FINDINGS_BY_KEY_SQL = """
DELETE FROM findings_cache
WHERE file_hash = ?
  AND dimension = ?
  AND model_version = ?
  AND prompt_version = ?
  AND schema_version = ?
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
SELECT report_json, mac
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
    prompt_versions, schema_version, report_json, computed_at, mac
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

_DELETE_FULL_REPORT_BY_KEY_SQL = """
DELETE FROM full_report_cache
WHERE repo_signature = ?
  AND spectra_version = ?
  AND model_versions = ?
  AND prompt_versions = ?
  AND schema_version = ?
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
    secret: CacheSecret | None,
) -> tuple[object, ...]:
    """Pack key + report (+ ADR-012 mac) into the upsert parameter tuple."""
    payload = report.model_dump_json()
    key_parts = _full_report_key_params(key)
    mac = _compute_mac(secret, key_parts, payload) if secret else b""
    return (
        key.repo_signature,
        key.spectra_version,
        key.model_versions,
        key.prompt_versions,
        key.schema_version,
        payload,
        datetime.now(UTC),
        mac,
    )


_SELECT_BATCH_FINDINGS_SQL = """
SELECT findings_json, mac
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
    schema_version, spectra_version, findings_json, computed_at, mac
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_DELETE_BATCH_FINDINGS_BY_KEY_SQL = """
DELETE FROM findings_batches
WHERE batch_id = ?
  AND dimension = ?
  AND model_version = ?
  AND prompt_version = ?
  AND schema_version = ?
  AND spectra_version = ?
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
    secret: CacheSecret | None,
) -> tuple[object, ...]:
    """Pack key + findings (+ ADR-012 mac) into the upsert parameter tuple."""
    payload = _serialize_findings(findings)
    key_parts = _batch_key_params(key)
    mac = _compute_mac(secret, key_parts, payload) if secret else b""
    return (
        key.batch_id,
        key.dimension,
        key.model_version,
        key.prompt_version,
        key.schema_version,
        key.spectra_version,
        payload,
        datetime.now(UTC),
        mac,
    )


# ── SQLite type adapters (Python 3.12+ requires explicit registration) ──


def _adapt_datetime_iso(value: datetime) -> str:
    """Serialize datetime → ISO 8601 string for SQLite TIMESTAMP columns."""
    return value.isoformat()


def _convert_timestamp_iso(value: bytes) -> datetime:
    """Inverse of ``_adapt_datetime_iso`` for query results."""
    return datetime.fromisoformat(value.decode("utf-8"))


_stdlib_sqlite3.register_adapter(datetime, _adapt_datetime_iso)
_stdlib_sqlite3.register_converter("TIMESTAMP", _convert_timestamp_iso)
if _sqlcipher is not None:  # pragma: no cover — branch tied to platform
    _sqlcipher.register_adapter(datetime, _adapt_datetime_iso)
    _sqlcipher.register_converter("TIMESTAMP", _convert_timestamp_iso)


# ── Path resolution (XDG-respecting, ADR-012 per-UID) ────────


def _spectra_cache_root() -> Path:
    """Return the unscoped Spectra cache root (the parent of the per-UID dir)."""
    base = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    return Path(base) / "spectra"


def _current_uid_segment() -> str:
    """Return the effective UID rendered as a decimal string.

    On Linux/macOS uses ``os.geteuid()``. Windows lacks the syscall,
    so we fall back to ``"win"`` — the keyring-only secret remains the
    integrity boundary, but per-user file isolation degrades to a single
    shared dir until SPEC-010 is wired through composition root.
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return "win"
    return str(geteuid())


def default_cache_path() -> Path:
    """Return the default cache DB path: ``$XDG/spectra/$UID/cache.db`` (ADR-012)."""
    return _spectra_cache_root() / _current_uid_segment() / "cache.db"


def legacy_cache_path() -> Path:
    """Return the pre-ADR-012 unscoped path: ``$XDG/spectra/cache.db``."""
    return _spectra_cache_root() / "cache.db"


def migrate_legacy_cache() -> bool:
    """Drop the pre-ADR-012 cache.db at the unscoped path.

    Returns True when an old cache existed and was removed. The deletion
    is intentional — re-keying the entire DB under the freshly generated
    per-user secret would be more work than the warm cache is worth, and
    the next run cold-caches naturally.
    """
    old = legacy_cache_path()
    if not old.exists():
        return False
    try:
        old.unlink()
        # Best-effort cleanup of WAL/SHM siblings.
        for suffix in ("-wal", "-shm", "-journal"):
            sibling = old.with_name(old.name + suffix)
            if sibling.exists():
                sibling.unlink()
    except OSError as exc:
        _LOG.warning("SPEC-010: legacy cache removal failed: %s", exc)
        return False
    return True


# ── Roadmap #13: Cache shred helpers ─────────────────────────


_SHRED_CHUNK = 64 * 1024  # 64 KiB random-fill chunks


def shred_cache_file(db_path: Path, *, passes: int = 3) -> None:
    """Overwrite cache.db with random bytes ``passes`` times, then unlink.

    Best-effort secure deletion: the standard caveats apply (journaling
    filesystems, SSD wear-levelling, COW snapshots can preserve previous
    pages). The aim is "no plaintext findings on the active block list",
    not military-grade sanitisation.

    Always processes the WAL + SHM siblings too; missing files are
    silently skipped so the function is safe to call on a cold cache.
    """
    targets = [db_path] + [db_path.with_name(db_path.name + suffix) for suffix in ("-wal", "-shm", "-journal")]
    for target in targets:
        if not target.exists():
            continue
        _overwrite_then_unlink(target, passes=passes)


def _overwrite_then_unlink(target: Path, *, passes: int) -> None:
    """Overwrite ``target`` with random bytes ``passes`` times then delete."""
    try:
        size = target.stat().st_size
    except OSError:
        return
    try:
        with target.open("r+b") as handle:
            for _ in range(passes):
                handle.seek(0)
                _write_random_bytes(handle, size)
                handle.flush()
                os.fsync(handle.fileno())
        target.unlink()
    except OSError as exc:
        _LOG.warning("SPEC-010: shred of %s failed: %s", target, exc)


def _write_random_bytes(handle: Any, size: int) -> None:  # noqa: ANN401 — file handle
    """Write ``size`` random bytes to ``handle`` in 64 KiB chunks."""
    remaining = size
    while remaining > 0:
        chunk = min(_SHRED_CHUNK, remaining)
        handle.write(_secrets.token_bytes(chunk))
        remaining -= chunk
