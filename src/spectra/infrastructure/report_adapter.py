"""Report rendering adapter — implements ReportPort using Jinja2.

Transforms an ``AnalysisReport`` into a self-contained HTML file with:
- Executive summary and spectrum bar
- Per-dimension score breakdown
- Severity-sorted findings list
- VC due diligence frameworks (OWASP, SOC 2, issue concentration, etc.)
- Investment readiness score
"""

from __future__ import annotations

import re
import secrets
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import jinja2

from spectra.adapters.brand import build_verdict, dim_label
from spectra.entities.enums import Dimension, Grade
from spectra.entities.models import AnalysisReport, Finding

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "templates"

_DIMENSIONS_ORDER: tuple[Dimension, ...] = (
    "architecture",
    "security",
    "quality",
    "documentation",
    "maintainability",
    "performance",
)

_GRADE_CLASS: dict[str, str] = {
    "A+": "grade-a",
    "A": "grade-a",
    "A-": "grade-a",
    "B+": "grade-b",
    "B": "grade-b",
    "B-": "grade-b",
    "C+": "grade-c",
    "C": "grade-c",
    "C-": "grade-c",
    "D+": "grade-d",
    "D": "grade-d",
    "D-": "grade-d",
    "F": "grade-f",
}

_BAR_CLASS: dict[str, str] = {
    "A+": "bar-a",
    "A": "bar-a",
    "A-": "bar-a",
    "B+": "bar-b",
    "B": "bar-b",
    "B-": "bar-b",
    "C+": "bar-c",
    "C": "bar-c",
    "C-": "bar-c",
    "D+": "bar-d",
    "D": "bar-d",
    "D-": "bar-d",
    "F": "bar-f",
}

_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}

_STRENGTH_KEYWORDS: tuple[str, ...] = (
    "well-structured",
    "positive signal",
    "well-organized",
    "properly",
    "comprehensive",
    "good separation",
    "well-designed",
    "well-documented",
    "follows best",
    "clean",
)

_SPECTRUM_COLOR: dict[str, str] = {
    "grade-a": "#22C55E",
    "grade-b": "#06B6D4",
    "grade-c": "#F59E0B",
    "grade-d": "#EF4444",
    "grade-f": "#EF4444",
}

_BADGE_COLOR: dict[str, str] = {
    "A": "22C55E",
    "B": "06B6D4",
    "C": "F59E0B",
    "D": "EF4444",
    "F": "EF4444",
}


def _grade_class(grade: Grade) -> str:
    return _GRADE_CLASS.get(grade, "grade-f")


def _bar_class(grade: Grade) -> str:
    return _BAR_CLASS.get(grade, "bar-f")


def _critical_count(findings: tuple[Finding, ...]) -> int:
    return sum(1 for f in findings if f.severity == "critical")


def _sort_by_severity(findings: list[Finding]) -> list[Finding]:
    """Sort findings: critical -> high -> medium -> low -> info."""
    return sorted(
        findings,
        key=lambda f: _SEVERITY_ORDER.get(f.severity, 5),
    )


def _severity_distribution(
    findings: tuple[Finding, ...],
) -> dict[str, int]:
    """Count findings per severity level."""
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        if f.severity in counts:
            counts[f.severity] += 1
    return counts


def _build_spectrum_segments(
    report: AnalysisReport,
) -> list[dict[str, object]]:
    """Build ordered spectrum bar segments from dimension scores."""
    segments: list[dict[str, object]] = []
    dim_lookup = {d.dimension: d for d in report.score_card.dimensions}
    for dim in _DIMENSIONS_ORDER:
        ds = dim_lookup.get(dim)
        if ds is None:
            continue
        gc = _grade_class(ds.grade)
        segments.append(
            {
                "label": dim_label(dim),
                "score": int(ds.score),
                "grade": ds.grade,
                "weight_pct": ds.weight * 100,
                "color": _SPECTRUM_COLOR.get(gc, "#EF4444"),
            }
        )
    return segments


def _top_findings(findings: tuple[Finding, ...]) -> list[Finding]:
    """Return the top 5 actionable findings by severity."""
    sorted_all = sorted(
        findings,
        key=lambda f: _SEVERITY_ORDER.get(f.severity, 5),
    )
    return sorted_all[:5]


def _total_hours(findings: tuple[Finding, ...]) -> float:
    """Sum estimated_hours across all findings."""
    return round(sum(f.estimated_hours for f in findings), 1)


def _dimension_hours(
    findings: tuple[Finding, ...],
) -> dict[Dimension, float]:
    """Sum estimated hours per dimension."""
    hours: dict[Dimension, float] = {}
    for f in findings:
        hours[f.dimension] = hours.get(f.dimension, 0.0) + f.estimated_hours
    return {k: round(v, 1) for k, v in hours.items()}


def _build_executive_summary(report: AnalysisReport) -> dict[str, object]:
    """Compute executive summary data for the HTML template."""
    dims = sorted(
        report.score_card.dimensions,
        key=lambda d: d.score,
        reverse=True,
    )
    bottom = dims[-3:] if len(dims) >= 3 else dims
    return {
        "verdict": build_verdict(report),
        "strengths": dims[:3],
        "concerns": list(reversed(bottom)),
        "critical_count": _critical_count(report.findings),
        "total_findings": len(report.findings),
        "agents_count": len(report.agents_used),
        "duration": report.analysis_duration_seconds,
        "severity_dist": _severity_distribution(report.findings),
        "total_tech_debt_hours": _total_hours(report.findings),
        "dimension_hours": _dimension_hours(report.findings),
    }


