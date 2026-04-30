"""Tests for ``filter_findings_by_waivers`` + inline-pragma scanning.

Covers:
    - waiver matching by (file_path, rule_id, severity) signature
    - inline ``# spectra: ignore-next-line RULE`` parsing → ephemeral
      waiver applied to the next line for that file
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from spectra.entities.models import (
    FileLocation,
    Finding,
    Waiver,
    compute_finding_signature,
)
from spectra.use_cases.waiver_filter import (
    InlinePragma,
    filter_findings_by_waivers,
    parse_inline_pragmas,
    pragmas_to_ephemeral_waivers,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _finding(
    *,
    file_path: str = "src/x.py",
    line: int = 10,
    rule_id: str = "SEC-AUTH-101",
    severity: str = "high",
) -> Finding:
    return Finding(
        id=f"F-{file_path}-{line}",
        dimension="security",
        severity=severity,
        title="t",
        description="d",
        location=FileLocation(file_path=file_path, line_start=line),
        recommendation="r",
        agent_role="security",
        confidence=0.9,
        rule_id=rule_id,
    )


def _waiver_for(finding: Finding) -> Waiver:
    sig = compute_finding_signature(
        finding.location.file_path,
        finding.rule_id,
        finding.severity,
    )
    return Waiver(
        repo_signature="r" * 32,
        finding_signature=sig,
        reason="documented bypass",
        waived_by="alice",
        waived_at=_now(),
        expires_at=_now() + timedelta(days=30),
        signature="x" * 128,
    )


class TestFilterFindings:
    def test_waiver_suppresses_matching_finding(self) -> None:
        f = _finding()
        w = _waiver_for(f)
        kept = filter_findings_by_waivers((f,), (w,))
        assert kept == ()

    def test_no_waivers_keeps_all_findings(self) -> None:
        f = _finding()
        kept = filter_findings_by_waivers((f,), ())
        assert kept == (f,)

    def test_unrelated_waiver_does_not_suppress(self) -> None:
        f = _finding(rule_id="SEC-AUTH-101")
        other = _finding(rule_id="SEC-XSS-204")
        w = _waiver_for(other)  # waiver for the other rule
        kept = filter_findings_by_waivers((f,), (w,))
        assert kept == (f,)


class TestInlinePragmas:
    def test_parses_ignore_next_line(self) -> None:
        source = (
            "def foo():\n"
            "    # spectra: ignore-next-line SEC-AUTH-101\n"
            "    return user_input\n"
        )
        pragmas = parse_inline_pragmas("src/x.py", source)
        assert pragmas == (
            InlinePragma(file_path="src/x.py", line=3, rule_id="SEC-AUTH-101"),
        )

    def test_no_pragma_returns_empty(self) -> None:
        source = "def foo():\n    return 1\n"
        assert parse_inline_pragmas("src/x.py", source) == ()

    def test_pragma_at_eof_is_ignored(self) -> None:
        # The pragma points to "next line" but file ends — drop it.
        source = "x = 1\n# spectra: ignore-next-line SEC-AUTH-101\n"
        assert parse_inline_pragmas("src/x.py", source) == ()

    def test_pragma_with_trailing_text_parses(self) -> None:
        source = "# spectra: ignore-next-line SEC-AUTH-101 (justified)\nx = 1\n"
        pragmas = parse_inline_pragmas("src/x.py", source)
        assert len(pragmas) == 1
        assert pragmas[0].rule_id == "SEC-AUTH-101"


class TestPragmaSuppression:
    def test_pragma_filters_matching_finding(self) -> None:
        f = _finding(file_path="src/x.py", line=42, rule_id="SEC-AUTH-101")
        pragma = InlinePragma(file_path="src/x.py", line=42, rule_id="SEC-AUTH-101")
        ephemeral = pragmas_to_ephemeral_waivers((pragma,), (f,))
        kept = filter_findings_by_waivers((f,), ephemeral)
        assert kept == ()

    def test_pragma_does_not_filter_different_line(self) -> None:
        f = _finding(file_path="src/x.py", line=99, rule_id="SEC-AUTH-101")
        pragma = InlinePragma(file_path="src/x.py", line=42, rule_id="SEC-AUTH-101")
        ephemeral = pragmas_to_ephemeral_waivers((pragma,), (f,))
        # Different line — no suppression
        kept = filter_findings_by_waivers((f,), ephemeral)
        assert kept == (f,)

    def test_pragma_does_not_filter_different_rule(self) -> None:
        f = _finding(file_path="src/x.py", line=42, rule_id="SEC-XSS-204")
        pragma = InlinePragma(file_path="src/x.py", line=42, rule_id="SEC-AUTH-101")
        ephemeral = pragmas_to_ephemeral_waivers((pragma,), (f,))
        kept = filter_findings_by_waivers((f,), ephemeral)
        assert kept == (f,)
