"""Integration test: post-scan drift hook fires NotifierPort (#27 + #34).

Asserts that after every successful scan, the orchestrator queries the
history store for drift and fires a ``NotifierPort.send`` with a
brand-voice message when one is detected. Failures from the notifier
must NEVER abort the pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spectra.entities.models import (
    DimensionScore,
    Finding,
    NotifierMessage,
    ReportSummary,
    ScoreCard,
    score_to_grade,
)
from spectra.use_cases.analyze_repository import _safe_drift_alert  # type: ignore[attr-defined]

# ── Fakes ────────────────────────────────────────────────────


def _summary(*, overall: float, when: datetime, repo_signature: str = "abc") -> ReportSummary:
    dims = tuple(
        DimensionScore(
            dimension=dim,  # type: ignore[arg-type]
            score=overall,
            grade=score_to_grade(overall),
            findings_count=0,
            weight=1 / 6,
        )
        for dim in (
            "architecture",
            "security",
            "quality",
            "documentation",
            "maintainability",
            "performance",
        )
    )
    return ReportSummary(
        scan_id=f"s-{when.isoformat()}",
        repo_signature=repo_signature,
        repo_url="https://example.com/payments",
        repo_name="payments",
        timestamp=when,
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        score_card=ScoreCard(
            overall_score=overall,
            overall_grade=score_to_grade(overall),
            dimensions=dims,
            total_findings=0,
        ),
        total_findings=0,
        finding_count_by_severity={},
        finding_count_by_dimension={},
        model_versions="opus-4.7",
        prompt_versions="p1",
        spectra_version="0.7.0",
        is_degraded=False,
        validation_status="validated",
        duration_seconds=10.0,
        cost_usd=0.5,
    )


class _FakeStore:
    def __init__(self, summaries: list[ReportSummary]) -> None:
        self._summaries = sorted(summaries, key=lambda s: s.timestamp, reverse=True)

    async def store(self, report: ReportSummary) -> None:
        self._summaries.append(report)
        self._summaries.sort(key=lambda s: s.timestamp, reverse=True)

    async def latest(self, repo_signature: str) -> ReportSummary | None:
        for s in self._summaries:
            if s.repo_signature == repo_signature:
                return s
        return None

    async def history(
        self,
        repo_signature: str,
        since: datetime,
        until: datetime,
    ) -> tuple[ReportSummary, ...]:
        return tuple(s for s in self._summaries if s.repo_signature == repo_signature and since <= s.timestamp < until)


class _RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[NotifierMessage] = []

    async def send(self, message: NotifierMessage) -> None:
        self.sent.append(message)


class _RaisingNotifier:
    async def send(self, message: NotifierMessage) -> None:
        msg = "boom"
        raise RuntimeError(msg)


# ── Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drift_hook_fires_on_drop() -> None:
    """A 12pt overall drop fires one notifier message."""
    now = datetime.now(UTC)
    store = _FakeStore(
        [
            _summary(overall=92.0, when=now - timedelta(days=7)),
            _summary(overall=80.0, when=now),
        ]
    )
    notifier = _RecordingNotifier()
    await _safe_drift_alert(
        notifier=notifier,
        history=store,
        repo_signature="abc",
        repo_name="payments",
        report_url="https://spectra.example/r/x",
    )
    assert len(notifier.sent) == 1
    msg = notifier.sent[0]
    assert "payments" in msg.title or "payments" in msg.body_markdown
    assert "A" in msg.body_markdown
    assert "B" in msg.body_markdown


@pytest.mark.asyncio
async def test_drift_hook_silent_when_no_drift() -> None:
    """Same score on both scans → no notification."""
    now = datetime.now(UTC)
    store = _FakeStore(
        [
            _summary(overall=92.0, when=now - timedelta(days=7)),
            _summary(overall=92.0, when=now),
        ]
    )
    notifier = _RecordingNotifier()
    await _safe_drift_alert(
        notifier=notifier,
        history=store,
        repo_signature="abc",
        repo_name="payments",
        report_url=None,
    )
    assert notifier.sent == []


@pytest.mark.asyncio
async def test_drift_hook_silent_with_no_notifier() -> None:
    """A None notifier is a valid configuration — opt-out."""
    now = datetime.now(UTC)
    store = _FakeStore(
        [
            _summary(overall=92.0, when=now - timedelta(days=7)),
            _summary(overall=80.0, when=now),
        ]
    )
    # No assertions beyond "does not raise" — None notifier is a no-op.
    await _safe_drift_alert(
        notifier=None,
        history=store,
        repo_signature="abc",
        repo_name="payments",
        report_url=None,
    )


@pytest.mark.asyncio
async def test_drift_hook_swallows_notifier_failure() -> None:
    """Notifier raising must NEVER abort the post-scan flow."""
    now = datetime.now(UTC)
    store = _FakeStore(
        [
            _summary(overall=92.0, when=now - timedelta(days=7)),
            _summary(overall=80.0, when=now),
        ]
    )
    # _RaisingNotifier raises on every send. The hook must catch.
    await _safe_drift_alert(
        notifier=_RaisingNotifier(),
        history=store,
        repo_signature="abc",
        repo_name="payments",
        report_url=None,
    )


# ── Per-finding alert (#34) ─────────────────────────────────


@pytest.mark.asyncio
async def test_critical_finding_alert_fires_for_new_critical() -> None:
    """A new critical finding (not in previous scan) fires one notifier message."""
    from spectra.use_cases.analyze_repository import _safe_critical_finding_alert  # type: ignore[attr-defined]

    notifier = _RecordingNotifier()
    new_finding = Finding(
        id="sec-1",
        dimension="security",
        severity="critical",
        title="SQL injection",
        description="raw string interpolation in auth/login.py",
        location={"file_path": "auth/login.py", "line_start": 42},  # type: ignore[arg-type]
        recommendation="Parameterize the query",
        agent_role="security",
        confidence=0.95,
        rule_id="SEC-SQLI-001",
    )
    await _safe_critical_finding_alert(
        notifier=notifier,
        new_critical_findings=(new_finding,),
        repo_name="payments",
        report_url="https://spectra.example/r/x",
    )
    assert len(notifier.sent) == 1
    msg = notifier.sent[0]
    assert msg.severity == "critical"
    assert "SQL injection" in msg.title or "SQL injection" in msg.body_markdown


@pytest.mark.asyncio
async def test_critical_finding_alert_silent_when_no_findings() -> None:
    from spectra.use_cases.analyze_repository import _safe_critical_finding_alert  # type: ignore[attr-defined]

    notifier = _RecordingNotifier()
    await _safe_critical_finding_alert(
        notifier=notifier,
        new_critical_findings=(),
        repo_name="payments",
        report_url=None,
    )
    assert notifier.sent == []