_DEV_RATE_USD = 150  # Average hourly dev rate for cost estimation

# ── OWASP Top 10 (2021 + 2024) ──────────────────────────────

_OWASP_2021_CATEGORIES: dict[str, str] = {
    "A01": "A01:2021 Broken Access Control",
    "A02": "A02:2021 Cryptographic Failures",
    "A03": "A03:2021 Injection",
    "A04": "A04:2021 Insecure Design",
    "A05": "A05:2021 Security Misconfiguration",
    "A06": "A06:2021 Vulnerable and Outdated Components",
    "A07": "A07:2021 Identification and Auth Failures",
    "A08": "A08:2021 Software and Data Integrity Failures",
    "A09": "A09:2021 Security Logging and Monitoring Failures",
    "A10": "A10:2021 Server-Side Request Forgery",
}

_OWASP_2025_CATEGORIES: dict[str, str] = {
    "A01": "A01:2025 Broken Access Control",
    "A02": "A02:2025 Security Misconfiguration",
    "A03": "A03:2025 Software Supply Chain Failures",
    "A04": "A04:2025 Cryptographic Failures",
    "A05": "A05:2025 Injection",
    "A06": "A06:2025 Insecure Design",
    "A07": "A07:2025 Authentication Failures",
    "A08": "A08:2025 Software or Data Integrity Failures",
    "A09": "A09:2025 Logging and Alerting Failures",
    "A10": "A10:2025 Mishandling of Exceptional Conditions",
}

# Unified mapping used by compliance functions — includes both editions
_OWASP_CATEGORIES: dict[str, str] = {
    **_OWASP_2021_CATEGORIES,
    **{f"{k}_2024": v for k, v in _OWASP_2025_CATEGORIES.items()},
}

_OWASP_RE = re.compile(r"A0[1-9]|A10", re.IGNORECASE)
_CWE_RE = re.compile(r"CWE-(\d+)")

# ── SOC 2 Trust Service Criteria ─────────────────────────────

_SOC2_CRITERIA: dict[str, dict[str, object]] = {
    "security": {
        "label": "Security (Common Criteria)",
        "dimensions": ("security", "architecture"),
        "severities": ("critical", "high", "medium"),
        "keywords": (
            "access control",
            "authentication",
            "authorization",
            "encryption",
            "firewall",
            "intrusion",
            "vulnerability",
        ),
    },
    "availability": {
        "label": "Availability",
        "dimensions": ("performance", "architecture"),
        "severities": ("critical", "high"),
        "keywords": (
            "uptime",
            "failover",
            "redundancy",
            "disaster recovery",
            "backup",
            "availability",
            "resilience",
            "timeout",
        ),
    },
    "processing_integrity": {
        "label": "Processing Integrity",
        "dimensions": ("quality", "architecture"),
        "severities": ("critical", "high", "medium"),
        "keywords": (
            "validation",
            "integrity",
            "accuracy",
            "completeness",
            "error handling",
            "data processing",
            "transaction",
        ),
    },
    "confidentiality": {
        "label": "Confidentiality",
        "dimensions": ("security",),
        "severities": ("critical", "high"),
        "keywords": (
            "encryption",
            "secret",
            "credential",
            "api key",
            "token",
            "password",
            "sensitive",
            "confidential",
            "pii",
        ),
    },
    "privacy": {
        "label": "Privacy",
        "dimensions": ("security", "documentation"),
        "severities": ("critical", "high", "medium"),
        "keywords": (
            "privacy",
            "gdpr",
            "personal data",
            "consent",
            "data retention",
            "anonymization",
            "pii",
            "ccpa",
        ),
    },
}

# ── SOC 2 Common Criteria Controls (CC1–CC9) ─────────────────

