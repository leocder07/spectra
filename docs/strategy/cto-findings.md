# CTO Findings — Platform requirements for Spectra v1.0

**Author:** CTO persona · 2026-04-29

---

## TL;DR

Spectra at v0.3.3 is a sharp single-developer tool. To recommend it for org-wide
adoption I need five things on the roadmap before signing the PO:

1. **Distributed cache + fleet rate-limiting.** Today the SQLite WAL cache is
   per-machine; CI runners and 50 engineers cannot share work. We need an
   `S3CachePort` (read-through, write-back) and a centralized token-bucket so
   the Anthropic Tier-N RPM limit is shared across runners — not pillaged by
   the noisiest team.
2. **Portfolio mode.** Multi-repo scheduling, trend storage in Postgres,
   drift alerts (`A → C in 30 days`), and a thin web UI for engineering
   leaders. The CTO-shaped use case is "scan all 312 services weekly" and
   it is not the use case the CLI was designed for.
3. **OpenTelemetry-native observability.** Per-agent spans, token/$ as span
   attributes, SLOs (p95 < 5min, $/scan < $X), failure-mode taxonomy in
   metrics. Without this we cannot operate the service or set error budgets.
4. **Custom rule packs + plugin specialists.** A 7th specialist for IaC
   (Terraform/Helm/K8s), a per-org rule-pack mechanism so the security team
   can ship `org-rules-v3` without touching the Spectra source. Specialist
   prompts and dimension weights become versioned configuration, not code.
5. **Integration surface, prioritized:** GitHub PR comment (have it) → Slack
   digest → Jira/Linear ticket auto-creation → IDE LSP. Skip the IDE in v1
   if budget forces a cut; ship Slack and Jira first because they reach the
   leaders who pay for the seat.

If we add only items 1, 2, and 3, Spectra is a credible internal platform.
Items 4 and 5 are what turn it from "internal tool" into "we just bought
the dev-loop dashboard."

---

## 1. Scale & throughput

### Current state

- **Single-process, single-machine.** `spectra analyze` clones the repo,
  spawns 6 specialists via `asyncio.gather`, throttled by an in-process
  `Semaphore(4)`. Connection pool is 10 keep-alive httpx connections —
  per-process, not fleet-wide. See `orchestrate_agents.py:101` and
  `anthropic_adapter.py:46`.
- **Cache is local SQLite WAL** at `~/.cache/spectra/cache.db`. Concurrent
  reads OK, multi-writer not designed in. Phase 4 added `cache prune` but
  not multi-tenant isolation.
- **Real-world numbers** from `docs/launch/leaderboard.md`: 5 OSS scans cost
  $33.44 / 247s avg wall-clock / ~600K tokens avg. Extrapolation: 5,000
  repos × $7/scan × 1 scan/week = **$1.8M/year** on Anthropic alone before
  any caching savings; 500K repos is non-starter at retail pricing.
- **Rate-limit blast radius.** A `Tier 1` Anthropic key (50 RPM) is
  exhausted by ≤8 concurrent specialists. The current Semaphore(4) is a
  per-process safety belt, not a fleet-wide budget.

### Required capabilities

- **Distributed cache adapter (`S3CachePort` / `RedisCachePort`)** —
  S3-backed read-through with local SQLite as L1, Redis for hot keys —
  effort: **M**. Keep `CachePort` Protocol unchanged; add a new Layer-4
  adapter; composition root selects by env var.
- **Fleet rate-limiting (centralized token bucket)** — Redis-backed
  distributed semaphore that all runners and CLIs subscribe to. The
  Anthropic key holder (the org) sees ≤Tier-N RPM regardless of how many
  callers — effort: **M**. Replaces the per-process `Semaphore(4)`.
- **Worker pool / job queue** for portfolio scans — RQ or Temporal,
  not in-process asyncio. The CLI stays as today; the platform gets a
  `spectra-worker` daemon that pulls scan jobs from a queue —
  effort: **L**.
- **Repo-level partitioning + sharding key** — when a 5K-repo org runs the
  weekly scan, route by repo-signature hash to N workers so cache locality
  holds — effort: **S** once the queue exists.
- **Anthropic Batch API for non-interactive scans** — overnight portfolio
  jobs do not need streaming; Batch API gives 50% cost saving and
  decouples from RPM limits entirely — effort: **S** (new code path in
  `AnthropicAdapter`).
