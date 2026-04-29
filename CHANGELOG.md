# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-04-29

### Added
- All 8 agents now run on Claude Opus 4.7, with per-agent `effort` and `task_budget` tuning and adaptive thinking for the CritiqueAgent.
- GitHub Action `spectra-ai/spectra@v1` for running Spectra in PR CI — see `docs/github-action.md`.
- CLI accepts local repository paths, e.g. `spectra analyze .` (no clone needed for the current working tree).
- Incremental analysis: new `CachePort` with a `SqliteCacheAdapter` (Phase 1) and ANALYZE-stage skip on file-tree match (Phase 2) — repeat runs on unchanged code reuse the previous report.
- `--force` flag to bypass the cache and re-run a full analysis.
- `--no-cache` flag to disable cache reads and writes for a single run.

### Changed
- `analyze_repository` collapses its 8 positional dependencies into a single `PipelineContext` for clearer wiring and easier testing.
- HLD/LLD documentation refreshed; 4 new ADRs added (005 Opus 4.7 migration, 006 CachePort, 007 GitHub Action, 008 adaptive thinking — supersedes ADR-003).
- All 5 architecture diagrams regenerated from their Mermaid sources.

### Fixed
- **Security (HIGH):** TOCTOU symlink bypass in path validation closed; SSRF gaps in URL handling tightened; git subprocess environment hardened against `GIT_*` injection.
- **Packaging:** Jinja2 report templates now ship inside the wheel — `pip install spectra-ai` produces a working report renderer (previously broken on PyPI installs).

### Removed
- Unused `extended_thinking` field on `AgentContext` (superseded by per-agent `task_budget` + adaptive thinking).
- Self-analysis CI workflows that ran Spectra against its own repo on every push (avoided API-key abuse on forks).

## [0.1.0] - 2026-04-XX

Initial PyPI release.