_SOC2_CONTROLS: dict[str, dict[str, object]] = {
    "CC1": {
        "id": "CC1",
        "category": "Security",
        "title": "Control Environment",
        "dimensions": ("documentation", "architecture", "quality"),
        "controls": [
            {
                "id": "CC1.1",
                "desc": "Integrity and ethical values",
                "keywords": ("ethics", "code of conduct", "integrity"),
            },
            {
                "id": "CC1.2",
                "desc": "Board independence and oversight",
                "keywords": ("governance", "oversight", "board"),
            },
            {
                "id": "CC1.3",
                "desc": "Management structure and reporting",
                "keywords": ("roles", "responsibilities", "organizational"),
            },
            {
                "id": "CC1.4",
                "desc": "Commitment to competence",
                "keywords": ("training", "competency", "onboarding", "skills"),
            },
            {
                "id": "CC1.5",
                "desc": "Accountability for internal controls",
                "keywords": ("accountability", "ownership", "audit trail"),
            },
        ],
    },
    "CC2": {
        "id": "CC2",
        "category": "Security",
        "title": "Communication and Information",
        "dimensions": ("documentation", "quality", "architecture"),
        "controls": [
            {
                "id": "CC2.1",
                "desc": "Information for internal control",
                "keywords": (
                    "documentation",
                    "api doc",
                    "readme",
                    "specification",
                ),
            },
            {
                "id": "CC2.2",
                "desc": "Internal communication of objectives",
                "keywords": (
                    "logging",
                    "notification",
                    "alert",
                    "error reporting",
                ),
            },
            {
                "id": "CC2.3",
                "desc": "External communication",
                "keywords": ("external api", "webhook", "disclosure"),
            },
        ],
    },
    "CC3": {
        "id": "CC3",
        "category": "Security",
        "title": "Risk Assessment",
        "dimensions": ("security", "architecture", "quality"),
        "controls": [
            {
                "id": "CC3.1",
                "desc": "Specification of suitable objectives",
                "keywords": ("requirements", "specification", "validation"),
            },
            {
                "id": "CC3.2",
                "desc": "Risk identification and analysis",
                "keywords": ("risk", "threat model", "vulnerability assessment"),
            },
            {
                "id": "CC3.3",
                "desc": "Consideration of fraud risk",
                "keywords": ("injection", "tampering", "spoofing", "xss", "csrf"),
            },
            {
                "id": "CC3.4",
                "desc": "Identification of significant changes",
                "keywords": ("migration", "breaking change", "deprecation"),
            },
        ],
    },
    "CC4": {
        "id": "CC4",
        "category": "Security",
        "title": "Monitoring Activities",
        "dimensions": ("performance", "security", "quality"),
        "controls": [
            {
                "id": "CC4.1",
                "desc": "Ongoing and separate evaluations",
                "keywords": (
                    "monitoring",
                    "health check",
                    "metrics",
                    "observability",
                ),
            },
            {
                "id": "CC4.2",
                "desc": "Communication of deficiencies",
                "keywords": (
                    "alerting",
                    "incident",
                    "deficiency",
                    "remediation",
                ),
            },
        ],
    },
    "CC5": {
        "id": "CC5",
        "category": "Security",
        "title": "Control Activities",
        "dimensions": ("quality", "security", "architecture"),
        "controls": [
            {
                "id": "CC5.1",
                "desc": "Selection of control activities",
                "keywords": (
                    "input validation",
                    "sanitization",
                    "rate limit",
                    "error handling",
                ),
            },
            {
                "id": "CC5.2",
                "desc": "Technology general controls",
                "keywords": (
                    "automated test",
                    "ci/cd",
                    "static analysis",
                    "linting",
                ),
            },
            {
                "id": "CC5.3",
                "desc": "Deployment through policies",
                "keywords": (
                    "code standard",
                    "style guide",
                    "configuration",
                    "policy",
                ),
            },
        ],
    },
    "CC6": {
        "id": "CC6",
        "category": "Security",
        "title": "Logical and Physical Access Controls",
        "dimensions": ("security", "architecture"),
        "controls": [
            {
                "id": "CC6.1",
                "desc": "Logical access security software",
                "keywords": ("authentication", "authorization", "access control"),
            },
            {
                "id": "CC6.2",
                "desc": "Credential and secret management",
                "keywords": (
                    "credential",
                    "password",
                    "api key",
                    "secret",
                    "token",
                ),
            },
            {
                "id": "CC6.3",
                "desc": "Role-based access authorization",
                "keywords": (
                    "rbac",
                    "role-based",
                    "permission",
                    "least privilege",
                ),
            },
            {
                "id": "CC6.4",
                "desc": "Access removal and session management",
                "keywords": ("session", "logout", "expiration", "revocation"),
            },
            {
                "id": "CC6.5",
                "desc": "Physical access restrictions",
                "keywords": ("physical", "data center", "server room"),
            },
            {
                "id": "CC6.6",
                "desc": "System boundary protection",
                "keywords": ("firewall", "network", "cors", "csp", "boundary"),
            },
            {
                "id": "CC6.7",
                "desc": "Data transmission security",
                "keywords": ("encryption", "tls", "ssl", "https", "transit"),
            },
            {
                "id": "CC6.8",
                "desc": "Prevention of unauthorized software",
                "keywords": (
                    "dependency scan",
                    "code signing",
                    "integrity check",
                    "malware",
                ),
            },
        ],
    },
    "CC7": {
        "id": "CC7",
        "category": "Security",
        "title": "System Operations",
        "dimensions": ("performance", "architecture", "security"),
        "controls": [
            {
                "id": "CC7.1",
                "desc": "Infrastructure and availability monitoring",
                "keywords": ("uptime", "availability", "health", "monitoring"),
            },
            {
                "id": "CC7.2",
                "desc": "Security event detection",
                "keywords": ("intrusion", "anomaly", "suspicious", "detection"),
            },
            {
                "id": "CC7.3",
                "desc": "Security event evaluation",
                "keywords": ("triage", "severity", "classification"),
            },
            {
                "id": "CC7.4",
                "desc": "Incident response procedures",
                "keywords": (
                    "incident response",
                    "disaster recovery",
                    "backup",
                ),
            },
            {
                "id": "CC7.5",
                "desc": "Recovery and resilience",
                "keywords": (
                    "failover",
                    "redundancy",
                    "resilience",
                    "restoration",
                ),
            },
        ],
    },
    "CC8": {
        "id": "CC8",
        "category": "Security",
        "title": "Change Management",
        "dimensions": ("quality", "maintainability", "architecture"),
        "controls": [
            {
                "id": "CC8.1",
                "desc": "Change control processes",
                "keywords": (
                    "version control",
                    "code review",
                    "deployment",
                    "rollback",
                    "change management",
                ),
            },
        ],
    },
    "CC9": {
        "id": "CC9",
        "category": "Security",
        "title": "Risk Mitigation",
        "dimensions": ("maintainability", "security"),
        "controls": [
            {
                "id": "CC9.1",
                "desc": "Risk mitigation for business disruptions",
                "keywords": (
                    "resilience",
                    "failover",
                    "backup",
                    "disaster recovery",
                    "continuity",
                ),
            },
            {
                "id": "CC9.2",
                "desc": "Third-party and vendor risk management",
                "keywords": (
                    "third-party",
                    "dependency",
                    "supply chain",
                    "vendor",
                    "outdated",
                    "vulnerability",
                    "cve",
                ),
            },
        ],
    },
}

