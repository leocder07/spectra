"""Facade — orchestrates the 6-stage analysis pipeline.

Stages:
    1. INGEST — Clone repo and extract file tree (handled externally).
    2. PLAN — MetaPrompter creates per-agent focus areas.
    3. ANALYZE — 6 specialists run in parallel via ``asyncio.gather``.
    4. MERGE — Deduplicate findings and validate file paths.
    5. CRITIQUE — CritiqueAgent validates findings (extended thinking).
    6. REPORT — Build ``AnalysisReport`` with computed ScoreCard.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from spectra.entities.enums import AgentRole, Dimension
from spectra.entities.errors import ERRORS, strip_code_fence
from spectra.entities.models import (
    DEFAULT_DIMENSION_SCORE,
    AgentOutput,
    AnalysisReport,
    AnalysisRequest,
    Codebase,
    DimensionScore,
    Finding,
    ScoreCard,
    TokenBudget,
    estimate_cost,
    score_to_grade,
)
from spectra.use_cases.interfaces import GitPort, ProgressObserver
from spectra.use_cases.manage_token_budget import (
    DIMENSION_WEIGHTS,
    allocate_specialist_budgets,
    check_budget_remaining,
)
from spectra.use_cases.orchestrate_agents import (
    AnalysisAgent,
    evaluate_results,
    run_specialists,
)

_log = logging.getLogger("spectra.pipeline")


# ── Pipeline context ─────────────────────────────────────────


@dataclass(frozen=True)
class PipelineContext:
    """Immutable config: request, codebase, agents, and ports."""

    request: AnalysisRequest
    codebase: Codebase
    meta_prompter: AnalysisAgent
    specialists: list[AnalysisAgent]
    critique_agent: AnalysisAgent | None = None
    git_port: GitPort | None = None
    observer: ProgressObserver | None = None


@dataclass
class _PipelineState:
    """Mutable accumulator for in-flight pipeline data."""

    budget: TokenBudget = field(default_factory=TokenBudget)
    agent_outputs: list[AgentOutput] = field(default_factory=list)
    tokens_used: int = 0
    start_time: float = 0.0
    source_files: dict[str, str] | None = None
    analysis: _AnalysisResult | None = None


@dataclass(frozen=True)
class _AnalysisResult:
    """Immutable result from the analysis stage."""

    results: list[AgentOutput | Exception]
    failed_roles: list[AgentRole]
    is_degraded: bool
    successes: list[AgentOutput]


@dataclass(frozen=True)
class _StageOutput:
    """Output from critique pipeline: findings + insights."""

    findings: tuple[Finding, ...]
    insights: tuple[str, ...]


@dataclass(frozen=True)
class _ReportMeta:
    """Computed metadata for the final report."""

    duration: float
    tokens: int
    cost: float
    agents: tuple[AgentRole, ...]
    is_degraded: bool
    degraded_dims: tuple[Dimension, ...]
    hallucinations: int


# ── Public entry point ────────────────────────────────────────


async def analyze_repository(
    request: AnalysisRequest,
    codebase: Codebase,
    meta_prompter: AnalysisAgent,
    specialists: list[AnalysisAgent],
    critique_agent: AnalysisAgent | None,
    source_files: dict[str, str] | None = None,
    git_port: GitPort | None = None,
    observer: ProgressObserver | None = None,
) -> AnalysisReport:
    """Run the full 6-stage analysis pipeline.

    This is the main entry point for the use-case layer. It
    coordinates planning, parallel analysis, merging, critique,
    and report assembly.

    Args:
        request: User analysis request with URL and options.
        codebase: Cloned repository metadata and file tree.
        meta_prompter: Planning agent (Sonnet 4.5).
        specialists: List of 6 specialist agents.
        critique_agent: Validation agent, or None to skip.
        source_files: Pre-read source files, or None to read lazily.
        git_port: Git adapter for lazy file reads.
        observer: Progress callback for terminal display.

    Returns:
        Complete analysis report with scores and findings.
    """
    ctx = PipelineContext(
        request,
        codebase,
        meta_prompter,
        specialists,
        critique_agent,
        git_port,
        observer,
    )
    state = _PipelineState(
        start_time=time.monotonic(),
        source_files=source_files,
    )
    return await _run_pipeline(ctx, state)


async def _run_pipeline(
    ctx: PipelineContext,
    state: _PipelineState,
) -> AnalysisReport:
    """Thin coordinator that delegates to stage functions."""
    plan = await _run_plan_stage(ctx, state)
    await _resolve_source_files(ctx, plan, state)
    state.analysis = await _run_analyze_stage(ctx, plan, state)
    findings = _run_merge_stage(state, ctx)
    output = await _run_critique_pipeline(ctx, findings, state)
    return _build_report(ctx, state, output)


# ── Stage 2: PLAN ────────────────────────────────────────────


async def _run_plan_stage(
    ctx: PipelineContext,
    state: _PipelineState,
) -> AgentOutput:
    """Execute MetaPrompter and wire token allocations."""
    _notify(ctx.observer, "on_stage_start", "PLAN", "Running MetaPrompter")
    plan_output = await ctx.meta_prompter.run(
        "\n".join(ctx.codebase.file_tree),
    )
    _track_output(state, plan_output)
    _notify(ctx.observer, "on_stage_complete", "PLAN", "Plan ready")
    allocs = _extract_token_allocations(plan_output.raw_response)
    allocate_specialist_budgets(state.budget, allocs)
    return plan_output


async def _resolve_source_files(
    ctx: PipelineContext,
    plan_output: AgentOutput,
    state: _PipelineState,
) -> None:
    """Read source files via git_port if not already provided."""
    if state.source_files is not None:
        return
    if ctx.git_port is None:
        return
    state.source_files = await _read_planned_files(
        ctx.git_port,
        ctx.codebase,
        plan_output.raw_response,
    )


# ── Stage 3: ANALYZE ─────────────────────────────────────────


async def _run_analyze_stage(
    ctx: PipelineContext,
    plan_output: AgentOutput,
    state: _PipelineState,
) -> _AnalysisResult:
    """Run 6 specialists in parallel and collect results."""
    _notify(ctx.observer, "on_stage_start", "ANALYZE", "Running specialists")
    prompts = _build_specialist_prompts(ctx, plan_output, state)
    analysis = await _execute_specialists(
        ctx.specialists,
        prompts,
        ctx.observer,
    )
    _track_outputs(state, analysis.successes)
    _notify(ctx.observer, "on_stage_complete", "ANALYZE", "Analysis complete")
    _log_budget_warning(state)
    return analysis


def _build_specialist_prompts(
    ctx: PipelineContext,
    plan_output: AgentOutput,
    state: _PipelineState,
) -> dict[AgentRole, str]:
    """Assemble prompt strings for each specialist."""
    full_tree = ctx.codebase.file_tree
    full_tree_text = "\n".join(full_tree)
    plan_ctx = _extract_plan_context(plan_output.raw_response)
    source_ctx = _build_source_context(state.source_files)
    agent_files = _extract_agent_files(plan_output.raw_response)

    prompts: dict[AgentRole, str] = {}
    for s in ctx.specialists:
        tree_text = _filtered_tree(full_tree, full_tree_text, agent_files.get(s.role))
        parts = [tree_text]
        if plan_ctx:
            parts.append(plan_ctx.get(s.role, ""))
        if source_ctx:
            parts.append(source_ctx)
        prompts[s.role] = "\n\n".join(p for p in parts if p)
    return prompts


def _filtered_tree(
    full_tree: tuple[str, ...],
    full_tree_text: str,
    agent_file_set: set[str] | None,
) -> str:
    """Return filtered file tree for an agent, or full tree if no filter."""
    if not agent_file_set:
        return full_tree_text
    return "\n".join(f for f in full_tree if f in agent_file_set)


def _log_budget_warning(state: _PipelineState) -> None:
    """Warn if token budget is exhausted after analysis."""
    remaining = check_budget_remaining(state.budget, state.tokens_used)
    if remaining == 0:
        _log.warning("SPEC-004: Token budget exhausted after analysis")


# ── Stage 4: MERGE ────────────────────────────────────────────


def _run_merge_stage(
    state: _PipelineState,
    ctx: PipelineContext,
) -> tuple[Finding, ...]:
    """Merge, deduplicate, and validate findings."""
    unique = _merge_findings(state.analysis.successes)
    return _validate_finding_paths(unique, ctx.codebase.file_tree)


# ── Stage 5: CRITIQUE ────────────────────────────────────────


async def _run_critique_pipeline(
    ctx: PipelineContext,
    findings: tuple[Finding, ...],
    state: _PipelineState,
) -> _StageOutput:
    """Run critique if eligible, return findings and insights."""
    remaining = check_budget_remaining(state.budget, state.tokens_used)
    eligible = _should_run_critique(
        ctx.request,
        state.analysis.is_degraded,
        ctx.critique_agent,
        remaining,
    )
    if not eligible:
        return _StageOutput(findings, ())
    if ctx.critique_agent is None:
        msg = "critique_agent must not be None when critique is enabled"
        raise RuntimeError(msg)
    return await _execute_critique(ctx, findings, state)


async def _execute_critique(
    ctx: PipelineContext,
    findings: tuple[Finding, ...],
    state: _PipelineState,
) -> _StageOutput:
    """Execute CritiqueAgent and apply results."""
    _notify(ctx.observer, "on_stage_start", "CRITIQUE", "Validating findings")
    filtered, insights, out = await _run_critique_stage(
        ctx.critique_agent,
        findings,
        ctx.observer,
    )
    if out is not None:
        _track_output(state, out)
    _notify(ctx.observer, "on_stage_complete", "CRITIQUE", "Critique complete")
    return _StageOutput(filtered, insights)


# ── Stage 6: REPORT ──────────────────────────────────────────


def _build_report(
    ctx: PipelineContext,
    state: _PipelineState,
    output: _StageOutput,
) -> AnalysisReport:
    """Compute scores and assemble the final report."""
    score_card = _compute_scorecard(
        output.findings,
        state.analysis.failed_roles,
        state.agent_outputs,
    )
    meta = _report_metadata(ctx, state)
    return AnalysisReport(
        repo_url=ctx.request.repo_url,
        repo_name=ctx.codebase.repo_name,
        score_card=score_card,
        findings=output.findings,
        analysis_duration_seconds=meta.duration,
        total_tokens_used=meta.tokens,
        total_cost_usd=meta.cost,
        agents_used=meta.agents,
        is_degraded=meta.is_degraded,
        degraded_dimensions=meta.degraded_dims,
        cross_cutting_insights=output.insights,
        hallucination_removed_count=meta.hallucinations,
    )


def _report_metadata(
    ctx: PipelineContext,
    state: _PipelineState,
) -> _ReportMeta:
    """Compute all derived metadata for the report."""
    analysis = state.analysis
    return _ReportMeta(
        duration=round(time.monotonic() - state.start_time, 2),
        tokens=state.tokens_used,
        cost=estimate_cost(tuple(state.agent_outputs)),
        agents=_active_agents(ctx.specialists, analysis),
        is_degraded=analysis.is_degraded,
        degraded_dims=_degraded_dims(analysis.failed_roles),
        hallucinations=_hallucination_count(
            analysis.successes,
            ctx.codebase,
        ),
    )


def _active_agents(
    specialists: list[AnalysisAgent],
    analysis: _AnalysisResult,
) -> tuple[AgentRole, ...]:
    """Return roles of specialists that succeeded."""
    return tuple(s.role for s in specialists if s.role not in analysis.failed_roles)


def _degraded_dims(
    failed_roles: list[AgentRole],
) -> tuple[Dimension, ...]:
    """Map failed roles to their dimensions."""
    return tuple(_role_to_dimension(r) for r in failed_roles)


def _hallucination_count(
    successes: list[AgentOutput],
    codebase: Codebase,
) -> int:
    """Count findings removed by path validation."""
    merged = _merge_findings(successes)
    validated = _validate_finding_paths(merged, codebase.file_tree)
    return len(merged) - len(validated)


# ── State tracking helpers ───────────────────────────────────


def _track_output(state: _PipelineState, output: AgentOutput) -> None:
    """Record a single agent output in the pipeline state."""
    state.agent_outputs.append(output)
    state.tokens_used += output.tokens_used


def _track_outputs(
    state: _PipelineState,
    outputs: list[AgentOutput],
) -> None:
    """Record multiple agent outputs in the pipeline state."""
    for output in outputs:
        _track_output(state, output)


# ── Specialist execution ─────────────────────────────────────


async def _execute_specialists(
    specialists: list[AnalysisAgent],
    prompts: dict[AgentRole, str],
    observer: ProgressObserver | None,
) -> _AnalysisResult:
    """Run specialists in parallel and evaluate results."""
    roles = [s.role for s in specialists]
    _notify_agent_starts(observer, roles)
    results = await run_specialists(specialists, prompts)
    successes, failed_roles, pipe_state = evaluate_results(
        results,
        roles,
    )
    _notify_agent_results(observer, results, roles)
    _log_spec007_if_needed(failed_roles)
    return _AnalysisResult(
        results,
        failed_roles,
        pipe_state == "degraded",
        successes,
    )


def _notify_agent_starts(
    observer: ProgressObserver | None,
    roles: list[AgentRole],
) -> None:
    """Send on_agent_start for each role."""
    for role in roles:
        _notify(observer, "on_agent_start", role)


def _notify_agent_results(
    observer: ProgressObserver | None,
    results: list[AgentOutput | Exception],
    roles: list[AgentRole],
) -> None:
    """Notify observer of each agent's success or failure."""
    for result, role in zip(results, roles, strict=False):
        if isinstance(result, Exception):
            _notify(observer, "on_agent_failure", role, str(result))
        else:
            _notify(
                observer,
                "on_agent_success",
                role,
                result.duration_seconds,
            )


