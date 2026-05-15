"""Spectra — 8 AI agents analyze your entire repository in under 5 minutes.

The full spectrum of your codebase: architecture, security, quality,
documentation, maintainability, and performance — analyzed in parallel
by 6 specialist agents, planned by MetaPrompter, and validated by
CritiqueAgent with adaptive thinking on Claude Opus 4.7.

Usage::

    spectra analyze https://github.com/org/repo
    spectra analyze https://github.com/org/repo --quick
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# Resolve from installed-distribution metadata. Limitation: if ``spectra`` is
# imported from a source checkout while a different ``spectra-ai`` distribution
# is also installed in the environment (e.g. ``pip install spectra-ai==0.7.0``
# in the same venv as a Git checkout), this returns the installed version, not
# the checkout's. Run ``pip install -e .`` after editing ``pyproject.toml`` to
# keep the two aligned. This matches the standard pattern used by ``pip``,
# ``anthropic``, and other mature packages — the alternative (parsing
# ``pyproject.toml`` at import time) trades a narrow edge case for permanent
# import-time disk I/O.
try:
    __version__ = _pkg_version("spectra-ai")
except PackageNotFoundError:
    __version__ = "0.0.0+source"

__all__ = ["__version__"]
