"""Tests for ``spectra portfolio`` subcommand (#26).

The CLI follows the same injection pattern as ``spectra cache`` and
``spectra history``: the composition root wires provider callables, the
CLI invokes them lazily, so subcommands work without an Anthropic API
key. Tests stub the registry and analyzer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from typer.testing import CliRunner

from spectra.adapters.cli_controller import (
    app,
    set_history_store_provider,
    set_portfolio_analyzer,
    set_portfolio_registry_provider,
)
from spectra.entities.models import (
    DimensionScore,
    RepoRegistryEntry,
    ReportSummary,
    ScoreCard,
    score_to_grade,
)

runner = CliRunner()

_NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)


# ── In-memory stubs ──────────────────────────────────────────


class _StubRegistry:
    """Synchronous in-memory ``RepoRegistryPort`` for CLI tests."""

    def __init__(self) -> None:
        self.entries: dict[str, RepoRegistryEntry] = {}

    def add(
        self,
        repo_url: str,
        *,
        tags: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> RepoRegistryEntry:
        existing = self.entries.get(repo_url)
        if existing is None:
            entry = RepoRegistryEntry(
                repo_url=repo_url,
                added_at=now or _NOW,
                tags=tags,
            )
        else:
            merged = tuple(dict.fromkeys((*existing.tags, *tags)))
            entry = existing.model_copy(update={"tags": merged})
        self.entries[repo_url] = entry
        return entry

    def remove(self, repo_url: str) -> bool:
        return self.entries.pop(repo_url, None) is not None

    def list(self, *, tag: str | None = None) -> tuple[RepoRegistryEntry, ...]:
        rows = sorted(self.entries.values(), key=lambda e: e.added_at)
        if tag is None:
            return tuple(rows)
        return tuple(r for r in rows if r.has_tag(tag))

    def mark_scanned(
        self,
        repo_url: str,
        *,
        scanned_at: datetime,
    ) -> RepoRegistryEntry | None:
        existing = self.entries.get(repo_url)
        if existing is None:
            return None
        updated = existing.model_copy(update={"last_scan_at": scanned_at})
        self.entries[repo_url] = updated
        return updated


class _StubHistoryStore:
    """In-memory ``ReportStorePort`` for dashboard rendering tests."""

    def __init__(self) -> None:
        self.summaries: list[ReportSummary] = []

    async def store(self, report: ReportSummary) -> None:
        self.summaries.append(report)

    async def latest(self, repo_signature: str) -> ReportSummary | None:
        for s in reversed(self.summaries):
            if s.repo_signature == repo_signature:
                return s
        return None

    async def history(
        self,
        repo_signature: str,
        since: datetime,
        until: datetime,
    ) -> tuple[ReportSummary, ...]:
        rows = [s for s in self.summaries if s.repo_signature == repo_signature and since <= s.timestamp < until]
        rows.sort(key=lambda s: s.timestamp, reverse=True)
        return tuple(rows)


def _scorecard(score: float = 82.5) -> ScoreCard:
    dims = (
        DimensionScore(dimension="architecture", score=85.0, grade="B", findings_count=3, weight=0.25),
        DimensionScore(dimension="security", score=90.0, grade="A-", findings_count=2, weight=0.25),
        DimensionScore(dimension="quality", score=78.0, grade="C+", findings_count=5, weight=0.20),
        DimensionScore(dimension="documentation", score=70.0, grade="C-", findings_count=4, weight=0.10),
        DimensionScore(dimension="maintainability", score=82.0, grade="B", findings_count=3, weight=0.10),
        DimensionScore(dimension="performance", score=88.0, grade="B+", findings_count=1, weight=0.10),
    )
    return ScoreCard(
        overall_score=score,
        overall_grade=score_to_grade(score),
        dimensions=dims,
        total_findings=18,
    )


def _signature_for(url: str) -> str:
    """Replicate the CLI's URL→signature shape so the stub history store can match."""
    from hashlib import blake2b

    digest = blake2b(digest_size=16)
    digest.update(url.encode("utf-8"))
    digest.update(b"\x00")
    return digest.hexdigest()