def _log_spec007_if_needed(
    failed_roles: list[AgentRole],
) -> None:
    """Log SPEC-007 warning when 2+ agents failed."""
    if len(failed_roles) < 2:
        return
    spec007 = ERRORS["SPEC-007"]
    _log.warning(
        "%s: %s — failed: %s",
        spec007.code,
        spec007.message,
        failed_roles,
    )


# ── Stage helpers ─────────────────────────────────────────────


def _extract_token_allocations(
    raw_plan: str,
) -> dict[str, int] | None:
    """Pull token_allocation map from MetaPrompter plan JSON."""
    try:
        plan = json.loads(strip_code_fence(raw_plan))
    except (json.JSONDecodeError, IndexError):
        return None
    allocs = plan.get("token_allocation")
    if isinstance(allocs, dict) and allocs:
        return allocs
    return None


async def _read_planned_files(
    git_port: GitPort,
    codebase: Codebase,
    raw_plan: str,
) -> dict[str, str]:
    """Read source files recommended by the MetaPrompter plan."""
    plan_files = _extract_plan_files(raw_plan)
    tree_set = set(codebase.file_tree)
    source: dict[str, str] = {}
    for path in sorted(plan_files & tree_set):
        try:
            source[path] = await git_port.read_file(
                codebase.local_path,
                path,
            )
        except (ValueError, OSError):
            continue
    return source


