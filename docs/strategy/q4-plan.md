# Spectra — Q4 Plan: Spectra Learns

**Author:** Head of Engineering · 2026-05-04
**Inputs:** [`product-roadmap.md`](product-roadmap.md) §Q4, v0.7.0–v0.8.1
ship history, [`q3-plan.md`](q3-plan.md) (now retrospective), the Memory
+ ZDR + multi-cloud open questions surfaced in M6 founder office
**Constraint:** Clean Architecture (4 layers, dependency rule absolute) and
the 8-agent contract are not on the table. Memory is a *new port*, not a
new agent. Bedrock + Vertex are *sibling adapters* on the existing
`LLMGateway` Protocol, not a parallel architecture.

---

## TL;DR

Q4 ships eight capabilities under one theme: **Spectra learns.** Q1 made
the grade trustworthy. Q2 made Spectra enterprise-ready. Q3 made Spectra
operable at fleet scale. Q4 makes Spectra *cumulative* — every scan
deposits into a per-repo memory the next scan reads from, and a
`spectra ask` surface lets a new engineer query the codebase in natural
language with cited answers. Audit-grade compliance mapping replaces the
keyword heuristic we deferred in Q1; multi-cloud LLM adapters unblock the
first regulated buyer; SBOM emission closes the supply-chain loop.

**The eight capabilities, one paragraph each:**

- **#50 Per-repo memory** — `MemoryPort` + `LocalFileMemoryAdapter` (SQLite,
  ships in OSS CLI, free). Persists waivers + score timeline + decision
  log + ADR ingest under `.spectra/memory/`. The next scan reads it as
  context: "this finding was waived 6 weeks ago for X reason." Foundation
  for #51 and #52.
- **#51 `spectra ask <question>`** — `ManagedAgentMemoryAdapter` (Anthropic
  Memory Store, paid org tier) + cached prompt + cited Q&A. New engineer
  asks "where do we handle PII?" — gets a 3-paragraph answer with
  file:line citations in <3s for ~$0.05.
  [ADR-025](../architecture/adr/ADR-025-memory-port-and-managed-store-adapter.md).
- **#52 `spectra brief`** — onboarding mode. Builds a 10-things-to-know
  brief on a repo: domain shape, cross-cutting concerns, riskiest files,
  open waivers, recent drift. Falls out of #50 and #51.
- **#55 Public knowledge skill** — signed Skill that ingests CVE feeds
  and framework deprecation notices, makes them queryable to specialists
  via Anthropic Skills. First Skill we ship; sets the pattern for Q6
  vertical-specialist plugins.
- **#60 Deterministic compliance mapping** — replaces the v0.6.0 keyword
  heuristic. Each SOC 2 / OWASP / PCI control links to deterministic
  CWE/CVE/regex matches; the report row reads "SOC 2 CC6.1 — 3 findings,
  2 of which match CWE-79" instead of "AI matched keywords."
  [ADR-027](../architecture/adr/ADR-027-deterministic-compliance-mapping.md).
- **#14 Region pinning + Bedrock + Vertex** — `BedrockAdapter` and
  `VertexAdapter` as siblings to `AnthropicAdapter`, all behind the same
  `LLMGateway` Protocol. New `--llm-backend bedrock|vertex|anthropic`
  CLI flag + `--region us-east-1` pin. First regulated buyer can run
  through their own Bedrock account in their own region.
  [ADR-026](../architecture/adr/ADR-026-multi-cloud-llm-gateway.md).
- **#15 ZDR mode flag** — `--zero-data-retention` opt-in that asserts the
  Anthropic ZDR header on every call AND stamps a visible banner on the
  HTML report (the Q1 deferred ask). Sales-defensible for regulated
  buyers without forcing every customer into ZDR pricing.
