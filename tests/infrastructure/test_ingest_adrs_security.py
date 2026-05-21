"""Adversarial tests for ADR scanner (PR #90 sec review HIGH).

A hostile repo must NOT be able to use symlinks to exfiltrate host files
into the memory DB, nor flood the scanner with giant or numerous files.
"""

from __future__ import annotations

import os
from pathlib import Path

from spectra.infrastructure.ingest_adrs import scan_adrs


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestSymlinkRejection:
    def test_symlinked_adr_directory_is_skipped(self, tmp_path: Path) -> None:
        # Hostile repo: docs/architecture/adr -> /tmp/host-secrets
        host_secrets = tmp_path / "host-secrets"
        host_secrets.mkdir()
        _write(host_secrets / "secret.md", "# SECRET TOKEN abc123\n\n## Status\n\nAccepted")

        workspace = tmp_path / "repo"
        (workspace / "docs/architecture").mkdir(parents=True)
        os.symlink(host_secrets, workspace / "docs/architecture/adr")

        events = scan_adrs(workspace=workspace, repo_url="r", actor="x")
        # Symlinked dir must be rejected — secret.md must NOT land in memory
        assert events == ()

    def test_symlinked_adr_file_is_skipped(self, tmp_path: Path) -> None:
        # Hostile repo: docs/architecture/adr/EVIL.md -> ~/.ssh/id_rsa equivalent
        outside = tmp_path / "outside"
        outside.mkdir()
        _write(outside / "id_rsa", "-----BEGIN PRIVATE KEY-----")

        workspace = tmp_path / "repo"
        adr_dir = workspace / "docs/architecture/adr"
        adr_dir.mkdir(parents=True)
        # Real ADR
        _write(adr_dir / "ADR-001.md", "# A\n\n## Status\n\nAccepted")
        # Hostile symlink
        os.symlink(outside / "id_rsa", adr_dir / "ADR-002.md")

        events = scan_adrs(workspace=workspace, repo_url="r", actor="x")
        # Only the legitimate ADR-001 lands; ADR-002 (symlink) is rejected
        assert len(events) == 1
        assert events[0].payload["title"] == "A"

    def test_real_files_after_symlink_still_scanned(self, tmp_path: Path) -> None:
        workspace = tmp_path / "repo"
        adr_dir = workspace / "docs/architecture/adr"
        adr_dir.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        _write(outside / "x.md", "should not be read")

        _write(adr_dir / "ADR-001-real.md", "# Real\n\n## Status\n\nAccepted")
        os.symlink(outside / "x.md", adr_dir / "ADR-002-hostile.md")
        _write(adr_dir / "ADR-003-real.md", "# Also Real\n\n## Status\n\nAccepted")

        events = scan_adrs(workspace=workspace, repo_url="r", actor="x")
        titles = sorted(e.payload["title"] for e in events)
        assert titles == ["Also Real", "Real"]


class TestSizeAndCountCaps:
    def test_oversized_adr_skipped(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs/architecture/adr"
        adr_dir.mkdir(parents=True)
        # 2 MB ADR — exceeds the 1 MB cap
        _write(adr_dir / "BIG.md", "# B\n\n## Status\n\nAccepted\n" + ("x" * (2 * 1024 * 1024)))
        _write(adr_dir / "SMALL.md", "# S\n\n## Status\n\nAccepted")

        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        titles = [e.payload["title"] for e in events]
        assert "S" in titles
        assert "B" not in titles

    def test_directory_flood_capped(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs/architecture/adr"
        adr_dir.mkdir(parents=True)
        # Create 600 ADR files; cap is 500
        for i in range(600):
            _write(adr_dir / f"ADR-{i:04d}.md", f"# ADR-{i}\n\n## Status\n\nAccepted")

        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert len(events) <= 500

    def test_oversized_title_truncated(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs/architecture/adr"
        adr_dir.mkdir(parents=True)
        long_title = "X" * 5000
        _write(adr_dir / "BIG.md", f"# {long_title}\n\n## Status\n\nAccepted")

        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert len(events) == 1
        assert len(events[0].payload["title"]) <= 200


class TestNonSymlinkedTreeStillWorks:
    def test_normal_repo_layout_unaffected(self, tmp_path: Path) -> None:
        # Regression: the symlink defenses must not break the happy path
        _write(tmp_path / "docs/architecture/adr/ADR-001.md", "# A\n\n## Status\n\nAccepted")
        events = scan_adrs(workspace=tmp_path, repo_url="r", actor="x")
        assert len(events) == 1