def _merge_findings(
    successes: list[AgentOutput],
) -> tuple[Finding, ...]:
    """Collect and deduplicate findings from all successful agents.

    Args:
        successes: Agent outputs that completed without error.

    Returns:
        Deduplicated findings preserving first-seen order.
    """
    # O(n) collection: extend is amortized O(1) per finding
    all_findings: list[Finding] = []
    for output in successes:
        all_findings.extend(output.findings)
    # O(n) deduplication: dict.fromkeys preserves insertion order
    # while deduplicating via Finding.__hash__/__eq__
    return tuple(dict.fromkeys(all_findings))


def _validate_finding_paths(
    findings: tuple[Finding, ...],
    file_tree: tuple[str, ...],
) -> tuple[Finding, ...]:
    """Remove findings that reference files not in the repo."""
    # Convert to set once for O(1) membership tests (vs O(n) per lookup)
    file_set = set(file_tree)
    return tuple(f for f in findings if _is_valid_path(f, file_set))


def _is_valid_path(finding: Finding, file_set: set[str]) -> bool:
    """Check whether a finding references a real file."""
    path = finding.location.file_path
    if not path or path in file_set:
        return True
    if any(path in ft for ft in file_set):
        return True
    _log.warning(
        "Hallucinated path removed: %s (finding: %s)",
        path,
        finding.id,
    )
    return False


