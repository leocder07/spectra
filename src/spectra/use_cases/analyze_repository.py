"""Facade — orchestrates the 6-stage analysis pipeline."""

from __future__ import annotations

import json
import time

import logging

from spectra.entities.enums import AgentRole, Dimension
from spectra.entities.errors import ERRORS
from spectra.entities.models import (
    AnalysisReport,
    AnalysisRequest,
    Codebase,
    DimensionScore,
    Finding,
    ScoreCard,
    TokenBudget,
    score_to_grade,
)
from spectra.use_cases.interfaces import GitPort
from spectra.use_cases.manage_token_budget import (
    DIMENSION_WEIGHTS,
    allocate_specialist_budgets,
)
from spectra.use_cases.orchestrate_agents import (
    AnalysisAgent,
    evaluate_results,
    run_specialists,
)


async def analyze_repository(
    request: AnalysisRequest,
    codebase: Codebase,
    meta_prompter: AnalysisAgent,
    specialists: list[AnalysisAgent],
    critique_agent: AnalysisAgent | None,
    source_files: dict[str, str] | None = None,
    git_port: GitPort | None = None,
) -> AnalysisReport:
    """Run the full 6-stage pipeline: INGEST -> PLAN -> ANALYZE -> MERGE -> CRITIQUE -> REPORT."""
    start = time.monotonic()
    budget = TokenBudget()
    tokens_used = 0

    # Stage 2: PLAN — MetaPrompter gets file tree only
    file_tree_text = "\n".join(codebase.file_tree)
    plan_output = await meta_prompter.run(file_tree_text)
    tokens_used += plan_output.tokens_used

    # Read source files based on plan if git_port provided
    if source_files is None and git_port is not None:
        plan_files = _extract_plan_files(plan_output.raw_response)
        source_files = await _read_source_files(
            git_port, codebase.local_path, plan_files, codebase.file_tree,
        )

    # Build specialist prompts with source code and plan context
    plan_context = _extract_plan_context(plan_output.raw_response)
    source_context = _build_source_context(source_files)

    roles: list[AgentRole] = [s.role for s in specialists]
    prompts: dict[AgentRole, str] = {}
    for s in specialists:
        parts = [file_tree_text]
        if plan_context:
            parts.append(plan_context.get(s.role, ""))
        if source_context:
            parts.append(source_context)
        prompts[s.role] = "\n\n".join(p for p in parts if p)

    # Stage 3: ANALYZE — 6 specialists in parallel
    _log = logging.getLogger("spectra.pipeline")
    results = await run_specialists(specialists, prompts)
    successes, failed_roles, state = evaluate_results(results, roles)

    if len(failed_roles) >= 2:
        spec007 = ERRORS["SPEC-007"]
        _log.warning("%s: %s — failed: %s", spec007.code, spec007.message, failed_roles)

    for output in successes:
        tokens_used += output.tokens_used

    # Stage 4: MERGE — collect and deduplicate findings
    all_findings: list[Finding] = []
    for output in successes:
        all_findings.extend(output.findings)
    unique_findings = tuple(dict.fromkeys(all_findings))

    # Stage 5: CRITIQUE (skip if --quick or degraded)
    is_degraded = state == "degraded"
    if not request.quick and not is_degraded and critique_agent is not None:
        findings_json = json.dumps(
            [f.model_dump() for f in unique_findings],
            indent=2,
        )
        try:
            critique_output = await critique_agent.run(findings_json)
        except Exception:
            spec008 = ERRORS["SPEC-008"]
            _log.warning("%s: %s", spec008.code, spec008.message)
        else:
            tokens_used += critique_output.tokens_used
            unique_findings = _apply_critique(
                unique_findings, critique_output.raw_response,
            )

    # Stage 6: REPORT — compute scores
    score_card = _compute_scorecard(unique_findings, failed_roles)
    duration = time.monotonic() - start

    agents_used: tuple[AgentRole, ...] = tuple(
        s.role for s in specialists if s.role not in failed_roles
    )
    degraded_dims: tuple[Dimension, ...] = tuple(
        _role_to_dimension(r) for r in failed_roles
    )

    return AnalysisReport(
        repo_url=request.repo_url,
        repo_name=codebase.repo_name,
        score_card=score_card,
        findings=unique_findings,
        analysis_duration_seconds=round(duration, 2),
        total_tokens_used=tokens_used,
        total_cost_usd=0.0,
        agents_used=agents_used,
        is_degraded=is_degraded,
        degraded_dimensions=degraded_dims,
    )