# ── License Detection ────────────────────────────────────────

_LICENSE_RE = re.compile(
    r"(?:MIT|Apache[- ]2\.0|GPL[- ]?[23](?:\.\d)?|BSD[- ]?[23]|ISC|"
    r"LGPL[- ]?[23](?:\.\d)?|MPL[- ]?2\.0|AGPL[- ]?3(?:\.\d)?|"
    r"Unlicense|WTFPL|CC0|Proprietary|BSL[- ]?1\.\d)",
    re.IGNORECASE,
)

# ── Complexity Detection ─────────────────────────────────────

_COMPLEXITY_RE = re.compile(
    r"(?:cyclomatic|cognitive)\s+complexity[\s:]*(\d+)",
    re.IGNORECASE,
)
_HIGH_COMPLEXITY_RE = re.compile(
    r"(?:high|excessive|complex)\s+(?:cyclomatic|cognitive|complexity)",
    re.IGNORECASE,
)

# ── Dependency Risk Keywords ─────────────────────────────────

_DEP_RISK_KEYWORDS: dict[str, int] = {
    "outdated": 15,
    "deprecated": 20,
    "vulnerable": 25,
    "unmaintained": 20,
    "end of life": 25,
    "eol": 25,
    "no longer maintained": 20,
    "known vulnerability": 25,
    "cve": 20,
    "security advisory": 15,
    "pinned": 5,
    "unpinned": 10,
    "lock file": 5,
    "transitive": 10,
}


# ── Existing Tech Debt / Compliance Functions ────────────────


def _separate_strengths(
    findings: tuple[Finding, ...],
) -> tuple[list[Finding], list[Finding]]:
    """Split findings into strengths and actual issues.

    Returns:
        A tuple of (strengths, issues) where strengths are info-severity
        findings with positive language, and issues are everything else.
    """
    strengths: list[Finding] = []
    issues: list[Finding] = []
    for f in findings:
        text = f"{f.title} {f.description}".lower()
        is_positive = f.severity == "info" and any(kw in text for kw in _STRENGTH_KEYWORDS)
        if is_positive:
            strengths.append(f)
        else:
            issues.append(f)
    return strengths, issues


def _tech_debt_summary(
    findings: tuple[Finding, ...],
) -> dict[str, object]:
    """Aggregate tech debt data for the report template."""
    total_hours = sum(f.estimated_hours for f in findings)
    by_dimension: dict[str, float] = {}
    by_severity: dict[str, float] = {}
    for f in findings:
        by_dimension[f.dimension] = by_dimension.get(f.dimension, 0.0) + f.estimated_hours
        by_severity[f.severity] = by_severity.get(f.severity, 0.0) + f.estimated_hours
    return {
        "total_hours": round(total_hours, 1),
        "cost_usd": round(total_hours * _DEV_RATE_USD),
        "by_dimension": by_dimension,
        "by_severity": by_severity,
    }


def _extract_owasp_hits(
    findings: tuple[Finding, ...],
) -> set[str]:
    """Scan finding text for OWASP Top 10 category references."""
    hits: set[str] = set()
    for f in findings:
        text = f"{f.description} {f.recommendation}"
        hits.update(_OWASP_RE.findall(text))
    return hits


def _build_owasp_coverage(
    categories: dict[str, str],
    hits: set[str],
) -> list[dict[str, str | bool]]:
    """Build coverage list for a single OWASP edition."""
    normalized = {o.upper() for o in hits}
    coverage: list[dict[str, str | bool]] = []
    for code, label in categories.items():
        covered = code.upper() in normalized
        coverage.append({"code": code, "label": label, "covered": covered})
    return coverage


def _dd_compliance_mapping(
    findings: tuple[Finding, ...],
) -> dict[str, object]:
    """Extract OWASP (2021 + 2024) and CWE references from findings."""
    owasp_hits = _extract_owasp_hits(findings)
    cwes_found: set[str] = set()
    for f in findings:
        text = f"{f.description} {f.recommendation}"
        cwes_found.update(_CWE_RE.findall(text))

    cov_2021 = _build_owasp_coverage(_OWASP_2021_CATEGORIES, owasp_hits)
    cov_2024 = _build_owasp_coverage(_OWASP_2025_CATEGORIES, owasp_hits)

    covered_2021 = sum(1 for o in cov_2021 if o["covered"])
    covered_2024 = sum(1 for o in cov_2024 if o["covered"])

    return {
        "owasp_coverage": cov_2021,
        "owasp_2025_coverage": cov_2024,
        "owasp_covered_count": covered_2021,
        "owasp_2025_covered_count": covered_2024,
        "owasp_total": len(_OWASP_2021_CATEGORIES),
        "owasp_2025_total": len(_OWASP_2025_CATEGORIES),
        "cwes": sorted(cwes_found, key=int),
    }


