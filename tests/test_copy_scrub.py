"""Copy-scrub guardrail — forbidden audit/compliance phrases stay out of marketing surfaces.

The indicative-analysis disclaimer is the ONE allowed home for phrases
like "compliance evidence" and "auditor-grade" — there they appear
inside an explicit negation telling users *not* to treat Spectra output
that way. Anywhere else, they read as a marketing claim Spectra cannot
back up.

The guardrail recognises two legitimate contexts:

1. **Allowlisted files.** ``src/spectra/entities/disclaimer.py`` is the
   canonical text source — the forbidden phrases live there by design.
2. **Disclaimer blocks in mixed files.** Templates and READMEs may
   render the disclaimer alongside other copy. Any line/paragraph that
   also contains the canonical opener (``Indicative analysis``) or the
   negation marker (``human verification``) is treated as part of the
   disclaimer surface and skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FORBIDDEN = re.compile(
    r"compliance evidence|audit[- ]grade|auditor[- ]ready|comprehensive solution",
    re.IGNORECASE,
)

# Markers that identify a disclaimer block — matches inside such a block
# are negations of the claim (the entire point of the disclaimer) and
# are not marketing copy.
_DISCLAIMER_MARKERS = (
    "indicative analysis",
    "human verification",
    "not auditor-grade",
)

# Canonical text source — forbidden phrases live here by design.
_ALLOWLIST = {
    _REPO_ROOT / "src" / "spectra" / "entities" / "disclaimer.py",
}


def _iter_target_files() -> list[Path]:
    """Files in scope for the marketing-copy guardrail."""
    targets: list[Path] = []
    targets.append(_REPO_ROOT / "README.md")
    for root in (_REPO_ROOT / "src",):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".md", ".html", ".j2", ".jinja", ".jinja2", ".txt"}:
                continue
            if path in _ALLOWLIST:
                continue
            targets.append(path)
    return targets


def _is_disclaimer_context(text: str, match_start: int) -> bool:
    """A match is a disclaimer negation if a marker appears within ±400 chars."""
    window = text[max(0, match_start - 400) : match_start + 400].lower()
    return any(marker in window for marker in _DISCLAIMER_MARKERS)


@pytest.mark.parametrize("path", _iter_target_files(), ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_no_forbidden_marketing_phrases(path: Path) -> None:
    """Forbidden phrases must not appear in src/templates/README outside the disclaimer."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    offending: list[str] = []
    for match in _FORBIDDEN.finditer(text):
        if _is_disclaimer_context(text, match.start()):
            continue
        offending.append(match.group(0))

    assert not offending, (
        f"{path.relative_to(_REPO_ROOT)} contains forbidden marketing copy: {offending}. "
        "Move language into the disclaimer entity if it is meant to *negate* the claim, "
        "otherwise rewrite without these terms."
    )
