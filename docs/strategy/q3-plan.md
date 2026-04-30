# Spectra — Q3 Plan: Operate at Fleet Scale

**Author:** Head of Engineering · 2026-04-30
**Inputs:** [`product-roadmap.md`](product-roadmap.md) §4 (Q3 scope), v0.5.0
+ v0.6.0 + post-R3 fix history, [ADR-021](../architecture/adr/ADR-021-distributed-cache-port-and-adapter-trio.md)
through [ADR-024](../architecture/adr/ADR-024-anthropic-batch-api-and-prompt-caching.md)
**Constraint:** Clean Architecture (4 layers, dependency rule absolute) and
the 8-agent contract are not on the table. Everything below is additive.

---

## TL;DR

Q3 ships nine capabilities under one theme: **operate at fleet scale**. Q1
made the grade trustworthy (prompt-injection isolation, cache HMAC, secret
pre-flight, signed wheels). Q2 made Spectra enterprise-ready (audit log,
signed receipts, encrypted cache, budget enforcement, policy/waivers, dual-
mode classification). Q3 makes Spectra operable when the workload is "every
service in a 312-repo portfolio scans every week." Distributed cache,
Postgres history, OpenTelemetry, Batch API, drift alerts, cost attribution.

**The nine capabilities, one paragraph each:**

- **#21 Distributed cache** — `RemoteCachePort` + Redis/S3 adapters + tiered
  L1+L2 composition. 50-engineer org cache hit rate climbs from ~30%
  (per-laptop) to ~85% (shared). [ADR-021](../architecture/adr/ADR-021-distributed-cache-port-and-adapter-trio.md).
- **#22 Fleet rate limiter** — Redis token-bucket coordinator on the
  `RateCoordinatorPort` that already exists ([ADR-013](../architecture/adr/ADR-013-task-budget-and-rate-coordination.md))
  but ships in-process today. 50 CI runners share one Anthropic Tier-N RPM
  envelope without the loudest team starving the rest.
- **#23 Anthropic Batch API + prompt caching** — `LLMGateway` extension
  for `cache_breakpoint()` and `submit_batch()`. Stacks ~75% cost reduction
  on portfolio workloads. [ADR-024](../architecture/adr/ADR-024-anthropic-batch-api-and-prompt-caching.md).
- **#25 Postgres history store** — new `ReportStorePort` + Postgres adapter
  + raw SQL migrations. The data foundation for trend, drift, leaderboard,
  and Slack alerts. [ADR-022](../architecture/adr/ADR-022-postgres-history-store.md).
