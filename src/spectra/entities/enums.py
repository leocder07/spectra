"""Literal type aliases for the Spectra domain."""

from typing import Literal

Severity = Literal["critical", "high", "medium", "low", "info"]

Dimension = Literal[
    "architecture",
    "security",
    "quality",
    "documentation",
    "maintainability",
    "performance",
]

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