# ── SOC 2 Trust Service Criteria Mapping ─────────────────────


def _matches_soc2_criterion(
    finding: Finding,
    criterion: dict[str, object],
) -> bool:
    """Check if a finding maps to a SOC 2 trust service criterion."""
    dims = criterion.get("dimensions", ())
    if finding.dimension not in dims:
        return False
    text = f"{finding.title} {finding.description}".lower()
    keywords = criterion.get("keywords", ())
    if any(kw in text for kw in keywords):
        return True
    for ctrl in criterion.get("controls", []):
        if any(kw in text for kw in ctrl.get("keywords", ())):
            return True
    return False


def _match_finding_to_cc(
    finding: Finding,
    control: dict[str, object],
    dimensions: tuple[str, ...],
) -> bool:
    """Check if a finding matches a specific CC sub-control."""
    if finding.dimension not in dimensions:
        return False
    text = f"{finding.title} {finding.description}".lower()
    return any(kw in text for kw in control.get("keywords", ()))


def _evaluate_cc_controls(
    findings: tuple[Finding, ...],
    cc_data: dict[str, object],
) -> list[dict[str, object]]:
    """Evaluate each sub-control within a CC category."""
    dims = cc_data.get("dimensions", ())
    results: list[dict[str, object]] = []
    for ctrl in cc_data.get("controls", []):
        matched = sum(1 for f in findings if _match_finding_to_cc(f, ctrl, dims))
        results.append(
            {
                "id": ctrl["id"],
                "desc": ctrl["desc"],
                "covered": matched > 0,
                "finding_count": matched,
            }
        )
    return results


def _cc_category_finding_count(
    findings: tuple[Finding, ...],
    cc_data: dict[str, object],
) -> int:
    """Count unique findings matching any control in a CC category."""
    dims = cc_data.get("dimensions", ())
    count = 0
    for f in findings:
        if f.dimension not in dims:
            continue
        text = f"{f.title} {f.description}".lower()
        for ctrl in cc_data.get("controls", []):
            if any(kw in text for kw in ctrl.get("keywords", ())):
                count += 1
                break
    return count


def _cc_has_critical(
    findings: tuple[Finding, ...],
    cc_data: dict[str, object],
) -> bool:
    """Check if any critical finding matches a CC category."""
    dims = cc_data.get("dimensions", ())
    for f in findings:
        if f.severity != "critical" or f.dimension not in dims:
            continue
        text = f"{f.title} {f.description}".lower()
        for ctrl in cc_data.get("controls", []):
            if any(kw in text for kw in ctrl.get("keywords", ())):
                return True
    return False


def _build_cc_category(
    findings: tuple[Finding, ...],
    cc_id: str,
    cc_data: dict[str, object],
) -> dict[str, object]:
    """Build coverage data for a single CC category."""
    ctrl_results = _evaluate_cc_controls(findings, cc_data)
    covered = sum(1 for c in ctrl_results if c["covered"])
    fc = _cc_category_finding_count(findings, cc_data)
    return {
        "id": cc_id,
        "title": cc_data["title"],
        "controls": ctrl_results,
        "covered_count": covered,
        "total_count": len(ctrl_results),
        "coverage_pct": _safe_pct(covered, len(ctrl_results)),
        "finding_count": fc,
        "has_critical": _cc_has_critical(findings, cc_data),
    }


def _build_tsc_criteria(
    findings: tuple[Finding, ...],
) -> list[dict[str, object]]:
    """Build old-format TSC criteria for backward compatibility."""
    results: list[dict[str, object]] = []
    for key, criterion in _SOC2_CRITERIA.items():
        matched = [f for f in findings if _matches_soc2_criterion(f, criterion)]
        sev = _severity_distribution(tuple(matched))
        results.append(
            {
                "key": key,
                "label": criterion["label"],
                "finding_count": len(matched),
                "severity_counts": sev,
                "has_critical": sev.get("critical", 0) > 0,
            }
        )
    return results


def _collect_cc_gaps(
    cc_categories: list[dict[str, object]],
) -> list[dict[str, str]]:
    """Collect all uncovered CC controls as a gap list."""
    gaps: list[dict[str, str]] = []
    for cat in cc_categories:
        for ctrl in cat["controls"]:
            if not ctrl["covered"]:
                gaps.append({"id": ctrl["id"], "desc": ctrl["desc"], "cc": cat["id"]})
    return gaps


def _soc2_mapping(
    findings: tuple[Finding, ...],
) -> dict[str, object]:
    """Map findings to SOC 2 CC controls and TSC categories."""
    tsc = _build_tsc_criteria(findings)
    cc = [_build_cc_category(findings, k, v) for k, v in _SOC2_CONTROLS.items()]
    total_ctrl = sum(c["total_count"] for c in cc)
    covered_ctrl = sum(c["covered_count"] for c in cc)
    total_mapped = sum(c["finding_count"] for c in cc)
    return {
        "criteria": tsc,
        "cc_categories": cc,
        "total_mapped": total_mapped,
        "coverage_pct": _safe_pct(covered_ctrl, total_ctrl),
        "readiness_score": _safe_pct(covered_ctrl, total_ctrl),
        "total_controls": total_ctrl,
        "covered_controls": covered_ctrl,
        "gap_controls": _collect_cc_gaps(cc),
    }