- **Prompt caching (`cache_control: ephemeral`)** — system prompts and
  large file context are stable across the 6 specialists in one run; we
  are paying input-token cost 6× for the same context. Anthropic's
  cache breakpoints are free — effort: **S**, big cost win.

---

## 2. Multi-repo / portfolio mode

### Current state

- One CLI invocation = one repo. No notion of an "org" or a "portfolio."
- Reports are HTML/JSON/SARIF files written to disk; no central history,
  no trend, no leaderboard schema in Spectra itself (the
  `docs/launch/leaderboard.md` is hand-authored markdown).
- `cache.db` per machine; trend data dies when the dev wipes their
  laptop or the runner is recycled.

### Required capabilities

- **Postgres-backed history store** — every `AnalysisReport` written to
  `reports(repo_id, run_at, scorecard, findings_json, cost_usd, tokens)`
  with a thin `ReportStorePort` in Layer 2 — effort: **M**. Use the
  existing `ReportPort` pattern; do not let SQLAlchemy leak inward.
- **Repo registry + scheduler** — `spectra portfolio add <url>`,
  `spectra portfolio scan --schedule weekly`. Register-once, scan-many.
  Cron-style triggers; auto-discovery via GitHub/GitLab org webhooks —
  effort: **M**.
- **Trend analysis + drift detection** — given the history table, this
  is just a SQL query: `delta(score) over window`. Surface as
  `spectra portfolio trends --since 30d` and as Slack alerts when a
  previously-A repo drops below B- — effort: **S** once history exists.
- **Org-wide leaderboard endpoint** — read-only HTML/JSON aggregation
  by team / language / severity. Single Jinja2 template like the
  per-repo report, just one level up — effort: **S**.
- **RBAC + multi-tenancy** — every repo belongs to a `team`; engineers
  see their team's findings; CISO sees everything. Standard
  org/team/user model — effort: **M**, but unavoidable for adoption.
- **Diff-mode for PRs in portfolio context** — "this PR introduced 2
  new high-severity findings vs main" requires both branches in the
  history table — effort: **S** on top of registry.

---

## 3. Observability & SRE

### Current state

- `LoggingDecorator → RetryDecorator → AnthropicAdapter` chain produces
  structured logs (`spectra.adapter` logger). No metrics export, no
  tracing, no SLO instrumentation.
- Failure state machine is real (`evaluate_results` in
  `orchestrate_agents.py:211`): 0-1 fail = `merging`, 2+ = `degraded`.
  Surfaced in CLI text but **not** as a metric or alert. CISO will
  not know that 12% of CI scans degraded last week.
- `last_usage` per call is captured (`AnthropicAdapter:89`) but not
  exported.
- SPEC-010 cache-degrade is silent — the run just gets slower.

### Required capabilities

- **OpenTelemetry tracing** — one root span per `analyze`, child span per
  agent, attributes = `model, effort, input_tokens, output_tokens,
  cost_usd, batch_id, cache_hit`. Drop into Honeycomb / Datadog /
  Grafana Tempo with no extra plumbing — effort: **M**. Wrap the
  decorator chain with `OtelDecorator`.
- **Prometheus metrics endpoint** for the worker daemon —
  `spectra_scan_duration_seconds`, `spectra_scan_cost_usd_total`,
  `spectra_agent_failures_total{role}`,
  `spectra_cache_hit_ratio{layer}`,
  `spectra_pipeline_state_total{state}` — effort: **S** once tracing
  is in.
- **SLO dashboards + error budgets** — predefined: p95 wall-clock < 5min,
  p99 < 10min, $/scan p95 < $10, degraded-pipeline rate < 1%. Burn
  alerts feed Slack and pause CI integration when budget is gone —
  effort: **M** (SLO definitions + alerting wiring).
- **Loud `degraded` and `SPEC-010` surfacing** — today these whisper.
  Promote to PagerDuty-class signal when degraded rate > threshold —
  effort: **S**.
- **Cost attribution per team/repo** — Anthropic invoice is one number;
  the CFO will demand breakdown. Tag every API call with
  `team, repo, run_id` and aggregate from the spans —
  effort: **S** on top of OTel.
- **Audit log** — who ran what scan against what repo when. Compliance
  prereq. Effort: **S** if the scheduler writes it; **M** if retro-fit.

---

## 4. Integration surface

### Current state

- GitHub Action (`action.yml` at repo root) with idempotent PR comment via
  `<!-- SPECTRA -->` sentinel. Solid baseline.
- HTML / JSON / SARIF outputs. SARIF is the IDE-integration path but no
  one has wired it.
