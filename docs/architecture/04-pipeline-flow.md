# 04 — Pipeline Flow

**Status:** Stable · **Baseline:** v0.5.0 · **Last revised:** 2026-04-30

## Purpose

Walk through the 6-stage pipeline (with Stage 1.5 pre-flight) end to end. Cover the happy path, the Phase 2 cache short-circuit, and the prompt-injection-detected branch.

## Audience

Engineers debugging a pipeline failure. Reviewers gating any change to `analyze_repository`, `orchestrate_agents`, or the composition root. Integrators reasoning about latency, cost, and exit codes.

## The 6 stages (+ Stage 1.5)

```
Stage 1   INGEST       GitPort.prepare_workspace (clone or validate local path)
Stage 1.5 PREFLIGHT    WorkspaceFilter + SecretScanner (block by default; v0.5.0)
Stage 2   PLAN         MetaPrompter (Opus 4.7 medium, FILE TREE ONLY ≤5K tokens)
Stage 2½  CACHE        Phase 2 — get_full_report(RepoCacheKey); HIT short-circuits 3-5
Stage 3   ANALYZE      Phase 3 partition_by_cache → asyncio.gather of 6 specialists
Stage 4   MERGE        Deduplicate findings, validate file paths
Stage 5   CRITIQUE     CritiqueAgent (Opus 4.7 high + adaptive thinking + task_budget=80K)
Stage 6   REPORT       put_full_report write-back, then HTML / JSON / SARIF render
```

## Happy path (cache miss)

![Pipeline happy path](./diagrams/04-pipeline-sequence.svg)

Source: [`diagrams/04-pipeline-sequence.puml`](./diagrams/04-pipeline-sequence.puml)

Walk-through against [`use_cases/analyze_repository.py`](../../src/spectra/use_cases/analyze_repository.py):

1. **INGEST** ([`main.py:_run_analysis`](../../src/spectra/infrastructure/main.py)). `GitPort.prepare_workspace` clones an HTTPS URL or validates a local path. Symlinks, missing `.git/`, and `..` traversal segments are rejected at the CLI seam ([`cli_controller._validate_local_path`](../../src/spectra/adapters/cli_controller.py)). Repo size cap enforced before stage exit.
2. **PREFLIGHT** ([`main._run_preflight_stage`](../../src/spectra/infrastructure/main.py) + [`use_cases/preflight.py`](../../src/spectra/use_cases/preflight.py)). `PathspecFilterAdapter` honours `.gitignore` (root + nested) and `.spectraignore`. The filtered tree feeds `RegexSecretScanner`; matched secrets raise `SPEC-011 SecretDetectedError` unless `--allow-secrets` is set. Filtered files are the canonical input to every downstream stage — an excluded path can never reach a prompt body or a cache key.
3. **PLAN** ([`_run_plan_stage`](../../src/spectra/use_cases/analyze_repository.py)). MetaPrompter receives only the file tree and emits a JSON plan with per-agent `focus_areas` and a `token_allocation` map. Total prompt budget capped at 5K tokens — the MetaPrompter never sees source code.
4. **CACHE check (Phase 2)** ([`_try_serve_from_cache`](../../src/spectra/use_cases/analyze_repository.py)). The factory built at composition root composes a `RepoCacheKey` from `repo_signature` + `model_versions` + `prompt_versions` + `schema_version` + `spectra_version`. A hit short-circuits to Stage 6.
5. **ANALYZE** ([`_run_analyze_stage`](../../src/spectra/use_cases/analyze_repository.py)). `_phase3_eligible(ctx)` is true when both `cache_port` and `git_port` are wired and `--force` is not set; the use case then partitions per-agent batches into cached + fresh ([`partition_by_cache`](../../src/spectra/use_cases/analyze_repository.py:624)) and runs only the fresh batches via `run_specialists_batched`. Pre-flight regex scan ([`injection_scanner.scan_files_for_injection`](../../src/spectra/use_cases/injection_scanner.py)) records flagged paths on the pipeline state for the CritiqueAgent.
6. **MERGE** ([`_run_merge_stage`](../../src/spectra/use_cases/analyze_repository.py)). O(n) deduplicate via `dict.fromkeys(...)` over `Finding.__hash__`; O(n) hallucinated-path filter against `set(file_tree)`.
7. **CRITIQUE** ([`_run_critique_pipeline`](../../src/spectra/use_cases/analyze_repository.py)). Skipped when `--quick`, when degraded, when no critique agent wired, or when token budget is exhausted. The CritiqueAgent receives `{"findings": [...], "flagged_files": [...]}`; emits `validated_findings`, `rejected_findings`, `severity_adjustments`, `cross_cutting_insights`, and (rare) `compromised_findings`. The `_extract_compromised_findings` step materialises any `compromised_findings` entry into a `Finding(rule_id="SPEC-PROMPT-INJECTION-DETECTED", confidence=1.0)`.
8. **REPORT** ([`_build_report` + `main.py`](../../src/spectra/infrastructure/main.py)). The report is written back to `full_report_cache` (skipping degraded runs — a partial report would poison the cache), then rendered via `ReportAdapter` (HTML), `build_json_payload` (JSON with disclaimer at top), or `_build_sarif` (SARIF v2.1.0 with disclaimer notification).