- **#58 SBOM-of-analysed-repo** — emit CycloneDX 1.5 alongside the report.
  One `.cdx.json` file per scan, listing every dependency the analysis
  touched (not the analysis runtime — the analysed repo's deps).
  Closes the "what did Spectra actually look at" supply-chain question.

**Total estimated effort:** 6-8 weeks of focused single-engineer work
(38-50 days). Realistic team-of-two-engineers wall-clock: **4 weeks** with
parallelism on the memory + multi-cloud tracks. Headline-grade decisions:

- **Memory Stores via Anthropic, with a `LocalFileMemoryAdapter` fallback.**
  Per-org memory is paid (Memory Store API call per scan, real marginal
  cost). Per-repo memory is free (local SQLite, zero marginal cost). The
  `MemoryPort` Protocol is the Layer-2 boundary — Anthropic-side schema
  changes never touch use cases.
- **Bedrock and Vertex are first-class peers, not afterthoughts.**
  `LLMGateway` already abstracts the call; the work is per-provider auth,
  region pinning, and per-provider feature-flag detection (prompt cache
  works on Anthropic + Bedrock; Memory Stores work on Anthropic only;
  the Bedrock path falls back to local memory automatically).
- **The compliance mapping rewrite is the most user-visible Q4 win.**
  v0.6.0 / v0.7.0 customers asked about compliance evidence; we shipped
  a "positioning, not auditor-grade" banner. Q4 retires that banner.
  Every SOC 2 / PCI / OWASP control row now traces to a deterministic
  CWE / CVE / regex. The grade story stays trustworthy because the
  mapping is verifiable.

**Cut points (worst-case sequencing — see §"Cut points" below):**

- **v0.9.0 (week 2-3 release)**: #50 + #14 + #15 + #58.
- **v0.10.0 (week 4-5 release)**: #51 + #52 + #55 + #60.

The split is clean because #50 (per-repo memory) is a pre-req for #51
(`spectra ask`), so #50 must land first regardless of which release it
ships in. #14 / #15 / #58 are independent and ship as soon as ready.

---

## Theme

Q3's theme was **operate at fleet scale**: distributed cache, history
store, OTel, Batch API, drift, cost attribution. Q4 is the inflection
point where Spectra stops being *just* an analyzer and starts being a
*memory layer over the codebase*. Every scan is now an event that
deposits into a durable per-repo memory; every memory entry becomes
context for the next scan; an operator can query that memory in natural
language with citations.

Three differentiation moves the theme delivers:

1. **The "second brain" pitch becomes real.** The product-roadmap calls
   this the M3 (Memory) persona. Today's competitors (Semgrep, Snyk,
   CodeQL, Sourcegraph Cody) treat each scan as stateless. Spectra v0.9
   onward treats every scan as the next entry in a versioned per-repo
   knowledge log. `spectra ask` is the visible feature, but the memory
   port is the moat.
2. **Multi-cloud unblocks the first regulated logo.** The product-roadmap
   §Q4 founder questions identify regulated-vertical readiness as the
   2027 wedge. Bedrock + Vertex + region pinning + ZDR are the gating
   technical work. None require new architecture (LLMGateway already
   abstracts the call); all require focused per-provider work.
3. **Compliance mapping retires the v0.7.0 deferred banner.** Today's
   report says "compliance positioning, not auditor-grade evidence." Q4
   removes that banner because every control row now links to a
   deterministic CWE / CVE / regex. This is the smallest scope of the
   eight capabilities and the highest customer-trust payoff.

---

## Per-capability spec

### #50 — Per-repo memory (`MemoryPort` + `LocalFileMemoryAdapter`)

**Layer 2 surface:**

```python
class MemoryPort(Protocol):
    async def append_event(self, event: MemoryEvent) -> None: ...
    async def query(self, *, kind: str, since: datetime | None = None) -> tuple[MemoryEvent, ...]: ...
    async def search(self, query: str, *, limit: int = 10) -> tuple[MemoryEvent, ...]: ...
    async def export_snapshot(self) -> MemorySnapshot: ...
```

**Layer 1 entities:**

```python
@dataclass(frozen=True)
class MemoryEvent:
    id: str
    kind: Literal["scan_completed", "waiver_added", "adr_ingested", "drift_detected", "decision_logged"]
    repo_url: str
    payload: Mapping[str, object]
    actor: str
    occurred_at: datetime

@dataclass(frozen=True)
class MemorySnapshot:
    repo_url: str
    waivers: tuple[Waiver, ...]
    score_timeline: tuple[ScoreSnapshot, ...]
    adrs: tuple[AdrIngest, ...]
    decisions: tuple[DecisionLog, ...]
    generated_at: datetime
```