def _summary(
    repo_url: str,
    *,
    scan_id: str,
    score: float = 82.5,
    ts: datetime | None = None,
) -> ReportSummary:
    name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
    return ReportSummary(
        scan_id=scan_id,
        repo_signature=_signature_for(repo_url),
        repo_url=repo_url,
        repo_name=name,
        timestamp=ts or _NOW,
        overall_score=score,
        overall_grade=score_to_grade(score),
        score_card=_scorecard(score),
        total_findings=18,
        finding_count_by_severity={"critical": 1, "high": 4, "medium": 8, "low": 3, "info": 2},
        finding_count_by_dimension={
            "architecture": 3,
            "security": 2,
            "quality": 5,
            "documentation": 4,
            "maintainability": 3,
            "performance": 1,
        },
        model_versions="claude-opus-4-7",
        prompt_versions="abcd1234",
        spectra_version="0.7.0",
        is_degraded=False,
        validation_status="validated",
        duration_seconds=142.7,
        cost_usd=0.42,
    )


@pytest.fixture(autouse=True)
def reset_providers() -> Any:
    """Reset CLI provider state between tests so they stay isolated."""
    set_portfolio_registry_provider(None)
    set_portfolio_analyzer(None)
    set_history_store_provider(None)
    yield
    set_portfolio_registry_provider(None)
    set_portfolio_analyzer(None)
    set_history_store_provider(None)


# ── add ──────────────────────────────────────────────────────


