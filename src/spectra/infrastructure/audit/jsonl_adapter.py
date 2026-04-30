"""JSON-Lines audit adapter — append-only file sink with daily rotation.

The sink is intentionally simple: one JSON object per line, UTC ISO
timestamps, no headers, no batching. ``logrotate`` (or any equivalent)
handles long-term rotation; we ship a minimal in-process daily roll so a
multi-day-running CI shard does not produce one giant file.

Failure model: I/O errors propagate up to ``safe_emit`` which logs at
DEBUG and swallows. Adapter never crashes the pipeline.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from spectra.entities.audit import AuditEvent


class JsonLinesAuditAdapter:
    """Append-only JSON-Lines audit sink.

    One event per line; rotated daily by renaming the current file with
    the previous day's date suffix when the first event of a new day
    arrives. The implementation is best-effort — any I/O error bubbles up
    to ``safe_emit``.
    """

    def __init__(self, path: Path) -> None:
        """Bind to ``path``; the file is created on first emit."""
        self._path = Path(path)
        self._current_date: date = datetime.now(UTC).date()

    @property
    def path(self) -> Path:
        """Currently active sink path."""
        return self._path

    async def emit(self, event: AuditEvent) -> None:
        """Append one JSON line for ``event`` to the active file."""
        self._maybe_rotate()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")

    async def flush(self) -> None:
        """No-op — the file handle is opened + closed per emit."""
        return

    def _maybe_rotate(self) -> None:
        """Rotate the file when the current calendar day differs from the bound date."""
        today = datetime.now(UTC).date()
        if today == self._current_date:
            return
        if self._path.exists():
            rotated = self._path.with_name(f"{self._path.name}.{self._current_date.isoformat()}")
            self._path.rename(rotated)
        self._current_date = today