- No Slack, no Jira, no LSP, no IDE plugin.

### Required capabilities

- **Slack / Teams digest + alerts** — daily/weekly portfolio digest +
  per-finding alert for `critical`. Webhooks, no apps required at
  v1 — effort: **S**. Highest CTO/EM-visible ROI per engineer-hour.
- **Jira / Linear / GitHub Issues auto-create** — for `critical` and
  `high` findings, open a ticket with stable dedup key
  `spectra:{repo}:{file}:{rule_id}`. Update ticket if finding moves
  but persists; close if finding is gone — effort: **M**. Idempotency
  is the hard part; we already have the pattern from the PR-comment
  sentinel.
- **GitLab MR + Bitbucket PR comments** — same pattern as the
  GitHub Action, different SDK — effort: **S** each.
- **VSCode / Cursor / JetBrains plugin via SARIF + LSP** — emit SARIF
  (have), build a thin LSP server that streams findings to any LSP
  client. SARIF gets us VSCode's native Problems pane for free —
  effort: **M** for LSP server, **S** for SARIF polish.
- **Grafana / Datadog / New Relic dashboards** — fall out of the OTel
  work in §3. Ship a starter Grafana JSON. Effort: **S** post-OTel.
- **Webhooks (`spectra.scan.completed`, `spectra.finding.critical`)** —
  the universal escape hatch for org-specific integrations — effort:
  **S**.
- **Bazel/Buck2/Pants integration for monorepos** — `spectra` as a
  build rule with hermetic inputs (file hashes feed our cache key
  beautifully) — effort: **L**, defer until a customer asks.
- **Chained scanners (Snyk/Semgrep/GitGuardian)** — accept their JSON
  as additional input to the `MERGE` stage. Spectra adds the LLM
  reasoning layer on top of their AST/secret findings — effort: **M**;
  see Build vs Buy.

---

## 5. Custom rules & extensibility

### Current state

- The 6 specialist prompts live in
  `src/spectra/infrastructure/agents/specialist_prompts.py`. Source-code
  changes only. There is no plugin-loading mechanism for specialists.
- `Strategy` pattern is in place — `SPECIALIST_CONFIGS` parameterizes one
  class for 6 dimensions — but it is hard-coded in the package.
- Dimension weights are constants in `analyze_repository.py` /
  scoring code. Org-specific weighting (e.g. "we care 2× about security")
  requires a fork.

### Required capabilities

- **Specialist plugin system** — entry-point-based discovery
  (`spectra.specialists` group in `pyproject.toml`). A 3rd-party
  package ships an `InfraSpecialist` class implementing `AnalysisAgent`,
  registers via entry point, and Spectra picks it up. Clean Architecture
  enables this — `AnalysisAgent` is already a `Protocol` —
  effort: **M**.
- **Versioned rule packs** — declarative YAML/TOML overlay on prompts
  + dimension weights + severity thresholds. `org-security-rules-v3.toml`
  shipped via private PyPI / OCI registry. The cache key already includes
  `prompt_version`; rule-pack version slots in there — effort: **M**.
- **Custom dimensions** — user-defined dimension with custom weight,
  custom specialist, custom score formula. The `Dimension` Literal type
  becomes a registry — effort: **L**, requires entity-layer change
  (which we should plan carefully — the frozen-Pydantic invariants
  must survive).
- **Per-language fine-tuning** — Rust-aware specialist that understands
  ownership; Go-aware specialist that knows about goroutine leaks.
  Implement once via the plugin system above — effort: **M** per
  language pack.
- **MetaPrompter steerability** — let the rule pack inject "always
  scrutinize files matching `auth/**`" into the planner's focus_areas —
  effort: **S**.
- **Suppression + waivers** — `# spectra: ignore-next-line SEC-AUTH-101`
  in source plus a centrally-managed waiver registry. Without this,
  developers will rage-quit the integration. Effort: **M**.

---

## 6. Build vs buy vs partner