def _should_run_critique(
    request: AnalysisRequest,
    is_degraded: bool,
    critique_agent: AnalysisAgent | None,
    remaining_tokens: int,
) -> bool:
    """Determine whether the critique stage should run."""
    if request.quick or is_degraded or critique_agent is None:
        return False
    return remaining_tokens != 0


async def _run_critique_stage(
    critique_agent: AnalysisAgent,
    findings: tuple[Finding, ...],
    observer: ProgressObserver | None,
) -> tuple[tuple[Finding, ...], tuple[str, ...], AgentOutput | None]:
    """Run CritiqueAgent; return filtered findings + insights."""
    _notify(observer, "on_agent_start", "critique")
    findings_json = json.dumps(
        [f.model_dump() for f in findings],
        indent=2,
    )
    try:
        critique_output = await critique_agent.run(findings_json)
    except Exception as exc:
        return _handle_critique_failure(observer, findings, exc)

    _notify(
        observer,
        "on_agent_success",
        "critique",
        critique_output.duration_seconds,
    )
    filtered = _apply_critique(findings, critique_output.raw_response)
    insights = _extract_cross_cutting_insights(
        critique_output.raw_response,
    )
    return filtered, insights, critique_output


def _handle_critique_failure(
    observer: ProgressObserver | None,
    findings: tuple[Finding, ...],
    exc: Exception,
) -> tuple[tuple[Finding, ...], tuple[str, ...], None]:
    """Log SPEC-008 and return unmodified findings."""
    spec008 = ERRORS["SPEC-008"]
    _log.warning("%s: %s — cause: %s", spec008.code, spec008.message, exc)
    _notify(observer, "on_agent_failure", "critique", spec008.message)
    return findings, (), None