## Cache-hit short-circuit

![Cache hit short-circuit](./diagrams/04-pipeline-sequence-cached.svg)

Source: [`diagrams/04-pipeline-sequence-cached.puml`](./diagrams/04-pipeline-sequence-cached.puml)

When the repo signature and every version key match a previous successful run, Stages 3, 4, 5 are skipped entirely. Wall-clock drops from ~3-5 minutes to ~0.5 second. The observer surfaces the cache stage marker so users see "served from cache (use --force to re-analyze)" in the terminal.

## Prompt-injection detected

![Prompt-injection detected](./diagrams/04-pipeline-sequence-compromised.svg)

Source: [`diagrams/04-pipeline-sequence-compromised.puml`](./diagrams/04-pipeline-sequence-compromised.puml)

Three defences trigger in concert ([07 — Security Architecture](./07-security-architecture.md)):

1. The specialist prompt wraps every analyzed file in `<<<SPECTRA-DATA-{nonce}>>>` … `<<<END-SPECTRA-DATA-{nonce}>>>` markers ([`specialist_agent.build_prompt`](../../src/spectra/infrastructure/agents/specialist_agent.py)). The nonce is `secrets.token_urlsafe(16)` per call — unguessable.
2. The pre-flight regex pass ([`injection_scanner.scan_files_for_injection`](../../src/spectra/use_cases/injection_scanner.py)) records files containing `IGNORE PRIOR INSTRUCTIONS`, `<system>`, role-play tags, or fake `<<<SPECTRA-DATA-` fences. The list flows to the CritiqueAgent as structured evidence.
3. The CritiqueAgent's `<adversarial_input_check>` block ([`critique_agent._SYSTEM_PROMPT`](../../src/spectra/infrastructure/agents/critique_agent.py)) inspects `flagged_files` and any specialist finding whose text smells like attacker bytes; emits a single `compromised_findings` entry on detection.

The orchestrator transitions `PipelineState` to `compromised`. The renderer surfaces a banner; the Q2-designed public-mode emission refuses to publish a grade.

## State machine

![PipelineState transitions](./diagrams/04-pipeline-state.svg)

Source: [`diagrams/04-pipeline-state.puml`](./diagrams/04-pipeline-state.puml)

Literals from [`enums.py:52`](../../src/spectra/entities/enums.py):

```python
PipelineState = Literal[
    "pending", "ingesting", "meta_prompting", "analyzing",
    "merging", "critiquing", "reporting", "complete",
    "degraded", "failed", "compromised",
]
```

