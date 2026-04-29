# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-04-29

### Fixed
- `spectra --version` was hardcoded to `v0.1.0` and never bumped — it now reads from `spectra.__version__`. Same fix for the SARIF report's `tool.driver.version` field (also hardcoded). Existing tests were tightened to assert `f"v{__version__}"` so future bumps don't silently regress.

## [0.3.0] - 2026-04-29

### Added
- Phase 3 per-`focus_area` batch caching with hit-log telemetry — splits each ANALYZE batch into cached vs fresh prompts, reuses per-focus_area work across runs, and writes per-lookup outcomes to `hit_log` for per-dimension hit-rate reporting (PR #18).
- Phase 4 cache management CLI: `spectra cache stats`, `spectra cache clear`, and `spectra cache prune`. `stats` surfaces total entries, on-disk size, and per-dimension hit-rate breakdown sourced from the new `hit_log` dimension columns; `prune` does the deferred physical deletion of stale rows (PR #19).
- 7 new architecture diagrams: system context, container view, cache subsystem, sequence with cache decision points, class model with cache entities, decorator chain LLD, and GitHub Action flow. 2 of them ship in Excalidraw form for slide-friendly editing (PR #20).
- ADR-009 (per-`focus_area` batch granularity locked in as the canonical cache unit) and ADR-010 (no self-dogfooding rationale) (PR #20).
- HLD/LLD/CLAUDE.md sync for the cache subsystem and Distribution model (PR #20).
- All 8 agents now run on Claude Opus 4.7, with per-agent `effort` and `task_budget` tuning and adaptive thinking for the CritiqueAgent.
- GitHub Action `spectra-ai/spectra@v1` for running Spectra in PR CI — see `docs/github-action.md`.
- CLI accepts local repository paths, e.g. `spectra analyze .` (no clone needed for the current working tree).
- Incremental analysis: new `CachePort` with a `SqliteCacheAdapter` (Phase 1) and ANALYZE-stage skip on file-tree match (Phase 2) — repeat runs on unchanged code reuse the previous report.
- `--force` flag to bypass the cache and re-run a full analysis.
- `--no-cache` flag to disable cache reads and writes for a single run.

### Changed
- `analyze_repository` collapses its 8 positional dependencies into a single `PipelineContext` for clearer wiring and easier testing.
- HLD/LLD documentation refreshed; 4 new ADRs added in v0.2.0-track work (005 Opus 4.7 migration, 006 CachePort, 007 GitHub Action, 008 adaptive thinking — supersedes ADR-003).
- All 5 architecture diagrams regenerated from their Mermaid sources.
- Error registry extended: SPEC-010 added for cache I/O failures — non-fatal, the pipeline degrades to no-cache for the rest of the run.

### Fixed
- **Security (HIGH):** TOCTOU symlink bypass in path validation closed; SSRF gaps in URL handling tightened; git subprocess environment hardened against `GIT_*` injection.
- **Packaging:** Jinja2 report templates now ship inside the wheel — `pip install spectra-ai` produces a working report renderer (previously broken on PyPI installs).

### Removed
- Unused `extended_thinking` field on `AgentContext` (superseded by per-agent `task_budget` + adaptive thinking).
- Self-analysis CI workflows that ran Spectra against its own repo on every push (avoided API-key abuse on forks).

## [0.2.0] - SKIPPED (never published)

Version bumped in PR #17 but never tagged. Contents folded into v0.3.0.

## [0.1.0] - 2026-04-XX

Initial PyPI release.