# ── Critique parsing ──────────────────────────────────────────


def _parse_critique_json(raw_critique: str) -> dict | None:
    """Parse critique JSON, returning None on failure."""
    try:
        return json.loads(strip_code_fence(raw_critique))
    except (json.JSONDecodeError, IndexError):
        return None


def _apply_critique(
    findings: tuple[Finding, ...],
    raw_critique: str,
) -> tuple[Finding, ...]:
    """Filter findings and apply severity adjustments."""
    critique = _parse_critique_json(raw_critique)
    if critique is None:
        return findings
    validated = _reject_findings(findings, critique)
    return _apply_severity_adjustments(validated, critique)


def _reject_findings(
    findings: tuple[Finding, ...],
    critique: dict,
) -> tuple[Finding, ...]:
    """Remove findings flagged as rejected by the critique."""
    rejected_ids = _collect_rejected_ids(critique)
    return tuple(f for f in findings if f.id not in rejected_ids)


def _collect_rejected_ids(critique: dict) -> set[str]:
    """Extract rejected finding IDs from critique payload."""
    ids: set[str] = set()
    for r in critique.get("rejected_findings", []):
        if isinstance(r, dict) and "id" in r:
            ids.add(r["id"])
        elif isinstance(r, str):
            ids.add(r)
    return ids


def _apply_severity_adjustments(
    findings: tuple[Finding, ...],
    critique: dict,
) -> tuple[Finding, ...]:
    """Apply severity overrides from critique agent."""
    adj_map = _build_severity_map(critique)
    if not adj_map:
        return findings
    return tuple(_adjust_finding(f, adj_map) for f in findings)


def _build_severity_map(critique: dict) -> dict[str, str]:
    """Build finding_id -> adjusted_severity mapping."""
    result: dict[str, str] = {}
    for adj in critique.get("severity_adjustments", []):
        if isinstance(adj, dict) and "finding_id" in adj:
            new_sev = adj.get("adjusted_severity", "")
            if new_sev:
                result[adj["finding_id"]] = new_sev
    return result


def _adjust_finding(
    finding: Finding,
    adj_map: dict[str, str],
) -> Finding:
    """Apply severity adjustment to a single finding."""
    if finding.id not in adj_map:
        return finding
    return finding.model_copy(
        update={
            "severity": adj_map[finding.id],
            "validated_by_critique": True,
        },
    )


