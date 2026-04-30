# Strategy Architecture — INDEX

**Author:** Chief Architect · 2026-04-29 · **Last revised:** 2026-04-30 (ADRs consolidated under `docs/architecture/adr/`)
**Scope:** Architectural commitments for the Q1-Q4 capabilities synthesised by the Head of Product in [`product-roadmap.md`](../product-roadmap.md). Builds on the original 10 ADRs at [`docs/architecture/adr/`](../../architecture/adr/) — ADRs 011-020 below now live in the same canonical directory.

These ADRs translate the four persona reports (Red Team, CISO, CTO, Memory) into architectural calls. They are written to be reviewable individually and to compose into the steady-state architecture described in [`agentic-architecture.md`](agentic-architecture.md). Every link below points to the consolidated `docs/architecture/adr/` location — see [`docs/glossary.md`](../../glossary.md) for the at-a-glance ADR index.

---

## Summary table

| ADR | Title | Decision (one line) | Quarter | Effort | Primary persona |
|-----|-------|---------------------|---------|--------|-----------------|
| **011** | [Prompt-injection isolation](../../architecture/adr/ADR-011-prompt-injection-isolation.md) | Per-file delimiter nonces + CritiqueAgent adversarial check + adversarial eval harness as the regression gate | Q1 | M | Red Team |
| **012** | [Cache HMAC + per-user namespace](../../architecture/adr/ADR-012-cache-hmac-per-user-namespace.md) | Per-user `$UID` cache directory + per-row HMAC against an OS-keyring secret + silent re-key migration | Q1 | S | Red Team + CISO |
| **013** | [Task budget + fleet rate coordination](../../architecture/adr/ADR-013-task-budget-and-rate-coordination.md) | `task_budget` on every agent role + per-run/per-window cost tracker + Redis-backed `RateCoordinatorPort` (in-process default, Redis for fleets) | Q1-Q3 | M | Red Team + CTO |
| **014** | [Anthropic Memory Stores for team/org tier](../../architecture/adr/ADR-014-anthropic-memory-stores-for-team-org.md) | One `MemoryPort` Protocol; three adapters (`LocalFileMemoryAdapter`, `DeveloperMemoryAdapter` against Memory Tool, `ManagedAgentMemoryAdapter` against Memory Stores); composite routes by scope | Q4 | L | Memory |
| **015** | [`query_codebase` use case](../../architecture/adr/ADR-015-query-codebase-use-case.md) | New Layer-2 use case + `spectra ask` / `spectra brief` CLI; prompt-cached preamble drives $0.05/cached-call; streaming Markdown answers with citations; per-Q&A audit event | Q4 | M | Memory |
| **016** | [Managed Agents gateway adapter](../../architecture/adr/ADR-016-managed-agents-gateway.md) | Sibling `ManagedAgentGateway` Protocol; `AnthropicManagedAgentAdapter` ships in Q5; A/B then cut-over in Q6; legacy `LLMGateway` stays for Bedrock/Vertex parity | Q5-Q6 | XL | CTO |
| **017** | [Custom rules + plugin architecture](../../architecture/adr/ADR-017-custom-rules-plugin-architecture.md) | `Specialist` Protocol + entry-point discovery (`spectra.specialists`) + Sigstore-signed plugins + YAML rule packs that overlay prompts/weights/thresholds + Skills for per-language knowledge | Q6 | M-L | CTO + Red Team |
| **018** | [Audit log + identity](../../architecture/adr/ADR-018-audit-log-and-identity.md) | `AuditPort` Protocol + JSON-Lines / OTLP / CloudWatch adapters; identity from env > git > OIDC > hostname; every state transition emits a structured event; payload privacy enforced at the adapter | Q2 | M | CISO |
| **019** | [Distributed cache adapters](../../architecture/adr/ADR-019-distributed-cache-adapters.md) | `RedisCacheAdapter` + `S3CacheAdapter` + `TieredCacheAdapter` (SQLite L1, Redis/S3 L2); Redis recommended for teams; single-flight to kill stampedes; HMAC contract extends to L2 | Q3 | M | CTO |
| **020** | [`--config-file` YAML](../../architecture/adr/ADR-020-config-file-yaml.md) | `.spectra.yml` with sections per port (`cache`, `audit`, `memory`, `cost`, `rate`, `plugins`, ...); precedence CLI > env > project > user > default; same Pydantic validator | Q2 | S-M | CTO + power users |

