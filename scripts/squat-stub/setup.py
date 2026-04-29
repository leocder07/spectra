"""Defensive squat stub.

This setup.py builds a tiny no-op package whose only purpose is to
reserve a name on PyPI that an attacker might otherwise typosquat.
The package name is injected via the SQUAT_NAME environment variable
so a single source tree can publish all variants in
scripts/register_pypi_squats.sh.

DO NOT add functionality here. The README.md sibling file is shipped
inside the wheel so anyone who installs by mistake sees the canonical
"the real package is spectra-ai" pointer immediately.
"""

import os

from setuptools import setup

squat_name = os.environ.get("SQUAT_NAME")
if not squat_name:
    raise SystemExit(
        "SQUAT_NAME env var is required (e.g. SQUAT_NAME=spectra_ai python -m build)"
    )

with open("README.md", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name=squat_name,
    version="0.0.1",
    description="Defensive squat for spectra-ai. Install spectra-ai instead.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Vivek Kumar",
    author_email="vivek@proxie.in",
    url="https://github.com/leocder07/spectra",
    license="MIT",
    py_modules=[],
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 7 - Inactive",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Topic :: Security",
    ],
    keywords=["spectra-ai", "defensive-squat", "typosquat-protection"],
    project_urls={
        "Real Package": "https://pypi.org/project/spectra-ai/",
        "Repository": "https://github.com/leocder07/spectra",
    },
)
