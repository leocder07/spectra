"""Integration tests for the pre-flight stage in the composition root.

Verifies the wiring across `_run_preflight_stage`, the
`PathspecFilterAdapter`, and `RegexSecretScanner` against a real
on-disk fixture — exercises the same code path as the CLI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from spectra.entities.errors import SecretDetectedError
from spectra.infrastructure.main import _run_preflight_stage

if TYPE_CHECKING:
    from pathlib import Path


def _make_observer() -> MagicMock:
    return MagicMock()


def _seed_repo(repo: Path, files: dict[str, str]) -> list[str]:
    """Write `files` (path → content) under `repo`; return relative-paths list."""
    for rel, content in files.items():
        full = repo / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    return sorted(files.keys())


# ── .gitignore honor ─────────────────────────────────────────


class TestGitignoreHonor:
    def test_env_excluded_by_gitignore(self, tmp_path: Path) -> None:
        files = _seed_repo(
            tmp_path,
            {
                ".gitignore": ".env\n",
                ".env": "DATABASE_URL=postgres://user:short\n",
                "src/main.py": "def main():\n    pass\n",
            },
        )
        observer = _make_observer()
        kept = _run_preflight_stage(
            str(tmp_path),
            files,
            observer,
            honor_gitignore=True,
            allow_secrets=False,
        )
        assert ".env" not in kept
        assert "src/main.py" in kept

    def test_no_gitignore_keeps_env(self, tmp_path: Path) -> None:
        files = _seed_repo(
            tmp_path,
            {
                ".gitignore": ".env\n",
                ".env": "PORT=3000\n",  # short value — no dotenv heuristic match
                "src/main.py": "def main():\n    pass\n",
            },
        )
        observer = _make_observer()
        kept = _run_preflight_stage(
            str(tmp_path),
            files,
            observer,
            honor_gitignore=False,
            allow_secrets=False,
        )
        assert ".env" in kept


class TestSpectraignoreHonor:
    def test_vendor_excluded_via_spectraignore(self, tmp_path: Path) -> None:
        files = _seed_repo(
            tmp_path,
            {
                ".spectraignore": "vendor/\n",
                "vendor/lib.go": "package vendor\n",
                "src/main.go": "package main\n",
            },
        )
        observer = _make_observer()
        kept = _run_preflight_stage(
            str(tmp_path),
            files,
            observer,
            honor_gitignore=True,
            allow_secrets=False,
        )
        assert "vendor/lib.go" not in kept
        assert "src/main.go" in kept


# ── SPEC-011 abort + bypass ──────────────────────────────────


class TestSecretGate:
    def test_planted_aws_key_aborts_with_spec011(self, tmp_path: Path) -> None:
        files = _seed_repo(
            tmp_path,
            {
                "src/leak.py": 'KEY = "AKIAIOSFODNN7EXAMPLE"\n',
            },
        )
        observer = _make_observer()
        with pytest.raises(SecretDetectedError) as exc:
            _run_preflight_stage(
                str(tmp_path),
                files,
                observer,
                honor_gitignore=True,
                allow_secrets=False,
            )
        assert exc.value.error.code == "SPEC-011"
        assert any(f.pattern_name == "aws_access_key" for f in exc.value.findings)

    def test_allow_secrets_bypasses_spec011(self, tmp_path: Path) -> None:
        files = _seed_repo(
            tmp_path,
            {
                "src/leak.py": 'KEY = "AKIAIOSFODNN7EXAMPLE"\n',
            },
        )
        observer = _make_observer()
        # Must not raise
        kept = _run_preflight_stage(
            str(tmp_path),
            files,
            observer,
            honor_gitignore=True,
            allow_secrets=True,
        )
        assert "src/leak.py" in kept

    def test_gitignored_secret_not_flagged(self, tmp_path: Path) -> None:
        # If .env is gitignored, scanner should NEVER even see it
        files = _seed_repo(
            tmp_path,
            {
                ".gitignore": ".env\n",
                ".env": "KEY=AKIAIOSFODNN7EXAMPLE\n",
                "src/main.py": "def main():\n    pass\n",
            },
        )
        observer = _make_observer()
        # No SecretDetectedError because filter excludes .env
        kept = _run_preflight_stage(
            str(tmp_path),
            files,
            observer,
            honor_gitignore=True,
            allow_secrets=False,
        )
        assert ".env" not in kept


# ── Observer signaling ───────────────────────────────────────


class TestObserverSignals:
    def test_stage_start_and_complete_called(self, tmp_path: Path) -> None:
        files = _seed_repo(
            tmp_path,
            {
                "src/main.py": "def main():\n    pass\n",
            },
        )
        observer = _make_observer()
        _run_preflight_stage(
            str(tmp_path),
            files,
            observer,
            honor_gitignore=True,
            allow_secrets=False,
        )
        observer.on_stage_start.assert_called_once_with("PREFLIGHT", "Scanning for secrets")
        observer.on_stage_complete.assert_called_once()
        # Brand-voice ≤80-char line check
        msg = observer.on_stage_complete.call_args[0][1]
        assert len(msg) <= 80
        assert not msg.endswith(".")