---

## Vision document

| Document | Purpose |
|----------|---------|
| [agentic-architecture.md](agentic-architecture.md) | The bigger picture in one place: what changes about the agent loop with Opus 4.7 capabilities; how the 6 specialists become Managed Agents with per-agent Memory Stores; MCP servers as analyzers; the 18-month steady-state C4 view. |

---

## Anthropic-native primitives map

For the canonical list of Anthropic primitives this batch adopts and where each lands, see [`agentic-architecture.md` §8](agentic-architecture.md). At-a-glance:

| Primitive | Adopted by ADR |
|-----------|----------------|
| Adaptive thinking + `task_budget` | ADR-013 (extends ADR-008 to all agents) |
| Prompt caching | ADR-015 (`query_codebase` preamble) |
| Files API | ADR-014, ADR-015 (ADR ingest, large file refs) |
| Memory Tool | ADR-014 (per-developer adapter) |
| Memory Stores | ADR-014 (per-team / per-org adapter) |
| Managed Agents | ADR-016 (sibling gateway) |
| Skills | ADR-017 (plugin packaging) |
| MCP tool wiring | ADR-016 + agentic-architecture §4 |
| Vision (high-res) | agentic-architecture §1.3 (CritiqueAgent) |
| Code execution sandbox | agentic-architecture §1.5 (CritiqueAgent, opt-in) |

---

## Backward compatibility checklist

Every new capability touches an existing port or adds a sibling. None breaks an existing contract.

| New work | Existing port touched | Breaking? | Migration |
|----------|----------------------|-----------|-----------|
| ADR-011 nonces | none — adds field to `BatchPrompt` | No | Tests adjust; nonce excluded from cache key |
| ADR-012 HMAC + per-user path | extends `SqliteCacheAdapter` row schema | No | Silent re-key on first run after upgrade |
| ADR-013 `task_budget` | extends `AnthropicAdapter.analyze` signature | No (default `None`) | Per-role defaults set in `AgentFactory` |
| ADR-013 cost tracker | new `CostTrackerPort` + new SQLite table | No | Composition root opt-in; defaults preserve behaviour |
| ADR-013 rate coordinator | replaces in-process semaphore | No | `InProcessRateCoordinator` is the default |
| ADR-014 `MemoryPort` | additive | No | All-new code path; existing pipelines unaffected |
| ADR-015 `query_codebase` | additive use case | No | New CLI subcommand; `analyze` unchanged |
| ADR-016 `ManagedAgentGateway` | additive sibling Protocol | No | `LLMGateway` path stays as default until Q6 |
| ADR-017 plugin registry | refactors built-in `SPECIALIST_CONFIGS` | No (default plugins = built-ins) | `BUILTIN_SPECIALISTS` registers same 6 as today |
| ADR-018 `AuditPort` | additive | No | `JsonlAuditAdapter` is the default; no opt-in needed |
| ADR-019 distributed cache | extends `CachePort` use; `SqliteCacheAdapter` unchanged | No | Tiered mode opt-in via config |
| ADR-020 YAML config | extends `AgentRunConfig` | No | Empty file = same as today |

---

## How the ADRs compose

