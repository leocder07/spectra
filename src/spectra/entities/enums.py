"""Literal type aliases for the Spectra domain.

Defines the core enum-like types used throughout all layers. Using
``Literal`` instead of ``enum.Enum`` keeps models JSON-serializable
without custom encoders and enables exhaustive type checking.

ADR references in this module: ADR-011 (prompt-injection isolation —
``ValidationStatus`` carries the compromised-run signal). See
``docs/architecture/adr/`` and ``docs/glossary.md`` for the at-a-glance
ADR index.
"""

from typing import Literal, cast, get_args

Severity = Literal["critical", "high", "medium", "low", "info"]
"""Finding severity from most to least urgent."""

_SEVERITIES: frozenset[str] = frozenset(get_args(Severity))


def coerce_severity(value: str, default: Severity = "info") -> Severity:
    """Return ``value`` when it is a valid severity, else ``default``.

    Used at JSON/LLM boundaries where a raw string must be narrowed to the
    ``Severity`` literal before constructing a ``Finding``. The input is
    normalized (trimmed + lowercased) first, so realistic LLM variants like
    ``"High"``, ``"CRITICAL"``, or ``"critical "`` map to their canonical
    severity instead of silently degrading to ``default`` — a severity
    downgrade would let a ``--fail-on high`` gate pass on a real finding.
    """
    normalized = value.strip().lower()
    if normalized in _SEVERITIES:
        return cast("Severity", normalized)
    return default


Dimension = Literal[
    "architecture",
    "security",
    "quality",
    "documentation",
    "maintainability",
    "performance",
]
"""Analysis dimension — each maps to one specialist agent."""

Grade = Literal[
    "A+",
    "A",
    "A-",
    "B+",
    "B",
    "B-",
    "C+",
    "C",
    "C-",
    "D+",
    "D",
    "D-",
    "F",
]
"""Letter grade derived from a 0-100 numeric score."""

AgentRole = Literal[
    "meta_prompter",
    "architecture",
    "security",
    "quality",
    "documentation",
    "dependency",
    "performance",
    "critique",
]
"""Identifier for each of the 8 pipeline agents."""

PipelineState = Literal[
    "pending",
    "ingesting",
    "meta_prompting",
    "analyzing",
    "merging",
    "critiquing",
    "reporting",
    "complete",
    "degraded",
    "failed",
    "compromised",
]
"""Pipeline lifecycle state machine values.

``compromised`` is the terminal state for a run where the CritiqueAgent
detected a prompt-injection attempt in the analyzed inputs (ADR-011 §2).
It is reported alongside the special ``SPEC-PROMPT-INJECTION-DETECTED``
finding and forces the report to render with a banner."""

SchemaVersion = Literal["v1"]
"""Cache schema version. Bumped when ``Finding`` or ``AgentOutput`` shape changes;
all rows tagged with a stale version are invalidated on lookup."""
