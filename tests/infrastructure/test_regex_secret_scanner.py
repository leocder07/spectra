"""Tests for RegexSecretScanner — pre-flight secret detection."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from spectra.infrastructure.regex_secret_scanner import RegexSecretScanner

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def scanner() -> RegexSecretScanner:
    return RegexSecretScanner()


# ── AWS keys ─────────────────────────────────────────────────


class TestAwsKeys:
    def test_aws_access_key_detected(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / "config.txt").write_text("aws_key = AKIAIOSFODNN7EXAMPLE\n")
        findings = scanner.scan(str(tmp_path), ["config.txt"])
        assert any(f.pattern_name == "aws_access_key" for f in findings)

    def test_aws_access_key_filename_in_finding(
        self,
        tmp_path: Path,
        scanner: RegexSecretScanner,
    ) -> None:
        (tmp_path / "deep" / "nested").mkdir(parents=True)
        (tmp_path / "deep" / "nested" / "leak.txt").write_text("KEY=AKIAIOSFODNN7EXAMPLE\n")
        findings = scanner.scan(str(tmp_path), ["deep/nested/leak.txt"])
        assert findings[0].file_path == "deep/nested/leak.txt"
        assert findings[0].line == 1


# ── Tokens & PATs ────────────────────────────────────────────


class TestTokens:
    def test_github_pat_detected(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / "src.py").write_text('TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n')
        findings = scanner.scan(str(tmp_path), ["src.py"])
        assert any(f.pattern_name == "github_pat" for f in findings)

    def test_anthropic_key_detected(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / "k.txt").write_text("ANTHROPIC_API_KEY=sk-ant-api03-abcdef0123456789ABCDEF0123456789\n")
        findings = scanner.scan(str(tmp_path), ["k.txt"])
        assert any(f.pattern_name == "anthropic_key" for f in findings)

    def test_bearer_token_detected(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / "auth.py").write_text('headers = {"Authorization": "Bearer xyz123abcdef456ghijkl789mnop"}\n')
        findings = scanner.scan(str(tmp_path), ["auth.py"])
        assert any(f.pattern_name == "bearer_token" for f in findings)

    def test_slack_webhook_detected(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        # Build the URL at runtime so this fixture does not trip GitHub's
        # push-protection scanner (which matches the literal prefix).
        host = "hooks" + ".slack.com"
        path_id = "/services/T00000000/B00000000/" + "X" * 24
        (tmp_path / "hook.py").write_text(f'URL = "https://{host}{path_id}"\n')
        findings = scanner.scan(str(tmp_path), ["hook.py"])
        assert any(f.pattern_name == "slack_webhook" for f in findings)


# ── Private keys ─────────────────────────────────────────────


class TestPrivateKeys:
    def test_rsa_private_key_detected(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / "id.pem").write_text(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n"
        )
        findings = scanner.scan(str(tmp_path), ["id.pem"])
        assert any(f.pattern_name == "private_key" for f in findings)

    def test_openssh_private_key_detected(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / "id_ed25519").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjE...\n")
        findings = scanner.scan(str(tmp_path), ["id_ed25519"])
        assert any(f.pattern_name == "private_key" for f in findings)


# ── .env heuristic (file-name conditional) ────────────────────


class TestDotenvHeuristic:
    def test_env_file_assignment_flagged(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / ".env").write_text("DATABASE_URL=postgres://user:pass@host:5432/dbname\n")
        findings = scanner.scan(str(tmp_path), [".env"])
        assert any(f.pattern_name == "dotenv_value" for f in findings)

    def test_non_env_file_assignment_not_flagged(
        self,
        tmp_path: Path,
        scanner: RegexSecretScanner,
    ) -> None:
        (tmp_path / "code.py").write_text("DATABASE_URL=postgres://user:pass@host:5432/dbname\n")
        findings = scanner.scan(str(tmp_path), ["code.py"])
        # Non-env files do not get the heuristic line-by-line trigger
        assert not any(f.pattern_name == "dotenv_value" for f in findings)

    def test_short_value_in_env_not_flagged(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / ".env").write_text("PORT=3000\n")
        findings = scanner.scan(str(tmp_path), [".env"])
        assert not findings

    def test_env_local_flagged(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / ".env.local").write_text("API_KEY=verylongapikeythatissecret123\n")
        findings = scanner.scan(str(tmp_path), [".env.local"])
        assert findings


# ── No false positives on clean files ────────────────────────


class TestCleanFiles:
    def test_python_source_clean(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / "main.py").write_text("def hello() -> str:\n    return 'world'\n")
        assert scanner.scan(str(tmp_path), ["main.py"]) == ()

    def test_readme_clean(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / "README.md").write_text("# project\n\n run `pip install foo`\n")
        assert scanner.scan(str(tmp_path), ["README.md"]) == ()

    def test_short_akia_lookalike_not_matched(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        # Real AKIA pattern is exactly 20 chars; shorter strings must not match
        (tmp_path / "x.py").write_text("PREFIX = 'AKIA12345'\n")
        assert scanner.scan(str(tmp_path), ["x.py"]) == ()


# ── Robustness ────────────────────────────────────────────────


class TestRobustness:
    def test_missing_file_skipped(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        # File listed in tree but not present on disk — must not raise
        result = scanner.scan(str(tmp_path), ["does-not-exist.py"])
        assert result == ()

    def test_binary_file_skipped(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02\xff" * 100)
        result = scanner.scan(str(tmp_path), ["blob.bin"])
        # We should not crash on undecodable bytes
        assert result == ()

    def test_multiple_findings_per_file(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        content = "AKIA0000000000000001\n# hi\nghp_abcdefghijklmnopqrstuvwxyz0123456789\n"
        (tmp_path / "leak.txt").write_text(content)
        findings = scanner.scan(str(tmp_path), ["leak.txt"])
        assert len(findings) >= 2
        lines = sorted(f.line for f in findings)
        assert lines == [1, 3]

    def test_empty_file_list(self, scanner: RegexSecretScanner, tmp_path: Path) -> None:
        assert scanner.scan(str(tmp_path), []) == ()


# ── Performance ──────────────────────────────────────────────


class TestPerformance:
    def test_under_200ms_on_50_files(self, tmp_path: Path, scanner: RegexSecretScanner) -> None:
        # Mix of clean + secret files; mimics a small repo
        files: list[str] = []
        for i in range(48):
            path = tmp_path / f"src_{i}.py"
            path.write_text(f"def fn_{i}() -> int:\n    return {i}\n" * 30)
            files.append(path.name)
        (tmp_path / "leak.env").write_text("API_KEY=AKIAIOSFODNN7EXAMPLE\n")
        files.append("leak.env")
        (tmp_path / "tok.py").write_text('TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n')
        files.append("tok.py")
        assert len(files) == 50
        start = time.perf_counter()
        findings = scanner.scan(str(tmp_path), files)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.2, f"scan took {elapsed * 1000:.0f}ms, expected <200ms"
        assert len(findings) >= 2
