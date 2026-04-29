"""Indicative-analysis disclaimer — single source of truth.

Renders identically across HTML, JSON, and SARIF output channels so that
SAST consumers, machine-readable pipelines, and human report viewers all
see the same wording. The text is intentionally a module-level constant
so a single edit propagates everywhere.

This is a Layer 1 entity — it imports nothing from the ``spectra``
package and depends only on the standard library.
"""

from __future__ import annotations

from typing import Final

DISCLAIMER_TEXT: Final[str] = (
    "Indicative analysis — not auditor-grade evidence. Spectra runs 8 LLM "
    "agents over your code; findings are heuristic and require human "
    "verification before being treated as compliance evidence, audit input, "
    "or pass/fail signal in regulated workflows."
)

DISCLAIMER_URL: Final[str] = "https://github.com/leocder07/spectra#disclaimer"


def disclaimer_payload() -> dict[str, str]:
    """Return the JSON-serializable disclaimer payload.

    Returned as a fresh ``dict`` so callers may mutate it without poking
    a shared module-level object.
    """
    return {"text": DISCLAIMER_TEXT, "url": DISCLAIMER_URL}


__all__ = [
    "DISCLAIMER_TEXT",
    "DISCLAIMER_URL",
    "disclaimer_payload",
]