def _extract_cross_cutting_insights(
    raw_critique: str,
) -> tuple[str, ...]:
    """Pull cross-cutting insights from critique output."""
    critique = _parse_critique_json(raw_critique)
    if critique is None:
        return ()
    insights = critique.get("cross_cutting_insights", [])
    if isinstance(insights, list):
        return tuple(str(i) for i in insights if i)
    return ()


# ── Plan & source parsing ─────────────────────────────────────


def _extract_plan_context(
    raw_plan: str,
) -> dict[AgentRole, str] | None:
    """Parse MetaPrompter plan into per-agent focus context."""
    try:
        plan = json.loads(strip_code_fence(raw_plan))
    except (json.JSONDecodeError, IndexError):
        return None

    focus_areas = plan.get("focus_areas", [])
    if not focus_areas:
        return None

    context: dict[AgentRole, str] = {}
    for area in focus_areas:
        _add_focus_context(context, area)
    return context or None


def _add_focus_context(
    context: dict[AgentRole, str],
    area: dict,
) -> None:
    """Add a single focus area to the context map."""
    agent = area.get("agent", "")
    files = area.get("files", [])
    concerns = area.get("concerns", [])
    if not agent or not (files or concerns):
        return
    parts = [f"PLAN — Focus for {agent}:"]
    if files:
        parts.append(f"  Files: {', '.join(str(f) for f in files)}")
    if concerns:
        parts.append(
            f"  Concerns: {', '.join(str(c) for c in concerns)}",
        )
    context[agent] = "\n".join(parts)


def _build_source_context(
    source_files: dict[str, str] | None,
) -> str:
    """Format source files into a single prompt section."""
    if not source_files:
        return ""
    parts = ["SOURCE CODE:"]
    for path, content in source_files.items():
        parts.append(f"--- {path} ---")
        parts.append(content)
    return "\n".join(parts)


def _extract_plan_files(raw_plan: str) -> set[str]:
    """Extract recommended file paths from MetaPrompter plan JSON."""
    try:
        plan = json.loads(strip_code_fence(raw_plan))
    except (json.JSONDecodeError, IndexError):
        return set()

    files: set[str] = set()
    for area in plan.get("focus_areas", []):
        for f in area.get("files", []):
            files.add(str(f))
    return files


def _extract_agent_files(
    raw_plan: str,
) -> dict[AgentRole, set[str]]:
    """Extract per-agent file sets from MetaPrompter plan."""
    try:
        plan = json.loads(strip_code_fence(raw_plan))
    except (json.JSONDecodeError, IndexError):
        return {}

    result: dict[AgentRole, set[str]] = {}
    for area in plan.get("focus_areas", []):
        agent = area.get("agent", "")
        files = area.get("files", [])
        if agent and files:
            result[agent] = {str(f) for f in files}
    return result


# ── Scoring ───────────────────────────────────────────────────


def _compute_scorecard(
    findings: tuple[Finding, ...],
    failed_roles: list[AgentRole],
    agent_outputs: list[AgentOutput] | None = None,
) -> ScoreCard:
    """Build ScoreCard from findings + LLM scores."""
    active_weights = _compute_active_weights(failed_roles)
    llm_scores = _build_llm_score_map(agent_outputs)
    dimensions = _score_dimensions(
        findings,
        active_weights,
        llm_scores,
    )
    return _finalize_scorecard(dimensions, findings)


def _finalize_scorecard(
    dimensions: list[DimensionScore],
    findings: tuple[Finding, ...],
) -> ScoreCard:
    """Compute overall score and build the ScoreCard."""
    overall = sum(d.score * d.weight for d in dimensions)
    return ScoreCard(
        overall_score=round(overall, 1),
        overall_grade=score_to_grade(overall),
        dimensions=tuple(dimensions),
        total_findings=len(findings),
    )


def _compute_active_weights(
    failed_roles: list[AgentRole],
) -> dict[Dimension, float]:
    """Filter dimension weights to exclude failed agents."""
    return {dim: w for dim, w in DIMENSION_WEIGHTS.items() if _dimension_to_role(dim) not in failed_roles}