def _safe_pct(numerator: int, denominator: int) -> float:
    """Compute percentage, returning 0.0 when denominator is zero."""
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


# ── Issue Concentration Analysis ─────────────────────────────


def _compute_file_concentration(
    findings: tuple[Finding, ...],
) -> list[dict[str, object]]:
    """Rank files by finding count (top 10 hotspots)."""
    file_counts: Counter[str] = Counter()
    for f in findings:
        file_counts[f.location.file_path] += 1
    return [{"file": path, "count": count} for path, count in file_counts.most_common(10)]


def _compute_issue_concentration(
    findings: tuple[Finding, ...],
) -> dict[str, object]:
    """Compute issue concentration from findings distribution across files."""
    if not findings:
        return {"score": 100, "rating": "healthy", "hotspots": []}

    file_counts: Counter[str] = Counter()
    for f in findings:
        file_counts[f.location.file_path] += 1

    total = sum(file_counts.values())
    hotspots = _compute_file_concentration(findings)
    concentration = _gini_coefficient(list(file_counts.values()))
    rating = _concentration_rating(concentration)
    score = max(0, round(100 - (concentration * 100)))

    return {
        "score": score,
        "rating": rating,
        "concentration": round(concentration, 3),
        "unique_files": len(file_counts),
        "total_issues": total,
        "hotspots": hotspots,
    }


def _gini_coefficient(values: list[int]) -> float:
    """Compute Gini coefficient for issue concentration (0=even, 1=all in one)."""
    if not values or sum(values) == 0:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    total = sum(sorted_vals)
    cumulative = sum((i + 1) * v for i, v in enumerate(sorted_vals))
    return (2 * cumulative) / (n * total) - (n + 1) / n


def _concentration_rating(concentration: float) -> str:
    """Map Gini concentration to a human-readable risk rating."""
    if concentration < 0.3:
        return "healthy"
    if concentration < 0.5:
        return "moderate"
    if concentration < 0.7:
        return "concerning"
    return "critical"


# ── License Compliance ───────────────────────────────────────


def _license_compliance(
    findings: tuple[Finding, ...],
) -> dict[str, object]:
    """Extract license mentions from findings and flag risks."""
    license_hits: Counter[str] = Counter()
    flagged_findings: list[dict[str, str]] = []
    for f in findings:
        text = f"{f.title} {f.description} {f.recommendation}"
        matches = _LICENSE_RE.findall(text)
        for lic in matches:
            normalized = lic.upper().replace(" ", "-")
            license_hits[normalized] += 1
            flagged_findings.append(
                {
                    "license": normalized,
                    "finding_id": f.id,
                    "title": f.title,
                    "severity": f.severity,
                }
            )

    copyleft = _detect_copyleft_risk(license_hits)
    return {
        "licenses_found": dict(license_hits.most_common()),
        "total_mentions": sum(license_hits.values()),
        "unique_licenses": len(license_hits),
        "copyleft_risk": copyleft,
        "flagged": flagged_findings[:20],
    }


def _detect_copyleft_risk(
    license_hits: Counter[str],
) -> dict[str, object]:
    """Identify copyleft licenses that may restrict distribution."""
    copyleft_patterns = {"GPL", "AGPL", "LGPL"}
    found: list[str] = []
    for lic in license_hits:
        if any(cp in lic for cp in copyleft_patterns):
            found.append(lic)
    return {
        "has_copyleft": len(found) > 0,
        "copyleft_licenses": found,
        "risk_level": "high" if found else "none",
    }


# ── Code Complexity Indicators ───────────────────────────────


def _complexity_indicators(
    findings: tuple[Finding, ...],
) -> dict[str, object]:
    """Extract cyclomatic/cognitive complexity signals from findings."""
    scores: list[int] = []
    high_complexity_files: list[dict[str, object]] = []

    for f in findings:
        text = f"{f.title} {f.description} {f.recommendation}"
        numeric = _COMPLEXITY_RE.findall(text)
        scores.extend(int(s) for s in numeric)
        if _HIGH_COMPLEXITY_RE.search(text):
            high_complexity_files.append(
                {
                    "file": f.location.file_path,
                    "title": f.title,
                    "severity": f.severity,
                }
            )

    return {
        "mentioned_scores": sorted(scores, reverse=True)[:20],
        "max_complexity": max(scores) if scores else 0,
        "avg_complexity": _safe_avg(scores),
        "high_complexity_count": len(high_complexity_files),
        "high_complexity_files": high_complexity_files[:10],
        "risk_level": _complexity_risk_level(scores),
    }


def _safe_avg(values: list[int]) -> float:
    """Compute average, returning 0.0 for empty lists."""
    if not values:
        return 0.0
    return round(sum(values) / len(values), 1)


def _complexity_risk_level(scores: list[int]) -> str:
    """Categorize overall complexity risk from extracted scores."""
    if not scores:
        return "unknown"
    max_score = max(scores)
    if max_score > 30:
        return "critical"
    if max_score > 20:
        return "high"
    if max_score > 10:
        return "moderate"
    return "low"


# ── Dependency Risk Score ────────────────────────────────────