The Q2-designed `budget_exceeded` transition (ADR-013 + roadmap #5) is shown dashed-grey.

## Failure handling

| Scenario | Code | Behaviour |
|----------|------|-----------|
| Git clone failed | SPEC-001 | Retry x2 then `failed` |
| Anthropic API unreachable | SPEC-002 | RetryDecorator: backoff 1s/2s/4s + jitter, max 3 |
| Rate-limited (429) | SPEC-003 | Same retry policy; logged separately |
| Token budget exceeded | SPEC-004 | Logged WARN, pipeline continues if remaining > 0 |
| Agent output validation failed | SPEC-005 | Retry x1 then bubble |
| Agent timeout (120 s) | SPEC-006 | Per-agent `asyncio.wait_for`; bubble as exception |
| 2+ agents failed | SPEC-007 | Pipeline transitions to `degraded`; partial report; `is_degraded=True` |
| CritiqueAgent failed | SPEC-008 | Logged WARN; findings returned unmodified |
| Report render failed | SPEC-009 | Bubble as `ReportError`; non-zero exit |
| Cache I/O failed | SPEC-010 | **Never fatal.** Degrade to no-cache for the rest of the run. |
| Secret detected in workspace | SPEC-011 | Default: abort. `--allow-secrets`: WARN line per finding, continue. |

The orchestrator's [`evaluate_results`](../../src/spectra/use_cases/orchestrate_agents.py:211) is the failure-state-machine source.

## Latency budget

| Stage | Target wall-clock | Notes |
|-------|-------------------|-------|
| INGEST | ≤30 s | Repo size cap enforced; long clones surface SPEC-001 |
| PREFLIGHT | ≤200 ms target / 500 ms CI gate | Performance-regression test pinned |
| PLAN | ≤30 s | Single MetaPrompter call, file tree only |
| ANALYZE | ≤120 s per agent | Semaphore(4) caps API concurrency; 6 launched in parallel |
| MERGE | ≤1 s | O(n) dedupe + O(n) path validation |
| CRITIQUE | ≤90 s | Adaptive thinking + 80K task budget |
| REPORT | ≤2 s | Jinja2 render; SARIF JSON write |

End-to-end target: ≤5 minutes for a typical repo. Cache hits drop this to ~1 second.

## Token budget

[`TokenBudget`](../../src/spectra/entities/models.py) defaults:

```
total              800_000
meta_prompter        5_000
specialists_pool   500_000
critique_reserved  200_000
buffer              95_000
```

The MetaPrompter's `token_allocation` JSON output redistributes the specialists pool across the 6 dimensions ([`manage_token_budget.allocate_specialist_budgets`](../../src/spectra/use_cases/manage_token_budget.py)). When the pool is exhausted, the use case logs SPEC-004 WARN and proceeds with what remains.

## Output formats

| `--format` | Adapter | Disclaimer |
|------------|---------|------------|
| `html` (default) | `ReportAdapter` (Jinja2 template at `templates/report.html.j2`) | Sticky amber banner, ARIA-labelled, dismissible (sessionStorage) |
| `json` | `build_json_payload` | Top-level `disclaimer: { text, url }` field |
| `sarif` | `_build_sarif` | `runs[0].invocations[0].notifications[]` carries the disclaimer |
| `pr-comment` (subcommand) | `pr_comment_renderer.render_pr_comment` | Field allowlist: only safe fields rendered |

The disclaimer text is sourced from [`entities/disclaimer.py`](../../src/spectra/entities/disclaimer.py) — single source of truth across all four formats.

## Invariants and key decisions

- **MetaPrompter never gets full code.** File tree only, ≤5K tokens. Enforced by the prompt template.
- **6 specialists ALWAYS run in parallel.** `asyncio.gather(*tasks, return_exceptions=True)` with a `Semaphore(max_concurrency=4)` to bound API bursts.
- **Adaptive thinking is CritiqueAgent-only.** No other agent uses it (ADR-008). Q2 work generalises this per-batch (ADR-013).
- **Every agent output is Pydantic-validated BEFORE merge.** Garbage findings never reach the report.
- **Per-agent `asyncio.wait_for(timeout=120)`.** No single slow agent stalls the pipeline.
- **Degraded runs do NOT poison the cache.** `_store_in_cache` returns early when `report.is_degraded`.

## Open questions

1. The MetaPrompter `token_allocation` map is honoured but not enforced. A specialist that overruns its allocation logs SPEC-004 WARN but continues until the pool is exhausted. Q2 work (ADR-013 `task_budget` per agent) makes this a hard gate.
2. The `_phase3_eligible` check requires both `cache_port` and `git_port`. A test stub that omits `git_port` falls back to one batch per dimension. Documented behaviour, but the fallback path is rarely exercised — flag for an integration test.
