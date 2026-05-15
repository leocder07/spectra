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

try:
    __version__ = _pkg_version("spectra-ai")
except PackageNotFoundError:
    __version__ = "0.0.0+source"

__all__ = ["__version__"]
