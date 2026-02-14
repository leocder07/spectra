"""Facade — orchestrates the 6-stage analysis pipeline."""

from __future__ import annotations

import json
import logging
import time

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
    """Run the full 6-stage pipeline."""
    start = time.monotonic()
    budget = TokenBudget()
    agent_outputs: list[AgentOutput] = []

    # Stage 2: PLAN
    _notify(observer, "on_stage_start", "PLAN", "Running MetaPrompter")
    plan_output = await meta_prompter.run(
        "\n".join(codebase.file_tree),
    )
    agent_outputs.append(plan_output)
    tokens_used = plan_output.tokens_used
    _notify(observer, "on_stage_complete", "PLAN", "Plan ready")

    # Wire token budget from plan allocations
    allocations = _extract_token_allocations(plan_output.raw_response)
    allocate_specialist_budgets(budget, allocations)

    # Read source files if needed
    if source_files is None and git_port is not None:
        source_files = await _read_planned_files(
            git_port, codebase, plan_output.raw_response,
        )

    # Stage 3: ANALYZE
    _notify(observer, "on_stage_start", "ANALYZE", "Running specialists")
    prompts = _build_prompts(
        specialists, codebase, plan_output.raw_response, source_files,
    )
    results, failed_roles, is_degraded, successes = (
        await _run_analysis_stage(
            specialists, prompts, observer,
        )
    )
    agent_outputs.extend(successes)
    tokens_used += sum(o.tokens_used for o in successes)
    _notify(observer, "on_stage_complete", "ANALYZE", "Analysis complete")

    # Check budget before critique
    remaining = check_budget_remaining(budget, tokens_used)
    if remaining == 0:
        _log.warning("SPEC-004: Token budget exhausted after analysis")

    # Stage 4: MERGE
    unique_findings = _merge_findings(successes)

    # Stage 5: CRITIQUE
    critique_insights: tuple[str, ...] = ()
    if _should_run_critique(request, is_degraded, critique_agent, remaining):
        _notify(observer, "on_stage_start", "CRITIQUE", "Validating findings")
        unique_findings, critique_insights, critique_out = (
            await _run_critique_stage(
                critique_agent, unique_findings, observer,  # type: ignore[arg-type]
            )
        )
        if critique_out is not None:
            agent_outputs.append(critique_out)
            tokens_used += critique_out.tokens_used
        _notify(observer, "on_stage_complete", "CRITIQUE", "Critique complete")

    # Stage 6: REPORT — compute scores
    score_card = _compute_scorecard(unique_findings, failed_roles, agent_outputs)
    cost = estimate_cost(tuple(agent_outputs))

    return AnalysisReport(
        repo_url=request.repo_url,
        repo_name=codebase.repo_name,
        score_card=score_card,
        findings=unique_findings,
        analysis_duration_seconds=round(time.monotonic() - start, 2),
        total_tokens_used=tokens_used,
        total_cost_usd=cost,
        agents_used=tuple(
            s.role for s in specialists if s.role not in failed_roles
        ),
        is_degraded=is_degraded,
        degraded_dimensions=tuple(
            _role_to_dimension(r) for r in failed_roles
        ),
        cross_cutting_insights=critique_insights,
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
                codebase.local_path, path,
            )
        except (ValueError, OSError):
            continue
    return source


def _build_prompts(
    specialists: list[AnalysisAgent],
    codebase: Codebase,
    raw_plan: str,
    source_files: dict[str, str] | None,
) -> dict[AgentRole, str]:
    """Build per-specialist prompt strings."""
    file_tree_text = "\n".join(codebase.file_tree)
    plan_context = _extract_plan_context(raw_plan)
    source_context = _build_source_context(source_files)

    prompts: dict[AgentRole, str] = {}
    for s in specialists:
        parts = [file_tree_text]
        if plan_context:
            parts.append(plan_context.get(s.role, ""))
        if source_context:
            parts.append(source_context)
        prompts[s.role] = "\n\n".join(p for p in parts if p)
    return prompts


async def _run_analysis_stage(
    specialists: list[AnalysisAgent],
    prompts: dict[AgentRole, str],
    observer: ProgressObserver | None,
) -> tuple[
    list[AgentOutput | Exception],
    list[AgentRole],
    bool,
    list[AgentOutput],
]:
    """Run specialists in parallel, notify observer, return results."""
    roles: list[AgentRole] = [s.role for s in specialists]
    for role in roles:
        _notify(observer, "on_agent_start", role)

    results = await run_specialists(specialists, prompts)
    successes, failed_roles, state = evaluate_results(results, roles)

    # Notify observer per agent
    for result, role in zip(results, roles, strict=False):
        if isinstance(result, Exception):
            _notify(observer, "on_agent_failure", role, str(result))
        else:
            _notify(
                observer, "on_agent_success", role, result.duration_seconds,
            )

    if len(failed_roles) >= 2:
        spec007 = ERRORS["SPEC-007"]
        _log.warning(
            "%s: %s — failed: %s",
            spec007.code,
            spec007.message,
            failed_roles,
        )

    return results, failed_roles, state == "degraded", successes


