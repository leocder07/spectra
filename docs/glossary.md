# Glossary — capabilities, error codes, ADRs

**Author:** Vivek Kumar, Head of Engineering · **Last revised:** 2026-04-30
**Baseline:** v0.6.0

A single at-a-glance index for the three numbering schemes that recur across
the codebase, prompts, audit events, and CLI messages: roadmap **capability
numbers** (`#N`), **`SPEC-NNN`** error codes, and **`ADR-NNN`** architecture
decision records. Code comments and docstrings reference these by number; this
glossary is the lookup.

- **Roadmap capability numbers** — `#1` through `#70`. Authored by Head of
  Product in [`docs/strategy/product-roadmap.md`](./strategy/product-roadmap.md).
- **`SPEC-NNN` error codes** — `SPEC-001` through `SPEC-014`. Authored by
  the entities layer in [`src/spectra/entities/errors.py`](../src/spectra/entities/errors.py),
  fully documented in [`docs/error-codes.md`](./error-codes.md).
- **`ADR-NNN` architecture decisions** — `ADR-001` through `ADR-020`. All
  20 ADRs live in [`docs/architecture/adr/`](./architecture/adr/); the
  index is [`docs/architecture/INDEX.md`](./architecture/README.md). (Q1/Q2
  ADRs 011-020 were consolidated from `docs/strategy/architecture/` into
  `docs/architecture/adr/` on 2026-04-30 — there is now one canonical home
  for every ADR.)

---

## SPEC-NNN — error codes

Every fallible operation raises a `SpectraError` subclass carrying one of
these stable codes. CI logs, brand-voice CLI messages, audit events, and
SARIF notifications all speak this language. Full descriptions —
including when each fires, what to do, and the retry policy — are in
[`docs/error-codes.md`](./error-codes.md).