def _dependency_risk_score(
    findings: tuple[Finding, ...],
) -> dict[str, object]:
    """Aggregate dependency risk from dependency agent findings."""
    dep_findings = [f for f in findings if f.dimension == "maintainability"]
    if not dep_findings:
        dep_findings = [f for f in findings if f.agent_role == "dependency"]

    risk_points = 0
    matched_keywords: list[dict[str, object]] = []
    for f in dep_findings:
        text = f"{f.title} {f.description} {f.recommendation}".lower()
        for keyword, weight in _DEP_RISK_KEYWORDS.items():
            if keyword in text:
                risk_points += weight
                matched_keywords.append(
                    {
                        "keyword": keyword,
                        "weight": weight,
                        "finding_id": f.id,
                    }
                )

    severity_penalty = _dep_severity_penalty(dep_findings)
    raw_score = min(100, risk_points + severity_penalty)
    return {
        "score": raw_score,
        "rating": _dep_risk_rating(raw_score),
        "total_dep_findings": len(dep_findings),
        "risk_signals": matched_keywords[:15],
        "severity_penalty": severity_penalty,
    }


def _dep_severity_penalty(findings: list[Finding]) -> int:
    """Compute penalty points from finding severity counts."""
    penalty = 0
    for f in findings:
        if f.severity == "critical":
            penalty += 20
        elif f.severity == "high":
            penalty += 10
        elif f.severity == "medium":
            penalty += 5
    return min(50, penalty)


def _dep_risk_rating(score: int) -> str:
    """Map numeric dependency risk to a human-readable rating."""
    if score < 20:
        return "low"
    if score < 40:
        return "moderate"
    if score < 60:
        return "elevated"
    if score < 80:
        return "high"
    return "critical"


# ── Investment Readiness Score ───────────────────────────────

# Weights for each DD metric contributing to investment readiness
_IR_WEIGHTS: dict[str, float] = {
    "overall_score": 0.25,
    "security_posture": 0.20,
    "issue_concentration": 0.10,
    "dependency_risk": 0.10,
    "complexity": 0.10,
    "license_compliance": 0.10,
    "soc2_readiness": 0.10,
    "critical_findings": 0.05,
}


def _investment_readiness_score(
    report: AnalysisReport,
    issue_concentration: dict[str, object],
    dep_risk: dict[str, object],
    complexity: dict[str, object],
    license_data: dict[str, object],
    soc2: dict[str, object],
) -> dict[str, object]:
    """Compute investment readiness from all DD metrics (0-100)."""
    components = _ir_component_scores(
        report,
        issue_concentration,
        dep_risk,
        complexity,
        license_data,
        soc2,
    )
    weighted = sum(components[k] * _IR_WEIGHTS[k] for k in _IR_WEIGHTS)
    final = round(min(100, max(0, weighted)), 1)
    return {
        "score": final,
        "rating": _ir_rating(final),
        "components": components,
        "weights": _IR_WEIGHTS,
    }


def _ir_component_scores(
    report: AnalysisReport,
    issue_concentration: dict[str, object],
    dep_risk: dict[str, object],
    complexity: dict[str, object],
    license_data: dict[str, object],
    soc2: dict[str, object],
) -> dict[str, float]:
    """Compute individual component scores for investment readiness."""
    sec_score = _security_posture_score(report)
    dep_score = max(0, 100 - int(dep_risk.get("score", 0)))
    cmplx = _complexity_component_score(complexity)
    lic = _license_component_score(license_data)
    soc2_pct = float(soc2.get("coverage_pct", 0))
    crit_penalty = _critical_findings_score(report)

    return {
        "overall_score": report.score_card.overall_score,
        "security_posture": sec_score,
        "issue_concentration": float(issue_concentration.get("score", 50)),
        "dependency_risk": dep_score,
        "complexity": cmplx,
        "license_compliance": lic,
        "soc2_readiness": min(100, soc2_pct),
        "critical_findings": crit_penalty,
    }


def _security_posture_score(report: AnalysisReport) -> float:
    """Extract security dimension score, defaulting to 50."""
    for d in report.score_card.dimensions:
        if d.dimension == "security":
            return d.score
    return 50.0


def _complexity_component_score(
    complexity: dict[str, object],
) -> float:
    """Convert complexity risk level to a 0-100 score."""
    level = str(complexity.get("risk_level", "unknown"))
    mapping = {"low": 90, "moderate": 70, "high": 40, "critical": 15}
    return float(mapping.get(level, 50))


def _license_component_score(
    license_data: dict[str, object],
) -> float:
    """Score license compliance (100 = clean, penalize copyleft)."""
    copyleft = license_data.get("copyleft_risk", {})
    if isinstance(copyleft, dict) and copyleft.get("has_copyleft"):
        return 40.0
    return 95.0


def _critical_findings_score(report: AnalysisReport) -> float:
    """Penalize for critical findings (each deducts 15 points from 100)."""
    crit = report.critical_finding_count()
    return max(0.0, 100.0 - (crit * 15.0))


def _ir_rating(score: float) -> str:
    """Map investment readiness score to a VC-facing rating."""
    if score >= 85:
        return "investment-ready"
    if score >= 70:
        return "near-ready"
    if score >= 50:
        return "needs-work"
    if score >= 30:
        return "significant-gaps"
    return "not-ready"


# ── ROI Calculator ("The $47 Line") ──────────────────────────

