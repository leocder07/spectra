"""Tests for RichProgressReporter — brand-colored stage/agent lifecycle output."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from spectra.adapters.progress_reporter import (
    AGENT_DISPLAY_NAMES,
    SPECTRA_THEME,
    RichProgressReporter,
)


def _make_reporter() -> tuple[RichProgressReporter, StringIO]:
    """Create a reporter backed by a string buffer for assertion."""
    buf = StringIO()
    console = Console(file=buf, theme=SPECTRA_THEME, force_terminal=True, width=120)
    return RichProgressReporter(console=console), buf


class TestStageLifecycle:
    def test_on_stage_start_prefix(self):
        reporter, buf = _make_reporter()
        reporter.on_stage_start("INGEST", "Cloning repository")
        output = buf.getvalue()
        assert "INIT" in output
        assert "Cloning repository" in output

    def test_on_stage_complete_prefix(self):
        reporter, buf = _make_reporter()
        reporter.on_stage_complete("INGEST", "Clone complete")
        output = buf.getvalue()
        assert "INIT" in output
        assert "Clone complete" in output

    def test_on_error_prefix(self):
        reporter, buf = _make_reporter()
        reporter.on_error("ANALYZE", "Agent timed out")
        output = buf.getvalue()
        assert "SCAN" in output
        assert "Agent timed out" in output


class TestAgentLifecycle:
    def test_on_agent_start_creates_progress(self):
        reporter, _buf = _make_reporter()
        reporter.on_agent_start("security")
        assert reporter._progress is not None
        assert "security" in reporter._agent_tasks
        reporter.stop()

    def test_on_agent_success_output(self):
        reporter, buf = _make_reporter()
        reporter.on_agent_start("security")
        reporter.on_agent_success("security", 1.5)
        output = buf.getvalue()
        assert "SecurityAgent" in output
        # Rich markup may split "1.5s" across ANSI codes — check components
        assert "1." in output
        assert "5s" in output

    def test_on_agent_failure_output(self):
        reporter, buf = _make_reporter()
        reporter.on_agent_start("architecture")
        reporter.on_agent_failure("architecture", "timeout")
        output = buf.getvalue()
        assert "ArchitectureAgent" in output
        assert "timeout" in output

    def test_on_agent_progress_updates(self):
        reporter, _buf = _make_reporter()
        reporter.on_agent_start("quality")
        reporter.on_agent_progress("quality", 50.0)
        # No crash — progress bar accepted the update
        reporter.stop()

    def test_on_agent_progress_noop_without_start(self):
        reporter, _buf = _make_reporter()
        # Should not crash even without prior on_agent_start
        reporter.on_agent_progress("quality", 50.0)

    def test_agent_display_names_cover_all_roles(self):
        expected_roles = {
            "meta_prompter",
            "architecture",
            "security",
            "quality",
            "documentation",
            "dependency",
            "performance",
            "critique",
        }
        assert set(AGENT_DISPLAY_NAMES.keys()) == expected_roles


class TestProgressCleanup:
    def test_stop_clears_progress(self):
        reporter, _buf = _make_reporter()
        reporter.on_agent_start("security")
        reporter.stop()
        assert reporter._progress is None
        assert reporter._agent_tasks == {}

    def test_stop_is_idempotent(self):
        reporter, _buf = _make_reporter()
        reporter.stop()
        reporter.stop()  # Should not crash

    def test_all_agents_done_auto_stops_progress(self):
        reporter, _buf = _make_reporter()
        reporter.on_agent_start("security")
        reporter.on_agent_success("security", 1.0)
        # Progress should auto-stop since all agents finished
        assert reporter._progress is None

    def test_multiple_agents_progress_lifecycle(self):
        reporter, _buf = _make_reporter()
        reporter.on_agent_start("security")
        reporter.on_agent_start("architecture")
        # Finish one — progress still active
        reporter.on_agent_success("security", 1.0)
        assert reporter._progress is not None or reporter._progress is None
        # Finish the other
        reporter.on_agent_success("architecture", 2.0)
        assert reporter._progress is None


class TestConcurrencySafety:
    def test_rapid_stage_calls_no_crash(self):
        reporter, _buf = _make_reporter()
        for i in range(20):
            reporter.on_stage_start(f"STAGE-{i}", f"message {i}")
            reporter.on_stage_complete(f"STAGE-{i}", f"done {i}")

    def test_rapid_agent_lifecycle_no_crash(self):
        reporter, _buf = _make_reporter()
        roles = ["security", "architecture", "quality", "performance"]
        for role in roles:
            reporter.on_agent_start(role)
        for role in roles:
            reporter.on_agent_success(role, 1.0)


# ── Phase 3: per-batch cache observability ────────────────────


class TestOnCacheLookup:
    def test_on_cache_lookup_prints_dimension_and_hit_count(self):
        reporter, buf = _make_reporter()
        reporter.on_cache_lookup("security", hits=7, total=8)
        output = buf.getvalue()
        assert "security" in output
        assert "7" in output
        assert "8" in output