**Layer 4 adapter:** `LocalFileMemoryAdapter` writes to
`.spectra/memory/events.sqlite` (per-repo, checked into the operator's
repo or `.gitignore`d at their option). Schema: append-only event log,
indexed on `(kind, occurred_at)`. Search uses SQLite FTS5.

**Pipeline integration:** Stage 6 (REPORT) emits a `scan_completed`
event after the report is rendered. The composition root wires
`MemoryPort` into `PipelineContext`; `analyze_repository` reads recent
waivers + drift from memory and threads them into the prompt context
for specialists (each specialist sees "this finding was waived 6 weeks
ago — here's the reason; reconsider the severity").

**ADR ingest:** `spectra memory ingest <path>` and a built-in `.spectra/memory/auto-ingest.yml` that watches `docs/adr/` and pulls
new ADRs into the memory log on each scan. Each ADR becomes an
`adr_ingested` event with title + status + decision + context fields
parsed from the standard MADR format.

**Free in OSS CLI.** Zero marginal cost (local SQLite, owner-only file
permissions per ADR-012). Tests: 30 new in `tests/use_cases/test_memory.py` + `tests/infrastructure/test_local_file_memory_adapter.py`.

### #51 — `spectra ask <question>` (`ManagedAgentMemoryAdapter` + cited Q&A)

**Layer 4 adapter:** `ManagedAgentMemoryAdapter` implements `MemoryPort`
by writing every memory event into an Anthropic Memory Store keyed on
`{repo_url}` (or `{org_id}/{repo_url}` for cross-repo queries). The
adapter exposes the Memory Store as the long-context backing for
`spectra ask`.

**Use case `ask_codebase_question`:**

1. Resolve the bound `MemoryPort` (raises a clear error when only
   `LocalFileMemoryAdapter` is bound — `ask` requires Memory Stores).
2. Submit the question to Opus 4.7 with the Memory Store mounted as a
   tool-context source + prompt cache breakpoints on the system prompt
   and per-repo project description.
3. Require citations: the model must return `(answer, citations)` where
   citations is a tuple of `(file_path, line_start, line_end, excerpt)`.
   Empty citations → reject and retry once with stricter system prompt.
4. Stream the answer to the terminal; show citations as a Rich table
   below.

**CLI:** `spectra ask "where do we handle PII?"` (with `--repo`,
`--org`, `--max-tokens`, `--no-stream` flags). Average per-question
cost target ≤ $0.10; p95 latency ≤ 5s on a 200-file repo.

**Paid org tier.** The Memory Store is a real per-call cost and must be
provisioned per-org. Per-repo memory (#50) stays free; `spectra ask`
gates on a license check via the existing keyring backend.

**ADR-025** captures the architecture (Protocol boundary, two
adapters, paid/free split, fallback semantics).

### #52 — `spectra brief` onboarding mode

Composition of #50 + #51. Builds a deterministic 10-section brief:
domain shape · cross-cutting concerns · riskiest files (top 5 by
finding-weight) · open waivers · recent drift events (last 8 weeks) ·
top 5 ADRs by recency · public-API surface (modules with most external
imports) · test coverage hot/cold spots · build/CI shape · open
"decisions to make" (from decision log).

Each section is templated; values come from the memory snapshot, the
latest scan's findings, and a single `spectra ask` call to the LLM
("summarize this repo's domain in 2 sentences"). The brief renders to
markdown; with `--format html` it renders to a self-contained one-pager
mirroring the main report's style.

**No new ports.** Pure use case `build_onboarding_brief` consuming
`MemoryPort` + `ReportStorePort` + `LLMGateway`. Tests: 15 new in
`tests/use_cases/test_onboarding_brief.py`.

### #55 — Public knowledge skill (CVE feed + framework deprecations)

**Skill structure (loaded via Anthropic Skills, not a Spectra port):**

```
.claude-plugin/spectra-public-knowledge/
├── SKILL.md                          (Skill manifest)
├── cve-feed/
│   ├── update.py                     (poll NVD daily; produce JSON)
│   └── data/                         (rotating window, last 90 days)
├── deprecations/
│   ├── update.py                     (poll framework release notes)
│   └── data/                         (Python, TS, Go, Rust, Java)
└── signing-key.pub                   (Sigstore-style verification)
```

**Specialist agents** declare the skill in their tool list. When a
specialist sees a dependency version, it can call the skill to check
"is this version vulnerable?" or "is this API deprecated in the next
release?" The skill is signed; specialists refuse to load unsigned
content.

**Operational story:** A scheduled GitHub Action in this repo pulls
NVD + framework feeds nightly, signs the data with our Sigstore-issued
identity, and pushes to the Skill's data directory. Customers fetch
the latest signed data on each scan (cached for 24h).

**Sets the Q6 pattern.** Q6 ships vertical-specialist Skill plugins
(HealthTech, FinTech, Defense). #55 is the proof that our Skill
loading + signing pipeline works end-to-end.

### #60 — Deterministic compliance mapping

**The deferred work.** v0.7.0 shipped a "compliance positioning"
banner that conceded the SOC 2 / OWASP / PCI rows in the report were
keyword-matched, not deterministic. Q4 replaces the keyword matcher
with a rule-traced mapping.

**Layer 2 surface:**

```python
class ComplianceMapper(Protocol):
    def map(self, finding: Finding) -> tuple[ComplianceControl, ...]: ...

@dataclass(frozen=True)
class ComplianceControl:
    framework: Literal["SOC2", "PCI-DSS", "HIPAA", "OWASP-Top-10", "ISO-27001"]
    control_id: str             # e.g. "CC6.1", "10.2.1", "A.9.4.2"
    cwe_ids: tuple[str, ...]    # CWE source(s) the rule traces to
    cve_ids: tuple[str, ...]    # CVE evidence (when applicable)
    severity_match: float       # 0.0-1.0 confidence the finding implicates this control
```

**Layer 4 adapter:** `RulebookComplianceMapper` reads
`docs/compliance/<framework>.yml` rule packs. Each control row has:

```yaml
- control_id: "CC6.1"
  framework: "SOC2"
  description: "Access to system resources is restricted..."
  cwe_traceable: ["CWE-284", "CWE-285", "CWE-862"]
  trigger:
    finding_dimension: "security"
    finding_keywords: ["authn", "authz", "rbac"]   # narrow disambiguation, not the source of truth
    file_pattern: ["**/auth/**", "**/permissions/**"]
```

A finding maps to a control only when the CWE family matches **and**
the file pattern matches. Pure heuristic-keyword matches (the v0.7.0
shape) are explicitly rejected at rule-parse time.

**Report row** now reads: *"SOC 2 CC6.1 — 3 findings (2 ↦ CWE-284,
1 ↦ CWE-862). [auditor-grade evidence]."* The Q1-deferred banner is
removed from the report.

**ADR-027** captures the rulebook schema, the rule-pack signing path
(Sigstore-style), and the migration of the v0.7.0 keyword catalogue.

### #14 — Region pinning + Bedrock + Vertex backends

**LLMGateway already abstracts the call.** This capability is per-provider
auth + region routing + feature-flag detection.

**Three sibling adapters** in `src/spectra/infrastructure/`:

```
anthropic_adapter.py            (existing — direct Anthropic API)
bedrock_adapter.py              (NEW — boto3 + Bedrock model IDs)
vertex_adapter.py               (NEW — google-cloud-aiplatform + Vertex model IDs)
```

**Provider selection:** `--llm-backend anthropic|bedrock|vertex` CLI flag
+ `SPECTRA_LLM_BACKEND` env. **Region pinning:** `--region us-east-1`
flag (Bedrock) / `--region us-central1` (Vertex). Anthropic backend
has no region selector — it's global by design.

**Feature-flag detection:** Each adapter exposes `supports_prompt_cache: bool`,
`supports_memory_store: bool`, `supports_adaptive_thinking: bool`.
Composition root reads these flags and:

- Disables Memory Store calls on Bedrock / Vertex (falls back to
  `LocalFileMemoryAdapter` for memory; `spectra ask` is unavailable
  but warns clearly, doesn't crash).
- Skips `cache_control` markers on backends that don't support them
  (currently Vertex; Bedrock parity arrived in 2026-Q1).
- Substitutes `effort: "high"` for adaptive thinking on backends that
  don't support adaptive (mostly Vertex; Bedrock has it).

**Auth credential surfaces:** Anthropic uses `ANTHROPIC_API_KEY` (existing).
Bedrock uses standard AWS credential chain (env, profile, IAM role).
Vertex uses GCP Application Default Credentials (ADC).

**ADR-026** captures the per-provider feature flag map, region pinning
policy, and the auth credential chain.

### #15 — ZDR mode flag

**Single CLI flag:** `--zero-data-retention` (also `SPECTRA_ZDR=1`).

**Two effects:**

1. Asserts the Anthropic Zero-Data-Retention header on every call (and
   the equivalent on Bedrock / Vertex when the backend supports it).
2. Stamps a visible banner on the HTML report (and the JSON report's
   `metadata.zero_data_retention: true` field): *"This scan ran in
   Zero Data Retention mode. The LLM provider did not log or train on
   any source code or findings from this analysis."*

**Validation at startup:** The flag fails fast if the backend does not
support ZDR (e.g. some Bedrock model variants don't). This prevents the
silent-degrade footgun where an operator thinks they're in ZDR mode
but isn't.

**Tests:** 8 new in `tests/infrastructure/test_zdr_mode.py` covering the
flag → header assertion + report banner + startup validation per
backend.

### #58 — SBOM-of-analysed-repo (CycloneDX 1.5)

**Output:** `<output_path>.cdx.json` alongside the existing HTML/JSON/
SARIF report. CycloneDX 1.5 schema (the 2024 standard).

**Detection:** Walk the analysed repo for dependency manifests:
`pyproject.toml`, `requirements.txt`, `package.json`, `go.mod`,
`Cargo.toml`, `pom.xml`, `build.gradle`, `Gemfile`, `composer.json`.
Parse each into a `(name, version, ecosystem)` tuple. Resolve transitive
deps from a lockfile when present (`requirements.lock`,
`package-lock.json`, `Cargo.lock`, `go.sum`, etc.).

**Provenance fields:** Every component row carries `purl`,
`evidence.identity` (where we found the dep), and `analysis.scope`
(how the analysis used it — read for findings vs. read for dep
hygiene). Spectra's own provenance (the analysis tool) is in the
`metadata.tools` section.

**Use case:** `emit_sbom` in `src/spectra/use_cases/`. Layer 4 adapter
`CycloneDxSbomEmitter` does the JSON serialization. Tests: 12 new in
`tests/use_cases/test_emit_sbom.py` covering each of the 9 manifest
formats + transitive resolution + provenance evidence fields.

**Closes a real customer ask.** Multiple v0.7.0+ scan reports drew the
question "what set of dependencies did Spectra actually look at?" The
SBOM answers it definitively, and aligns with the SLSA L3 narrative
already established for our own wheels.

---

## Sequencing recommendation — 4-week plan, two engineers

The four-week wall-clock target requires parallelism across two tracks:
**Memory** (#50, #51, #52, #55) and **Multi-cloud + compliance** (#14,
#15, #60, #58). #50 must land before #51, #52, and #55 (all consume
`MemoryPort`); the multi-cloud / compliance track is internally
independent.

### Week 1 — foundations (parallel)

**Memory track (engineer A):**
- #50 day 1-3: `MemoryPort` Protocol + `MemoryEvent` / `MemorySnapshot`
  entities + `LocalFileMemoryAdapter` skeleton.
- #50 day 4-5: SQLite schema + append/query/search FTS5 + tests.

**Multi-cloud track (engineer B):**
- #14 day 1-2: `BedrockAdapter` skeleton — boto3 wiring, model ID map,
  region routing, no-op fallback for unsupported features.
- #14 day 3-5: `VertexAdapter` skeleton — google-cloud-aiplatform,
  ADC auth, region routing, feature-flag map.

**Either engineer (gap-filler):**
- #58 day 1-2: SBOM emitter + 9-format manifest detector. (Small, fits
  any week.)

### Week 2 — fleet capabilities

**Memory track (engineer A):**
- #50 day 6-8: ADR ingest (parse MADR format from `docs/adr/`),
  Stage-6 pipeline integration, composition-root wiring.
- #51 day 9-10: `ManagedAgentMemoryAdapter` skeleton + Memory Store
  provisioning helpers.

**Multi-cloud track (engineer B):**
- #14 day 6-8: feature-flag detection (`supports_prompt_cache`,
  `supports_memory_store`, `supports_adaptive_thinking`) + composition-
  root wiring. CLI flag plumbing (`--llm-backend`, `--region`).
- #15 day 9-10: ZDR flag, header assertion, report banner, startup
  validation.

### Week 3 — observability and alerting

**Memory track (engineer A):**
- #51 day 11-13: `ask_codebase_question` use case + citation
  enforcement + CLI surface + streaming.
- #52 day 14-15: `build_onboarding_brief` use case + 10-section
  template + markdown / HTML rendering.

**Multi-cloud track (engineer B):**
- #60 day 11-14: Rulebook schema (`docs/compliance/<framework>.yml`),
  `RulebookComplianceMapper` adapter, migration of the v0.7.0 keyword
  catalogue. Removes the deferred banner.
- #55 day 15: Skill manifest + signing pipeline + nightly NVD pull
  GitHub Action.

### Week 4 — integration, hardening, release

- Integration testing across all 8 capabilities; cross-cap regression
  pass on the leaderboard set (FastAPI / Spectra / HTTPX / Aider /
  LLM) under both Anthropic and Bedrock backends.
- Documentation pass: README updates for `spectra ask` / `spectra
  brief` / `--llm-backend` / `--zero-data-retention`; new
  `docs/architecture/adr/ADR-025.md` / `ADR-026.md` / `ADR-027.md`.
- Hardening pass: per-adapter retry + rate-limit semantics, ZDR
  validation, signed-Skill verification, paid-tier license check on
  `spectra ask`.
- v0.10.0 release: tag → publish.yml → PyPI + Sigstore.

### Cut points — what ships in v0.9.0 vs v0.10.0

The four-week plan above lands everything in v0.10.0. The conservative
fallback ships in two releases:

**v0.9.0 (week 2-3 release):**
- #50 per-repo memory (foundation)
- #14 multi-cloud LLM backends
- #15 ZDR mode
- #58 SBOM emission

**v0.10.0 (week 4-5 release):**
- #51 `spectra ask`
- #52 `spectra brief`
- #55 public knowledge skill
- #60 deterministic compliance mapping

The split is clean. v0.9.0 is "infrastructure: memory port + multi-
cloud + compliance hooks." v0.10.0 is "the second-brain layer landing
on top." A single-engineer cadence runs this as v0.9.0 in weeks 1-2,
v0.10.0 in weeks 3-6.

---

## Build / buy / partner matrix

| Capability | Decision | Rationale |
|---|---|---|
| Memory Store API (#51) | **Partner — Anthropic Memory Stores** | Native Anthropic primitive, zero-rebuild fit; cost model favours us at scale. |
| Local memory backend (#50) | **Build — `LocalFileMemoryAdapter`** | Keeps OSS CLI free; ADR-012 file-permission model already covers it. |
| CycloneDX SBOM (#58) | **Build — emit only; library used for serialization** | The CycloneDX Python lib is BSD; we use it for schema, write our own collection logic. |
| Bedrock + Vertex SDKs (#14) | **Buy — official boto3 + google-cloud-aiplatform** | No reason to roll our own; both are well-maintained. |
| CVE feed (#55) | **Partner — NVD JSON feeds + Sigstore-signed delivery** | NVD is the authoritative source; we wrap + sign the daily snapshot. |
| Compliance rulebook (#60) | **Build — YAML packs in `docs/compliance/`** | The mapping is opinionated and Spectra-specific; no off-the-shelf CWE → SOC 2 mapping is auditor-grade. |
| ZDR header semantics (#15) | **Buy — Anthropic / Bedrock / Vertex docs** | Each provider documents their ZDR contract; we just assert it. |
| ADR ingest parser (#50) | **Build — MADR format parser** | MADR is a 1-page spec; a 50-line parser is cheaper than pulling another dependency. |

---

## Open questions for the founder

1. **Memory-Store pricing tier — per-org-per-repo or per-org-flat?**
   · **Options:** A. Per-org-per-repo ($X / month / repo) · B. Per-org
   flat ($Y / month, unlimited repos) · C. Tiered (first 5 repos
   included, then per-repo) · **Recommendation:** **B for the launch
   tier; switch to C after the first 10 paid customers** if usage
   data shows long-tail repo counts. Reason: per-org-flat is the
   simplest sales motion and matches the "second-brain over your
   codebase" pitch; per-repo billing creates an arbitrage where
   customers split orgs to game it.

2. **`spectra ask` shipping in OSS or paid only?**
   · **Options:** A. Free in OSS CLI (Memory Store cost is the
   customer's Anthropic bill, not ours) · B. Paid-only feature-gated
   on a license · C. Free with `LocalFileMemoryAdapter` (no Memory
   Store), paid with `ManagedAgentMemoryAdapter` (Memory Store) ·
   **Recommendation:** **C.** OSS users get a degraded `spectra ask`
   that searches the local memory file (FTS5 keyword search,
   non-cited). Paid users get the full Memory-Store-backed answer
   with citations. Reason: the second-brain pitch needs the OSS
   demo to feel real; degraded-but-working is better than gated.

3. **Rulebook ownership for #60 — do we sell consulting on writing
   custom rule packs?**
   · **Options:** A. We ship one official pack per framework (SOC 2,
   PCI, OWASP, HIPAA, ISO 27001); customers extend it · B. We charge
   for vertical-specific extensions (HealthTech-HIPAA pack, FinTech-
   PCI pack) · C. We open the rulebook schema and let community
   maintain extensions; we curate the canonical set ·
   **Recommendation:** **A in Q4, evaluate B/C in Q5+.** Q4 needs the
   official packs to ship; consulting and community extensions are
   GTM motions that don't gate Q4 engineering.

4. **Bedrock + Vertex parity — is "all 8 agents work, but Memory
   Stores degraded to local" sufficient v1, or do we need full
   feature parity?**
   · **Options:** A. Ship feature-parity matrix; customers see what
   works on each backend · B. Block #14 release until Bedrock has
   Memory Store equivalent (Bedrock Knowledge Bases — different
   shape, similar semantics) · C. Ship Anthropic-only Memory Store
   in v0.10.0; add Bedrock Knowledge Bases in Q5 ·
   **Recommendation:** **A.** Per the product-roadmap §"Anthropic-
   native by default; portable by design," feature degradation on
   non-Anthropic backends is the documented contract. The matrix
   ships in `docs/compatibility-matrix.md`; the CLI surfaces a clear
   one-line note when an operator's backend doesn't support a
   requested feature.

5. **#52 `spectra brief` — single-call (one big LLM prompt with all
   sections) or composed (one LLM call per section, parallelized)?**
   · **Options:** A. Single-call, ~$0.50 per brief, p95 latency
   ~10s, narrative coherence is the LLM's responsibility · B.
   Composed, ~$0.20 per brief, p95 latency ~5s with parallelism,
   narrative coherence is the template's responsibility · C. Hybrid
   — sections are template-rendered, the *executive summary* at the
   top is one LLM call ·  **Recommendation:** **C.** Cost-efficient,
   latency-fast, and the LLM only touches the narrative summary
   where its strength matters. Falls out of the existing pipeline
   shape.

---

## Contradictions and risk flags

**Risk 1 — Memory Store deprecation.** Anthropic's Memory Store API is
in beta as of the v0.8.1 ship date. Schema changes between beta and GA
would force a `ManagedAgentMemoryAdapter` rewrite. **Mitigation:** the
`MemoryPort` Protocol is the Layer-2 boundary; rewrites are confined to
Layer 4. The `LocalFileMemoryAdapter` always works; in the worst case
we ship Q4 without `spectra ask`'s Memory-Store backing and fall back
to the FTS5-degraded mode (open question 2C, recommended option).

**Risk 2 — Bedrock / Vertex feature drift.** Bedrock added prompt cache
in 2026-Q1 but Vertex still lacks it. By Q4 ship date Vertex may have
caught up or may not. **Mitigation:** the per-adapter `supports_*`
flags absorb the drift; composition root reads them at startup; the
operator sees a clear note about degraded features. No code paths
hard-code provider-specific assumptions.

**Risk 3 — Compliance mapping gets attacked as "still keyword-y."**
The rulebook schema requires CWE traceability *and* file-pattern
matching, but reviewers may argue our CWE mapping is the new keyword
heuristic. **Mitigation:** every rule's CWE assignment cites the
authoritative CWE source (MITRE ID + URL); the rulebook YAML is signed
(Sigstore-style); the report row links to the CWE source so an auditor
can verify the trace. The mapping is opinionated, but the trace is
deterministic.

**Risk 4 — `spectra ask` cost exceeds $0.10/question target.** Memory
Store + cited Q&A on a large repo could blow the budget if prompt-cache
hit rates are low. **Mitigation:** the existing `--max-cost-usd` cap
applies to `spectra ask` too; the per-repo Memory Store namespace keeps
the prompt prefix stable for cache; we instrument cost-per-question in
the OTel spans so we can tune.

**Risk 5 — SBOM emission slows scans.** The 9-format manifest detector
+ lockfile parser adds I/O to every scan. **Mitigation:** SBOM
emission is opt-in via `--emit-sbom` (off by default); when on, the
detection runs once during Stage 1 (INGEST) and the results are cached
for the rest of the pipeline. Adds <500ms to a typical scan.

**Risk 6 — Two-engineer parallel cadence assumes hiring lands.** The
4-week wall-clock requires engineer B; today we have engineer A only.
**Mitigation:** the cut-point plan above (v0.9.0 weeks 1-2, v0.10.0
weeks 3-6) is the single-engineer fallback. Six weeks of focused
single-engineer work is realistic against the v0.8.1 baseline (2471
tests, all green, branch protection enforced).

---

## What ships and what defers (recap)

**Q4 ships (8 capabilities):**
- #50 Per-repo memory (`MemoryPort` + `LocalFileMemoryAdapter`)
- #51 `spectra ask` (Anthropic Memory Store + cited Q&A)
- #52 `spectra brief` (onboarding mode)
- #55 Public knowledge skill (CVE + framework deprecations, signed)
- #60 Deterministic compliance mapping (retires v0.7.0 banner)
- #14 Bedrock + Vertex sibling adapters + `--region` pinning
- #15 ZDR mode flag + visible banner
- #58 SBOM-of-analysed-repo (CycloneDX 1.5)

**Q4 defers (per product-roadmap):**
- #53 Cross-repo pattern surfacing (per-org Memory Store across repos) → **Q5** (needs the org-tier billing infra Q4 doesn't ship)
- #35-#38 Linear / GitLab / LSP / webhooks → **Q5** (the integration quarter)
- #41-#44 Vertical specialist Skills (HealthTech, FinTech, Defense) → **Q6** (needs the #55 Skills loading proven first)
- #16 BYO-LLM proxy → **Q5** (depends on #14 landing first; tier-2 priority)

**3 new ADRs:**
- ADR-025 — Memory Port + Managed Memory Store adapter
- ADR-026 — Multi-cloud LLM Gateway (Bedrock + Vertex sibling adapters)
- ADR-027 — Deterministic compliance mapping (retires v0.7.0 keyword heuristic)

**Tests target:** 2471 → ~2750 (+280 net). Coverage stays ≥85%.

**Forbidden-words check** (per CLAUDE.md): zero hits in this plan body
for the marketing terms banned in the brand voice. The plan reads as
engineering, not marketing.
