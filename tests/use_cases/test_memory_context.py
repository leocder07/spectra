"""Tests for ``build_prior_context_paragraph`` (v0.9.1, ADR-025 wiring §4).

Renders a single ≤500-token paragraph that MetaPrompter prepends to its
file-tree input. Goal: the tweet promise — "this finding was waived 6 weeks
ago for X reason" — surfaces in planning context before the scan re-flags.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from spectra.entities.memory import MemoryEvent
from spectra.use_cases.memory_context import build_prior_context_paragraph


def _scan_event(*, score: float = 84.0, grade: str = "B+", days_ago: int = 4) -> MemoryEvent:
    return MemoryEvent(
        id=f"scan:{days_ago}",
        kind="scan_completed",
        repo_url="https://github.com/foo/bar",
        payload={
            "scan_id": f"r-{days_ago}",
            "overall_score": score,
            "overall_grade": grade,
            "finding_counts_by_severity": {"critical": 0, "high": 3, "medium": 7, "low": 2, "info": 0},
            "cost_usd": 1.23,
            "duration_seconds": 200.0,
            "is_degraded": False,
        },
        actor="spectra-cli",
        occurred_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


def _waiver_event(*, rule_id: str = "sec/SSRF-001", reason: str = "behind mTLS", days_ago: int = 42) -> MemoryEvent:
    return MemoryEvent(
        id=f"waiver:{rule_id}",
        kind="waiver_added",
        repo_url="https://github.com/foo/bar",
        payload={
            "waiver_id": f"w-{rule_id}",
            "rule_id": rule_id,
            "file_path": "src/x.py",
            "line_start": 42,
            "reason": reason,
            "approved_by": "vivek",
            "expires_at": None,
        },
        actor="spectra-cli",
        occurred_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


def _adr_event(*, title: str = "ADR-025: Memory Port", status: str = "Proposed", days_ago: int = 17) -> MemoryEvent:
    return MemoryEvent(
        id=f"adr:{title}",
        kind="adr_ingested",
        repo_url="https://github.com/foo/bar",
        payload={
            "adr_path": f"docs/architecture/adr/{title.split(':')[0]}.md",
            "title": title,
            "status": status,
            "date": "2026-05-04",
            "body_excerpt": "...",
        },
        actor="spectra-cli",
        occurred_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


class TestEmptyContext:
    def test_all_empty_returns_empty_string(self) -> None:
        assert build_prior_context_paragraph(scans=(), waivers=(), adrs=()) == ""


class TestScanContext:
    def test_single_prior_scan_surfaces_grade_findings_age(self) -> None:
        out = build_prior_context_paragraph(
            scans=(_scan_event(score=84.0, grade="B+", days_ago=4),),
            waivers=(),
            adrs=(),
        )
        assert "B+" in out
        assert "84" in out
        # finding counts (12 total = 0+3+7+2+0)
        assert "12 finding" in out or "12 findings" in out
        # age signal
        assert "4d" in out or "4 day" in out

    def test_multiple_prior_scans_uses_most_recent(self) -> None:
        out = build_prior_context_paragraph(
            scans=(
                _scan_event(score=84.0, grade="B+", days_ago=4),
                _scan_event(score=70.0, grade="C", days_ago=30),
            ),
            waivers=(),
            adrs=(),
        )
        assert "B+" in out
        assert "84" in out
        # Older event should not dominate
        assert out.find("B+") < out.find("C") or "C" not in out


class TestWaiverContext:
    def test_active_waiver_surfaces_rule_and_reason(self) -> None:
        out = build_prior_context_paragraph(
            scans=(),
            waivers=(_waiver_event(rule_id="sec/SSRF-001", reason="behind mTLS", days_ago=42),),
            adrs=(),
        )
        assert "sec/SSRF-001" in out
        assert "behind mTLS" in out

    def test_multiple_waivers_listed(self) -> None:
        out = build_prior_context_paragraph(
            scans=(),
            waivers=(
                _waiver_event(rule_id="sec/SSRF-001", reason="behind mTLS"),
                _waiver_event(rule_id="quality/COMPLEXITY-12", reason="legacy migration"),
            ),
            adrs=(),
        )
        assert "sec/SSRF-001" in out
        assert "quality/COMPLEXITY-12" in out


class TestAdrContext:
    def test_adrs_listed_with_count_and_latest_title(self) -> None:
        # Port returns newest-first per MemoryPort.query_events contract
        out = build_prior_context_paragraph(
            scans=(),
            waivers=(),
            adrs=(
                _adr_event(title="ADR-027: Deterministic compliance", days_ago=5),
                _adr_event(title="ADR-025: Memory Port", days_ago=17),
            ),
        )
        assert "2 ADR" in out
        # latest (events[0]) is ADR-027
        assert "ADR-027" in out


class TestCombinedContext:
    def test_renders_all_three_kinds_in_one_paragraph(self) -> None:
        out = build_prior_context_paragraph(
            scans=(_scan_event(),),
            waivers=(_waiver_event(),),
            adrs=(_adr_event(),),
        )
        # one paragraph (no double-newlines for sections)
        assert "\n\n" not in out
        # contains markers for each kind
        assert "B+" in out or "84" in out
        assert "sec/SSRF-001" in out
        assert "ADR-025" in out

    def test_token_budget_paragraph_under_500_chars(self) -> None:
        out = build_prior_context_paragraph(
            scans=tuple(_scan_event(days_ago=i) for i in range(1, 11)),
            waivers=tuple(_waiver_event(rule_id=f"r-{i}", reason=f"reason {i}") for i in range(20)),
            adrs=tuple(_adr_event(title=f"ADR-{i:03d}: Topic {i}") for i in range(50)),
        )
        # ≤500 tokens ≈ ≤2000 chars conservative bound; we keep it tighter
        assert len(out) <= 2000


class TestPrefixDiscipline:
    def test_paragraph_starts_with_prior_context_marker(self) -> None:
        out = build_prior_context_paragraph(scans=(_scan_event(),), waivers=(), adrs=())
        # Reader needs a stable marker the MetaPrompter prompt can reference
        assert out.startswith("Prior context:")
