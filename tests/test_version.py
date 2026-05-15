"""Regression test: ``spectra.__version__`` must be the single source of truth.

The version string is read by 9+ runtime sites (cache composite key, SARIF
metadata, OpenTelemetry attributes, report receipts, the CLI ``--version``
output). Before PR #87 it lived in two places — ``pyproject.toml`` and
``src/spectra/__init__.py`` — and PR #86 shipped a pyproject bump that
forgot the ``__init__.py`` bump (caught by Greptile pre-merge). This test
ensures the two can never drift again by asserting the runtime value is
derived from installed package metadata.
"""

from __future__ import annotations

from importlib.metadata import version as pkg_version


def test_runtime_version_matches_installed_package_metadata() -> None:
    import spectra

    assert spectra.__version__ == pkg_version("spectra-ai")