| Code | Category | Retryable | One-line description |
|------|----------|-----------|----------------------|
| [SPEC-001](./error-codes.md#spec-001) | Infrastructure | Yes (2x) | Git clone failed |
| [SPEC-002](./error-codes.md#spec-002) | Infrastructure | Yes (3x) | Anthropic API unreachable |
| [SPEC-003](./error-codes.md#spec-003) | Rate limit | Yes (3x) | Anthropic 429 rate limited |
| [SPEC-004](./error-codes.md#spec-004) | Budget | No | Token budget exceeded |
| [SPEC-005](./error-codes.md#spec-005) | Validation | Yes (1x) | Agent output failed Pydantic validation |
| [SPEC-006](./error-codes.md#spec-006) | Timeout | No | Agent exceeded 120s timeout |
| [SPEC-007](./error-codes.md#spec-007) | Pipeline | No | 2+ agents failed — aborted with partial report |
| [SPEC-008](./error-codes.md#spec-008) | Critique | No | CritiqueAgent failed |
| [SPEC-009](./error-codes.md#spec-009) | Report | No | Template render failed |
| [SPEC-010](./error-codes.md#spec-010) | Cache | No (degrade) | Cache I/O failed — pipeline runs without cache |
| [SPEC-011](./error-codes.md#spec-011) | Security | No | Secret detected by pre-flight scan |
| [SPEC-012](./error-codes.md#spec-012) | Config | No | `.spectra-policy.yml` / `.spectra-waivers.yml` malformed |
| [SPEC-013](./error-codes.md#spec-013) | Policy | No | Policy gate failed — fix violations or update policy |
| [SPEC-014](./error-codes.md#spec-014) | Cost budget | No | `--max-cost-usd` / `--max-cost-per-hour` cap exceeded |

---

## ADR-NNN — architecture decision records

All 20 ADRs live in [`docs/architecture/adr/`](./architecture/adr/). The
[architecture index](./architecture/README.md) is the entry point — it
maps every shipped capability to its source ADR.

| ID | Title | Status |
|----|-------|--------|
| [ADR-001](./architecture/adr/ADR-001-clean-architecture.md) | Clean Architecture (4 layers, dependency rule absolute) | Stable |
| [ADR-002](./architecture/adr/ADR-002-parallel-agent-pipeline.md) | Parallel agent pipeline via `asyncio.gather` | Stable |
| [ADR-003](./architecture/adr/ADR-003-extended-thinking-critique-only.md) | Extended thinking — CritiqueAgent only (superseded by ADR-008) | Superseded |
| [ADR-004](./architecture/adr/ADR-004-frozen-pydantic-models.md) | Frozen Pydantic models for every entity | Stable |
| [ADR-005](./architecture/adr/ADR-005-opus-4-7-migration.md) | Opus 4.7 migration | Stable |
| [ADR-006](./architecture/adr/ADR-006-cache-port-incremental-analysis.md) | `CachePort` for incremental analysis | Stable |
| [ADR-007](./architecture/adr/ADR-007-github-action-distribution.md) | GitHub Action distribution channel | Stable |
| [ADR-008](./architecture/adr/ADR-008-adaptive-thinking-supersedes-extended.md) | Adaptive thinking supersedes extended (CritiqueAgent) | Stable |
| [ADR-009](./architecture/adr/ADR-009-batch-granularity-per-focus-area.md) | Batch granularity per `focus_area` (Phase 3 cache) | Stable |
| [ADR-010](./architecture/adr/ADR-010-no-self-dogfooding.md) | No self-dogfooding inside the analyzer | Stable |
| [ADR-011](./architecture/adr/ADR-011-prompt-injection-isolation.md) | Prompt-injection isolation (per-call nonces + adversarial check) | Shipped v0.5.0 |
| [ADR-012](./architecture/adr/ADR-012-cache-hmac-per-user-namespace.md) | Cache HMAC + per-user namespace + silent re-key | Shipped v0.5.0 |
| [ADR-013](./architecture/adr/ADR-013-task-budget-and-rate-coordination.md) | Per-agent `task_budget` + cost tracker + rate coordinator | Shipped v0.6.0 (cost), Q3 (rate) |
| [ADR-014](./architecture/adr/ADR-014-anthropic-memory-stores-for-team-org.md) | Anthropic Memory Stores for team / org tier | Q4 designed |
| [ADR-015](./architecture/adr/ADR-015-query-codebase-use-case.md) | `query_codebase` use case (`spectra ask` / `spectra brief`) | Q4 designed |
| [ADR-016](./architecture/adr/ADR-016-managed-agents-gateway.md) | Managed Agents gateway adapter | Q5-Q6 designed |
| [ADR-017](./architecture/adr/ADR-017-custom-rules-plugin-architecture.md) | Custom rules + plugin architecture (Skills, Specialists) | Q6 designed |
| [ADR-018](./architecture/adr/ADR-018-audit-log-and-identity.md) | Audit log + identity (`AuditPort` + JSON Lines / OTLP) | Shipped v0.6.0 |
| [ADR-019](./architecture/adr/ADR-019-distributed-cache-adapters.md) | Distributed cache adapters (Redis, S3, Tiered) | Q3 designed |
| [ADR-020](./architecture/adr/ADR-020-config-file-yaml.md) | `.spectra.yml` config substrate (per-port sections) | Shipped v0.6.0 (waivers/policy) |

The strategy-side index at
[`docs/strategy/architecture/INDEX.md`](./strategy/architecture/INDEX.md)
keeps the narrative composition view (how ADRs 011-020 compose, quarterly
release sequencing, architectural open questions for the founder).

---

## Roadmap capability numbers (`#N`)

Roadmap capabilities `#1` through `#70` are authored in
[`docs/strategy/product-roadmap.md`](./strategy/product-roadmap.md). Code
comments use bare `#N` to reference the row; this table is the lookup.
"Shipped" rows reference the corresponding release; "Designed" rows
reference the source ADR.

### Q1 — security baseline (shipped in v0.5.0)

| `#` | Capability | Status |
|-----|-----------|--------|
| `#1` | Prompt-injection isolation (per-file delimiter nonces + critique adversarial prompt) | Shipped v0.5.0 — [ADR-011](./architecture/adr/ADR-011-prompt-injection-isolation.md) |
| `#2` | Adversarial eval harness + published catch-rate | Shipped v0.5.0 — 100% (20/20) — [ADR-011 §4](./architecture/adr/ADR-011-prompt-injection-isolation.md) |
| `#3` | Per-row HMAC + per-user cache namespace | Shipped v0.5.0 — [ADR-012](./architecture/adr/ADR-012-cache-hmac-per-user-namespace.md) |
| `#4` | Markdown-safe PR comment renderer + finding-field allowlist | Shipped v0.5.0 — `pr_comment_renderer.py` |
| `#6` | Honor `.gitignore` + secret pre-flight scan + `.spectraignore` | Shipped v0.5.0 — `regex_secret_scanner.py`, `pathspec_filter_adapter.py` |
| `#7` | SLSA L3 build provenance + Sigstore-signed wheels | Shipped v0.5.0 |
| `#8` | SECURITY.md + vulnerability disclosure policy + CNA | Shipped v0.5.0 |
| `#9` | Dependency upper bounds + shipped lockfile + Renovate | Shipped v0.5.0 |
| `#10` | Defensive PyPI squats | Shipped v0.5.0 |
| `#61` | "Indicative — not audit evidence" disclaimer banner | Shipped v0.5.0 |

### Q2 — audit + policy + receipts (shipped in v0.6.0)

| `#` | Capability | Status |
|-----|-----------|--------|
| `#5` | `--max-cost-usd` per-run + per-hour budget enforcement | Shipped v0.6.0 — SPEC-014 — [ADR-013](./architecture/adr/ADR-013-task-budget-and-rate-coordination.md) |
| `#11` | DPA + sub-processor declaration + Anthropic data flow diagram | Shipped v0.6.0 — `docs/legal/` |
| `#12` | Audit log (JSON Lines, append-only, pluggable sink) | Shipped v0.6.0 — [ADR-018](./architecture/adr/ADR-018-audit-log-and-identity.md) |
| `#13` | Encrypted cache at rest (SQLCipher) + `spectra cache shred` | Shipped v0.6.0 — `cache_adapter.py` |
| `#17` | `.spectra-policy.yml` (org + repo level) + severity gating | Shipped v0.6.0 — SPEC-013 — `yaml_policy_adapter.py` |
| `#18` | `.spectra-waivers.yml` + cryptographic approver signature + 180-day TTL | Shipped v0.6.0 — `yaml_waiver_adapter.py` |
| `#19` | Severity-gate Action input (`with: fail-on: critical`) | Shipped v0.6.0 — `--fail-on` CLI flag |
| `#20` | "Non-validated" stamp on `--quick` and `--no-critique` runs | Shipped v0.6.0 — `validation_status` field |
| `#56` | Report classification + watermark + dual-mode render | Shipped v0.6.0 — `--classification confidential\|public` |
| `#57` | Globally unique scan ID + Ed25519-signed scan receipt + `spectra verify` | Shipped v0.6.0 — `receipt_signer.py` |
| `#68` | Inline suppression pragma (`# spectra: ignore-next-line`) | Shipped v0.6.0 — see `#18` |

### Q3+ — designed but not shipped

| `#` | Capability | Status |
|-----|-----------|--------|
| `#14` | Region pinning + Bedrock + Vertex AI backends via `LLMGateway` | Q4 designed |
| `#15` | ZDR mode flag + visible pre-run banner | Designed |
| `#16` | BYO-LLM proxy via `SPECTRA_LLM_BASE_URL` | Designed |
| `#21` | Distributed cache adapter (S3, Redis) | Q3 designed — [ADR-019](./architecture/adr/ADR-019-distributed-cache-adapters.md) |
| `#22` | Fleet-wide rate limiter (Redis token bucket) | Q3 designed — [ADR-013](./architecture/adr/ADR-013-task-budget-and-rate-coordination.md) |
| `#23` | Anthropic Batch API + prompt caching | Q3 designed |
| `#24` | Worker pool / job queue (Temporal) | Q3+ designed |
| `#25` | Postgres history store (`reports` table) | Designed |
| `#26` | Repo registry + scheduler (`spectra portfolio`) | Designed |
| `#27` | Trend / drift detection + Slack drift alerts | Designed |
| `#28` | Org leaderboard endpoint (HTML + JSON) | Designed |
| `#29` | RBAC + multi-tenancy | Deferred |
| `#30` | OpenTelemetry tracing + per-agent spans | Designed |
| `#31` | Prometheus metrics endpoint | Designed |
| `#32` | SLO dashboards + error budgets | Designed |
| `#33` | Cost attribution per team / repo (tagged spans) | Designed |
| `#34` | Slack / Teams digest + per-finding alert | Designed |
| `#35` | Jira / Linear ticket auto-create | Designed |
| `#36` | GitLab MR + Bitbucket PR comment integrations | Designed |
| `#37` | LSP server + SARIF polish (VSCode/Cursor/JetBrains) | Designed |
| `#38` | Webhooks (`spectra.scan.completed`, etc.) | Designed |
| `#39` | Specialist plugin system (entry-point discovery) | Q6 designed — [ADR-017](./architecture/adr/ADR-017-custom-rules-plugin-architecture.md) |
| `#40` | Versioned rule packs (YAML overlay) | Q6 designed — [ADR-017](./architecture/adr/ADR-017-custom-rules-plugin-architecture.md) |
| `#41` | Web3 specialist plugin (Solidity, SWC) | Q6 designed |
| `#42` | IaC specialist plugin (Terraform / K8s / Helm / Dockerfile) | Q6 designed |
| `#43` | ML security specialist plugin (pickle, torch.load, RAG injection) | Q6 designed |
| `#44` | CI/CD pipeline specialist plugin | Q6 designed |
| `#45` | Crypto / SSTI / XXE / Zip Slip / SSRF prompt enrichments | Designed |
| `#46` | Authn/authz logic prompt enrichment (BOLA, IDOR, JWT none) | Designed |
| `#47` | Supply-chain prompt enrichment (typosquats, dep confusion) | Designed |
| `#48` | Privacy / telemetry prompt enrichment (consent, PII in logs) | Designed |
| `#49` | Prototype pollution / unsafe caching enrichments | Designed |
| `#50` | Per-repo memory: waivers + score timeline + decision log + ADR ingest | Q4 designed — [ADR-014](./architecture/adr/ADR-014-anthropic-memory-stores-for-team-org.md) |
| `#51` | `spectra ask <question>` codebase Q&A | Q4 designed — [ADR-015](./architecture/adr/ADR-015-query-codebase-use-case.md) |
| `#52` | `spectra brief` onboarding mode | Q4 designed — [ADR-015](./architecture/adr/ADR-015-query-codebase-use-case.md) |
| `#53` | Cross-repo pattern surfacing (per-org Memory Store) | Q4 designed — [ADR-014](./architecture/adr/ADR-014-anthropic-memory-stores-for-team-org.md) |
| `#54` | Per-developer reviewer profile + finding routing | Deferred |
| `#55` | Public knowledge skill (CVE feed, framework deprecations) | Designed |
| `#58` | SBOM-of-analysed-repo (CycloneDX 1.5) | Designed |
| `#59` | SBOM-of-Spectra (CycloneDX + SPDX) attached to release | Designed |
| `#60` | Deterministic compliance mapping (CWE/CVE → control) | Deferred |
| `#62` | HIPAA mode + BAA template (`--hipaa`) | Designed |
| `#63` | SOC 2 Type II for Spectra service | Deferred |
| `#64` | Auditor evidence pack (`spectra evidence --framework soc2`) | Deferred |
| `#65` | OS-keychain / Vault / AWS SM secret backend abstraction | Designed |
| `#66` | Maintainer security baseline (hardware-key 2FA, signed commits) | Designed |
| `#67` | Pin Action to commit SHA + `tags-ignore` filter | Designed |
| `#69` | Findings ownership + SLA fields + Jira sync | Deferred |
| `#70` | Per-team scan budget enforcement | Deferred |

---

## Conventions

- Code comments and docstrings reference these by bare number (`#17`,
  `SPEC-014`, `ADR-018 §3`). Use the tables above to navigate.
- ADR filenames are zero-padded to three digits (`ADR-011`, not `ADR-11`)
  to keep filesystem ordering stable past `ADR-099`.
- When a capability ships, flip its row from "designed" to "Shipped vX.Y.Z"
  here and in [`docs/architecture/README.md`](./architecture/README.md).
  Stale glossary rows are a defect.
