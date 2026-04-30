"""Error taxonomy for fallible operations.

Defines the ``SpectraError`` hierarchy and the canonical error registry
(SPEC-001 through SPEC-009).  Each error carries retry metadata so the
``RetryDecorator`` can decide whether to back-off or abort.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spectra.entities.models import SecretFinding, Violation


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
    "SPEC-010": SpectraError("SPEC-010", "Cache I/O failed", retryable=False),
    "SPEC-011": SpectraError("SPEC-011", "Secret detected in workspace", retryable=False),
    "SPEC-012": SpectraError(
        "SPEC-012",
        "Policy or waiver file invalid",
        retryable=False,
    ),
    "SPEC-013": SpectraError(
        "SPEC-013",
        "Policy gate failed",
        retryable=False,
    ),
    "SPEC-014": SpectraError("SPEC-014", "Cost budget exceeded", retryable=False),
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


class BudgetExceededError(Exception):
    """Raised when the next agent call would push spend over the cap (SPEC-014).

    Carries the per-agent breakdown so the CLI can render a brand-voice
    failure listing which dimension consumed the most. Non-retryable —
    the operator must rerun with a higher cap or split scope.

    Attributes:
        error: The underlying ``SpectraError`` (always SPEC-014).
        spent_usd: Total USD recorded so far when the gate fired.
        budget_usd: The cap that was exceeded.
        per_agent: ``{agent_name: cost_usd}`` map for the run.
    """

    def __init__(
        self,
        spent_usd: float,
        budget_usd: float,
        per_agent: dict[str, float],
    ) -> None:
        self.error = ERRORS["SPEC-014"]
        self.spent_usd = spent_usd
        self.budget_usd = budget_usd
        self.per_agent = per_agent
        super().__init__(f"{self.error.code}: {self.error.message}")


class SecretDetectedError(Exception):
    """Raised when the pre-flight secret scan finds one or more secrets (SPEC-011).

    Block-by-default behavior: callers may override with ``--allow-secrets`` at
    the CLI seam. The detected findings are surfaced on the exception so the
    composition root can render a brand-voice failure message naming each file.

    Attributes:
        error: The underlying ``SpectraError`` (always SPEC-011).
        findings: Tuple of ``SecretFinding`` value objects discovered in the
            workspace. Empty tuple is technically valid but should never be
            raised in practice — pre-flight only signals on a non-empty set.
    """

    def __init__(self, findings: tuple[SecretFinding, ...]) -> None:
        self.error = ERRORS["SPEC-011"]
        self.findings = findings
        super().__init__(f"{self.error.code}: {self.error.message}")


class PolicyGateError(Exception):
    """Raised when ``.spectra-policy.yml`` rejects the run (SPEC-013).

    Lives in ``entities`` so both infrastructure (the composition root,
    where ``_enforce_policy`` raises it) and the CLI adapter (where it
    is caught and rendered) can reference the same class without
    violating the Dependency Rule.

    Attributes:
        error: ``SpectraError`` SPEC-013 — non-retryable.
        violations: Tuple of ``Violation`` entries returned by
            ``PolicyPort.evaluate``.
    """

    def __init__(self, violations: tuple[Violation, ...]) -> None:
        self.error: SpectraError = ERRORS["SPEC-013"]
        self.violations: tuple[Violation, ...] = violations
        super().__init__(f"{self.error.code}: {self.error.message}")


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