- **#26 Repo registry + scheduler** — `spectra portfolio add|scan|status`
  CLI commands. Routes through Batch API (#23) for overnight scans. Reads
  from history store (#25). No daemon — ships as a CLI subcommand the
  customer schedules with cron / GitHub Actions.
- **#27 Trend / drift detection + Slack alerts** — `DetectDrift` use case
  + Slack webhook adapter. Pings when `service-payments` drops B+ → C+
  week-over-week. Reads exclusively from #25.
- **#30 OpenTelemetry tracing** — `TracerPort` + OTel adapter + `noop`
  fallback. Per-stage and per-agent spans. OTLP exporter; customers route
  through their OTel collector. [ADR-023](../architecture/adr/ADR-023-opentelemetry-tracing-and-cost-attribution.md).
- **#33 Cost attribution per team / repo** — falls out of #30 as span
  attributes (`spectra.team`, `spectra.repo`, `llm.cost.usd`). CFO query
  is one PromQL filter.
- **#34 Slack / Teams digest + per-finding alert** — outbound webhook
  adapter. Weekly digest reads from #25; per-finding ping fires from
  `analyze_repository`'s post-Stage-6 hook.

**Total estimated effort:** 7-9 weeks of focused single-engineer work
(43-57 days). Realistic team-of-two-engineers wall-clock: **4 weeks** with
parallelism on the data and observability tracks. Headline-grade decisions:

- **Postgres adopted as a standard backend; SQLite stays as the single-
  user fallback.** Both implement `ReportStorePort`. Customers without a
  Postgres get full functionality at one-machine scale.
- **S3 stays first-class but is *not* the recommended team default.**
  Redis wins on latency for the dev-loop workload; S3 wins for read-mostly
  portfolio + zero-infra AWS shops.
- **Native OTel + OTLP exporter; no proprietary backend adapters.**
  Customers route through an OTel Collector — same pattern as the audit
  log in [ADR-018](../architecture/adr/ADR-018-audit-log-and-identity.md).
- **The portfolio scheduler is a CLI subcommand, not a daemon.** Customers
  cron / Action it. Avoids the "Spectra is a service" architectural commit.
- **Slack/Teams ships as outbound webhook only.** No hosted Slack app, no
  app-store listing. Customers register their own webhook URL.

---

## Theme

**Q3 is "operate at fleet scale."** Every Q3 capability ties back to one
question: when 50 engineers in a 312-service organisation use Spectra
weekly, how does it stay fast, cheap, observable, and informative?

Q1 ("make the grade trustworthy") made Spectra safe. Q2 ("enterprise-
ready") made Spectra signable. Q3 makes Spectra **operable**. Operability
has four shapes here:

- **Shared work.** Distributed cache (#21) means the team does each piece
  of work once. Fleet rate limiter (#22) means the team shares one
  Anthropic envelope cooperatively.
- **Compressed cost.** Batch API + prompt caching (#23) reshapes the per-
  scan unit economics so a portfolio scan is a normal-business expense,
  not a one-off project.
- **Visible operations.** OTel (#30) + cost attribution (#33) give the
  platform team and the CFO their dashboards without Spectra owning a
  control plane.
- **Operational signal.** History (#25) + scheduler (#26) + drift
  detection (#27) + alerting (#34) close the loop: Spectra runs every
  week, knows when grades are slipping, and tells the right person.

The capabilities chain together. Drift detection needs history. The
scheduler needs Batch API to be cost-affordable. Cost attribution needs
OTel to carry the spans. Slack alerts need history to know what counts as
a regression. The dependency graph is intentional — by the end of Q3, the
nine capabilities are one operating model, not nine features.

---

## Per-capability spec

### #21 — Distributed cache (`RemoteCachePort` + adapter trio)

- **User story:** As a 50-engineer organisation, I want the cache shared
  across machines so my team does not redo each other's analysis on every
  PR.
- **Architectural shape:** New `RemoteCachePort` Protocol in Layer 2,
  sibling to the existing `CachePort` ([ADR-006](../architecture/adr/ADR-006-cache-port-incremental-analysis.md)).
  Three Layer-4 adapters: `RedisRemoteCacheAdapter`, `S3RemoteCacheAdapter`,
  and `TieredCacheAdapter` (composes `SqliteCacheAdapter` as L1 with a
  `RemoteCachePort` as L2). The composition root selects the trio from
  `.spectra.yml`. Composite-key invariant from
  [ADR-006](../architecture/adr/ADR-006-cache-port-incremental-analysis.md)
  and per-row HMAC from [ADR-012](../architecture/adr/ADR-012-cache-hmac-per-user-namespace.md)
  carry through unchanged.
- **Dependencies:** [ADR-006](../architecture/adr/ADR-006-cache-port-incremental-analysis.md)
  (`CachePort`), [ADR-012](../architecture/adr/ADR-012-cache-hmac-per-user-namespace.md)
  (HMAC), [ADR-020](../architecture/adr/ADR-020-config-file-yaml.md)
  (`.spectra.yml`).
- **External infra:** Redis (recommended team default) **or** S3 bucket
  (zero-infra AWS shops).
- **Effort:** **L** (8-12 days). See [ADR-021](../architecture/adr/ADR-021-distributed-cache-port-and-adapter-trio.md).
- **Risks + mitigations:** L2 staleness on schema/version skew across
  writers — mitigated by composite-key invariant (different versions
  produce different keys; no two writers can write the same key for
  divergent context). L2 outage degrading scans — mitigated by circuit
  breaker + L1 fallback (2x2 failure matrix in
  [ADR-021](../architecture/adr/ADR-021-distributed-cache-port-and-adapter-trio.md)).
- **Acceptance criteria:** Demo: 5 simulated CI runners scan a monorepo
  concurrently. First runner cold-fills L2 over Redis. Subsequent runners
  hit L2 directly with ~85% hit rate. Cache stampede load test: 50
  concurrent runners, 1 LLM call (single-flight verified). Failure
  injection: kill Redis mid-run; pipeline continues with WARN banner; one
  audit event.
- **ADR:** [ADR-021](../architecture/adr/ADR-021-distributed-cache-port-and-adapter-trio.md).

### #22 — Fleet-wide rate limiter (Redis token bucket)

- **User story:** As an Anthropic Tier-N key holder, I want fleet-wide
  RPM enforcement so the loudest CI runner does not starve the rest of
  the organisation.
- **Architectural shape:** `RateCoordinatorPort` already exists
  ([ADR-013](../architecture/adr/ADR-013-task-budget-and-rate-coordination.md))
  but ships only with `InProcessRateCoordinator`. Q3 adds
  `RedisRateCoordinator` (token-bucket Lua script against
  `spectra:rpm:{api_key_id}:{model}:{minute_bucket}`). Reuses the same
  Redis instance as the L2 cache (#21). Composition root selects from
  `.spectra.yml`.
- **Dependencies:** [ADR-013](../architecture/adr/ADR-013-task-budget-and-rate-coordination.md)
  defined the Protocol; this work ships the second adapter. Stacks with
  #21 (same Redis).
- **External infra:** Redis (shared with #21).
- **Effort:** **M** (3-5 days, mostly Lua + circuit breaker + tests).
- **Risks + mitigations:** Hot-key contention on the rate-limit key —
  mitigated by Lua atomic INCR + fixed minute-bucket (one HINCRBY per
  call). Redis outage — circuit breaker falls back to in-process for the
  rest of the run; loud audit event; logged in `cache.l2_circuit_opened`-
  shaped audit event.
- **Acceptance criteria:** Demo: 4 concurrent processes share a single
  Redis with `per_minute=10`. Total throughput across all 4 processes is
  exactly 10/min. Kill Redis: each process falls back to its own in-
  process limit; processes are independent; pipeline continues.
- **ADR:** [ADR-013](../architecture/adr/ADR-013-task-budget-and-rate-coordination.md)
  (no new ADR — Q3 is the second adapter for an existing Port).

### #23 — Anthropic Batch API + prompt caching

- **User story:** As a finance lead, I want lower per-scan cost via Batch
  API on overnight portfolio runs and prompt caching on every interactive
  scan.
- **Architectural shape:** `LLMGateway` Protocol gains
  `cache_breakpoint()` (per-block hint), `submit_batch()` and
  `poll_batch()` (async batch lifecycle). New entities `PromptBlock`,
  `BatchHandle`, `BatchResult`, `RunMode`, `CostBreakdown`. Three stable
  cache-breakpoint sites (specialist system prompt, MetaPrompter system
  prompt, critique system prompt). `RunMode` enum dispatches sync vs
  batch routing in the orchestrator. `CostBreakdown` renders savings on
  every report; span attributes carry `llm.cached_tokens` and
  `llm.batch_discount_applied`.
- **Dependencies:** [ADR-013](../architecture/adr/ADR-013-task-budget-and-rate-coordination.md)
  (`PRICING_TABLE`), [ADR-021](../architecture/adr/ADR-021-distributed-cache-port-and-adapter-trio.md)
  (Spectra cache short-circuits *before* the LLM call; this ADR optimises
  the calls that miss the Spectra cache), [ADR-022](../architecture/adr/ADR-022-postgres-history-store.md)
  (#26 portfolio scheduler routes through Batch).
- **External infra:** none net-new (Anthropic-side feature).
- **Effort:** **M** (5-7 days).
- **Risks + mitigations:** Prompt-cache prefix drift (one trailing
  whitespace flushes the cache) — byte-stability unit test on every PR.
  Batch 24h timeout — graceful fall back to sync; partial results render
  per `pipeline_state = degraded`. Bedrock/Vertex no equivalent —
  documented; `submit_batch` raises `NotImplementedError`; orchestrator
  falls back; one-line WARN banner.
- **Acceptance criteria:** Demo: a 312-repo portfolio scan in
  `portfolio_batch` mode completes in 18h at ~$700-800. Compare with
  same-shape sync run at ~$2,180. Report shows
  `cost: $4.20 (saved $2.80 via prompt caching + Batch API)` per scan.
  OTel span on `llm.call` shows `llm.cached_tokens > 0`.
- **ADR:** [ADR-024](../architecture/adr/ADR-024-anthropic-batch-api-and-prompt-caching.md).

### #25 — Postgres history store + `ReportStorePort`

- **User story:** As an engineering leader, I want trends and grade
  history over time so I can act on drift before customers see it.
- **Architectural shape:** New `ReportStorePort` (Layer 2) +
  `PostgresReportStoreAdapter` (Layer 4) + `SqliteReportStoreAdapter`
  fallback. Three tables (`reports`, `report_dimension_scores`,
  `report_severity_counts`). Raw SQL migrations applied by
  `spectra history migrate`. Async `psycopg` 3 connection pool — no ORM.
  No findings, no code, no PII in the history store: signatures + counts
  + scores only (privacy boundary inherited from
  [ADR-018](../architecture/adr/ADR-018-audit-log-and-identity.md)).
- **Dependencies:** [ADR-018](../architecture/adr/ADR-018-audit-log-and-identity.md)
  (privacy boundary), [ADR-020](../architecture/adr/ADR-020-config-file-yaml.md)
  (`history:` config section).
- **External infra:** Postgres 14+ (or any Postgres-wire-compatible —
  Aurora, AlloyDB, CockroachDB).
- **Effort:** **L** (10-14 days).
- **Risks + mitigations:** Migration regression — every release that
  ships a migration has a `spectra history doctor` check + a smoke-test
  run on a fresh DB in CI. SQL injection — `psycopg` parameterised
  queries are the only path; lint rule forbids f-string SQL. Connection-
  pool exhaustion — documented `max_connections` ceiling per process; we
  ship a sizing guide.
- **Acceptance criteria:** Demo: 100 scans across 30 repos written to
  Postgres in CI. `SELECT repo_signature, overall_grade, ts FROM reports
  WHERE org_id = ? ORDER BY ts DESC` returns sorted history. `spectra
  trend acme/api --since 4w` renders an ASCII sparkline. Migration runs
  cleanly on a fresh DB and is idempotent on re-run. Same flow works
  against the SQLite fallback for a single-user demo.
- **ADR:** [ADR-022](../architecture/adr/ADR-022-postgres-history-store.md).

### #26 — Repo registry + scheduler (`spectra portfolio`)

- **User story:** As a CTO, I want to register every service my
  organisation owns and run weekly scans across all of them, with
  results visible from one command.
- **Architectural shape:** New use case `manage_portfolio` (Layer 2) +
  CLI subcommands `spectra portfolio add|remove|list|scan|status`.
  Repository registry persisted in the Postgres history store (#25) as
  a fourth table (`portfolio_repositories`). `spectra portfolio scan`
  enumerates registered repos and dispatches via `RunMode.PORTFOLIO_BATCH`
  through Batch API (#23). `spectra portfolio status` queries history
  (#25) for the latest `overall_grade` per repo.
- **Dependencies:** #23 (Batch API for cost-affordable overnight runs),
  #25 (history for status query). The scheduler is **not a daemon** —
  customers schedule with cron / GitHub Actions / Cloud Scheduler. The
  CLI does the work; the schedule is the customer's.
- **External infra:** none net-new (Postgres from #25).
- **Effort:** **M** (4-6 days).
- **Risks + mitigations:** Scheduler scope creep — explicit decision in
  open questions: CLI-only, no background daemon, no Spectra-operated
  control plane (consistent with [product-roadmap.md TL;DR](product-roadmap.md)).
  Partial-failure during a 312-repo run — every per-repo scan is
  independent; one failure does not abort the rest; status command shows
  `pipeline_state = degraded` for failed repos.
- **Acceptance criteria:** Demo: register 5 repos with `spectra portfolio
  add`. Run `spectra portfolio scan` (overnight via cron). Next morning,
  `spectra portfolio status` shows grades + drift since prior week. Total
  cost line at the bottom: aggregate cost-saved-via-Batch.
- **ADR:** No new ADR — implementation falls under [ADR-022](../architecture/adr/ADR-022-postgres-history-store.md)
  (history schema), [ADR-024](../architecture/adr/ADR-024-anthropic-batch-api-and-prompt-caching.md)
  (Batch routing).

### #27 — Trend / drift detection + Slack alerts

- **User story:** As an engineering leader, I want a Slack ping when a
  previously-A repo drops below B-, with the diff link to the PR that
  caused it.
- **Architectural shape:** New use case `DetectDrift` (Layer 2) wraps a
  window-function query against `ReportStorePort` (#25). `DriftThreshold`
  entity (configurable: default 5-point drop OR full-grade drop).
  Outbound notifier abstracted as `NotifierPort` (Layer 2) with
  `SlackWebhookAdapter` (Layer 4). The scheduler (#26) calls
  `DetectDrift.run()` after each `portfolio scan`; drift events fan out
  to `NotifierPort.send(message)`.
- **Dependencies:** #25 (history), #26 (scheduler triggers it),
  potentially #34 (notifier adapter is shared).
- **External infra:** Slack (webhook URL, customer-provisioned).
- **Effort:** **S-M** (3-4 days).
- **Risks + mitigations:** Threshold tuning (too noisy or too quiet) —
  default conservative (5-point drop or full-grade drop), customer
  overrides in `.spectra.yml`. False alerts on stochasticity — drift
  detection ignores deltas < 2 points absolute (within stochastic noise
  per the post-R3 self-scan caveat).
- **Acceptance criteria:** Demo: set `service-payments` to A in week 1
  history, B+ in week 2, C+ in week 3. `DetectDrift.run()` returns one
  drift event for week 3 (crossed full-grade drop). Slack message
  arrives at the configured webhook with repo name, prior grade, current
  grade, and a deeplink to the latest report.
- **ADR:** No new ADR — uses [ADR-022](../architecture/adr/ADR-022-postgres-history-store.md)
  query patterns; the Slack notifier is one ~80-LoC adapter.

### #30 — OpenTelemetry tracing + per-agent spans

- **User story:** As an SRE on the platform team, I want OTel spans for
  every Spectra scan so my Honeycomb / Datadog / Tempo dashboards show
  per-agent latency and per-stage failure rates.
- **Architectural shape:** New `TracerPort` Protocol in Layer 2 + `Span`
  Protocol + `SpanKind` enum. Two adapters: `OpenTelemetryTracerAdapter`
  (default when `observability.tracing.enabled`) and
  `NoOpTracerAdapter` (zero-overhead default when not configured).
  Trace tree: `analyze_repository` (root) → per-stage spans → per-agent
  spans → per-LLM-call spans. Decorator chain on `LLMGateway` gains
  `TracingDecorator` at the top. Exporter: OTLP/HTTP only; customers
  route through their OTel Collector (Honeycomb, Datadog, Splunk, Tempo
  all reachable that way).
- **Dependencies:** [ADR-013](../architecture/adr/ADR-013-task-budget-and-rate-coordination.md)
  (`PRICING_TABLE` for the cost attribute), [ADR-018](../architecture/adr/ADR-018-audit-log-and-identity.md)
  (privacy boundary inherited).
- **External infra:** OpenTelemetry Collector (customer-provisioned).
  Or any OTLP-compatible endpoint.
- **Effort:** **M** (5-8 days). See [ADR-023](../architecture/adr/ADR-023-opentelemetry-tracing-and-cost-attribution.md).
- **Risks + mitigations:** Span volume at fleet scale — `sample_ratio`
  config (default 1.0; customers reduce). PII leak via attribute — strict
  attribute-key allowlist + redaction at adapter boundary, asserted by
  unit test. OTel SDK install size — `[otel]` extra (optional);
  no-op default keeps the core install small.
- **Acceptance criteria:** Demo: a `spectra analyze` run produces a
  trace in Tempo with `analyze_repository` root span containing 7 stage
  children and (within `stage.analyze`) 6 agent spans, each containing
  per-batch `llm.call` leaves. Trace shows `llm.cost.usd`,
  `llm.cached_tokens`, `spectra.team`, `spectra.repo_url` on the right
  spans.
- **ADR:** [ADR-023](../architecture/adr/ADR-023-opentelemetry-tracing-and-cost-attribution.md).

### #33 — Cost attribution per team / repo (tagged spans)

- **User story:** As a CFO, I want Anthropic spend broken down by
  engineering team and by repo so I can budget per cost-center.
- **Architectural shape:** Falls out of #30 entirely. `llm.call` and
  `agent.*` and `stage.*` spans carry `spectra.team`, `spectra.repo_url`,
  `spectra.repo_signature`, `spectra.org_id`, `llm.cost.usd`,
  `llm.cached_tokens`. Customer's TraceQL / PromQL filter computes the
  rollup. No additional Spectra code beyond the attribute set in #30.
- **Dependencies:** #30 (OTel infrastructure). Configuration:
  `.spectra.yml` `observability.attributes.team` plus inherited
  `org_id` and `actor`.
- **External infra:** none net-new.
- **Effort:** **S** (1-2 days, mostly tests + docs).
- **Risks + mitigations:** Customer adds new tag they want surfaced —
  `observability.attributes.custom: {key: value}` flat dict in
  `.spectra.yml` covers arbitrary extension. Tag-key collision with
  reserved span attributes — adapter validates against an allow-list.
- **Acceptance criteria:** Demo: a multi-team org with `team: payments`,
  `team: identity`, `team: ml-platform` tags running 30 scans across
  teams. CFO query in Tempo's TraceQL: `{} | aggregations sum(llm.cost.usd)
  by spectra.team` returns three rows. Same query as a Grafana
  dashboard panel. CSV export from the dashboard satisfies the FinOps
  pipeline.
- **ADR:** [ADR-023](../architecture/adr/ADR-023-opentelemetry-tracing-and-cost-attribution.md)
  (covers #30 + #33 in one unit).

### #34 — Slack / Teams digest + per-finding alert

- **User story:** As an engineering manager, I want a weekly digest in
  Slack listing my repos' grades and drift, plus a per-critical-finding
  ping when one fires mid-week.
- **Architectural shape:** Shares `NotifierPort` with #27. Two adapters:
  `SlackWebhookAdapter`, `TeamsWebhookAdapter`. New use case
  `compose_weekly_digest` reads from `ReportStorePort` (#25) and
  formats one message per team. Per-finding alert hooks
  `analyze_repository` post-Stage-6: when `severity = critical` and
  `notify_on_critical = true`, emit one message per finding. Idempotency:
  finding signatures (from [ADR-018](../architecture/adr/ADR-018-audit-log-and-identity.md))
  are tracked; the same finding does not re-ping the next scan.
- **Dependencies:** #25 (history for the digest), #27 (shares
  `NotifierPort`).
- **External infra:** Slack and/or Microsoft Teams webhooks (customer-
  provisioned).
- **Effort:** **S-M** (3-4 days).
- **Risks + mitigations:** Notifier outage — `NotifierPort.send()`
  failures are non-fatal and audit-logged; the scan and digest succeed
  regardless. Spam (every finding pings) — idempotency via finding
  signature; only NEW criticals ping; the rest live in the digest.
- **Acceptance criteria:** Demo: weekly cron triggers `spectra portfolio
  scan`. After completion, weekly digest message lands in #spectra-team
  Slack channel listing 12 repos sorted by grade. A critical finding
  fires mid-week from a developer's CI run; one Slack message arrives in
  #spectra-alerts with finding details + report link.
- **ADR:** No new ADR — uses [ADR-022](../architecture/adr/ADR-022-postgres-history-store.md)
  query patterns + the small notifier adapter pattern from #27.

---

## Sequencing recommendation — 4-week plan, two engineers

The Q3 capabilities form three parallel tracks. With two engineers, the
plan is:

### Week 1 — foundations (parallel)

- **Engineer A — Cost track:** #23 (Batch API + prompt caching). Self-
  contained; no dependencies on the other tracks. ~5 days.
- **Engineer B — Data track:** #25 (Postgres history store) — start
  with `ReportStorePort` Protocol, schema, migrations, and the SQLite
  fallback first; Postgres adapter second. ~5 days.

**End of Week 1 demo:** Spectra reports show "Cost: $4.20 (saved $2.80
via prompt caching)" on every interactive scan. `spectra history migrate`
applies cleanly. A scan writes one `ReportSummary` row.

### Week 2 — fleet capabilities

- **Engineer A — Fleet track:** #21 (distributed cache: Redis +
  TieredCacheAdapter) + #22 (Redis rate limiter). Same Redis instance,
  one Docker container, one HMAC secret. ~5 days.
- **Engineer B — Data track:** Finish #25 Postgres adapter + #26
  (`spectra portfolio` CLI). The portfolio scheduler depends on Batch
  API (#23) shipped in Week 1. ~5 days.

**End of Week 2 demo:** 5-runner stampede load test shows 1 LLM call +
4 waiters. Same Redis enforces fleet RPM. `spectra portfolio add` and
`scan` work end-to-end against a small registry.

### Week 3 — observability and alerting

- **Engineer A — Observability track:** #30 (OpenTelemetry) + #33 (cost
  attribution falls out for free). ~5 days. Tempo + Grafana docker-
  compose for local validation.
- **Engineer B — Workflow track:** #27 (drift detection + Slack) + #34
  (digest + per-finding alert). Both share `NotifierPort`. ~5 days.

**End of Week 3 demo:** Tempo dashboard shows per-stage and per-agent
spans. Grafana panel shows cost-by-team rollup. Slack channel pings on
drift event from synthetic 3-week history.

### Week 4 — integration, hardening, release

- Both engineers: integration tests across the nine capabilities
  end-to-end. 312-repo simulated portfolio run as the headline demo.
  Operator docs (Postgres deployment guide, Tempo + Grafana setup,
  webhook configuration). v0.7.0 release notes + CHANGELOG. Smoke test
  on golden-files set.

### Cut points — what ships in v0.7.0 vs v0.8.0

If the team is one engineer, not two, ship in two phases:

- **v0.7.0 (Q3a, weeks 1-4):** #23, #25, #21, #22. The cost + cache +
  fleet foundation. Customer can run portfolio scans cheaply with shared
  cache; fleet RPM works; history is recorded; trend can be queried by
  hand.
- **v0.8.0 (Q3b, weeks 5-8):** #26, #27, #30, #33, #34. The workflow +
  observability layer. Customer gets `spectra portfolio scan`, drift
  alerts, OTel, cost rollups, Slack/Teams digests.

Splitting like this keeps each release shippable; v0.7.0 by itself is
already valuable to a 50-engineer organisation; v0.8.0 layers the
visibility on top.

---

## Build / buy / partner matrix

For each non-trivial dependency in the Q3 plan:

| Capability / dependency | Decision | Rationale |
|------|----------|-----------|
| OpenTelemetry SDK | **Partner — opentelemetry-python (standard SDK)** | Vendor-neutral; never lock to a proprietary backend. The standard SDK is mature; rolling our own would be reinventing nothing useful. |
| OTel exporter / collector | **Partner — OTLP/HTTP exporter; customer brings the collector** | One exporter (OTLP), customer routes from there to Honeycomb / Datadog / Splunk / Tempo. Same pattern as our audit log adapters. |
| OTel collector dev stack | **Build a docker-compose snippet** for Tempo + Grafana + OTel Collector. Document but do not ship as a Spectra dependency. |
| Postgres driver | **Partner — `psycopg[binary,pool]` 3.x** | Mature, async-native, bundled connection pool. No SQLAlchemy (nine queries does not justify an ORM). |
| Postgres migrations | **Build raw SQL files** + tiny migration runner. Reject Alembic (no ORM models to introspect; raw SQL is DBA-reviewable). |
| SQLite fallback for history | **Build** | ~120 LoC; reuses the same Protocol contract tests. |
| Redis client | **Partner — `redis>=5,<6` (the modern unified client; `aioredis` was merged into `redis-py` 4.2+)** | One library covers sync + async; Lua script support is first-class. |
| Redis dev stack | **Build a docker-compose snippet** for development; customer brings managed Redis (ElastiCache, Cloud Memorystore, Upstash) for production. |
| S3 client | **Partner — `boto3` + `aioboto3`** for the S3 cache adapter | Standard AWS SDK; conditional writes via `If-None-Match: *` are first-class. Optional extra `pip install spectra-ai[aws]`. |
| Anthropic Batch API | **Partner — native Anthropic API** | First-party; no abstraction needed beyond our `LLMGateway` extension. |
| Anthropic prompt caching | **Partner — native Anthropic feature** | Same: thin `cache_breakpoint()` shim in `LLMGateway`; provider-side caching does the work. |
| Slack notifier | **Build outbound webhook adapter** (~80 LoC); reject hosted Slack app for v1 (no app-store listing, no OAuth flow). Customer registers their own webhook URL. |
| Microsoft Teams notifier | **Build outbound webhook adapter** (Incoming Webhook connector; same pattern as Slack). |
| Drift detection | **Build** — one window-function query in the use case. Domain-specific. |
| Portfolio scheduler | **Build CLI subcommand**; reject background daemon for v1. Customer schedules via cron / GitHub Actions / Cloud Scheduler. |
| Cron / scheduling | **Partner — customer's existing scheduler** (cron, GitHub Actions, Cloud Scheduler, EventBridge). Spectra is not in the scheduling business. |
| HMAC secret backend | **Partner — keyring (single-machine), AWS Secrets Manager, HashiCorp Vault** | Existing dependencies (`keyring` already in `pyproject.toml` per [ADR-012](../architecture/adr/ADR-012-cache-hmac-per-user-namespace.md)). Add boto3 / hvac for AWS / Vault as optional extras. |

---

## Open questions for the founder

1. **Do we ship a `docker-compose.yml` dev stack for users to test
   against locally?** We will need Postgres + Redis + OTel Collector +
   Tempo + Grafana for the full Q3 demo. Options: (A) ship one master
   `docker-compose.yml` in `examples/dev-stack/` covering all five
   services; (B) ship per-service snippets in each ADR's docs; (C) link
   to upstream Bitnami / Confluent / Grafana Labs compose files. **Our
   recommendation:** **A**, scoped to `examples/dev-stack/`, kept
   intentionally separate from the main install so no user accidentally
   thinks Spectra requires Docker. This is for the developer who wants
   to validate Q3 features end-to-end without provisioning AWS.
2. **Is the portfolio scheduler a CLI command or a background daemon?**
   Our recommendation in this plan is CLI-only (cron / Actions /
   Cloud Scheduler do the scheduling). This keeps the architectural
   commitment "Spectra is not a service." Founder should confirm; the
   alternative (daemon) reshapes [ADR-022](../architecture/adr/ADR-022-postgres-history-store.md)
   schema (we would need a `scan_jobs` queue table) and adds operational
   surface (process management, restart policy, leader election). Punt
   to v0.9.0+ if asked.
3. **Do we host a Spectra Slack app or just emit webhook payloads
   users register themselves?** Our recommendation: webhook only for
   v0.7.0/v0.8.0. A hosted Slack app means an app-store listing, OAuth
   flow, multi-tenant token storage — a step toward SaaS that the
   product-roadmap TL;DR explicitly defers. Webhooks land in 80 LoC and
   work day one. Founder should confirm; if a customer asks for the
   hosted app in writing, we revisit.
4. **HMAC secret rotation playbook ownership.** With distributed cache
   (#21), the HMAC secret is per-org and rotation invalidates the
   entire L2 cache. Options: (A) we publish a "HMAC rotation" runbook
   document and customers own it; (B) we ship `spectra cache rotate-
   hmac --new-secret-id <id>` that invalidates L2 for a controlled
   window then re-warms; (C) we keep two secrets active during a
   transition period (current-and-previous), accepting the L2 pollution
   for the rotation window. **Our recommendation:** **A** for v0.7.0,
   **B** as a v0.8.0 follow-up if customers ask. (C) is operationally
   complex and we should not pre-build it.
5. **Cost attribution beyond `team`.** [ADR-023](../architecture/adr/ADR-023-opentelemetry-tracing-and-cost-attribution.md)
   carries `spectra.team`, `spectra.repo_url`, `spectra.org_id`, plus a
   flat-dict `attributes.custom`. Some customers may want `cost_center`,
   `business_unit`, `product_line`, `environment` — all reasonable, all
   org-specific. Question: do we publish a recommended attribute schema
   (FinOps Foundation FOCUS-aligned) or stay flat-dict-permissive?
   **Our recommendation:** flat-dict-permissive in v0.7.0; revisit a
   FOCUS-aligned schema in v0.9.0 once two customers have used it in
   production and we know the real shape.

---

## Contradictions and risk flags

In the per-capability spec, no contradictions surfaced between the nine
Q3 capabilities — the dependency graph is consistent (history feeds
drift, drift feeds Slack, OTel attributes give cost attribution, Batch
API makes the portfolio scheduler affordable). One small architectural
tension worth naming:

**The Postgres history store (#25) and the distributed cache (#21) both
ship with their own composition root selection logic in `.spectra.yml`.**
By the end of Q3 the config schema has:

- `cache: l1=sqlite, l2=redis|s3|none`
- `history: backend=postgres|sqlite`
- `rate: coordinator=in-process|redis`
- `audit: backend=jsonl|otlp|cloudwatch|none` (Q2)
- `observability.tracing.enabled` (Q3)
- `notifiers: slack=..., teams=...` (Q3)

This is fine — every section is a clean adapter selection — but the
operator runbook for Q3 is now a real document. We commit to documenting
each section's adapter selection inline in `.spectra.yml` examples and
in [ADR-020](../architecture/adr/ADR-020-config-file-yaml.md)'s schema
reference.

There is **no contradiction** between the distributed cache assumption
and the Postgres history store: the cache holds findings (composite-key
shape, finding rows), the history store holds report summaries (one row
per scan, scan-shaped). They serve different queries, share no schema,
share no key. Both can scale independently.

---

## What ships and what defers (recap)

**Ships in Q3:** #21, #22, #23, #25, #26, #27, #30, #33, #34 — nine
capabilities, four ADRs ([ADR-021](../architecture/adr/ADR-021-distributed-cache-port-and-adapter-trio.md)
through [ADR-024](../architecture/adr/ADR-024-anthropic-batch-api-and-prompt-caching.md)),
one config schema extension ([ADR-020](../architecture/adr/ADR-020-config-file-yaml.md)
gains `history`, `observability`, `notifiers` sections).

**Defers to Q4:** #14 (Bedrock + Vertex), #15 (ZDR mode), #50-#55
(memory tier work). The Anthropic-native bet ([product-roadmap.md §6](product-roadmap.md))
holds — Q3's Batch API + prompt caching reinforce it.

**Defers to Q5+:** #28 (leaderboard endpoint — needs RBAC), #29 (RBAC),
#31 (Prometheus endpoint — needs daemon mode), #32 (SLO dashboards).
None of these block Q3; all benefit from Q3's data foundation when
they ship.

---

*End of Q3 plan. Next deliverable: per-week milestone briefs translating
the four-week sequencing recommendation into PR-sized work units.*
