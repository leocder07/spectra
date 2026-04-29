"""Literal type aliases for the Spectra domain.

Defines the core enum-like types used throughout all layers. Using
``Literal`` instead of ``enum.Enum`` keeps models JSON-serializable
without custom encoders and enables exhaustive type checking.
"""

from typing import Literal

Severity = Literal["critical", "high", "medium", "low", "info"]
"""Finding severity from most to least urgent."""

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
]
"""Pipeline lifecycle state machine values."""

SchemaVersion = Literal["v1"]
"""Cache schema version. Bumped when ``Finding`` or ``AgentOutput`` shape changes;
all rows tagged with a stale version are invalidated on lookup."""