| Capability | Build | Buy | Partner | Recommendation |
|---|---|---|---|---|
| AST-based code analysis | Heavy (years of language coverage) | Sourcegraph (~$$$) | Semgrep (OSS + Pro) | **Partner — Semgrep for AST, Spectra for LLM reasoning.** Run Semgrep first, feed findings into MERGE as evidence. We add the prioritization, the explanation, and the fix recommendation. |
| Secret scanning | Trivial regex; brittle | TruffleHog Enterprise, GitGuardian | TruffleHog OSS | **Partner — TruffleHog OSS in INGEST.** Don't reinvent regex packs. Surface their findings as `dependency`/`security` evidence. |
| SCA / CVE scanning | Heavy (NVD ingest, license DB) | Snyk, Mend | OSV.dev (free), Trivy | **Partner — OSV.dev + Trivy.** Free, well-maintained. Our `DependencyAgent` does the LLM reasoning over their raw CVE list. |
| Cache layer | We have SQLite | Redis Cloud, Momento | Redis OSS, S3 | **Build adapter, partner on infra.** Add `S3CachePort` and `RedisCachePort`; let customers BYO infra. |
| Telemetry / tracing | Have a decorator chain | Datadog, Honeycomb | OpenTelemetry (vendor-neutral) | **Build OTel adapter; users buy the backend.** OTel is the standard; do not lock in a vendor. |
| Worker queue | RQ / custom | Temporal Cloud, Inngest | RQ OSS, Temporal OSS | **Build on Temporal OSS.** Workflows-as-code matches our pipeline model. Self-host for v1, Temporal Cloud for managed customers. |
| Issue creation | One adapter per tracker | Linear/Jira have SDKs | Linear, Jira, GitHub | **Build adapters.** Thin; idempotency-key pattern reused from PR-comment sentinel. |
| IDE integration | LSP server is real work | Sourcegraph Cody, Codeium | VSCode SARIF native | **Partner with the LSP standard, build a thin server.** SARIF gets us the Problems pane for free; LSP unlocks all editors with one investment. |
| Auth / SSO | Heavy (SAML, OIDC, SCIM) | WorkOS, Auth0 | WorkOS | **Buy — WorkOS.** Don't build auth. Period. |
| Hosting / inference | Self-hosted Anthropic isn't a thing | Anthropic API (today), Bedrock, Vertex | Anthropic Managed Agents (see below) | **Partner with Anthropic; evaluate Managed Agents seriously.** |
| Vector store / embeddings (future) | pgvector | Pinecone, Turbopuffer | Postgres + pgvector | **Build on pgvector.** Don't add a 2nd database. |
| LLM eval harness | Have a few golden_files | Braintrust, LangSmith | Braintrust (lightweight) | **Buy — Braintrust.** Eval is a discipline; we shouldn't build it from scratch. |

---

## How Anthropic Managed Agents could change the architecture

Managed Agents (the hosted agent-loop offering — file mounts, persistent
containers, native MCP, vault-managed credentials) lets us delete a
non-trivial slice of `infrastructure/`. The 6 specialists today execute
locally: clone repo, mount file system, call Anthropic over HTTPS,
parse JSON, validate Pydantic. With Managed Agents the loop runs
inside Anthropic's container with the repo file-mounted — the
`AnthropicAdapter` shrinks to a thin job-submission client, and
`GitAdapter` becomes a "ship workspace to managed runtime" call.

