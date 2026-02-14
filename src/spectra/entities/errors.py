"""Error taxonomy and Result type for fallible operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class SpectraError:
    """Immutable error with retry metadata."""

    code: str
    message: str
    retryable: bool
    max_retries: int = 0


ERRORS: dict[str, SpectraError] = {
    "SPEC-001": SpectraError("SPEC-001", "Git clone failed", retryable=True, max_retries=2),
    "SPEC-002": SpectraError("SPEC-002", "Anthropic API unreachable", retryable=True, max_retries=3),
    "SPEC-003": SpectraError("SPEC-003", "Rate limited (429)", retryable=True, max_retries=3),
    "SPEC-004": SpectraError("SPEC-004", "Token budget exceeded", retryable=False),
    "SPEC-005": SpectraError("SPEC-005", "Agent output validation failed", retryable=True, max_retries=1),
    "SPEC-006": SpectraError("SPEC-006", "Agent timeout (120s)", retryable=False),
    "SPEC-007": SpectraError("SPEC-007", "2+ agents failed", retryable=False),
    "SPEC-008": SpectraError("SPEC-008", "CritiqueAgent failed", retryable=False),
    "SPEC-009": SpectraError("SPEC-009", "Report render failed", retryable=False),
}


class AgentError(Exception):
    """Raised when an agent operation fails with a domain error."""

    def __init__(self, error: SpectraError) -> None:
        self.error = error
        super().__init__(f"{error.code}: {error.message}")


class GitError(Exception):
    """Raised when a git operation fails with a domain error."""

    def __init__(self, error: SpectraError) -> None:
        self.error = error
        super().__init__(f"{error.code}: {error.message}")


class SpectraRetryError(Exception):
    """Raised when all retry attempts are exhausted for a SpectraError."""

    def __init__(self, error: SpectraError) -> None:
        self.error = error
        super().__init__(f"{error.code}: {error.message}")


def strip_code_fence(raw: str) -> str:
    """Remove markdown code fences from LLM output."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned


@dataclass(frozen=True)
class Result(Generic[T]):
    """Outcome of a fallible operation — either value or error, never both."""

    value: T | None = None
    error: SpectraError | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None

    @property
    def is_err(self) -> bool:
        return self.error is not None