def _extract_plan_context(
    raw_plan: str,
) -> dict[AgentRole, str] | None:
    """Parse MetaPrompter plan into per-agent focus context."""
    try:
        cleaned = raw_plan.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        plan = json.loads(cleaned)
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
                parts.append(f"  Files: {', '.join(str(f) for f in files)}")
            if concerns:
                parts.append(
                    f"  Concerns: {', '.join(str(c) for c in concerns)}"
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
        cleaned = raw_plan.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        plan = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        return set()

    files: set[str] = set()
    for area in plan.get("focus_areas", []):
        for f in area.get("files", []):
            files.add(str(f))
    return files


async def _read_source_files(
    git_port: GitPort,
    local_path: str,
    plan_files: set[str],
    file_tree: tuple[str, ...],
) -> dict[str, str]:
    """Read source files recommended by the MetaPrompter plan."""
    tree_set = set(file_tree)
    to_read = sorted(plan_files & tree_set)
    source: dict[str, str] = {}
    for path in to_read:
        try:
            source[path] = await git_port.read_file(local_path, path)
        except (ValueError, OSError):
            continue
    return source


def _apply_critique(
    findings: tuple[Finding, ...],
    raw_critique: str,
) -> tuple[Finding, ...]:
    """Filter findings using CritiqueAgent validation results."""
    try:
        cleaned = raw_critique.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        critique = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        return findings

    rejected_ids: set[str] = set()
    for r in critique.get("rejected_findings", []):
        if isinstance(r, dict) and "id" in r:
            rejected_ids.add(r["id"])
        elif isinstance(r, str):
            rejected_ids.add(r)

    if not rejected_ids:
        return findings

    validated = tuple(f for f in findings if f.id not in rejected_ids)
    return validated


def _compute_scorecard(
    findings: tuple[Finding, ...],
    failed_roles: list[AgentRole],
) -> ScoreCard:
    """Build ScoreCard from findings, reweighting if dimensions failed."""
    active_weights = {
        dim: w
        for dim, w in DIMENSION_WEIGHTS.items()
        if _dimension_to_role(dim) not in failed_roles
    }
    total_weight = sum(active_weights.values()) or 1.0

    dimensions: list[DimensionScore] = []
    for dim, raw_weight in active_weights.items():
        dim_findings = [f for f in findings if f.dimension == dim]
        score = _estimate_score(dim_findings)
        normalized_weight = raw_weight / total_weight
        dimensions.append(
            DimensionScore(
                dimension=dim,
                score=score,
                grade=score_to_grade(score),
                findings_count=len(dim_findings),
                weight=round(normalized_weight, 3),
            )
        )

    overall = sum(d.score * d.weight for d in dimensions)
    return ScoreCard(
        overall_score=round(overall, 1),
        overall_grade=score_to_grade(overall),
        dimensions=tuple(dimensions),
        total_findings=len(findings),
    )


def _estimate_score(findings: list[Finding]) -> float:
    """Estimate dimension score from findings severity distribution."""
    if not findings:
        return 85.0

    penalty_map = {
        "critical": 20.0,
        "high": 10.0,
        "medium": 5.0,
        "low": 2.0,
        "info": 0.0,
    }
    total_penalty = sum(penalty_map.get(f.severity, 0.0) for f in findings)
    return max(0.0, min(100.0, 100.0 - total_penalty))


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
