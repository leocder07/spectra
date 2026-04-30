"""Pure policy gate (Capability #17 — RICE-65).

Evaluates a ``Policy`` against an ``AnalysisReport`` and returns a tuple
of ``Violation`` describing every rule that fired. Empty tuple means
the run passes the gate.

The composition root surfaces a non-empty result as ``SPEC-013``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spectra.entities.models import Violation

if TYPE_CHECKING:
    from spectra.entities.enums import Severity
    from spectra.entities.models import AnalysisReport, Finding, Policy


# Severity rank: 0 = info, 4 = critical. Used by the severity_gate check —
# a finding with rank >= gate_rank fails the gate.
_SEVERITY_RANK: dict[str, int] = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

# severity_gate=X means "block any finding with severity >= X".
# A `none` gate maps to a sentinel above the highest rank to disable the check.
_GATE_THRESHOLD: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "none": 5,
}


def evaluate_policy(policy: Policy, report: AnalysisReport) -> tuple[Violation, ...]:
    """Return every ``Violation`` triggered by ``policy`` against ``report``.

    The four checks run independently and their violations concatenate;
    callers do not get an early-exit semantics so the brand-voice error
    block can list every reason at once.

    Args:
        policy: The loaded org governance policy.
        report: The completed analysis report.

    Returns:
        Tuple of ``Violation`` (empty when the run passes).
    """
    out: list[Violation] = []
    out.extend(_check_severity_gate(policy, report.findings))
    out.extend(_check_forbidden_rule_ids(policy, report.findings))
    out.extend(_check_min_score(policy, report))
    out.extend(_check_required_dimensions(policy, report))
    return tuple(out)


def _check_severity_gate(
    policy: Policy,
    findings: tuple[Finding, ...],
) -> list[Violation]:
    """Block findings whose severity rank meets or exceeds the gate threshold."""
    threshold = _GATE_THRESHOLD[policy.severity_gate]
    if threshold > 4:  # 'none' disables the gate
        return []
    out: list[Violation] = []
    for f in findings:
        rank = _SEVERITY_RANK.get(f.severity, 0)
        if rank >= threshold:
            out.append(
                Violation(
                    kind="severity_gate",
                    message=(
                        f"{f.severity} finding {f.id} exceeds gate "
                        f"{policy.severity_gate!r}"
                    ),
                    finding_id=f.id,
                )
            )
    return out


def _check_forbidden_rule_ids(
    policy: Policy,
    findings: tuple[Finding, ...],
) -> list[Violation]:
    """Block any finding whose ``rule_id`` appears in the forbidden tuple."""
    if not policy.forbidden_rule_ids:
        return []
    forbidden = set(policy.forbidden_rule_ids)
    out: list[Violation] = []
    for f in findings:
        if f.rule_id and f.rule_id in forbidden:
            out.append(
                Violation(
                    kind="forbidden_rule_id",
                    message=f"forbidden rule {f.rule_id} present in finding {f.id}",
                    finding_id=f.id,
                    rule_id=f.rule_id,
                )
            )
    return out


def _check_min_score(policy: Policy, report: AnalysisReport) -> list[Violation]:
    """Block when ``score_card.overall_score`` falls below the floor."""
    floor = policy.min_score_overall
    if floor is None:
        return []
    actual = report.score_card.overall_score
    if actual >= floor:
        return []
    return [
        Violation(
            kind="min_score_overall",
            message=f"overall score {actual:.1f} below required {floor:.1f}",
        )
    ]


def _check_required_dimensions(
    policy: Policy,
    report: AnalysisReport,
) -> list[Violation]:
    """Block when a required dimension is absent from ``score_card.dimensions``."""
    if not policy.required_dimensions:
        return []
    present = {d.dimension for d in report.score_card.dimensions}
    out: list[Violation] = []
    for required in policy.required_dimensions:
        if required not in present:
            out.append(
                Violation(
                    kind="required_dimension",
                    message=f"required dimension {required!r} missing from report",
                    dimension=required,
                )
            )
    return out


__all__ = ["evaluate_policy"]
