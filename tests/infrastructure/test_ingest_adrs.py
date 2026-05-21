"""Tests for the ADR scanner (v0.9.1, ADR-025 wiring §3).

Per the design doc §3, ADR ingest lives at Layer 4 (infrastructure)
because path globbing is a composition-root concern. The scanner takes
a workspace path, walks the conventional ADR locations, parses
title/status/date, and returns a tuple of ``MemoryEvent`` ready for
deposit through ``MemoryPort.append_event``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spectra.infrastructure.ingest_adrs import scan_adrs


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestScanAdrsHappyPath:
    def test_scans_docs_architecture_adr_directory(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "docs/architecture/adr/ADR-025-memory-port.md",
            "# ADR-025: Memory Port\n\n## Status\n\nProposed (2026-05-04)\n\n## Context\n\nQ3 made…",
        )
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert len(events) == 1
        evt = events[0]
        assert evt.kind == "adr_ingested"
        assert evt.payload["title"] == "ADR-025: Memory Port"
        assert evt.payload["status"] == "Proposed (2026-05-04)"
        assert evt.payload["adr_path"] == "docs/architecture/adr/ADR-025-memory-port.md"

    def test_scans_doc_adr_alternative_directory(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "doc/adr/0001-record-architecture-decisions.md",
            "# 1. Record architecture decisions\n\n## Status\n\nAccepted",
        )
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert len(events) == 1
        assert events[0].payload["title"] == "1. Record architecture decisions"

    def test_scans_docs_adrs_alternative_directory(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "docs/adrs/001-use-microservices.md",
            "# 001: Use microservices\n\n## Status\n\nDeprecated",
        )
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert len(events) == 1
        assert events[0].payload["status"] == "Deprecated"

    def test_returns_empty_when_no_adr_dirs_exist(self, tmp_path: Path) -> None:
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert events == ()

    def test_skips_non_markdown_files(self, tmp_path: Path) -> None:
        _write(tmp_path / "docs/architecture/adr/README.txt", "not an ADR")
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert events == ()

    def test_multiple_adrs_returned_in_path_order(self, tmp_path: Path) -> None:
        for n in (1, 25, 27):
            _write(
                tmp_path / f"docs/architecture/adr/ADR-{n:03d}-topic.md",
                f"# ADR-{n}\n\n## Status\n\nAccepted",
            )
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert len(events) == 3
        titles = [e.payload["title"] for e in events]
        assert "ADR-1" in titles
        assert "ADR-25" in titles
        assert "ADR-27" in titles


class TestScanAdrsMalformed:
    def test_missing_h1_falls_back_to_filename(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "docs/architecture/adr/ADR-099-no-h1.md",
            "Some text without an H1.\n\n## Status\n\nAccepted",
        )
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert len(events) == 1
        # Falls back to filename stem
        assert events[0].payload["title"] == "ADR-099-no-h1"

    def test_missing_status_section_yields_unknown(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "docs/architecture/adr/ADR-100-no-status.md",
            "# ADR-100\n\n## Context\n\nNo status section here.",
        )
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert len(events) == 1
        assert events[0].payload["status"] == "unknown"

    def test_empty_status_section_yields_unknown(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "docs/architecture/adr/ADR-101.md",
            "# ADR-101\n\n## Status\n\n\n## Context\n\nx",
        )
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert events[0].payload["status"] == "unknown"

    def test_body_excerpt_is_truncated_to_500_chars(self, tmp_path: Path) -> None:
        long_body = "abcde " * 200  # 1200 chars
        _write(
            tmp_path / "docs/architecture/adr/ADR-102.md",
            f"# ADR-102\n\n## Status\n\nAccepted\n\n## Context\n\n{long_body}",
        )
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert len(events[0].payload["body_excerpt"]) <= 500


class TestScanAdrsDate:
    def test_date_parsed_from_filename_yyyy_mm_dd(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "docs/architecture/adr/2026-05-04-memory-port.md",
            "# Memory Port\n\n## Status\n\nProposed",
        )
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert events[0].payload["date"] == "2026-05-04"

    def test_date_none_when_no_date_in_filename_or_body(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "docs/architecture/adr/ADR-200-no-date.md",
            "# A\n\n## Status\n\nAccepted",
        )
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert events[0].payload["date"] is None

    def test_date_parsed_from_status_line_with_iso_date(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "docs/architecture/adr/ADR-201.md",
            "# A\n\n## Status\n\nProposed (2026-05-04)",
        )
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert events[0].payload["date"] == "2026-05-04"


class TestScanAdrsIdempotency:
    def test_same_adr_path_yields_same_event_id(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "docs/architecture/adr/ADR-001.md",
            "# A\n\n## Status\n\nAccepted",
        )
        first = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        second = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert first[0].id == second[0].id


class TestScanAdrsFailureModes:
    def test_unreadable_adr_file_is_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Create a valid one and patch read_text on a sibling path to fail
        ok_path = tmp_path / "docs/architecture/adr/ADR-001.md"
        _write(ok_path, "# A\n\n## Status\n\nAccepted")
        bad_path = tmp_path / "docs/architecture/adr/ADR-002.md"
        _write(bad_path, "# B\n\n## Status\n\nAccepted")
        original_read = Path.read_text

        def fake_read(self: Path, *args: object, **kwargs: object) -> str:
            if "ADR-002" in str(self):
                raise OSError("simulated read failure")
            return original_read(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", fake_read)
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        # ADR-001 still parses; ADR-002 is skipped silently
        titles = [e.payload["title"] for e in events]
        assert "A" in titles
        assert "B" not in titles