def _merge_findings(
    successes: list[AgentOutput],
) -> tuple[Finding, ...]:
    """Collect and deduplicate findings from successful agents."""
    all_findings: list[Finding] = []
    for output in successes:
        all_findings.extend(output.findings)
    return tuple(dict.fromkeys(all_findings))


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
        [f.model_dump() for f in findings], indent=2,
    )
    try:
        critique_output = await critique_agent.run(findings_json)
    except Exception:
        spec008 = ERRORS["SPEC-008"]
        _log.warning("%s: %s", spec008.code, spec008.message)
        _notify(observer, "on_agent_failure", "critique", spec008.message)
        return findings, (), None

    _notify(
        observer, "on_agent_success", "critique",
        critique_output.duration_seconds,
    )
    filtered = _apply_critique(findings, critique_output.raw_response)
    insights = _extract_cross_cutting_insights(
        critique_output.raw_response,
    )
    return filtered, insights, critique_output


# ── Critique parsing ──────────────────────────────────────────


def _apply_critique(
    findings: tuple[Finding, ...],
    raw_critique: str,
) -> tuple[Finding, ...]:
    """Filter findings and apply severity adjustments from critique."""
    try:
        critique = json.loads(strip_code_fence(raw_critique))
    except (json.JSONDecodeError, IndexError):
        return findings

    # Reject findings the critique agent flagged
    rejected_ids: set[str] = set()
    for r in critique.get("rejected_findings", []):
        if isinstance(r, dict) and "id" in r:
            rejected_ids.add(r["id"])
        elif isinstance(r, str):
            rejected_ids.add(r)

    validated = tuple(f for f in findings if f.id not in rejected_ids)

    # Apply severity adjustments (create new Finding since frozen)
    adjustments = critique.get("severity_adjustments", [])
    if not adjustments:
        return validated

    adj_map: dict[str, str] = {}
    for adj in adjustments:
        if isinstance(adj, dict) and "finding_id" in adj:
            new_sev = adj.get("adjusted_severity", "")
            if new_sev:
                adj_map[adj["finding_id"]] = new_sev

    if not adj_map:
        return validated

    result: list[Finding] = []
    for f in validated:
        if f.id in adj_map:
            result.append(
                f.model_copy(
                    update={
                        "severity": adj_map[f.id],
                        "validated_by_critique": True,
                    },
                ),
            )
        else:
            result.append(f)
    return tuple(result)


def _extract_cross_cutting_insights(
    raw_critique: str,
) -> tuple[str, ...]:
    """Pull cross-cutting insights from critique output."""
    try:
        critique = json.loads(strip_code_fence(raw_critique))
    except (json.JSONDecodeError, IndexError):
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
        agent = area.get("agent", "")
        files = area.get("files", [])
        concerns = area.get("concerns", [])
        if agent and (files or concerns):
            parts = [f"PLAN — Focus for {agent}:"]
            if files:
                parts.append(
                    f"  Files: {', '.join(str(f) for f in files)}",
                )
            if concerns:
                parts.append(
                    f"  Concerns: {', '.join(str(c) for c in concerns)}",
                )
            context[agent] = "\n".join(parts)
    return context or None


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


# ── Scoring ───────────────────────────────────────────────────


def _compute_scorecard(
    findings: tuple[Finding, ...],
    failed_roles: list[AgentRole],
    agent_outputs: list[AgentOutput] | None = None,
) -> ScoreCard:
    """Build ScoreCard from findings + LLM scores, reweighting if dimensions failed."""
    active_weights = {
        dim: w
        for dim, w in DIMENSION_WEIGHTS.items()
        if _dimension_to_role(dim) not in failed_roles
    }
    total_weight = sum(active_weights.values()) or 1.0

    # Build LLM score map from agent outputs
    llm_scores: dict[Dimension, float] = {}
    if agent_outputs:
        for out in agent_outputs:
            dim = _role_to_dimension(out.agent_role)
            if out.dimension_score is not None:
                llm_scores[dim] = out.dimension_score

    dimensions: list[DimensionScore] = []
    for dim, raw_weight in active_weights.items():
        dim_findings = [f for f in findings if f.dimension == dim]
        score = _estimate_score(dim_findings, llm_scores.get(dim))
        normalized_weight = raw_weight / total_weight
        dimensions.append(
            DimensionScore(
                dimension=dim,
                score=score,
                grade=score_to_grade(score),
                findings_count=len(dim_findings),
                weight=round(normalized_weight, 3),
            ),
        )

    overall = sum(d.score * d.weight for d in dimensions)
    return ScoreCard(
        overall_score=round(overall, 1),
        overall_grade=score_to_grade(overall),
        dimensions=tuple(dimensions),
        total_findings=len(findings),
    )


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
    """Estimate dimension score blending LLM assessment with penalty formula."""
    if not findings:
        return DEFAULT_DIMENSION_SCORE

    raw_penalty = sum(
        _PENALTY_MAP.get(f.severity, 0.0) for f in findings
    )
    capped_penalty = min(raw_penalty, _MAX_PENALTY)
    penalty_score = max(0.0, 100.0 - capped_penalty)

    if llm_score is not None:
        return round(0.4 * llm_score + 0.6 * penalty_score, 1)
    return round(penalty_score, 1)


# ── Role/dimension mapping ────────────────────────────────────

_ROLE_TO_DIM: dict[AgentRole, Dimension] = {
    "architecture": "architecture",
    "security": "security",
    "quality": "quality",
    "documentation": "documentation",
    "dependency": "maintainability",
    "performance": "performance",
}

_DIM_TO_ROLE: dict[Dimension, AgentRole] = {
    v: k for k, v in _ROLE_TO_DIM.items()
}


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
