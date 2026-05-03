# Architecture Decision Records — Index

Spectra captures architectural decisions as ADRs (Architecture Decision
Records) in the format described by Michael Nygard. Each ADR has a status,
context, decision, consequences, and alternatives section. Decisions are
append-only — when a decision changes, a new ADR is added that supersedes
the old one rather than editing the old one in place.

## Status legend

- **Accepted** — implemented in code; the binding architectural commitment
- **Proposed** — written and under review; intended for the next milestone
- **Deprecated** — superseded by a later ADR; retained for the historical
  record
- **Rejected** — the decision was considered and not taken; retained for
  the historical record

## ADRs

| ID | Title | Status | Theme |
|----|-------|--------|-------|
| [ADR-001](ADR-001-clean-architecture.md) | Clean Architecture (4 layers, dependency rule) | Accepted | Foundation |
| [ADR-002](ADR-002-parallel-agent-pipeline.md) | Parallel agent pipeline (`asyncio.gather`) | Accepted | Foundation |
| [ADR-003](ADR-003-extended-thinking-critique-only.md) | Extended thinking limited to CritiqueAgent | Deprecated | Quality |
| [ADR-004](ADR-004-frozen-pydantic-models.md) | Frozen Pydantic entities | Accepted | Foundation |
| [ADR-005](ADR-005-opus-4-7-migration.md) | Opus 4.7 migration | Accepted | Quality |
| [ADR-006](ADR-006-cache-port-incremental-analysis.md) | `CachePort` + per-`focus_area` SQLite cache | Accepted | Performance |
| [ADR-007](ADR-007-github-action-distribution.md) | GitHub Action distribution | Accepted | Distribution |
| [ADR-008](ADR-008-adaptive-thinking-supersedes-extended.md) | Adaptive thinking supersedes extended (supersedes ADR-003) | Accepted | Quality |
| [ADR-009](ADR-009-batch-granularity-per-focus-area.md) | Batch granularity per `focus_area` | Accepted | Performance |
| [ADR-010](ADR-010-no-self-dogfooding.md) | No self-dogfooding for grading claims | Accepted | Discipline |
| [ADR-011](ADR-011-prompt-injection-isolation.md) | Prompt-injection isolation | Accepted | Security |
| [ADR-012](ADR-012-cache-hmac-per-user-namespace.md) | Cache HMAC + per-user namespace | Accepted | Security |
| [ADR-013](ADR-013-task-budget-and-rate-coordination.md) | `task_budget` everywhere + fleet rate coordinator | Proposed | Cost / Performance |
| [ADR-014](ADR-014-anthropic-memory-stores-for-team-org.md) | Anthropic Memory Stores for team / org tier | Proposed | Memory (Q4) |
| [ADR-015](ADR-015-query-codebase-use-case.md) | `query_codebase` use case (`spectra ask`) | Proposed | Memory (Q4) |
| [ADR-016](ADR-016-managed-agents-gateway.md) | Managed Agents gateway adapter | Proposed | Anthropic-native (Q5-Q6) |
| [ADR-017](ADR-017-custom-rules-plugin-architecture.md) | Custom rules plugin architecture | Proposed | Extensibility (Q6) |
| [ADR-018](ADR-018-audit-log-and-identity.md) | Audit log + identity | Proposed | Compliance (Q2) |
| [ADR-019](ADR-019-distributed-cache-adapters.md) | Distributed cache adapters (Redis + S3) | Proposed (superseded by ADR-021 before implementation) | Performance |
| [ADR-020](ADR-020-config-file-yaml.md) | `--config-file` + portable YAML config | Proposed | Operability |
| [ADR-021](ADR-021-distributed-cache-port-and-adapter-trio.md) | Distributed cache port + adapter trio (supersedes ADR-019) | Proposed | Performance (Q3) |
| [ADR-022](ADR-022-postgres-history-store.md) | Postgres history store + `ReportStorePort` for trend / drift | Proposed | Data (Q3) |
| [ADR-023](ADR-023-opentelemetry-tracing-and-cost-attribution.md) | OpenTelemetry tracing + per-agent spans + cost attribution | Proposed | Observability (Q3) |
| [ADR-024](ADR-024-anthropic-batch-api-and-prompt-caching.md) | Anthropic Batch API + prompt caching | Proposed | Cost (Q3) |
| [ADR-025](ADR-025-memory-port-and-managed-store-adapter.md) | Memory Port + Managed Memory Store adapter (refines ADR-014 + ADR-015) | Proposed | Memory (Q4) |
| [ADR-026](ADR-026-multi-cloud-llm-gateway.md) | Multi-cloud LLM Gateway (Bedrock + Vertex sibling adapters) | Proposed | Multi-cloud (Q4) |
| [ADR-027](ADR-027-deterministic-compliance-mapping.md) | Deterministic compliance mapping (retires v0.7.0 keyword heuristic) | Proposed | Compliance (Q4) |

## ADRs grouped by quarter

- **Foundation (pre-Q1):** ADR-001, ADR-002, ADR-004, ADR-005, ADR-006,
  ADR-007, ADR-008, ADR-009, ADR-010, ADR-011, ADR-012
- **Q2 — Enterprise-ready:** ADR-018, ADR-020
- **Q3 — Platform / fleet scale:** ADR-013, ADR-021, ADR-022, ADR-023, ADR-024
- **Q4 — Memory + 2nd brain + multi-cloud + compliance:** ADR-014, ADR-015 (refined by ADR-025), ADR-025, ADR-026, ADR-027
- **Q5-Q6 — Extensibility + Anthropic-native:** ADR-016, ADR-017

## Conventions

- ADR filename: `ADR-NNN-kebab-case-title.md`
- ADRs are append-only. To change a decision, add a new ADR with status
  Proposed that says "Supersedes ADR-NNN" in its status block. The new
  ADR's References section links back to the superseded one. Do not edit
  the body of the old ADR — leave it as the historical record.
- Every ADR ends with a `## References` section listing code paths,
  related ADRs, and source findings.

---

*Last updated: 2026-04-30.*
