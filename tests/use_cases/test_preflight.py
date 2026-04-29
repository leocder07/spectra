"""Tests for the pre-flight use case (Stage 1.5).

Verifies the use case wires WorkspaceFilterPort + SecretScannerPort
correctly and enforces the block-by-default contract on SPEC-011.
"""

from __future__ import annotations

import pytest

from spectra.entities.errors import SecretDetectedError
from spectra.entities.models import SecretFinding
from spectra.use_cases.preflight import PreflightConfig, PreflightResult, run_preflight


class _StubFilter:
    """In-memory WorkspaceFilterPort double."""

    def __init__(self, kept: list[str]) -> None:
        self._kept = kept
        self.calls: list[tuple[str, list[str]]] = []

    def filter_files(self, repo_dir: str, file_paths: list[str]) -> list[str]:
        self.calls.append((repo_dir, file_paths))
        return list(self._kept)


class _StubScanner:
    """In-memory SecretScannerPort double."""

    def __init__(self, findings: tuple[SecretFinding, ...]) -> None:
        self._findings = findings
        self.calls: list[tuple[str, list[str]]] = []

    def scan(
        self,
        repo_dir: str,
        file_paths: list[str],
    ) -> tuple[SecretFinding, ...]:
        self.calls.append((repo_dir, file_paths))
        return self._findings


# ── Filter behavior ──────────────────────────────────────────


class TestFilter:
    def test_returns_filtered_file_list(self) -> None:
        flt = _StubFilter(["src/main.py"])
        scn = _StubScanner(())
        result = run_preflight(
            "/repo",
            ["src/main.py", ".env"],
            flt,
            scn,
            PreflightConfig(),
        )
        assert isinstance(result, PreflightResult)
        assert result.filtered_files == ["src/main.py"]

    def test_scanner_only_sees_filtered_files(self) -> None:
        flt = _StubFilter(["src/main.py"])
        scn = _StubScanner(())
        run_preflight("/repo", ["src/main.py", ".env"], flt, scn, PreflightConfig())
        # Scanner must NOT see .env if filter excluded it
        assert scn.calls == [("/repo", ["src/main.py"])]


# ── Block-by-default ─────────────────────────────────────────


class TestBlockOnDetection:
    def test_secret_raises_spec011_by_default(self) -> None:
        flt = _StubFilter(["src/leak.py"])
        scn = _StubScanner((SecretFinding(file_path="src/leak.py", line=1, pattern_name="aws_access_key"),))
        with pytest.raises(SecretDetectedError) as exc_info:
            run_preflight("/repo", ["src/leak.py"], flt, scn, PreflightConfig())
        assert exc_info.value.error.code == "SPEC-011"
        assert len(exc_info.value.findings) == 1

    def test_no_secrets_returns_clean_result(self) -> None:
        flt = _StubFilter(["src/main.py"])
        scn = _StubScanner(())
        result = run_preflight("/repo", ["src/main.py"], flt, scn, PreflightConfig())
        assert result.secret_findings == ()


# ── Allow-secrets bypass ─────────────────────────────────────


class TestAllowSecretsBypass:
    def test_allow_secrets_returns_findings_without_raising(self) -> None:
        flt = _StubFilter(["src/leak.py"])
        scn = _StubScanner((SecretFinding(file_path="src/leak.py", line=1, pattern_name="github_pat"),))
        result = run_preflight(
            "/repo",
            ["src/leak.py"],
            flt,
            scn,
            PreflightConfig(allow_secrets=True),
        )
        # Detected but not raised
        assert len(result.secret_findings) == 1
        assert result.secret_findings[0].pattern_name == "github_pat"


# ── Multiple findings preserved ──────────────────────────────


class TestMultipleFindings:
    def test_all_findings_in_exception(self) -> None:
        flt = _StubFilter(["a.env", "b.env"])
        findings = (
            SecretFinding(file_path="a.env", line=1, pattern_name="aws_access_key"),
            SecretFinding(file_path="b.env", line=4, pattern_name="github_pat"),
            SecretFinding(file_path="b.env", line=10, pattern_name="dotenv_value"),
        )
        scn = _StubScanner(findings)
        with pytest.raises(SecretDetectedError) as exc_info:
            run_preflight("/repo", ["a.env", "b.env"], flt, scn, PreflightConfig())
        assert exc_info.value.findings == findings
