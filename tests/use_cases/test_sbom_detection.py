"""Tests for the manifest detectors (Layer 2, Q4 #58).

Three detectors in this slice — Python (``pyproject.toml``), JavaScript
(``package.json``), Go (``go.mod``). Six other formats
(``requirements.txt``, ``Cargo.toml``, ``pom.xml``, ``build.gradle``,
``Gemfile``, ``composer.json``) and lockfile transitive parsing land in
follow-up PRs.

Detectors are pure functions taking ``(file_paths, file_reader)`` —
no I/O of their own; the caller threads in a reader closure so the
tests can inject in-memory content without touching disk.
"""

from __future__ import annotations

from collections.abc import Callable

from spectra.use_cases.sbom_detection import (
    detect_all_components,
    detect_go_components,
    detect_npm_components,
    detect_python_components,
)

# ── Helpers ────────────────────────────────────────────────────


def _reader(files: dict[str, str]) -> Callable[[str], str]:
    return lambda path: files[path]


# ── Python (pyproject.toml) ────────────────────────────────────


class TestPythonDetector:
    def test_pep621_dependencies(self) -> None:
        files = {
            "pyproject.toml": """
[project]
name = "example"
version = "1.0.0"
dependencies = [
    "requests>=2.31",
    "pydantic>=2.5,<3.0",
    "typer",
]
""",
        }
        result = detect_python_components(tuple(files.keys()), _reader(files))
        names = {c.name for c in result}
        assert names == {"requests", "pydantic", "typer"}
        assert all(c.ecosystem == "pypi" for c in result)
        assert all(c.evidence_path == "pyproject.toml" for c in result)

    def test_purl_format(self) -> None:
        files = {"pyproject.toml": '[project]\nname = "x"\nversion = "0.1"\ndependencies = ["requests>=2.31"]\n'}
        result = detect_python_components(tuple(files.keys()), _reader(files))
        assert result[0].purl.startswith("pkg:pypi/requests")

    def test_no_pyproject_returns_empty(self) -> None:
        result = detect_python_components(("README.md", "src/main.py"), _reader({}))
        assert result == ()

    def test_malformed_pyproject_returns_empty_not_raises(self) -> None:
        files = {"pyproject.toml": "not toml at all [[["}
        result = detect_python_components(("pyproject.toml",), _reader(files))
        assert result == ()


# ── JavaScript (package.json) ──────────────────────────────────


class TestNpmDetector:
    def test_dependencies_and_devdependencies(self) -> None:
        files = {
            "package.json": """
{
  "name": "example",
  "version": "1.0.0",
  "dependencies": {
    "react": "^18.0.0",
    "lodash": "4.17.21"
  },
  "devDependencies": {
    "vitest": "^1.0.0"
  }
}
""",
        }
        result = detect_npm_components(tuple(files.keys()), _reader(files))
        names = {c.name for c in result}
        assert names == {"react", "lodash", "vitest"}
        assert all(c.ecosystem == "npm" for c in result)

    def test_scoped_package_handled(self) -> None:
        files = {
            "package.json": """
{
  "name": "x",
  "version": "1.0.0",
  "dependencies": {"@anthropic-ai/sdk": "^0.30.0"}
}
""",
        }
        result = detect_npm_components(tuple(files.keys()), _reader(files))
        assert any(c.name == "@anthropic-ai/sdk" for c in result)

    def test_no_package_json_returns_empty(self) -> None:
        result = detect_npm_components(("README.md",), _reader({}))
        assert result == ()


# ── Go (go.mod) ─────────────────────────────────────────────────


class TestGoDetector:
    def test_require_block(self) -> None:
        files = {
            "go.mod": """
module example.com/my/repo

go 1.22

require (
\tgithub.com/spf13/cobra v1.8.0
\tgithub.com/stretchr/testify v1.9.0
)
""",
        }
        result = detect_go_components(tuple(files.keys()), _reader(files))
        names = {c.name for c in result}
        assert names == {"github.com/spf13/cobra", "github.com/stretchr/testify"}
        assert all(c.ecosystem == "go" for c in result)

    def test_single_require_line(self) -> None:
        files = {"go.mod": "module x\nrequire github.com/google/uuid v1.6.0\n"}
        result = detect_go_components(tuple(files.keys()), _reader(files))
        assert result[0].name == "github.com/google/uuid"

    def test_no_go_mod_returns_empty(self) -> None:
        result = detect_go_components(("README.md",), _reader({}))
        assert result == ()


# ── Aggregator ──────────────────────────────────────────────────


class TestDetectAll:
    def test_combines_all_three_detectors(self) -> None:
        files = {
            "pyproject.toml": '[project]\nname = "x"\nversion = "0.1"\ndependencies = ["requests"]',
            "frontend/package.json": '{"name": "f", "version": "1", "dependencies": {"react": "18"}}',
            "go.mod": "module x\nrequire github.com/google/uuid v1\n",
        }
        result = detect_all_components(tuple(files.keys()), _reader(files))
        ecosystems = {c.ecosystem for c in result}
        assert ecosystems == {"pypi", "npm", "go"}

    def test_detector_failure_isolated(self) -> None:
        # A bad pyproject.toml does not prevent the npm detector from running.
        files = {
            "pyproject.toml": "garbage",
            "package.json": '{"name": "x", "version": "1", "dependencies": {"lodash": "1"}}',
        }
        result = detect_all_components(tuple(files.keys()), _reader(files))
        assert any(c.name == "lodash" for c in result)
