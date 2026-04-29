"""Error taxonomy for fallible operations.

Defines the ``SpectraError`` hierarchy and the canonical error registry
(SPEC-001 through SPEC-009).  Each error carries retry metadata so the
``RetryDecorator`` can decide whether to back-off or abort.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SpectraError:
    """Immutable error descriptor with retry metadata.

    Attributes:
        code: Unique error code (e.g. ``SPEC-001``).
        message: Human-readable description.
        retryable: Whether the operation can be retried.
        max_retries: Maximum retry attempts (0 = no retry).
    """

    code: str
    message: str
    retryable: bool
    max_retries: int = 0


ERRORS: dict[str, SpectraError] = {
    "SPEC-001": SpectraError("SPEC-001", "Git clone failed", retryable=True, max_retries=2),
    "SPEC-002": SpectraError(
        "SPEC-002",
        "Anthropic API unreachable",
        retryable=True,
        max_retries=3,
    ),
    "SPEC-003": SpectraError("SPEC-003", "Rate limited (429)", retryable=True, max_retries=3),
    "SPEC-004": SpectraError("SPEC-004", "Token budget exceeded", retryable=False),
    "SPEC-005": SpectraError(
        "SPEC-005",
        "Agent output validation failed",
        retryable=True,
        max_retries=1,
    ),
    "SPEC-006": SpectraError("SPEC-006", "Agent timeout (120s)", retryable=False),
    "SPEC-007": SpectraError("SPEC-007", "2+ agents failed", retryable=False),
    "SPEC-008": SpectraError("SPEC-008", "CritiqueAgent failed", retryable=False),
    "SPEC-009": SpectraError("SPEC-009", "Report render failed", retryable=False),
}


class AgentError(Exception):
    """Raised when an agent operation fails with a domain error.

    Attributes:
        error: The underlying ``SpectraError`` with code and retry info.
    """

    def __init__(self, error: SpectraError) -> None:
        self.error = error
        super().__init__(f"{error.code}: {error.message}")


class GitError(Exception):
    """Raised when a git operation fails with a domain error.

    Attributes:
        error: The underlying ``SpectraError`` with code and retry info.
    """

    def __init__(self, error: SpectraError) -> None:
        self.error = error
        super().__init__(f"{error.code}: {error.message}")


class SpectraRetryError(Exception):
    """Raised when a retryable operation fails and should be retried.

    The ``RetryDecorator`` catches this to apply exponential back-off.

    Attributes:
        error: The underlying ``SpectraError`` with code and retry info.
    """

    def __init__(self, error: SpectraError) -> None:
        self.error = error
        super().__init__(f"{error.code}: {error.message}")


# Matches ```json ... ``` fenced blocks in LLM output
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


def strip_code_fence(raw: str) -> str:
    """Extract JSON from LLM output, handling code fences and text.

    Tries three strategies in order:
    1. Extract content from ````` ```json ... ``` ````` blocks.
    2. Strip wrapping code fences from the entire output.
    3. Locate the outermost ``{`` … ``}`` pair in free text.

    Args:
        raw: Raw LLM response that may contain markdown fences.

    Returns:
        Cleaned string likely containing valid JSON.
    """
    cleaned = raw.strip()
    # Case 1: extract content from ```json ... ``` blocks
    json_blocks = _JSON_BLOCK_RE.findall(cleaned)
    for block in json_blocks:
        stripped_block = block.strip()
        if stripped_block.startswith("{"):
            return stripped_block
    # Case 2: entire output is wrapped in code fences
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]
        return cleaned.strip()
    # Case 3: JSON embedded in text — find first { and last }
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return cleaned[first_brace : last_brace + 1]
    return cleaned