```
                        ┌───────────────────────────────────────────────┐
                        │  ADR-020 .spectra.yml — config substrate       │
                        └────────────────┬───────────────────────────────┘
                                         │ provides config to every port
                                         ▼
              ┌────────────┬─────────────┬──────────────┬─────────────┐
              │            │             │              │             │
   ADR-011 (prompt-       ADR-013       ADR-014        ADR-018      ADR-019
   injection isolation)   (cost +       (MemoryPort)   (AuditPort)  (distributed
              │           rate)           │              │           cache)
              │            │              │              │             │
              └─►          │              ├─►            │             │
            CritiqueAgent  │            ADR-015          │             │
            adversarial    │            (query_codebase) │             │
            check          │              │              │             │
                           │              │              │             │
                           └──────────────┼──────────────┘             │
                                          │                            │
                                          ▼                            │
                                 ADR-016 (Managed Agents)              │
                                 specialists become managed            │
                                 sessions; uses MemoryPort per-agent;  │
                                 inherits ratelimit + cost guards      │
                                          │                            │
                                          ▼                            │
                                 ADR-017 (plugin architecture)         │
                                 Specialist Protocol + Skills         │
                                 packaged via .claude-plugin/         │
                                          │                            │
                                          └────────────┬───────────────┘
                                                       ▼
                                          ADR-012 (cache HMAC)
                                          MAC contract extends
                                          to every cache layer
```

---

## Release sequencing — when each ADR ships

| Quarter | ADRs landing |
|---------|--------------|
| **Q1** | ADR-011 (prompt-injection), ADR-012 (cache HMAC), ADR-013 partial (`task_budget` + per-run cost) |
| **Q2** | ADR-018 (audit log), ADR-020 (YAML config), ADR-013 finish (per-window cost) |
| **Q3** | ADR-019 (distributed cache), ADR-013 finish (Redis rate coordinator) |
| **Q4** | ADR-014 (Memory Stores), ADR-015 (`query_codebase`), region pinning + Bedrock/Vertex `LLMGateway` adapters (covered in [product-roadmap.md #14](../product-roadmap.md)) |
| **Q5** | ADR-016 (Managed Agents) — proof on one specialist, A/B leaderboard |
| **Q6** | ADR-016 finish (cut-over), ADR-017 (plugin system + 4 vertical specialists) |

---

## Open architectural questions for the founder

These five mirror [product-roadmap.md §7](../product-roadmap.md) but framed as architecture asks:

1. **Should `spectra serve` (HTTP/MCP server mode) ship in Q5 alongside ADR-016?** [ADR-015](../../architecture/adr/ADR-015-query-codebase-use-case.md) deferred this; [agentic-architecture.md §5.2](agentic-architecture.md) keeps it out of steady-state. Greenlight unlocks Slack-bot / hosted-Q&A; rejection keeps the CLI-only commitment.
2. **Per-org Memory Store as a paid SKU from day one, or freemium for ≤3 repos?** ADR-014 assumed paid; product Conflict 5 backs that. Confirm before [ADR-014](../../architecture/adr/ADR-014-anthropic-memory-stores-for-team-org.md) ships.
3. **A 7th ScoreCard dimension — when?** ADR-017 keeps the dimension count fixed at 6. A Web3-shop buyer asking for "DeFi" as a top-level dimension forces an entity-layer change. Decide threshold ($X ARR or N customer asks) for unblocking.
4. **Plugin trust model — Sigstore + Spectra trust root, or community-signed?** ADR-017 commits to Sigstore + Spectra-rooted; if the founder wants community-signed for ecosystem velocity, the trust model changes.
5. **Bedrock / Vertex priority.** ADR-016 + ADR-014 commit to fallback paths. Whether to prioritise Bedrock-equivalent of Memory Stores when AWS ships one is a customer-driven call.

---

*All ADR links above point to the canonical [`docs/architecture/adr/`](../../architecture/adr/) directory (consolidated 2026-04-30). The glossary at [`docs/glossary.md`](../../glossary.md) is the at-a-glance index.*

*Last updated: 2026-04-30.*
