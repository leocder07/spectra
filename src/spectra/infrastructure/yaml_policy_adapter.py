"""YAML adapter for ``.spectra-policy.yml`` (Capability #17 — RICE-65).

Layer 4 implementation of ``PolicyPort``. Reads a YAML file from disk,
validates it against the ``Policy`` Pydantic model, and delegates
evaluation to ``policy_evaluation.evaluate_policy``.

Failure mode: malformed YAML or schema-violation raises
``AgentError(ERRORS["SPEC-012"])`` so the composition root can render a
brand-voice ``✗`` error block at the CLI seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from spectra.entities.errors import ERRORS, AgentError
from spectra.entities.models import EmptyPolicy, Policy
from spectra.use_cases.policy_evaluation import evaluate_policy

if TYPE_CHECKING:
    from pathlib import Path

    from spectra.entities.models import AnalysisReport, Violation


class YamlPolicyAdapter:
    """Loads ``.spectra-policy.yml`` and runs the policy gate."""

    def load(self, path: Path) -> Policy:
        """Return a frozen :class:`Policy` parsed from ``path``.

        Behaviour:
            - Missing file → ``EmptyPolicy()`` (no-op gate).
            - Empty file or comments-only → ``EmptyPolicy()``.
            - Malformed YAML or schema violation → ``AgentError`` SPEC-012.

        Args:
            path: Filesystem path to the policy YAML.

        Returns:
            Validated ``Policy`` instance.

        Raises:
            AgentError: SPEC-012 when YAML is malformed or fails Pydantic
                validation. The exception ``__cause__`` carries the
                original parser error for the CLI seam to render.
        """
        if not path.exists():
            return EmptyPolicy()
        raw = self._read_file(path)
        data = self._parse_yaml(path, raw)
        if data is None:
            return EmptyPolicy()
        return self._validate(path, data)

    def evaluate(
        self,
        policy: Policy,
        report: AnalysisReport,
    ) -> tuple[Violation, ...]:
        """Delegate to the pure ``evaluate_policy`` use case."""
        return evaluate_policy(policy, report)

    @staticmethod
    def _read_file(path: Path) -> str:
        """Read the YAML text; SPEC-012 on I/O failure."""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise _spec_012(f"cannot read {path}: {exc}", exc) from exc

    @staticmethod
    def _parse_yaml(path: Path, raw: str) -> dict | None:
        """Parse YAML; return None for empty/comments-only documents."""
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise _spec_012(f"invalid YAML in {path}: {exc}", exc) from exc
        if data is None:
            return None
        if not isinstance(data, dict):
            msg = f"{path} must be a YAML mapping at the top level"
            raise _spec_012(msg, ValueError(msg))
        return data

    @staticmethod
    def _validate(path: Path, data: dict) -> Policy:
        """Validate the parsed mapping with the Pydantic model."""
        try:
            return Policy.model_validate(data)
        except ValidationError as exc:
            raise _spec_012(f"invalid policy in {path}: {exc}", exc) from exc


def _spec_012(message: str, cause: BaseException) -> AgentError:
    """Wrap a parse/validation failure as :class:`AgentError` SPEC-012."""
    err = AgentError(ERRORS["SPEC-012"])
    err.args = (f"SPEC-012: {message}",)
    err.__cause__ = cause
    return err


__all__ = ["YamlPolicyAdapter"]