_ENGINEER_HOURLY_RATE = 175  # Senior engineer market rate
_MANUAL_REVIEW_HOURS = 4.0  # Estimated hours for equivalent manual review


def _compute_roi(report: AnalysisReport) -> dict[str, object]:
    """Compute ROI comparison: Spectra cost vs. manual review cost.

    Returns data for the "savings" callout in the report template.
    """
    spectra_cost = report.total_cost_usd
    manual_cost = _ENGINEER_HOURLY_RATE * _MANUAL_REVIEW_HOURS
    savings = manual_cost - spectra_cost
    findings_count = len(report.findings)
    cost_per_finding = round(spectra_cost / findings_count, 2) if findings_count else 0.0
    return {
        "spectra_cost": round(spectra_cost, 2),
        "manual_cost": round(manual_cost),
        "savings": round(savings),
        "savings_pct": round((savings / manual_cost) * 100) if manual_cost else 0,
        "cost_per_finding": cost_per_finding,
        "findings_count": findings_count,
        "engineer_rate": _ENGINEER_HOURLY_RATE,
        "manual_hours": _MANUAL_REVIEW_HOURS,
    }


# ── Report Adapter Class ─────────────────────────────────────


class ReportAdapter:
    """Renders analysis reports to HTML via Jinja2.

    Loads the ``report.html.j2`` template and injects helper functions
    as Jinja2 globals for use in template expressions.
    """

    def __init__(self, template_dir: Path = _TEMPLATE_DIR) -> None:
        """Initialize the report renderer.

        Args:
            template_dir: Directory containing Jinja2 templates.
        """
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            autoescape=True,
        )
        self._env.globals["_grade_class"] = _grade_class
        self._env.globals["_bar_class"] = _bar_class
        self._env.globals["_dim_label"] = dim_label
        self._env.globals["_critical_count"] = _critical_count
        self._env.globals["_sort_by_severity"] = _sort_by_severity
        self._env.globals["dimensions_order"] = _DIMENSIONS_ORDER

    def render(self, report: AnalysisReport, output_path: str) -> str:
        """Render the analysis report to an HTML file.

        Args:
            report: Completed analysis report.
            output_path: Destination file path for the HTML.

        Returns:
            The output path string.
        """
        template = self._env.get_template("report.html.j2")
        has_mermaid = any("```mermaid" in f.description for f in report.findings)
        dd_frameworks = self._build_dd_frameworks(report)
        csp_nonce = secrets.token_urlsafe(32)
        finding_strengths, finding_issues = _separate_strengths(
            report.findings,
        )
        html = template.render(
            report=report,
            summary=_build_executive_summary(report),
            spectrum_segments=_build_spectrum_segments(report),
            top_findings=_top_findings(report.findings),
            tech_debt=_tech_debt_summary(report.findings),
            strengths=finding_strengths,
            filtered_findings=finding_issues,
            dd_compliance=dd_frameworks["dd_compliance"],
            soc2=dd_frameworks["soc2"],
            issue_concentration=dd_frameworks["issue_concentration"],
            license_compliance=dd_frameworks["license_compliance"],
            complexity=dd_frameworks["complexity"],
            dependency_risk=dd_frameworks["dependency_risk"],
            investment_readiness=dd_frameworks["investment_readiness"],
            badge_svg=self.render_badge(report),
            roi=_compute_roi(report),
            has_mermaid=has_mermaid,
            csp_nonce=csp_nonce,
            generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        )
        Path(output_path).write_text(html, encoding="utf-8")
        return output_path

    def _build_dd_frameworks(
        self,
        report: AnalysisReport,
    ) -> dict[str, dict[str, object]]:
        """Compute all VC due diligence framework data."""
        dd_compliance = _dd_compliance_mapping(report.findings)
        soc2 = _soc2_mapping(report.findings)
        issue_concentration = _compute_issue_concentration(report.findings)
        license_data = _license_compliance(report.findings)
        complexity = _complexity_indicators(report.findings)
        dep_risk = _dependency_risk_score(report.findings)
        ir_score = _investment_readiness_score(
            report,
            issue_concentration,
            dep_risk,
            complexity,
            license_data,
            soc2,
        )
        return {
            "dd_compliance": dd_compliance,
            "soc2": soc2,
            "issue_concentration": issue_concentration,
            "license_compliance": license_data,
            "complexity": complexity,
            "dependency_risk": dep_risk,
            "investment_readiness": ir_score,
        }

    def render_badge(self, report: AnalysisReport) -> str:
        """Render an inline SVG badge for the overall grade.

        Args:
            report: Analysis report with score_card data.

        Returns:
            SVG markup string (shields.io style).
        """
        grade = report.score_card.overall_grade
        score = round(report.score_card.overall_score)
        grade_color = _BADGE_COLOR.get(grade[0], "6B7280")
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="160"'
            f' height="20">'
            f'<rect width="80" height="20" rx="3" fill="#555"/>'
            f'<rect x="80" width="80" height="20" rx="3" fill="'
            f'#{grade_color}"/>'
            f'<text x="40" y="14" fill="#fff" text-anchor="middle"'
            f' font-size="11" font-family="Verdana">Spectra</text>'
            f'<text x="120" y="14" fill="#fff" text-anchor="middle"'
            f' font-size="11" font-family="Verdana">'
            f"{grade} {score}/100</text></svg>"
        )
