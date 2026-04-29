"""Pre-flight use case — Stage 1.5 between INGEST and PLAN.

Composes :class:`WorkspaceFilterPort` and :class:`SecretScannerPort`
behind a thin orchestration function. The pipeline always:

    1. Filters the file tree through the WorkspaceFilterPort
       (``.gitignore`` + ``.spectraignore``). Filtered paths NEVER
       flow into the scanner — that would defeat the .gitignore
       guarantee for users who deliberately ignore ``.env``.

    2. Scans the kept paths through the SecretScannerPort.

    3. If any secret is detected and ``allow_secrets`` is False,
       raises :class:`SecretDetectedError` (SPEC-011) carrying
       every match. Otherwise, returns a :class:`PreflightResult`
       carrying the filtered file list and any findings (which the
       composition root may surface as a WARN log).

Layer 2 only — no infrastructure imports. The composition root
provides the concrete adapter instances.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spectra.entities.errors import SecretDetectedError

if TYPE_CHECKING:
    from spectra.entities.models import SecretFinding
    from spectra.use_cases.interfaces import (
        SecretScannerPort,
        WorkspaceFilterPort,
    )


@dataclass(frozen=True)
class PreflightConfig:
    """Composition-time toggles for the pre-flight stage.

    Attributes:
        allow_secrets: When True, secret findings are reported but
            do NOT raise SPEC-011. The composition root logs a WARN
            and the pipeline continues.  Wired to the ``--allow-secrets``
            CLI flag. Default: False (block-by-default).
    """

    allow_secrets: bool = False


@dataclass(frozen=True)
class PreflightResult:
    """Outcome of the pre-flight stage.

    Attributes:
        filtered_files: File-tree subset that survives every active
            ignore filter. Downstream stages MUST use this list, not
            the raw file tree.
        secret_findings: Tuple of detected secrets. Empty on a clean
            scan; non-empty only when ``allow_secrets=True`` (otherwise
            SPEC-011 is raised before this struct is constructed).
    """

    filtered_files: list[str]
    secret_findings: tuple[SecretFinding, ...]


def run_preflight(
    repo_dir: str,
    file_tree: list[str],
    workspace_filter: WorkspaceFilterPort,
    secret_scanner: SecretScannerPort,
    config: PreflightConfig,
) -> PreflightResult:
    """Run the workspace filter + secret scan; return the verified result.

    Args:
        repo_dir: Absolute path to the prepared workspace.
        file_tree: Repository-relative paths produced by Stage 1 (INGEST).
        workspace_filter: Concrete adapter implementing the filter port.
        secret_scanner: Concrete adapter implementing the scanner port.
        config: Composition-time toggles.

    Returns:
        :class:`PreflightResult` carrying the filtered file list and
        any detected (but allowed) secret findings.

    Raises:
        SecretDetectedError: SPEC-011 when secrets are detected and
            ``config.allow_secrets`` is False.
    """
    filtered = workspace_filter.filter_files(repo_dir, file_tree)
    findings = secret_scanner.scan(repo_dir, filtered)
    if findings and not config.allow_secrets:
        raise SecretDetectedError(findings)
    return PreflightResult(filtered_files=filtered, secret_findings=findings)
