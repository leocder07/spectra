"""Rich Progress reporter implementing ProgressObserver — Layer 3 adapter."""

from __future__ import annotations

import time

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.style import Style
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from spectra.adapters.brand import AMBER, GREEN, RED, VIOLET
from spectra.entities.enums import AgentRole

# ── Theme ────────────────────────────────────────────────────────────────

SPECTRA_THEME = Theme(
    {
        "progress.description": Style(color=VIOLET, bold=True),
        "progress.percentage": Style(color=AMBER),
        "bar.complete": Style(color=VIOLET),
        "bar.finished": Style(color=GREEN),
    }
)

# ── Agent display names ─────────────────────────────────────────────────

AGENT_DISPLAY_NAMES: dict[AgentRole, str] = {
    "meta_prompter": "MetaPrompter",
    "architecture": "ArchitectureAgent",
    "security": "SecurityAgent",
    "quality": "QualityAgent",
    "documentation": "DocumentationAgent",
    "dependency": "DependencyAgent",
    "performance": "PerformanceAgent",
    "critique": "CritiqueAgent",
}

# ── Stage aesthetics ────────────────────────────────────────────────────

_STAGE_TAGS: dict[str, str] = {
    "INGEST": "INIT",
    "PLAN": "PLAN",
    "ANALYZE": "SCAN",
    "MERGE": "LINK",
    "CRITIQUE": "EVAL",
    "REPORT": "EMIT",
}

_STAGE_BARS: dict[str, str] = {
    "INIT": "\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591",
    "PLAN": "\u2593\u2593\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591",
    "SCAN": "\u2593\u2593\u2593\u2593\u2591\u2591\u2591\u2591\u2591\u2591",
    "LINK": "\u2593\u2593\u2593\u2593\u2593\u2593\u2591\u2591\u2591\u2591",
    "EVAL": "\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2591\u2591",
    "EMIT": "\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593",
}

# ── Specialist agents shown in the ANALYZE tree ─────────────────────────

_SPECIALIST_ROLES: list[AgentRole] = [
    "architecture",
    "security",
    "quality",
    "documentation",
    "dependency",
    "performance",
]


def _make_bar(pct: float) -> str:
    """Build a 10-character block bar from a 0-100 percentage."""
    filled = round(pct / 10)
    return "\u2588" * filled + "\u2591" * (10 - filled)


