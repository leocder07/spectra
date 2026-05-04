"""Manifest-format detectors for SBOM emission (Layer 2, Q4 #58).

Three detectors in this slice:
- ``detect_python_components`` — PEP 621 ``pyproject.toml``
- ``detect_npm_components`` — ``package.json`` (``dependencies`` + ``devDependencies``)
- ``detect_go_components`` — ``go.mod`` (``require`` block + single-line)

Six other formats (``requirements.txt``, ``Cargo.toml``, ``pom.xml``,
``build.gradle``, ``Gemfile``, ``composer.json``) and lockfile transitive
parsing land in follow-up PRs. The aggregator ``detect_all_components``
runs every detector and isolates failures: a malformed manifest in one
ecosystem does not prevent the others from running.

Detectors are pure functions taking ``(file_paths, file_reader)`` —
no I/O of their own; the caller (use case or pipeline stage) threads
in a reader closure. This keeps the detector layer testable without
touching the disk.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from collections.abc import Callable, Iterable

from spectra.entities.sbom import SbomComponent

_LOG = logging.getLogger("spectra.sbom")

FileReader = Callable[[str], str]

# PEP 508 dependency spec — strip everything after a marker char so
# the name is extractable. We do NOT try to parse the version
# constraint; the SBOM records the *declared* version range when one
# is pinned, otherwise None.
_PEP508_NAME_RE = re.compile(r"^([A-Za-z0-9_.\-]+)")
_PEP508_VERSION_RE = re.compile(r"==\s*([A-Za-z0-9_.\-]+)")

# Match three line shapes:
#   - ``require github.com/x/y v1.0.0``      (single-line require)
#   - ``\tgithub.com/x/y v1.0.0``            (inside a ``require ( ... )`` block)
#   - skip ``module foo/bar`` (no v-version follows the name)
# Optional ``require `` prefix lets both forms hit the same regex.
_GOMOD_REQUIRE_LINE_RE = re.compile(
    r"^\s*(?:require\s+)?([\w./\-]+)\s+(v[\w.\-+]+)",
    re.MULTILINE,
)


def _filter_paths(paths: Iterable[str], suffix: str) -> tuple[str, ...]:
    """Return paths whose basename matches ``suffix``."""
    return tuple(p for p in paths if p.endswith(suffix))


# ── Python (pyproject.toml) ────────────────────────────────────


def detect_python_components(
    file_paths: tuple[str, ...],
    file_reader: FileReader,
) -> tuple[SbomComponent, ...]:
    """Detect PyPI components from PEP 621 ``[project].dependencies``.

    Returns an empty tuple on missing or malformed manifest — never raises.
    """
    out: list[SbomComponent] = []
    for path in _filter_paths(file_paths, "pyproject.toml"):
        try:
            doc = tomllib.loads(file_reader(path))
        except (tomllib.TOMLDecodeError, KeyError, OSError):
            continue
        deps = doc.get("project", {}).get("dependencies", [])
        for dep in deps:
            if not isinstance(dep, str):
                continue
            name_match = _PEP508_NAME_RE.match(dep.strip())
            if not name_match:
                continue
            name = name_match.group(1)
            ver_match = _PEP508_VERSION_RE.search(dep)
            version = ver_match.group(1) if ver_match else None
            purl = f"pkg:pypi/{name}@{version}" if version else f"pkg:pypi/{name}"
            out.append(
                SbomComponent(
                    purl=purl,
                    name=name,
                    version=version,
                    ecosystem="pypi",
                    evidence_path=path,
                ),
            )
    return tuple(out)


# ── JavaScript (package.json) ──────────────────────────────────


def detect_npm_components(
    file_paths: tuple[str, ...],
    file_reader: FileReader,
) -> tuple[SbomComponent, ...]:
    """Detect npm components from ``dependencies`` + ``devDependencies``.

    Returns an empty tuple on missing or malformed manifest.
    """
    out: list[SbomComponent] = []
    for path in _filter_paths(file_paths, "package.json"):
        try:
            doc = json.loads(file_reader(path))
        except (json.JSONDecodeError, OSError):
            continue
        for section in ("dependencies", "devDependencies"):
            block = doc.get(section, {})
            if not isinstance(block, dict):
                continue
            for name, version_spec in block.items():
                if not isinstance(name, str) or not isinstance(version_spec, str):
                    continue
                version = _strip_npm_range(version_spec)
                # Scoped packages (``@anthropic-ai/sdk``) keep their full
                # name in the purl after URL-encoding the slash.
                purl_name = name.replace("/", "%2F") if name.startswith("@") else name
                purl = f"pkg:npm/{purl_name}@{version}" if version else f"pkg:npm/{purl_name}"
                out.append(
                    SbomComponent(
                        purl=purl,
                        name=name,
                        version=version,
                        ecosystem="npm",
                        evidence_path=path,
                    ),
                )
    return tuple(out)


def _strip_npm_range(spec: str) -> str | None:
    """Drop ``^``, ``~``, ``>=``, ``*`` etc. so we keep a clean version.

    Returns ``None`` when the spec is a tarball URL, git+ref, or other
    non-semver shape we can't reliably parse.
    """
    s = spec.strip()
    if not s or s.startswith(("file:", "git+", "http://", "https://", "*", "latest")):
        return None
    # Strip leading range characters; keep what looks like a version.
    return s.lstrip("^~>=<")


# ── Go (go.mod) ─────────────────────────────────────────────────


def detect_go_components(
    file_paths: tuple[str, ...],
    file_reader: FileReader,
) -> tuple[SbomComponent, ...]:
    """Detect Go modules from ``go.mod`` ``require`` lines.

    Handles both the parenthesised block ``require ( ... )`` and the
    single-line form ``require <module> <version>``.
    """
    out: list[SbomComponent] = []
    for path in _filter_paths(file_paths, "go.mod"):
        try:
            content = file_reader(path)
        except OSError:
            continue
        for match in _GOMOD_REQUIRE_LINE_RE.finditer(content):
            name = match.group(1)
            version = match.group(2)
            # Skip the module declaration line ("module foo/bar") — it
            # matches the regex but has no leading require keyword. The
            # heuristic: the first capture group on a "module ..." line
            # is "module" itself. We filter those.
            if name == "module":
                continue
            out.append(
                SbomComponent(
                    purl=f"pkg:golang/{name}@{version}",
                    name=name,
                    version=version,
                    ecosystem="go",
                    evidence_path=path,
                ),
            )
    return tuple(out)


# ── Aggregator ──────────────────────────────────────────────────


def detect_all_components(
    file_paths: tuple[str, ...],
    file_reader: FileReader,
) -> tuple[SbomComponent, ...]:
    """Run every detector; isolate failures so one bad manifest doesn't kill the rest."""
    detectors = (
        detect_python_components,
        detect_npm_components,
        detect_go_components,
    )
    out: list[SbomComponent] = []
    for detector in detectors:
        try:
            out.extend(detector(file_paths, file_reader))
        except Exception as exc:
            _LOG.debug("sbom detector %s failed (%s); skipping", detector.__name__, exc)
    return tuple(out)


__all__ = [
    "detect_all_components",
    "detect_go_components",
    "detect_npm_components",
    "detect_python_components",
]