**What stays in Spectra:** Layer 1 (entities), Layer 2 (use cases —
including `analyze_repository` facade and `orchestrate_agents` —
because the parallel-fan-out + merge + critique discipline is *our*
IP, not Anthropic's). The `MERGE`, `CRITIQUE`, and `REPORT` stages
stay local because they need our scoring weights, our deduplication,
and our Jinja2 templates.

**What moves to Managed Agents:** the 6 `SpecialistAgent` instances
become managed-agent definitions with skills mounted from our
`specialist_prompts.py`. Tool calls (read file, grep, regex search)
that today we hand-roll into the prompt become *real tools* the
managed agent invokes — improving precision and reducing
hallucination. The cache layer collapses partly: Anthropic's
prompt cache + our batch cache work together; we keep the
batch cache for cross-run reuse (Anthropic's prompt cache is
intra-session).

**New capabilities that open up:**

1. **Persistent agent containers** — the security specialist can keep a
   warm grep index between runs on the same repo, dropping cold-run
   latency. We get incremental analysis at the runtime layer too,
   not just our cache.
2. **Vault-managed credentials** — for enterprise customers, their
   GitHub/GitLab tokens never touch their dev machine or our
   infra; Managed Agents fetches them from their vault.
3. **Native MCP tool wiring** — Semgrep, Snyk, OSV.dev all have MCP
   servers (or will). We wire them as tools to the `SecurityAgent`
   instead of pre-running and feeding findings as text. This is
   strictly better for grounding.
4. **Reduced ops surface** — no httpx connection pool to tune, no
   per-process semaphore — the managed runtime handles concurrency
   and backpressure. Our `orchestrate_agents` shrinks.

**Risk:** vendor lock-in to a specific Anthropic feature surface. Mitigation:
keep `LLMGateway` Protocol the boundary; add `ManagedAgentAdapter` as a
sibling to `AnthropicAdapter`; prove parity on the leaderboard set before
flipping the default.

---

## Top 15 platform capabilities ranked by adoption-blocker severity

1. **Distributed cache (S3 / Redis)** — ROI: $$$$, effort: M, deps: none.
   Without this, 50 engineers redo each other's work.
2. **Fleet-wide rate-limiting** — ROI: $$$$, effort: M, deps: Redis.
   Without this, the loudest team starves the rest.
3. **OpenTelemetry tracing + per-agent spans** — ROI: $$$, effort: M,
   deps: none. Cannot operate what you cannot see.
4. **Postgres history store + trend queries** — ROI: $$$$, effort: M,
   deps: none. The CTO ask is trends, not point-in-time.
5. **Repo registry + scheduler (`spectra portfolio`)** — ROI: $$$$,
   effort: M, deps: history store. The whole portfolio narrative.
6. **Slack / Teams digest** — ROI: $$$, effort: S, deps: history store.
   Cheapest big-visibility win.
7. **Jira / Linear ticket auto-create with idempotency** — ROI: $$$,
   effort: M, deps: history store. Closes the loop from finding → fix.
8. **Anthropic Batch API + prompt caching** — ROI: $$$ (cost), effort: S,
   deps: none. Halves the per-scan bill.
9. **Specialist plugin system (entry points)** — ROI: $$$, effort: M,
   deps: none. Unlocks IaC, Rust, custom-domain specialists.
10. **Versioned rule packs (YAML overlay on prompts/weights)** — ROI: $$$,
    effort: M, deps: plugin system. CISO ships rules without forking.
11. **Suppression / waiver mechanism** — ROI: $$$, effort: M, deps: none.
    Adoption blocker — devs revolt without it.
12. **Worker daemon + job queue (Temporal)** — ROI: $$, effort: L,
    deps: scheduler. Required for portfolio scale; can defer if
    initial portfolio is < 500 repos.
13. **RBAC + multi-tenancy** — ROI: $$$, effort: M, deps: history store.
    Required for any shared deployment.
14. **LSP server + IDE plugins** — ROI: $$, effort: M, deps: SARIF polish.
    Big developer-love story but org-adoption can land without it.
15. **Webhooks + GitLab/Bitbucket PR comments** — ROI: $$, effort: S each,
    deps: none. Long-tail integrations; ship as customers ask.

---

## Open questions for the Head of Product + CISO + Red Team

1. **Where does the source code live during a managed scan?**
   Do enterprise customers accept that their repo is cloned to our
   runner / Anthropic's managed container? If not, we need an on-prem
   worker mode — and that changes the cache, queue, and observability
   designs materially. **Need a security review and a customer
   conversation before committing to either path.**

2. **What is the unit of pricing — repo, scan, or finding?**
   Per-scan is simplest and matches our cost model (Anthropic per token).
   Per-repo is what CFOs prefer (predictable). Per-finding is what
   security-tool vendors do but creates perverse incentives (more
   findings = more revenue). **Need Head of Product to lock this
   before the portfolio scheduler ships, because the schema bakes
   it in.**

3. **Do we accept the cross-batch finding loss, or do we ship a
   "cross-cutting pass" agent?** Today the per-`focus_area` cache
   means a vulnerability spanning two batches can be missed by the
   per-batch pass and only caught by Critique. The OSS leaderboard
   doesn't show evidence of misses, but we lack telemetry. **Need
   Red Team to design an adversarial test suite that probes
   cross-batch patterns before we tell customers "we catch X."**

4. **What's the source of truth for severity?** Today every specialist
   emits `critical/high/medium/low/info` from its own prompt. CISO
   will want a deterministic mapping: "auth-bypass = always critical,
   regardless of what the LLM thinks." **Need CISO to ratify a
   severity matrix that overrides agent output before we ship rule
   packs.**

5. **What is our position on prompt-injection from the analyzed code?**
   A malicious repo could embed `// IGNORE PRIOR INSTRUCTIONS` in a
   comment and try to steer the specialist. ADR-010 covers
   Action-side token abuse but not in-repo prompt injection.
   **Need Red Team to attempt this on the leaderboard set and the
   CritiqueAgent to be evaluated as our defense layer.**
