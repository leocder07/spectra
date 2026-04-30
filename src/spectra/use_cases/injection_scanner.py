"""Pre-flight regex scanner for prompt-injection markers (ADR-011 §3).

Cheap defence-in-depth pre-pass that flags files whose content contains
known injection markers (``IGNORE PRIOR INSTRUCTIONS``, ``<system>``,
fake closing tags, role-play prompts, fake data fences). Matches are
NEVER stripped — that would mask the attack from the user and from the
CritiqueAgent. The flagged file list is structured input for the
adversarial check (ADR-011 §2).

Performance contract: bounded to ≤200ms on 10MB of source. The scanner
runs synchronously inside ``analyze_repository`` and never gates
pipeline progress.

Layer 2 (use_cases) — pure function, no infrastructure imports.

ADR references: ADR-011 (prompt-injection isolation).
See ``docs/architecture/adr/ADR-011-prompt-injection-isolation.md`` and
``docs/glossary.md`` for the at-a-glance ADR index.
"""

from __future__ import annotations

import re

INJECTION_MARKERS: tuple[str, ...] = (
    "IGNORE PRIOR INSTRUCTIONS",
    "<system>",
    "</analyzed_code>",
    "assistant:",
    "human:",
    "<<<SPECTRA-DATA-",
)
"""Curated list of injection markers — see ADR-011 §3.

Updating this list does not require a major version bump (ADR §Neutral).
Adversarial tests assume these exact patterns are caught.
"""

# Single compiled regex with all alternatives keeps the per-byte cost
# inside Python's C-implemented re engine. Case-insensitive matching
# catches variants like "ignore prior instructions" and "Assistant:".
_PATTERN: re.Pattern[str] = re.compile(
    "|".join(re.escape(m) for m in INJECTION_MARKERS),
    re.IGNORECASE,
)


def scan_files_for_injection(
    files: dict[str, str],
) -> tuple[str, ...]:
    """Return the sorted list of file paths whose content matches a marker.

    Args:
        files: ``{path: content}`` mapping. NOT mutated.

    Returns:
        Tuple of repo-relative paths whose content contains at least
        one injection marker. Empty when no markers match. Sorted for
        deterministic output (test stability + audit-log clarity).
    """
    flagged = [path for path, content in files.items() if _PATTERN.search(content)]
    return tuple(sorted(flagged))