class TestPortfolioAdd:
    """``spectra portfolio add <url> [--tag t]``"""

    def test_add_inserts_repo_with_tag(self) -> None:
        reg = _StubRegistry()
        set_portfolio_registry_provider(lambda: reg)

        result = runner.invoke(
            app,
            ["portfolio", "add", "https://github.com/octocat/spoon-knife", "--tag", "team:payments"],
        )

        assert result.exit_code == 0, result.stdout
        assert "https://github.com/octocat/spoon-knife" in reg.entries
        assert reg.entries["https://github.com/octocat/spoon-knife"].tags == ("team:payments",)
        assert "added" in result.stdout.lower() or "✓" in result.stdout

    def test_add_without_tag_inserts_with_empty_tags(self) -> None:
        reg = _StubRegistry()
        set_portfolio_registry_provider(lambda: reg)

        result = runner.invoke(
            app,
            ["portfolio", "add", "https://github.com/octocat/spoon-knife"],
        )

        assert result.exit_code == 0, result.stdout
        assert reg.entries["https://github.com/octocat/spoon-knife"].tags == ()

    def test_add_supports_multiple_tag_flags(self) -> None:
        reg = _StubRegistry()
        set_portfolio_registry_provider(lambda: reg)

        result = runner.invoke(
            app,
            [
                "portfolio",
                "add",
                "https://github.com/octocat/spoon-knife",
                "--tag",
                "team:payments",
                "--tag",
                "tier:1",
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert reg.entries["https://github.com/octocat/spoon-knife"].tags == ("team:payments", "tier:1")

    def test_add_exits_one_when_provider_missing(self) -> None:
        result = runner.invoke(app, ["portfolio", "add", "https://github.com/a/b"])

        assert result.exit_code == 1


# ── remove ───────────────────────────────────────────────────


class TestPortfolioRemove:
    """``spectra portfolio remove <url>``"""

    def test_remove_deletes_existing(self) -> None:
        reg = _StubRegistry()
        reg.add("https://github.com/a/b")
        set_portfolio_registry_provider(lambda: reg)

        result = runner.invoke(app, ["portfolio", "remove", "https://github.com/a/b"])

        assert result.exit_code == 0, result.stdout
        assert "https://github.com/a/b" not in reg.entries
        assert "removed" in result.stdout.lower() or "✓" in result.stdout

    def test_remove_warns_when_missing(self) -> None:
        reg = _StubRegistry()
        set_portfolio_registry_provider(lambda: reg)

        result = runner.invoke(app, ["portfolio", "remove", "https://github.com/a/missing"])

        assert result.exit_code == 0, result.stdout
        assert "not found" in result.stdout.lower() or "no entry" in result.stdout.lower()


# ── list ─────────────────────────────────────────────────────


class TestPortfolioList:
    """``spectra portfolio list [--tag t]``"""

    def test_list_prints_each_url(self) -> None:
        reg = _StubRegistry()
        reg.add("https://github.com/a/payments", tags=("team:payments",))
        reg.add("https://github.com/a/web", tags=("team:web",))
        set_portfolio_registry_provider(lambda: reg)

        result = runner.invoke(app, ["portfolio", "list"])

        assert result.exit_code == 0, result.stdout
        assert "payments" in result.stdout
        assert "web" in result.stdout

    def test_list_filters_by_tag(self) -> None:
        reg = _StubRegistry()
        reg.add("https://github.com/a/payments", tags=("team:payments",))
        reg.add("https://github.com/a/web", tags=("team:web",))
        set_portfolio_registry_provider(lambda: reg)

        result = runner.invoke(app, ["portfolio", "list", "--tag", "team:payments"])

        assert result.exit_code == 0, result.stdout
        assert "payments" in result.stdout
        assert "/web" not in result.stdout

    def test_list_friendly_message_when_empty(self) -> None:
        reg = _StubRegistry()
        set_portfolio_registry_provider(lambda: reg)

        result = runner.invoke(app, ["portfolio", "list"])

        assert result.exit_code == 0, result.stdout
        assert "no repos" in result.stdout.lower() or "empty" in result.stdout.lower()


# ── scan ─────────────────────────────────────────────────────


class TestPortfolioScan:
    """``spectra portfolio scan`` iterates the analyzer over the partition."""

    def test_scan_calls_analyzer_for_each_to_scan_entry(self) -> None:
        reg = _StubRegistry()
        reg.add("https://github.com/a/b")
        reg.add("https://github.com/c/d")
        set_portfolio_registry_provider(lambda: reg)

        called: list[str] = []

        async def _analyzer(repo_url: str) -> object:
            called.append(repo_url)

            class _Report:
                pass

            return _Report()

        set_portfolio_analyzer(_analyzer)

        result = runner.invoke(app, ["portfolio", "scan"])

        assert result.exit_code == 0, result.stdout
        assert sorted(called) == [
            "https://github.com/a/b",
            "https://github.com/c/d",
        ]

    def test_scan_skips_recently_scanned_repos(self) -> None:
        reg = _StubRegistry()
        reg.add("https://github.com/a/fresh")
        reg.mark_scanned(
            "https://github.com/a/fresh",
            scanned_at=datetime.now(UTC) - timedelta(days=2),
        )
        set_portfolio_registry_provider(lambda: reg)

        called: list[str] = []

        async def _analyzer(repo_url: str) -> object:
            called.append(repo_url)
            return object()

        set_portfolio_analyzer(_analyzer)

        result = runner.invoke(app, ["portfolio", "scan", "--since", "7d"])

        assert result.exit_code == 0, result.stdout
        assert called == []
        assert "skipped" in result.stdout.lower() or "0" in result.stdout

    def test_scan_filters_by_tag(self) -> None:
        reg = _StubRegistry()
        reg.add("https://github.com/a/payments", tags=("team:payments",))
        reg.add("https://github.com/a/web", tags=("team:web",))
        set_portfolio_registry_provider(lambda: reg)

        called: list[str] = []

        async def _analyzer(repo_url: str) -> object:
            called.append(repo_url)
            return object()

        set_portfolio_analyzer(_analyzer)

        result = runner.invoke(app, ["portfolio", "scan", "--tag", "team:payments"])

        assert result.exit_code == 0, result.stdout
        assert called == ["https://github.com/a/payments"]

    def test_scan_continues_on_per_repo_failure(self) -> None:
        reg = _StubRegistry()
        reg.add("https://github.com/a/good")
        reg.add("https://github.com/a/bad")
        reg.add("https://github.com/a/also-good")
        set_portfolio_registry_provider(lambda: reg)

        called: list[str] = []

        async def _analyzer(repo_url: str) -> object:
            called.append(repo_url)
            if "bad" in repo_url:
                msg = "boom"
                raise RuntimeError(msg)
            return object()

        set_portfolio_analyzer(_analyzer)

        result = runner.invoke(app, ["portfolio", "scan"])

        # Exit code 0 — partial-failure is non-fatal per acceptance criteria
        assert result.exit_code == 0, result.stdout
        assert sorted(called) == [
            "https://github.com/a/also-good",
            "https://github.com/a/bad",
            "https://github.com/a/good",
        ]

    def test_scan_marks_scanned_after_each_success(self) -> None:
        reg = _StubRegistry()
        reg.add("https://github.com/a/b")
        set_portfolio_registry_provider(lambda: reg)

        async def _analyzer(repo_url: str) -> object:
            return object()

        set_portfolio_analyzer(_analyzer)

        result = runner.invoke(app, ["portfolio", "scan"])

        assert result.exit_code == 0, result.stdout
        assert reg.entries["https://github.com/a/b"].last_scan_at is not None

    def test_scan_empty_plan_prints_friendly_message(self) -> None:
        reg = _StubRegistry()
        set_portfolio_registry_provider(lambda: reg)

        async def _analyzer(repo_url: str) -> object:
            return object()

        set_portfolio_analyzer(_analyzer)

        result = runner.invoke(app, ["portfolio", "scan"])

        assert result.exit_code == 0, result.stdout
        assert "no repos" in result.stdout.lower() or "nothing to scan" in result.stdout.lower()


# ── dashboard ────────────────────────────────────────────────


class TestPortfolioDashboard:
    """``spectra portfolio dashboard`` prints a leaderboard from the history store."""

    def test_dashboard_renders_one_row_per_registered_repo(self) -> None:
        reg = _StubRegistry()
        reg.add("https://github.com/a/payments", tags=("team:payments",))
        reg.add("https://github.com/a/web", tags=("team:web",))
        set_portfolio_registry_provider(lambda: reg)

        store = _StubHistoryStore()
        # latest summaries
        store.summaries.append(_summary("https://github.com/a/payments", scan_id="s1", score=92.0, ts=_NOW))
        store.summaries.append(_summary("https://github.com/a/web", scan_id="s2", score=72.0, ts=_NOW))
        set_history_store_provider(lambda: store)

        result = runner.invoke(app, ["portfolio", "dashboard"])

        assert result.exit_code == 0, result.stdout
        assert "payments" in result.stdout
        assert "web" in result.stdout
        # Sorted by score desc — payments (92) before web (72) in stdout
        payments_idx = result.stdout.index("payments")
        web_idx = result.stdout.index("/web")
        assert payments_idx < web_idx

    def test_dashboard_shows_dash_when_repo_never_scanned(self) -> None:
        reg = _StubRegistry()
        reg.add("https://github.com/a/never", tags=())
        set_portfolio_registry_provider(lambda: reg)

        store = _StubHistoryStore()
        set_history_store_provider(lambda: store)

        result = runner.invoke(app, ["portfolio", "dashboard"])

        assert result.exit_code == 0, result.stdout
        assert "never" in result.stdout
        # No grade column populated → dash placeholder
        assert "—" in result.stdout or "-" in result.stdout

    def test_dashboard_friendly_message_when_registry_empty(self) -> None:
        reg = _StubRegistry()
        set_portfolio_registry_provider(lambda: reg)

        store = _StubHistoryStore()
        set_history_store_provider(lambda: store)

        result = runner.invoke(app, ["portfolio", "dashboard"])

        assert result.exit_code == 0, result.stdout
        assert "no repos" in result.stdout.lower() or "empty" in result.stdout.lower()

    def test_dashboard_exits_one_when_history_provider_missing(self) -> None:
        reg = _StubRegistry()
        reg.add("https://github.com/a/b")
        set_portfolio_registry_provider(lambda: reg)

        result = runner.invoke(app, ["portfolio", "dashboard"])

        assert result.exit_code == 1
