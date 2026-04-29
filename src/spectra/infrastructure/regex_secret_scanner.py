"""Pre-flight regex secret scanner — implements ``SecretScannerPort``.

A pure-Python regex scanner that runs once over the filtered file list
*before* any LLM call so a leaked secret never lands in a prompt body.

Pattern catalogue (intentionally curated, NOT exhaustive):
    aws_access_key   AKIA[0-9A-Z]{16}                    ← format-locked
    github_pat       ghp_[A-Za-z0-9]{36}                 ← format-locked
    anthropic_key    sk-ant-[A-Za-z0-9_-]{32,}           ← format-locked
    bearer_token     Bearer [A-Za-z0-9._-]{20,}          ← high-confidence
    slack_webhook    https://hooks.slack.com/services/.. ← URL-locked
    private_key      BEGIN (RSA|OPENSSH) PRIVATE KEY     ← header-locked
    dotenv_value     ^[A-Z_]+=.{12,}$ inside .env*       ← heuristic only

The dotenv heuristic is intentionally file-scoped — a generic
``KEY=value`` pattern would false-positive on every config dict in
source code. The Tier-S patterns above are evaluated against every
file regardless of name.

Operational guarantees:
    - Per-file decode errors are swallowed; binary files yield no matches.
    - Missing files (raced deletions) yield no matches; never raise.
    - File reads use a small chunk cap (1 MB) — no zip-bomb risk.
    - Pattern set is compiled once at construction; no per-call setup cost.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from spectra.entities.models import SecretFinding

# 1 MB read cap matches GitAdapter's per-file ceiling — anything larger
# is almost certainly a binary blob we don't want to scan anyway.
_MAX_SCAN_BYTES: Final[int] = 1_048_576


# ── Pattern catalogue ─────────────────────────────────────────


_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    # AWS access key — exactly 20 chars total (4 prefix + 16).
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # GitHub personal access token — exactly 40 chars (4 prefix + 36).
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    # Anthropic API key — sk-ant-* with at least 32 chars of payload.
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}\b")),
    # Bearer token — capital "Bearer " required to avoid false hits.
    ("bearer_token", re.compile(r"\bBearer [A-Za-z0-9._-]{20,}\b")),
    # Slack incoming webhook — URL prefix uniquely identifies it.
    (
        "slack_webhook",
        re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+"),
    ),
    # Private key headers (RSA + OpenSSH covered in one alt).
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY-----"),
    ),
)

# Heuristic: in a .env-style file, any ALL_CAPS=value with ≥12 chars
# of value is suspicious. Only triggers for files matching ``.env*``.
_DOTENV_LINE: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9_]*=.{12,}$")


def _is_dotenv_file(path: str) -> bool:
    """Return True iff the basename is ``.env`` or starts with ``.env.``."""
    name = Path(path).name
    return name == ".env" or name.startswith(".env.")


def _read_text_bounded(full: Path) -> str | None:
    """Read up to ``_MAX_SCAN_BYTES`` of UTF-8 text, or ``None`` on any error.

    Binary files raise ``UnicodeDecodeError`` and yield ``None`` so the
    caller skips them silently.
    """
    try:
        with full.open("rb") as fh:
            raw = fh.read(_MAX_SCAN_BYTES)
    except OSError:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _scan_lines_for_patterns(
    lines: list[str],
    relative_path: str,
) -> list[SecretFinding]:
    """Apply the Tier-S compiled patterns to every line.

    Returns at most one finding per (line, pattern_name) pair so a single
    line containing two distinct secrets shows up as two findings, but a
    line repeating the same pattern only counts once.
    """
    findings: list[SecretFinding] = []
    for lineno, line in enumerate(lines, start=1):
        for name, pattern in _PATTERNS:
            if pattern.search(line):
                findings.append(
                    SecretFinding(
                        file_path=relative_path,
                        line=lineno,
                        pattern_name=name,
                    )
                )
    return findings


def _scan_dotenv_heuristic(
    lines: list[str],
    relative_path: str,
) -> list[SecretFinding]:
    """Flag ALL_CAPS=value lines where value is ≥12 chars long."""
    findings: list[SecretFinding] = []
    for lineno, line in enumerate(lines, start=1):
        if _DOTENV_LINE.match(line.strip()):
            findings.append(
                SecretFinding(
                    file_path=relative_path,
                    line=lineno,
                    pattern_name="dotenv_value",
                )
            )
    return findings


class RegexSecretScanner:
    """Pure-Python regex scanner implementing ``SecretScannerPort``."""

    def scan(
        self,
        repo_dir: str,
        file_paths: list[str],
    ) -> tuple[SecretFinding, ...]:
        """Scan every file; return all findings as an immutable tuple."""
        if not file_paths:
            return ()
        root = Path(repo_dir).resolve()
        out: list[SecretFinding] = []
        for rel in file_paths:
            out.extend(self._scan_one(root, rel))
        return tuple(out)

    def _scan_one(self, root: Path, relative_path: str) -> list[SecretFinding]:
        """Scan a single file; return [] on any I/O or decode error."""
        full = root / relative_path
        if not full.is_file():
            return []
        text = _read_text_bounded(full)
        if text is None:
            return []
        lines = text.splitlines()
        findings = _scan_lines_for_patterns(lines, relative_path)
        if _is_dotenv_file(relative_path):
            findings.extend(_scan_dotenv_heuristic(lines, relative_path))
        return findings
