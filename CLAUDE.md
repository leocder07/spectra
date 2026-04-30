# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Spectra?

Spectra deploys 8 AI agents (6 parallel specialists + MetaPrompter + CritiqueAgent) to analyze entire repositories across 6 dimensions — architecture, security, quality, documentation, maintainability, performance — in under 5 minutes. Python CLI. Clean Architecture.

**Tagline:** "The full spectrum of your codebase."
**One-liner:** "8 AI agents analyze your entire repository in under 5 minutes."

---

## Development Commands

```bash
# Install dependencies
pip install -e ".[dev]"

# Run CLI
spectra analyze <repo-url>
spectra analyze <repo-url> --quick    # Skip CritiqueAgent
spectra analyze <repo-url> --format json
spectra analyze <repo-url> --audit-sink stdout|file:<path>|otlp:<url>
spectra verify spectra-report.json    # Verify Ed25519 receipt

# Run tests
pytest tests/ -v
pytest tests/entities/ -v              # Unit tests only
pytest tests/integration/ -v           # Integration tests
pytest tests/ --cov=spectra --cov-report=html

# Lint and type check
ruff check src/ tests/
ruff format src/ tests/
mypy src/

# Build and publish
python -m build
pip install dist/spectra_cli-*.whl
```

---

## Architecture — ABSOLUTE RULES (NEVER VIOLATE)

### The Dependency Rule

Source code dependencies ONLY point inward:

```
Layer 1 (entities/)         → imports NOTHING from spectra package
Layer 2 (use_cases/)        → imports ONLY from entities/
Layer 3 (adapters/)         → imports from entities/ + use_cases/
Layer 4 (infrastructure/)   → imports from all inner layers
```

**Violation = immediate rejection. No exceptions.**

### Code Standards

- Functions: ≤20 lines, ≤3 parameters, cyclomatic complexity ≤10
- No `Any` type. No `# type: ignore`.
- No `print()` in src/ — use ProgressObserver port via Rich Console
- Every entity: `frozen=True` on Pydantic models. Immutable.
- Fallible operations: `Result` dataclass pattern
- All agent outputs: validated with Pydantic model BEFORE merge
- `Literal` types for enums: `Severity = Literal["critical", "high", "medium", "low", "info"]`
- Export everything from `__init__.py` with `__all__`

### Cache Subsystem