def _build_llm_score_map(
    agent_outputs: list[AgentOutput] | None,
) -> dict[Dimension, float]:
    """Extract LLM-assigned dimension scores from outputs."""
    scores: dict[Dimension, float] = {}
    if not agent_outputs:
        return scores
    for out in agent_outputs:
        if out.dimension_score is not None:
            dim = _role_to_dimension(out.agent_role)
            scores[dim] = out.dimension_score
    return scores


def _score_dimensions(
    findings: tuple[Finding, ...],
    active_weights: dict[Dimension, float],
    llm_scores: dict[Dimension, float],
) -> list[DimensionScore]:
    """Score each active dimension."""
    total = sum(active_weights.values()) or 1.0
    grouped = _group_findings_by_dimension(findings)
    dimensions: list[DimensionScore] = []
    for dim, raw_weight in active_weights.items():
        dim_findings = grouped.get(dim, [])
        score = _estimate_score(dim_findings, llm_scores.get(dim))
        dimensions.append(
            DimensionScore(
                dimension=dim,
                score=score,
                grade=score_to_grade(score),
                findings_count=len(dim_findings),
                weight=round(raw_weight / total, 3),
            )
        )
    return dimensions


def _group_findings_by_dimension(
    findings: tuple[Finding, ...],
) -> dict[Dimension, list[Finding]]:
    """Pre-group findings by dimension in a single pass (O(n)).

    Uses ``dict.setdefault`` for O(1) amortized insertion per finding.
    No secondary iteration or sorting required — findings are bucketed
    as they are encountered.
    """
    # O(n) single-pass grouping — one dict lookup per finding
    grouped: dict[Dimension, list[Finding]] = {}
    for f in findings:
        grouped.setdefault(f.dimension, []).append(f)
    return grouped


_PENALTY_MAP: dict[str, float] = {
    "critical": 15.0,
    "high": 8.0,
    "medium": 3.0,
    "low": 1.0,
    "info": 0.0,
}
_MAX_PENALTY: float = 55.0


def _estimate_score(
    findings: list[Finding],
    llm_score: float | None = None,
) -> float:
    """Blend LLM assessment with penalty-based formula.

    When the LLM provides a holistic score, we weight it 40% and the
    penalty-based score 60% to anchor on evidence while respecting
    the LLM's broader context awareness.

    Args:
        findings: Findings for a single dimension.
        llm_score: Optional LLM-assigned score (0-100).

    Returns:
        Blended dimension score between 0 and 100.
    """
    if not findings:
        return DEFAULT_DIMENSION_SCORE
    penalty_score = _compute_penalty_score(findings)
    if llm_score is not None:
        # 40/60 blend: trust evidence more than LLM self-assessment
        return round(0.4 * llm_score + 0.6 * penalty_score, 1)
    return round(penalty_score, 1)


def _compute_penalty_score(findings: list[Finding]) -> float:
    """Calculate penalty-based score from findings."""
    raw_penalty = sum(_PENALTY_MAP.get(f.severity, 0.0) for f in findings)
    capped = min(raw_penalty, _MAX_PENALTY)
    return max(0.0, 100.0 - capped)


# ── Role/dimension mapping ────────────────────────────────────

_ROLE_TO_DIM: dict[AgentRole, Dimension] = {
    "architecture": "architecture",
    "security": "security",
    "quality": "quality",
    "documentation": "documentation",
    "dependency": "maintainability",
    "performance": "performance",
}

_DIM_TO_ROLE: dict[Dimension, AgentRole] = {v: k for k, v in _ROLE_TO_DIM.items()}


def _role_to_dimension(role: AgentRole) -> Dimension:
    return _ROLE_TO_DIM.get(role, "architecture")


def _dimension_to_role(dim: Dimension) -> AgentRole:
    return _DIM_TO_ROLE.get(dim, "architecture")


# ── Observer helper ───────────────────────────────────────────


def _notify(
    observer: ProgressObserver | None,
    method: str,
    *args: object,
) -> None:
    """Call observer method if observer is present."""
    if observer is not None:
        getattr(observer, method)(*args)