class RichProgressReporter:
    """Rich-based implementation of ProgressObserver protocol.

    Displays stage transitions and parallel agent progress using
    Rich Progress bars, panels, and box-drawing characters for a
    premium hacker/terminal aesthetic.
    """

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console(theme=SPECTRA_THEME)
        self._progress: Progress | None = None
        self._agent_tasks: dict[AgentRole, TaskID] = {}
        self._stage_timers: dict[str, float] = {}
        self._agent_pcts: dict[AgentRole, float] = {}
        self._agent_durations: dict[AgentRole, float] = {}
        self._agent_errors: dict[AgentRole, str] = {}
        self._finished_agents: set[AgentRole] = set()
        self._failed_agents: set[AgentRole] = set()

    # ── Stage lifecycle ──────────────────────────────────────────────

    def on_stage_start(self, stage: str, message: str) -> None:
        """Display stage start with hacker-aesthetic tag and scan bar."""
        self._stage_timers[stage] = time.monotonic()
        tag = _STAGE_TAGS.get(stage, stage[:4].upper())
        bar = _STAGE_BARS.get(tag, _STAGE_BARS["INIT"])
        self._console.print(f"[{VIOLET}][{tag}][/] [{AMBER}]{bar}[/] [bold]{message}[/]")

    def on_stage_complete(self, stage: str, message: str) -> None:
        """Display stage completion with timing."""
        elapsed = self._elapsed_for(stage)
        tag = _STAGE_TAGS.get(stage, stage[:4].upper())
        time_str = f" [{elapsed:.1f}s]" if elapsed > 0 else ""
        self._console.print(
            f"[{GREEN}][{tag}][/] "
            f"[{GREEN}]\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593[/] "
            f"[{GREEN}]{message}{time_str}[/]"
        )

    # ── Agent lifecycle ──────────────────────────────────────────────

    def on_agent_start(self, agent: AgentRole) -> None:
        """Add agent to parallel progress display."""
        display_name = AGENT_DISPLAY_NAMES.get(agent, str(agent))
        self._agent_pcts[agent] = 0.0

        if self._progress is None:
            self._progress = Progress(
                SpinnerColumn(style=Style(color=AMBER)),
                TextColumn(
                    "[progress.description]{task.description}",
                ),
                BarColumn(
                    bar_width=20,
                    complete_style=Style(color=VIOLET),
                    finished_style=Style(color=GREEN),
                ),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=self._console,
            )
            self._progress.start()

        task_id = self._progress.add_task(
            description=f"  \u251c\u2500 {display_name:<20}",
            total=100,
        )
        self._agent_tasks[agent] = task_id

    def on_agent_progress(self, agent: AgentRole, pct: float) -> None:
        """Update agent progress percentage."""
        self._agent_pcts[agent] = pct
        if self._progress is not None and agent in self._agent_tasks:
            self._progress.update(
                self._agent_tasks[agent],
                completed=pct,
            )

    def on_agent_success(self, agent: AgentRole, duration: float) -> None:
        """Mark agent as successfully complete."""
        display_name = AGENT_DISPLAY_NAMES.get(agent, str(agent))
        self._agent_pcts[agent] = 100.0
        self._agent_durations[agent] = duration
        self._finished_agents.add(agent)

        if self._progress is not None and agent in self._agent_tasks:
            task_id = self._agent_tasks[agent]
            self._progress.update(
                task_id,
                completed=100,
                description=f"  \u251c\u2500 {display_name:<20}",
            )

        all_done = self._all_agents_done()
        if all_done:
            self._stop_progress()
            self._render_agent_panel()
        else:
            self._console.print(f"[{GREEN}]  \u2713[/] {display_name} complete ({duration:.1f}s)")

    def on_agent_failure(self, agent: AgentRole, error: str) -> None:
        """Mark agent as failed."""
        display_name = AGENT_DISPLAY_NAMES.get(agent, str(agent))
        self._failed_agents.add(agent)
        self._agent_errors[agent] = error

        if self._progress is not None and agent in self._agent_tasks:
            task_id = self._agent_tasks[agent]
            self._progress.update(
                task_id,
                description=(f"  \u251c\u2500 [{RED}]{display_name:<20}[/]"),
            )

        all_done = self._all_agents_done()
        if all_done:
            self._stop_progress()
            self._render_agent_panel()
        else:
            self._console.print(f"[{RED}]  \u2717[/] {display_name} failed: {error}")

    # ── Error / stop ─────────────────────────────────────────────────

    def on_error(self, stage: str, error: str) -> None:
        """Display error with tag and explanation."""
        tag = _STAGE_TAGS.get(stage, "ERR!")
        self._console.print(f"[{RED}][{tag}][/] [{RED}]{error}[/]")

    def stop(self) -> None:
        """Clean up progress bars if still running."""
        self._stop_progress()

    # ── Internals ────────────────────────────────────────────────────

    def _elapsed_for(self, stage: str) -> float:
        """Return elapsed seconds for a stage, or 0 if not tracked."""
        start = self._stage_timers.get(stage)
        if start is None:
            return 0.0
        return time.monotonic() - start

    def _all_agents_done(self) -> bool:
        """True when every tracked agent has finished or failed."""
        if not self._agent_tasks:
            return False
        tracked = set(self._agent_tasks.keys())
        done = self._finished_agents | self._failed_agents
        return tracked.issubset(done)

    def _stop_progress(self) -> None:
        """Tear down the Rich Progress bar and clear state."""
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._agent_tasks.clear()

    def _render_agent_panel(self) -> None:
        """Draw a box-drawing agent tree panel after all agents finish."""
        table = Table(
            show_header=False,
            show_edge=False,
            box=None,
            padding=(0, 1),
        )
        table.add_column("tree", no_wrap=True)
        table.add_column("bar", no_wrap=True, justify="left")
        table.add_column("pct", no_wrap=True, justify="right")
        table.add_column("time", no_wrap=True, justify="right")

        roles = [r for r in _SPECIALIST_ROLES if r in self._finished_agents or r in self._failed_agents]
        # Include non-specialist agents that were tracked
        extras = [r for r in self._finished_agents | self._failed_agents if r not in _SPECIALIST_ROLES]
        all_roles = roles + extras

        for idx, role in enumerate(all_roles):
            name = AGENT_DISPLAY_NAMES.get(role, str(role))
            pct = self._agent_pcts.get(role, 0.0)
            is_last = idx == len(all_roles) - 1
            branch = "\u2514\u2500\u2500" if is_last else "\u251c\u2500\u2500"

            if role in self._failed_agents:
                err = self._agent_errors.get(role, "unknown")
                tree_txt = Text(f" {branch} {name:<20}", style=RED)
                bar_txt = Text("FAILED", style=f"bold {RED}")
                pct_txt = Text("", style=RED)
                time_txt = Text(err[:20], style=RED)
            else:
                dur = self._agent_durations.get(role, 0.0)
                bar_str = _make_bar(pct)
                tree_txt = Text(f" {branch} {name:<20}")
                tree_txt.stylize(f"bold {GREEN}")
                bar_txt = Text(bar_str, style=VIOLET)
                pct_txt = Text(f"{pct:>3.0f}%", style=AMBER)
                time_txt = Text(f"{dur:.1f}s", style="dim")

            table.add_row(tree_txt, bar_txt, pct_txt, time_txt)

        title = Text(" ANALYZE ", style=f"bold {AMBER} on {VIOLET}")
        panel = Panel(
            table,
            title=title,
            border_style=VIOLET,
            padding=(0, 1),
        )
        self._console.print(panel)

        # Scan-complete animation line
        total_dur = sum(self._agent_durations.values())
        ok = len(self._finished_agents)
        fail = len(self._failed_agents)
        status = f"[{GREEN}]SCAN COMPLETE[/]" if fail == 0 else f"[{AMBER}]SCAN PARTIAL[/]"
        self._console.print(f"  {status} [dim]\u2500 {ok} passed, {fail} failed, {total_dur:.1f}s total[/]")

        # Reset per-run agent bookkeeping
        self._agent_pcts.clear()
        self._agent_durations.clear()
        self._agent_errors.clear()
        self._finished_agents.clear()
        self._failed_agents.clear()