- **`CachePort` (Layer 2) + `SqliteCacheAdapter` (Layer 4).** Single `cache.db` under `${XDG_CACHE_HOME:-~/.cache}/spectra/` in WAL mode. The use-case layer never imports `sqlite3`.
- **Three caches, one DB.** `findings_cache` (per-file, Phase 1), `full_report_cache` (per-repo+versions, Phase 2 short-circuits Stages 3-5), `findings_batches` (per-`focus_area` batch, Phase 3 — the killer feature). Plus `hit_log` for telemetry.
- **Composite-key invalidation, no policy.** Every key bundles `(content, dimension, model, prompt, schema, spectra)`. A stale row never matches a current-context lookup; physical deletion is deferred to `spectra cache prune` (Phase 4 — shipped in PR #19).
- **`bind_run_context` once at composition root.** Atomic four-tuple binding (`model_versions, prompt_versions, schema_version, spectra_version`) — eliminates the half-bound state.
- **Telemetry:** `record_hit` writes to `hit_log` per lookup; `ProgressObserver.on_cache_lookup(dim, hits, total)` surfaces the per-dimension tally in the terminal. `CacheStats.hit_rate_last_100` is the rolling rate.
- **Failure mode:** SPEC-010 — cache I/O errors degrade to no-cache for the rest of the run. **Cache failures are never fatal.**

---

## 8 Agents (6 Parallel Specialists)

```
Stage 1: INGEST     → GitPort.prepare_workspace (clone HTTPS or validate local path)
Stage 2: PLAN       → MetaPrompter (Opus 4.7 effort=medium, file tree ONLY ≤5K tokens, NEVER full code)
Stage 2½: CACHE     → Phase 2 — get_full_report(RepoCacheKey); HIT short-circuits Stages 3-5
Stage 3: ANALYZE    → Phase 3 — partition_by_cache splits batches into cached + fresh
                       Run only fresh BatchPrompts in PARALLEL via asyncio.gather:
                       Architecture + Security + Quality + Documentation + Dependency + Performance
                       (all Opus 4.7, effort=xhigh)
                       put_batch_findings(BatchCacheKey) on each success
Stage 4: MERGE      → Deduplicate findings (cached UNION fresh), cross-reference, compute scores
Stage 5: CRITIQUE   → CritiqueAgent (Opus 4.7, ADAPTIVE THINKING + task_budget, validates ALL findings)
Stage 6: REPORT     → put_full_report(RepoCacheKey, report) write-back, then render HTML/JSON/SARIF
```

### Agent Hard Rules

1. MetaPrompter NEVER gets full code. File tree only, ≤5K tokens.
2. Adaptive thinking: CritiqueAgent ONLY. No other agent uses it.
3. 6 specialists ALWAYS run in parallel: `await asyncio.gather(*agents, return_exceptions=True)`
4. Every agent output validated against Pydantic model BEFORE merge.
5. `asyncio.wait_for(timeout=120)` per agent.
6. If 2+ agents fail → abort with partial report (DEGRADED state).
7. All LLM calls through decorator chain: LoggingDecorator → RetryDecorator → AnthropicAdapter

---

## Agent Teams — File Ownership

| Teammate | Owns | Does NOT Touch |
|----------|------|----------------|
| architect-1 | `src/spectra/entities/*`, `src/spectra/use_cases/interfaces.py` | Everything else |
| pipeline-1 | `src/spectra/use_cases/*.py` (except interfaces.py), `src/spectra/infrastructure/` | entities/, adapters/, templates/ |
| interface-1 | `src/spectra/adapters/*`, `templates/*`, `README.md` | entities/, use_cases/, infrastructure/ |
| qa-1 | `tests/*`, `golden_files/*` | All src/ files |
| team-lead | `CLAUDE.md`, `pyproject.toml`, `.claude-plugin/` | Implementation files |

**RULE: Only edit files in YOUR ownership.**

---

## Project Structure (summary)

```
src/spectra/
├── entities/         # Layer 1 — frozen Pydantic, no spectra imports
├── use_cases/        # Layer 2 — entities/ only; ports as Protocols
├── adapters/         # Layer 3 — CLI, progress reporter, PR comment renderer
└── infrastructure/   # Layer 4 — composition root (main.py), Anthropic, cache,
                      #            git, audit sinks, signers, agents/
templates/            # Jinja2 HTML report template
tests/                # mirrors src/ layout
golden_files/         # fixture repos for adversarial + sample tests
```

**Full file-by-file map:** [`docs/architecture/02-component-architecture.md`](docs/architecture/02-component-architecture.md). The dependency rule is enforced; deviations get rejected at review.

---

## Glossary

Single at-a-glance index for the three numbering schemes that recur
across code, prompts, audit events, and CLI messages:

- Roadmap **capability numbers** (`#1` through `#70`)
- **`SPEC-NNN`** error codes (`SPEC-001` through `SPEC-014`)
- **`ADR-NNN`** architecture decision records (`ADR-001` through `ADR-020`)

Lookup table: [`docs/glossary.md`](docs/glossary.md). Use it whenever a
code comment, finding, or audit event references a bare number.

---

## Error Codes

User-facing reference: [`docs/error-codes.md`](docs/error-codes.md) — one
section per code with when it fires, what to do, and the retry policy.

| Code | Category | Retryable | Description |
|------|----------|-----------|-------------|
| SPEC-001 | Infrastructure | Yes (2x) | Git clone failed |
| SPEC-002 | Infrastructure | Yes (3x) | Anthropic API unreachable |
| SPEC-003 | Rate Limit | Yes (3x) | Anthropic 429 rate limited |
| SPEC-004 | Budget | No | Token budget exceeded |
| SPEC-005 | Validation | Yes (1x) | Agent output failed Pydantic validation |
| SPEC-006 | Timeout | No | Agent exceeded 120s timeout |
| SPEC-007 | Pipeline | No | 2+ agents failed |
| SPEC-008 | Critique | No | CritiqueAgent failed |
| SPEC-009 | Report | No | Template render failed |
| SPEC-010 | Cache | No (degrade) | Cache I/O failed — pipeline runs without cache for the rest of the run |
| SPEC-011 | Security | No | Secret detected by pre-flight scan — bypass with `--allow-secrets` |
| SPEC-012 | Config | No | `.spectra-policy.yml` / `.spectra-waivers.yml` malformed (#17, #18) |
| SPEC-013 | Policy | No | Policy gate failed — fix violations or update `.spectra-policy.yml` (#17) |
| SPEC-014 | Cost Budget | No | `--max-cost-usd` / `--max-cost-per-hour` cap exceeded — rerun with a higher cap or split scope (#5) |

---

## ScoreCard Weights

| Dimension | Weight | Agent |
|-----------|--------|-------|
| Architecture | 25% | ArchitectureAgent |
| Security | 25% | SecurityAgent |
| Quality | 20% | QualityAgent |
| Documentation | 10% | DocumentationAgent |
| Maintainability | 10% | DependencyAgent (secondary) |
| Performance | 10% | PerformanceAgent |

Grades: A+ (95-100), A (90-94), A- (87-89), B+ (83-86), B (80-82), B- (77-79), C+ (73-76), C (70-72), C- (67-69), D+ (63-66), D (60-62), D- (57-59), F (0-56)

---

## Brand Voice (summary)

**Voice:** Clear, Confident, Sharp, Warm. **CLI:** ≤80 chars/line, no trailing period. Progress `▸`, success `✓`, error `✗ [what failed]: [why]: [what to do]`. **Colors:** violet `#7C3AED`, amber `#F59E0B`, red `#EF4444`, green `#22C55E`.

**Forbidden words** (immediate reject in PR review): revolutionary, cutting-edge, game-changing, leverage, innovative, utilize, might be, could potentially, comprehensive solution, AI-powered (say "8 AI agents" instead).

---

## Key Dependencies

Source of truth: [`pyproject.toml`](pyproject.toml). Lockfile: [`requirements.lock`](requirements.lock) (hash-pinned via `uv pip compile --generate-hashes`). Conservative upper bounds on every runtime dep (Q1 #9) — a transitive minor bump cannot silently land in a regulated SDLC.

Notable runtime deps and the capability that pulled them in:
`anthropic` (LLM), `keyring` (ADR-012 per-user HMAC secret), `pathspec` (#6 gitignore), `pysqlcipher3` (#13 cache encryption — optional, degrades to plain SQLite + WARN), `cryptography` (#57 receipts + #18 waivers), `pyyaml` (#17 policy + waivers).

---

## Skills (Plugin)

In `.claude-plugin/` — `spectra-architect`, `spectra-orchestrator`, `spectra-brand-voice`, `spectra-hackathon`. See `.claude-plugin/plugin.json` for the up-to-date list.
