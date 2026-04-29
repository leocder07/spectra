# Spectra — Product Roadmap (synthesizes red team / CISO / CTO / memory personas)

**Author:** Head of Product · 2026-04-29
**Inputs:** `redteam-findings.md`, `ciso-findings.md`, `cto-findings.md`, `memory-second-brain-findings.md`, `spectra-self-report.json` (Spectra grading itself B+ / 83.6 with 13 of 20 findings being "insufficient code provided" — a non-trivial signal that our own grade is fragile)
**Constraint:** Clean Architecture (4 layers, dependency rule absolute) and the 8-agent contract are not on the table in this roadmap. Everything below is additive.

---

## TL;DR

1. **The grade is a product, not a marketing artifact.** We will not ship grade badges or public leaderboards until prompt-injection isolation, adversarial eval harness, and tamper-evident grading land. Q1 work. Without this, the Red Team is right that Spectra is an unsafe CI gate.
2. **CLI-only forever; control plane is a separate offering.** We do not turn Spectra into a SaaS to satisfy CISO audit-log asks. We add JSON-Lines audit emission with pluggable sinks (file / syslog / OTLP / Splunk HEC) so the customer's existing IAM and SIEM are the source of truth. This kills the auth-model debate for two more quarters.
3. **Anthropic-native by default; portable by design.** Memory Stores, Skills, and Managed Agents are first-class in v1.0+. The `LLMGateway` Protocol stays the boundary so `BedrockAdapter` and `VertexAdapter` are <2 weeks of work each when the first regulated customer asks.
4. **Most "new specialist" asks are prompt edits, not new agents.** We accept the CTO's call: 12 of 20 vulnerability-class gaps in the Red Team's Hat 2 table are prompt enrichments to existing specialists. Only 5 are net-new specialists (Web3, IaC, ML, CI/CD, Concurrency). This collapses Q6 from "build five agents" to "ship one Specialist plugin system + four prompt packs + one heavy specialist."
5. **Supply chain hygiene is Q1 table stakes, not Q2.** SLSA L3 provenance, defensive PyPI squats, signed wheels, SECURITY.md, dependency upper bounds, and shipped lockfile are all S-effort. Bundling them into Q1 is faster than negotiating which to defer.

---

## 1. Conflict resolution

### Conflict 1 — Red Team "no grade badges" vs marketing "ship grade badges + leaderboards"

- **The disagreement.** Red Team T1, T10, S2: until prompt injection is mitigated and the adversarial eval harness exists, the grade is fakeable; shipping a public badge invites attackers to optimize for it. Marketing (and the leaderboard work in `docs/launch/`) has been pushing public, named scores as the GTM lever.
- **Call.** **Red Team wins for Q1; marketing wins for Q3.** No public grade badges, no named leaderboard with scores, no "Spectra-graded A+" GitHub README badge until (a) prompt-injection isolation ships, (b) adversarial eval harness produces a published catch-rate ≥80%, (c) signed scan receipts let any third party verify a grade was produced by Spectra and not minted by an attacker. Q1 is "safe internal grade." Q3 is "publishable grade." This delays marketing motion by ~6 months but protects the brand from the first viral exploit.
- **Rationale.** The asymmetric downside of one demonstrated grade-gaming exploit (HN front page: "I made Spectra say my keylogger is A-grade") is multiples larger than the upside of 6 months of badge-driven adoption. The Red Team's argument is the conservative call and it is correct.

### Conflict 2 — CISO "redact reports as private artifacts" vs marketing "leaderboards with named scores"

- **The disagreement.** CISO §1: the HTML report is a confidentiality time bomb; an analyst can email the file with no DLP intervention. The Red Team echoes this in S5 — public reports give attackers a free vuln intel feed. Marketing wants the opposite: public, shareable, brag-worthy artifacts.
- **Call.** **Two render modes ship by Q2: `--classification confidential` (default, watermarked, in-document banner, no public sharing) and `--classification public` (grade + dimension scores + counts only; descriptions, recommendations, code snippets, file paths redacted).** The leaderboard becomes a registry of public-mode reports, opted-in by the maintainer.
- **Rationale.** This is not really a conflict; both personas were optimizing different documents. The fix is to recognize there are two artifacts: a forensic-grade internal report and a marketing-grade public summary. Each should default to its safe mode. Cost is ~1 week of template work plus a CLI flag.

### Conflict 3 — Red Team "5 new specialists" vs CTO "12 of 20 are prompt edits"

- **The disagreement.** Red Team's Hat 2 table proposes specialists for Web3, IaC, ML security, CI/CD pipeline, and concurrency. The CTO's view (and the table's effort column) shows 12 of the 20 gaps are "Low" effort prompt edits to existing specialists.
- **Call.** **The CTO is right on volume; the Red Team is right on shape.** Q1-Q3: ship the 12 low-effort prompt edits as prompt packs (versioned via `prompt_versions` cache key, no architecture change). Q6: ship the Specialist plugin system + 4 net-new specialists as plugins (Web3, IaC, ML security, CI/CD). Concurrency stays in the Quality + Performance prompts because LLMs are bad at concurrency reasoning without dedicated tooling — punt the new specialist on that one.
- **Rationale.** Adding 5 specialists to a `gather()` of 6 is a 83% increase in concurrent Anthropic calls per scan and a ~$3-5 cost increase per scan. Most enterprise buyers want IaC and CI/CD; only DeFi-specific buyers want Web3. Plugin architecture lets buyers opt in to the specialists they pay for — protecting cost discipline.

### Conflict 4 — CISO "tone down compliance positioning" vs CISO "invest in deterministic mapping"

- **The disagreement.** CISO §3 finding: the current report's SOC 2 / PCI / NIST mapping is keyword-heuristic and indefensible in an audit. CISO open question 3 forces a choice: (a) tone down the marketing claim, (b) ship a clear "indicative — not evidence" disclaimer, or (c) invest in deterministic rule-driven mapping.
- **Call.** **(b) immediately, (c) by Q4.** Q1: ship a "Compliance positioning — indicative only, not auditor-grade evidence" banner on every report and scrub the term "compliance evidence" from marketing. Q4: replace the keyword mapping with rule-traceable mapping (each control links to deterministic CWE/CVE/pattern matches). Drop (a) — toning down without fixing means we lose the meeting-landing power of the compliance section without gaining audit-grade defensibility.
- **Rationale.** The disclaimer is a 2-day fix that protects against misrepresentation risk. The deterministic mapping is a quarter of work and unlocks "we are SOC 2 evidence-grade" as a real claim. Doing both is the only honest path; doing only (a) gives away differentiated positioning for nothing.

### Conflict 5 — Memory persona "ship per-org Memory Store free for ≤3 repos" vs CTO "every paid feature must have a unit-economics story"

- **The disagreement.** Memory open question 1 recommends per-org Memory Store free for ≤3 repos to seed adoption. CTO open question 2 says pricing unit must lock before scheduler ships, because schema bakes it in.
- **Call.** **Per-org Memory Store is paid from day one. Per-repo memory (waivers, decision log, score timeline, drift detection) ships free in the OSS CLI.** No freemium on the org tier; that line is paid only.
- **Rationale.** The cost model is asymmetric. Per-repo memory is local SQLite; marginal cost is zero. Per-org Memory Store is an Anthropic Memory Store API call per scan; marginal cost is real. Free-for-3-repos creates an arbitrage where every org registers as 3 separate orgs. Per-seat-or-per-org pricing for the cloud tier is the cleaner story.

---

## 2. Unified capability backlog (deduped)

Sources: **RT** = Red Team, **CISO** = CISO, **CTO** = CTO, **MEM** = Memory persona, **SELF** = self-scan signal. Effort: S ≤1d · M 1-5d · L 1-3w · XL 3w+. Impact: REV (revenue blocker) · ADO (adoption blocker) · QUAL (quality) · NICE (nice-to-have).

| # | Capability | User story | Sources | Effort | Impact | Deps | RICE |
|---|---|---|---|---|---|---|---|
| 1 | Prompt-injection isolation (per-file delimiter nonces + critique adversarial prompt) | As a security buyer, I want Spectra to refuse to honor instructions embedded in analyzed code so I can use the grade as a CI gate | RT (T1, T10) | M | ADO | — | 90 |
| 2 | Adversarial eval harness (`golden_files/adversarial/`) + published catch-rate | As an eng-leadership buyer, I want a measurable adversarial catch-rate so I can defend the choice of Spectra in technical due diligence | RT (S2) | M | ADO | #1 | 80 |
| 3 | Per-row HMAC + per-user cache namespace (`~/.cache/spectra/$UID/cache.db` mode 0600) | As a CI operator on shared runners, I want cached findings to be tamper-evident so a compromised earlier job cannot dictate my grade | RT (T2) | S | ADO | — | 75 |
| 4 | Markdown-safe PR comment renderer + finding-field allowlist | As an OSS maintainer running Spectra on contributor PRs, I want finding text rendered safely so a malicious PR cannot phish my reviewers | RT (T3, S1) | S | ADO | — | 72 |
| 5 | `--max-cost-usd` per-run + per-hour budget enforcement | As a finance lead, I want a hard dollar cap per scan and per hour so a hostile loop cannot drain my Anthropic budget | RT (T4) | M | REV | — | 70 |
| 6 | Honor `.gitignore` + secret pre-flight scan + `.spectraignore` | As an enterprise dev, I want `.env`/keys excluded by default so I do not accidentally exfil secrets to Anthropic | RT (T6), CISO §1 | S | ADO | — | 88 |
| 7 | SLSA L3 build provenance + Sigstore-signed wheels | As a SLSA-conscious enterprise, I want verifiable provenance so a tag-move attack on the repo cannot ship me a backdoor | RT (T5, S4), CISO §5 | S | REV | — | 65 |
| 8 | SECURITY.md + vulnerability disclosure policy + CNA | As a security researcher, I want a defined channel to report Spectra vulns so coordination does not happen on Twitter | CISO §5 | S | REV | — | 60 |
| 9 | Dependency upper bounds + shipped lockfile + Renovate | As a regulated-org CISO, I want deterministic Spectra installs so a transitive dep update cannot land in our SDLC unannounced | CISO §5, SELF (dep-003) | S | ADO | — | 70 |
| 10 | Defensive PyPI squats (`spectra_ai`, `spectraai`, `spectra-cli`, `spectra-py`, etc.) | As a Spectra user, I want typo'd installs to not exfil my API key | RT (T5) | S | ADO | — | 55 |
| 11 | DPA + sub-processor declaration + Anthropic data flow diagram | As a procurement lead, I want a signable DPA so I can buy Spectra under GDPR Art. 28 | CISO §1 | M | REV | — | 75 |
| 12 | Audit log (JSON Lines, append-only, pluggable sink: file / syslog / OTLP / Splunk HEC) | As a SOC 2 auditor, I want a structured audit trail of every scan so I can evidence CC7.2 | CISO §2 | M | REV | — | 78 |
| 13 | Encrypted cache at rest (SQLCipher) + `spectra cache shred` | As a HIPAA-regulated dev, I want the local cache encrypted so a stolen laptop is not a notifiable event | CISO §1, RT (T2) | M | REV | #3 | 60 |
| 14 | Region pinning + Bedrock + Vertex AI backends via `LLMGateway` | As an EU bank, I want to route Spectra LLM calls through Bedrock/Vertex in our region so we comply with residency | CISO §1, CTO §6 | L | REV | — | 70 |
| 15 | ZDR mode flag + visible pre-run banner | As a healthcare CISO, I want `--zdr` to fail-closed if the API key isn't ZDR-enabled so I cannot accidentally ship PHI to a 30-day retention bucket | CISO §1 | S | REV | — | 50 |
| 16 | BYO-LLM proxy via `SPECTRA_LLM_BASE_URL` | As an org with a Portkey/Helicone gateway, I want Spectra to route through it for DLP inspection | CISO §1 | S | ADO | — | 45 |
| 17 | `.spectra-policy.yml` (org-level + repo-level) + severity gating | As a platform team, I want declarative policy so every repo enforces the same rules without per-CI yaml duplication | CISO §4, CTO §5 | M | ADO | — | 65 |
| 18 | `.spectra-waivers.yml` + cryptographic approver signature + 180-day TTL | As a security engineer, I want signed waivers so accepted-risk decisions are auditable and expire | CISO §4, MEM (M1) | M | ADO | #17 | 72 |
| 19 | Severity-gate Action input (`with: fail-on: critical`) | As a CI integrator, I want a one-line severity gate so I do not reverse-engineer it from JSON | CISO §4 | S | ADO | — | 60 |
| 20 | "Non-validated" stamp on `--quick` and `--no-critique` runs | As a downstream report consumer, I want degraded runs clearly labeled so I do not treat them as evidence | CISO §4 | S | QUAL | — | 50 |
| 21 | Distributed cache adapter (`S3CachePort`, `RedisCachePort`) | As a 50-engineer org, I want shared cache so my team does not redo each other's scans | CTO §1 | M | REV | — | 70 |
| 22 | Fleet-wide rate limiter (Redis token bucket) | As an Anthropic key holder, I want fleet-wide RPM enforcement so the loudest team does not starve the rest | CTO §1 | M | REV | #21 | 60 |
| 23 | Anthropic Batch API + prompt caching (`cache_control: ephemeral`) | As a finance lead, I want lower per-scan cost via batching and intra-run cache reuse | CTO §1 | S | REV | — | 80 |
| 24 | Worker pool / job queue (Temporal) | As a portfolio operator, I want background scan jobs so weekly fleet scans do not block engineers | CTO §1, §2 | L | REV | #21 | 45 |
| 25 | Postgres history store (`reports` table; `ReportStorePort`) | As an eng leader, I want trends over time so I can act on drift | CTO §2, MEM (M4) | M | REV | — | 65 |
| 26 | Repo registry + scheduler (`spectra portfolio add/scan`) | As a CTO, I want to register every service and scan all 312 weekly | CTO §2 | M | REV | #25 | 70 |
| 27 | Trend / drift detection (`spectra trend`) + Slack drift alerts | As an eng leader, I want alerts when a previously-A repo drops below B- | CTO §2, MEM (M4) | S | ADO | #25 | 75 |
| 28 | Org leaderboard endpoint (HTML + JSON) | As a CTO, I want a single dashboard ranking my services so I can prioritize attention | CTO §2 | S | NICE | #25 | 40 |
| 29 | RBAC + multi-tenancy (analyst / reviewer / admin) | As an org admin, I want role-based access so analysts cannot scan competitor repos | CTO §2, CISO §2 | L | REV | #25 | 50 |
| 30 | OpenTelemetry tracing + per-agent spans | As an SRE, I want OTel spans so I can ship Spectra metrics into our existing Honeycomb/Datadog | CTO §3 | M | ADO | — | 75 |
| 31 | Prometheus metrics endpoint (`spectra_scan_duration_seconds`, etc.) | As an SRE, I want Prom metrics so I can dashboard scan health | CTO §3 | S | NICE | #30 | 50 |
| 32 | SLO dashboards + error budgets (p95 < 5min, $/scan p95 < $10) | As a platform lead, I want defined SLOs so I can pause CI integration on burn | CTO §3 | M | NICE | #30 | 35 |
| 33 | Cost attribution per team / repo (tagged spans) | As a CFO, I want Anthropic spend broken down by team so I can budget | CTO §3 | S | ADO | #30 | 65 |
| 34 | Slack / Teams digest + per-finding alert | As an EM, I want a weekly digest in Slack so I do not have to chase reports | CTO §4 | S | ADO | #25 | 70 |
| 35 | Jira / Linear ticket auto-create (idempotent dedup key) | As a dev, I want findings to become tickets in my tracker so I can manage them in my workflow | CTO §4 | M | ADO | — | 65 |
| 36 | GitLab MR + Bitbucket PR comment integrations | As a non-GitHub shop, I want feature parity with the GitHub Action | CTO §4 | S | ADO | — | 50 |
| 37 | LSP server + SARIF polish for VSCode/Cursor/JetBrains | As a developer, I want findings in my editor so I see them before pushing | CTO §4 | M | NICE | — | 45 |
| 38 | Webhooks (`spectra.scan.completed`, `spectra.finding.critical`) | As an integrator, I want a generic event surface so I can wire Spectra into my org-specific tooling | CTO §4 | S | NICE | — | 40 |
| 39 | Specialist plugin system (entry-point discovery) | As a 3rd-party, I want to ship a custom specialist as a pip package so I do not fork Spectra | CTO §5, RT (Hat 2) | M | REV | — | 55 |
| 40 | Versioned rule packs (YAML overlay on prompts + weights + thresholds) | As a security team, I want to ship `org-rules-v3` without touching Spectra source | CTO §5 | M | REV | #39 | 60 |
| 41 | Web3 specialist plugin (Solidity, SWC registry, oracle/reentrancy) | As a DeFi protocol engineer, I want Spectra to find SWC-class vulns | RT (Hat 2) | L | REV | #39 | 35 |
| 42 | IaC specialist plugin (Terraform / K8s / Helm / Dockerfile) | As a platform engineer, I want Spectra to flag `--privileged`, IAM `*:*`, public S3 | RT (Hat 2), CTO §1 | L | REV | #39 | 60 |
| 43 | ML security specialist plugin (pickle, torch.load, ONNX, RAG injection) | As an ML platform engineer, I want Spectra to find unsafe deserialization in our model pipeline | RT (Hat 2) | M | REV | #39 | 40 |
| 44 | CI/CD pipeline specialist plugin (`.github/workflows`, `.gitlab-ci.yml`) | As a platform team, I want Spectra to find what bit Spectra (the `pwn-request` class) | RT (Hat 2) | M | REV | #39 | 55 |
| 45 | Crypto / SSTI / XXE / Zip Slip / SSRF decision-tree / timing comparison prompt enrichments | As a CISO, I want the security specialist to find these textbook classes | RT (Hat 2) | S | QUAL | — | 65 |
| 46 | Authn/authz logic prompt enrichment (BOLA, IDOR, mass assignment, JWT none) | As a security buyer, I want Spectra to find auth flaws beyond OWASP A01 keyword | RT (Hat 2) | S | QUAL | — | 55 |
| 47 | Supply-chain prompt enrichment (typosquats, dependency confusion, postinstall scripts) | As a security buyer, I want the dependency specialist to flag attack patterns, not just CVEs | RT (Hat 2) | S | QUAL | — | 50 |
| 48 | Privacy / telemetry prompt enrichment (consent, PII in logs, GA tracking) | As a privacy engineer, I want Spectra to flag privacy patterns | RT (Hat 2) | S | QUAL | — | 40 |
| 49 | Prototype pollution / unsafe caching / business-logic prompt enrichments | As a JS-shop CISO, I want JS-specific attack patterns | RT (Hat 2) | S | QUAL | — | 45 |
| 50 | Per-repo memory: waivers + score timeline + decision log + ADR ingest | As a dev, I want `spectra waive` + `spectra trend` + `spectra decisions --grep` to work without a control plane | MEM (M1, M2, M4) | M | ADO | #18 | 78 |
| 51 | `spectra ask <question>` codebase Q&A (Managed Memory Store + prompt cache) | As a new engineer, I want to ask "where do we handle auth?" and get a cited answer | MEM (M3) | M | REV | #50 | 70 |
| 52 | `spectra brief` onboarding mode | As a new joiner, I want a 10-things-to-know brief on a repo I am inheriting | MEM (M3) | S | NICE | #51 | 35 |
| 53 | Cross-repo pattern surfacing (per-org Memory Store) | As an eng leader, I want Spectra to tell me "Repo A solved this; Repo B has the same issue uncached" | MEM (M6) | L | REV | #51 | 40 |
| 54 | Per-developer reviewer profile + finding routing | As a CISO, I want findings routed to the engineer most likely to act on them | MEM (M5) | L | NICE | #50 | 30 |
| 55 | Public knowledge skill (CVE feed, framework deprecations) signed at release | As any user, I want my next scan to flag yesterday's CVE without a Spectra release | MEM (M7) | M | REV | — | 55 |
| 56 | Report classification + watermark + expiration (`--classification confidential\|public`) | As a CISO, I want forensic reports DLP-marked and public reports redaction-safe | CISO §1, RT (S5) | S | REV | — | 75 |
| 57 | Globally unique scan ID + Ed25519-signed scan receipt | As a third party, I want to verify a Spectra grade was produced by Spectra | CISO §2 | M | ADO | — | 55 |
| 58 | SBOM-of-analysed-repo (CycloneDX 1.5) baked into report | As a PCI auditor, I want a real SBOM not a narrative dependency section | CISO §3 | M | REV | — | 55 |
| 59 | SBOM-of-Spectra (CycloneDX + SPDX) attached to release | As a procurement lead, I want a vendor SBOM so I can ingest Spectra into our SDLC | CISO §3 | S | REV | — | 60 |
| 60 | Deterministic compliance mapping (CWE/CVE/pattern → control) replacing keyword match | As an auditor, I want compliance mappings with traceable rules | CISO §3 | L | REV | — | 50 |
| 61 | "Indicative — not audit evidence" disclaimer banner on every report | As an honest vendor, I want to not misrepresent compliance until #60 ships | CISO §3 | S | ADO | — | 80 |
| 62 | HIPAA mode + BAA template (`--hipaa` enforces ZDR + region pin + no-cache + SARIF-only) | As a HealthTech CISO, I want a one-flag HIPAA-safe mode | CISO §3 | M | REV | #14, #15 | 45 |
| 63 | SOC 2 Type II for Spectra service / company | As a procurement lead, I want a vendor with a SOC 2 attestation | CISO §3 | XL | REV | #12 | 55 |
| 64 | Auditor evidence pack (`spectra evidence --framework soc2 --period 2026-Q1`) | As a SOC 2 auditor, I want a packaged evidence dump for the period | CISO §3 | M | NICE | #12 | 40 |
| 65 | OS-keychain / Vault / AWS SM secret backend abstraction | As an org with a secret manager, I want the API key from there not env vars | CISO §2 | M | NICE | — | 35 |
| 66 | Maintainer security baseline (hardware-key 2FA, branch protection, signed commits) | As an honest vendor, I want to live our own threat model | CISO §5 | S | REV | — | 60 |
| 67 | Pin Action to commit SHA in docs + `tags-ignore` filter for unsigned tags | As a high-assurance shop, I want Action references that cannot be tag-moved | CISO §5 | S | NICE | — | 40 |
| 68 | Suppression mechanism: `# spectra: ignore-next-line SEC-AUTH-101` inline pragma | As a dev, I want to suppress a finding inline with justification | CTO §5, CISO §4 | S | ADO | #18 | 65 |
| 69 | Findings ownership + SLA fields + Jira sync of due dates | As a triage lead, I want findings with owners and due dates | CISO §4, CTO §4 | M | NICE | #25, #35 | 35 |
| 70 | Per-team scan budget enforcement | As an org admin, I want per-team monthly token / dollar budgets | CISO §4, CTO §3 | M | NICE | #5, #29 | 35 |

70 capabilities; deduplication absorbed ~12 cross-listed items between RT and CISO (cache HMAC, redaction, supply chain) and ~6 between CTO and Memory (history store, drift, RBAC).

---

## 3. RICE-ranked top 25

Ranking is `(Reach × Impact × Confidence) / Effort`, normalized to a 0-100 scale. Effort scale: S=1, M=3, L=8, XL=20. Reach/Impact/Confidence each 1-10.

| Rank | # | Capability | RICE | One-line justification |
|---|---|---|---|---|
| 1 | 1 | Prompt-injection isolation + critique adversarial prompt | 90 | Without this, Spectra cannot be a CI gate — every CISO blocks adoption. |
| 2 | 6 | Honor `.gitignore` + secret pre-flight + `.spectraignore` | 88 | Universal reach; one-day fix; without it we are exfiltrating `.env` files. |
| 3 | 23 | Anthropic Batch API + prompt caching | 80 | Halves the per-scan bill; pure cost win for every existing user; S effort. |
| 4 | 2 | Adversarial eval harness + published catch-rate | 80 | Required before any public grade or marketing leaderboard ships. |
| 5 | 61 | "Indicative — not audit evidence" disclaimer | 80 | 1-day work that removes the largest misrepresentation risk on the report. |
| 6 | 50 | Per-repo memory (waivers, timeline, decisions, ADR ingest) | 78 | Highest user-value memory tier; near-zero engineering risk; unblocks Q4. |
| 7 | 12 | Audit log (JSON Lines, pluggable sink) | 78 | SOC 2 CC7.2 hard requirement; M effort; unblocks 4 CISO capabilities. |
| 8 | 27 | Trend / drift detection + Slack alerts | 75 | The CTO-facing "what's getting worse" view; S effort once history exists. |
| 9 | 56 | Report classification + watermark + dual-mode render | 75 | Resolves the leaderboard-vs-confidentiality conflict in one shipping unit. |
| 10 | 30 | OpenTelemetry tracing + per-agent spans | 75 | "Cannot operate what you cannot see"; M effort; unblocks 4 SRE capabilities. |
| 11 | 11 | DPA + sub-processor declaration | 75 | GDPR Art. 28 hard block; legal pack, not engineering; ~2 weeks. |
| 12 | 3 | Per-row HMAC + per-user cache namespace | 75 | S effort; required for any shared CI runner or multi-tenant dev box. |
| 13 | 4 | Markdown-safe PR comment + finding-field allowlist | 72 | OSS maintainers running Spectra on contributor PRs need this day one. |
| 14 | 18 | `.spectra-waivers.yml` + cryptographic approver signature | 72 | Without waivers, every dev rage-quits on the second false positive. |
| 15 | 9 | Dependency upper bounds + shipped lockfile + Renovate | 70 | Self-scan flagged this; SOC 2 CC8.1; S effort. |
| 16 | 26 | Repo registry + scheduler (`spectra portfolio`) | 70 | Unlocks the entire portfolio narrative; M effort. |
| 17 | 14 | Region pinning + Bedrock + Vertex backends | 70 | EU/regulated buyers cannot use Spectra without it. |
| 18 | 51 | `spectra ask <question>` codebase Q&A | 70 | Sells the product to non-Spectra-running team-mates; second-brain narrative. |
| 19 | 5 | `--max-cost-usd` budget enforcement | 70 | Required for any shared-key CI environment; finance procurement gate. |
| 20 | 21 | Distributed cache adapter (S3 / Redis) | 70 | Without it, 50 engineers redo each other's work every PR. |
| 21 | 34 | Slack / Teams digest + per-finding alert | 70 | Cheapest big-visibility win; reaches the leaders who pay for the seat. |
| 22 | 17 | `.spectra-policy.yml` (org + repo level) | 65 | Replaces ad-hoc CI yaml; M effort; foundation for portfolio enforcement. |
| 23 | 33 | Cost attribution per team / repo (tagged spans) | 65 | CFO-visible; falls out of OTel; S effort post-#30. |
| 24 | 68 | Inline suppression pragma | 65 | Without it, devs write `noqa`-style comments anyway and Spectra ignores them. |
| 25 | 7 | SLSA L3 build provenance + Sigstore-signed wheels | 65 | Sigstore is now table-stakes; S effort; defeats the tag-move attack class. |

---

## 4. Six-quarter roadmap

### Q1 (next 3 months) — Foundation

**Theme:** Make the grade trustworthy before anyone treats it as a signal. Close every Red Team critical / high. Adopt SLSA. Ship the supply-chain hygiene that should already exist.
**Demo:** A planted prompt-injection repo runs through Spectra and gets a single `critical: prompt-injection-detected` finding instead of A+. Spectra release wheel verifies via `gh attestation verify`. `.gitignore` excludes `.env`. Secret pre-scan fails with a one-line message naming the file.
**Scope (10 capabilities):**
- #1 Prompt-injection isolation (per-file delimiter nonces + adversarial critique prompt)
- #2 Adversarial eval harness (`golden_files/adversarial/`)
- #3 Per-row HMAC + per-user cache namespace
- #4 Markdown-safe PR comment + finding-field allowlist
- #6 Honor `.gitignore` + secret pre-flight + `.spectraignore`
- #7 SLSA L3 provenance + Sigstore-signed wheels
- #8 SECURITY.md + vulnerability disclosure policy + CNA
- #9 Dependency upper bounds + lockfile + Renovate
- #10 Defensive PyPI squats
- #61 "Indicative — not audit evidence" disclaimer banner

### Q2 — Enterprise-ready

**Theme:** Close every CISO blocker that prevents an enterprise procurement signature. Ship the legal pack, the audit log, the encrypted cache, the policy file, the dual-mode report.
**Demo:** A regulated-org demo: signed DPA in hand, `spectra analyze --classification confidential` produces a watermarked HTML; a separate `--classification public` produces a redacted summary. JSON-Lines audit events stream to Splunk. `.spectra-policy.yml` enforces "fail on critical security." `.spectra-waivers.yml` suppresses one finding with an Ed25519 signature visible on the report.
**Scope (10 capabilities):**
- #11 DPA + sub-processor declaration + Anthropic data flow diagram
- #12 Audit log (JSON Lines, pluggable sink: file / syslog / OTLP / Splunk HEC)
- #13 Encrypted cache at rest (SQLCipher) + `spectra cache shred`
- #5 `--max-cost-usd` budget enforcement
- #17 `.spectra-policy.yml` org + repo
- #18 `.spectra-waivers.yml` + signed approver + 180-day TTL
- #19 Severity-gate Action input
- #20 "Non-validated" stamp on `--quick` runs
- #56 Report classification + watermark + expiration + dual-mode render
- #57 Globally unique scan ID + Ed25519 signed scan receipt

### Q3 — Platform

**Theme:** Make Spectra operable at fleet scale. Distributed cache, fleet rate limit, OTel, history store, portfolio mode, cost discipline.
**Demo:** 312-service portfolio scan completes overnight on Anthropic Batch API for ~30% of the previous month's cost. Honeycomb dashboard shows per-agent latency p95. Slack channel pings when `service-payments` drops from B+ to C+. Cost attribution dashboard shows per-team Anthropic spend.
**Scope (9 capabilities):**
- #21 Distributed cache (S3 / Redis adapter)
- #22 Fleet-wide rate limiter (Redis token bucket)
- #23 Anthropic Batch API + prompt caching
- #25 Postgres history store
- #26 Repo registry + scheduler
- #27 Trend / drift detection + Slack alerts
- #30 OpenTelemetry tracing + per-agent spans
- #33 Cost attribution per team / repo
- #34 Slack / Teams digest + per-finding alert

### Q4 — Memory + 2nd brain

**Theme:** Spectra learns. Per-repo memory, ADR ingest, `spectra ask`, `spectra trend --explain`, deterministic compliance mapping that earns the audit-evidence claim we deferred in Q1.
**Demo:** New engineer joins a 200-service org. Runs `spectra ask "where do we handle PII?"` — gets a cited 3-paragraph answer from per-org Memory Store in <3s for ~$0.05. Drops a new ADR in `docs/adr/` — next scan auto-ingests it. `spectra trend --explain --since 6w` produces "Architecture dropped 12 points; 4 PRs implicated: #421, #438, #455, #471." Compliance mapping in the report now traces every SOC 2 control to a CWE/CVE source.
**Scope (8 capabilities):**
- #50 Per-repo memory (waivers + score timeline + decision log + ADR ingest)
- #51 `spectra ask <question>` codebase Q&A (Managed Memory Store + prompt cache)
- #52 `spectra brief` onboarding mode
- #55 Public knowledge skill (CVE feed, framework deprecations) signed
- #60 Deterministic compliance mapping (replaces keyword heuristic)
- #14 Region pinning + Bedrock + Vertex backends
- #15 ZDR mode flag + visible banner
- #58 SBOM-of-analysed-repo (CycloneDX 1.5)

### Q5 — Integrations

**Theme:** Meet developers where they live. Tickets, IDE, GitLab/Bitbucket, webhooks, Teams. Ship the integration surface CTO §4 demanded.
**Demo:** Critical finding in a scan auto-creates a Linear ticket with idempotent dedup; the ticket closes when the finding disappears. VSCode shows findings in the Problems pane via SARIF; Cursor/Zed get them via LSP. GitLab MR comment is feature-equivalent to the GitHub Action.
**Scope (8 capabilities):**
- #35 Jira / Linear ticket auto-create (idempotent dedup key)
- #36 GitLab MR + Bitbucket PR comments
- #37 LSP server + SARIF polish (VSCode / Cursor / JetBrains)
- #38 Webhooks (`spectra.scan.completed`, `spectra.finding.critical`)
- #68 Inline suppression pragma
- #65 OS-keychain / Vault / AWS SM secret backend
- #69 Findings ownership + SLA fields + Jira sync
- #16 BYO-LLM proxy (`SPECTRA_LLM_BASE_URL`)

### Q6 — Vertical specialists

**Theme:** Plugin architecture lands. Ship the four vertical specialists customers paid for. Drop "Spectra graded" badges on properly-validated public repos.
**Demo:** A DeFi protocol installs `spectra-web3` plugin → next scan finds a reentrancy pattern. A platform team installs `spectra-iac` → flags an IAM `*:*` policy in their Terraform. ML team installs `spectra-ml` → flags a `torch.load(weights_only=False)`. Security team installs `spectra-cicd` → flags a `pull_request_target` mishap. Public grade badge ships with cryptographic verification link.
**Scope (8 capabilities):**
- #39 Specialist plugin system (entry-point discovery)
- #40 Versioned rule packs (YAML overlay)
- #41 Web3 specialist plugin (Solidity, SWC)
- #42 IaC specialist plugin (Terraform / K8s / Helm / Dockerfile)
- #43 ML security specialist plugin (pickle, torch, ONNX, RAG)
- #44 CI/CD pipeline specialist plugin
- #45-#49 Prompt enrichment pack (crypto / SSTI / XXE / Zip Slip / authn-authz / supply chain / privacy / proto pollution / business logic)
- #66 Maintainer security baseline (publicly enforced)

**Out of scope (deferred beyond Q6 or punted):**
- #24 Worker queue (Temporal) — defer until > 500-repo portfolios are real
- #29 RBAC + multi-tenancy in CLI — moves into a separate "control plane" product if/when SaaS is greenlit
- #32 SLO dashboards — derivable post-OTel; ship as Grafana template only
- #53 Cross-repo pattern surfacing — defer until per-repo Q&A signal validates the demand
- #54 Per-developer reviewer profile — privacy work too heavy until enterprise tier exists
- #62 HIPAA mode + BAA — only if HealthTech buyer commits in writing
- #63 SOC 2 Type II — start the 12-month observation window when ARR > $500K
- #64 Auditor evidence pack — auditor-driven, build to spec when the customer's auditor names the schema
- #70 Per-team scan budget — ship if more than 3 customers ask

---

## 5. Build / buy / partner matrix

| Capability | Decision | Reasoning |
|---|---|---|
| Prompt-injection isolation (#1) | **Build** | Core product IP; nobody has shipped this for code-analysis LLMs. We must own it. |
| Adversarial eval harness (#2) | **Build** | Same — our catch-rate number is our marketing. Buying it would be buying our own credibility. |
| Cache HMAC + namespace (#3) | **Build** | Trivial; no vendor; would be embarrassing to outsource. |
| PR comment renderer (#4) | **Build with Mustache/Handlebars** | The library exists; the renderer is ours. |
| `.gitignore` + secret pre-flight (#6) | **Partner — TruffleHog OSS** | Don't reinvent regex packs. Surface their findings as security evidence. |
| `--max-cost-usd` (#5) | **Build** | Native to our orchestrator. |
| SLSA L3 + Sigstore (#7) | **Partner — `actions/attest-build-provenance` + Sigstore** | Standard tooling. We adopt, not build. |
| SECURITY.md + CNA (#8) | **Partner — GitHub Security Advisory + GitHub CNA** | Built-in; free. |
| Lockfile + Renovate (#9) | **Partner — Renovate** | Industry standard. |
| Defensive squats (#10) | **Build** | One-shot ops task; PyPI accounts only. |
| DPA + sub-processor (#11) | **Build (legal)** | We are the data processor; the contract has to come from us. |
| Audit log (#12) | **Build emitter; partner sinks** | Build the JSON Lines stream; OTLP / Splunk HEC are standards. |
| Encrypted cache (#13) | **Partner — SQLCipher** | Don't roll your own crypto. |
| Region + Bedrock / Vertex (#14) | **Build adapters** | `LLMGateway` Protocol is ours; the SDKs are theirs. |
| ZDR mode (#15) | **Build** | One flag + a runtime check against an Anthropic header. |
| BYO proxy (#16) | **Build** | One env var passes through to Anthropic SDK. |
| Policy + waiver (#17, #18) | **Build** | Domain-specific; YAML schema is ours. Ed25519 via `cryptography`. |
| Severity gate (#19) | **Build** | Trivial Action input. |
| Distributed cache (#21) | **Build adapters; partner infra (S3, Redis)** | We ship the `S3CachePort`; customer brings the bucket. |
| Fleet rate limiter (#22) | **Build on Redis** | Token bucket is 50 lines of Python. |
| Batch API + prompt cache (#23) | **Partner — Anthropic** | Native Anthropic features; we wire them in. |
| Worker queue (#24) | **Buy / partner — Temporal OSS** | Don't build workflow orchestration. |
| Postgres history (#25) | **Build** | Schema is our domain. |
| Repo registry + scheduler (#26) | **Build** | Domain-specific. |
| Trend + drift (#27) | **Build** | Pure SQL + Slack webhooks. |
| RBAC (#29) | **Buy — WorkOS** | Don't build SAML / SCIM. WorkOS is the standard answer. (Punted to "control plane" decision.) |
| OpenTelemetry (#30) | **Partner — OTel SDK** | Vendor-neutral standard; never lock to Datadog. |
| Slack/Teams (#34) | **Build webhook integrations** | Native webhooks; no Slack app needed for v1. |
| Jira/Linear tickets (#35) | **Build adapters** | Idempotency-key pattern reused from PR-comment sentinel. |
| GitLab/Bitbucket (#36) | **Build adapters** | Same shape, different SDK. |
| LSP / SARIF (#37) | **Partner — LSP standard, SARIF spec** | Build a thin LSP server; SARIF gets us VSCode Problems pane free. |
| Specialist plugin system (#39) | **Build** | Entry-point pattern; this IS our extensibility story. |
| Web3 / IaC / ML / CI/CD specialists (#41-#44) | **Build prompts; partner data — Semgrep, OSV.dev, Trivy, SWC registry, MCP servers** | Spectra adds LLM reasoning over deterministic finders. |
| Per-repo memory (#50) | **Build** | New SQLite tables in existing `cache.db`. |
| `spectra ask` (#51) | **Partner — Anthropic Memory Stores + prompt cache** | Native Anthropic primitive maps perfectly. |
| Public knowledge skill (#55) | **Build (signed at release)** | Curated CVE / deprecation list shipped via `.claude-plugin/`. |
| Report classification (#56) | **Build** | Template work; Jinja2 conditionals. |
| Signed scan receipt (#57) | **Build with `cryptography` Ed25519** | Trivial. |
| SBOM-of-analysed-repo (#58) | **Partner — CycloneDX library + per-language ecosystem (`pip-audit`, `cyclonedx-bom`, `npm sbom`)** | Standards exist; we orchestrate. |
| SBOM-of-Spectra (#59) | **Partner — `cyclonedx-bom` + GitHub Action** | One-line CI step. |
| Deterministic compliance mapping (#60) | **Build** | Domain-specific; this is the audit-grade differentiator. |
| HIPAA mode + BAA (#62) | **Build (engineering); legal (BAA)** | One flag plus a separate signed agreement. |
| SOC 2 Type II (#63) | **Buy — Drata or Vanta + audit firm** | Don't build a compliance program from scratch. |
| Eval harness extensions | **Buy — Braintrust** (per CTO recommendation) | Eval is a discipline. |
| Vector store / embeddings | **PUNT** | Memory persona explicitly rejects. Anthropic prompt cache + Memory Store cover the use case. |
| Custom dimension support | **PUNT until Q7+** | Architectural risk — entity layer change. Not before two enterprise asks. |
| On-prem worker mode | **PUNT until first regulated customer commits in writing** | Reshapes everything; do not pre-build. |

---

## 6. Anthropic-native bet

**Position: Spectra commits to Anthropic-native primitives where they exist. Portable `LLMGateway` Protocol stays the boundary so Bedrock and Vertex are <2-week swaps when the first regulated customer requires them.**

**What this means concretely.** We adopt Memory Stores (Q4 #51), prompt caching (Q3 #23), Batch API (Q3 #23), Skills (Q4 #55, Q6 #41-#44), and adaptive thinking (already used in CritiqueAgent) as **first-class** in the architecture. We do not abstract them away behind a "lowest-common-denominator LLM port." Memory Stores get a dedicated `ManagedAgentMemoryAdapter`. Prompt caching gets `cache_control` markers in our prompt builders. Skills get loaded by the Anthropic SDK directly from `.claude-plugin/`. We evaluate Managed Agents in Q5-Q6 for the 6-specialist execution loop; if it parity-passes the leaderboard set we flip the default and Layer 4 shrinks ~30%.

**What stays portable.** The `LLMGateway` Protocol (used by every agent) is provider-agnostic. `BedrockAdapter` and `VertexAdapter` are sibling implementations that ship in Q4 alongside region pinning (#14). Memory Stores have a fallback path: when the customer is on Bedrock and Memory Stores aren't available, `ManagedAgentMemoryAdapter` falls back to `LocalFileMemoryAdapter` and we lose cross-machine memory sync but not correctness. Prompt caching falls back to repeated calls with no `cache_control` — we lose the cost win but not behavior. Skills fall back to in-prompt text injection — we lose modularity but not capability.

**Risk + reward.** The risk is Anthropic deprecates a primitive (Memory Stores schema changes, Managed Agents pricing model shifts) and we eat a refactor. Mitigation: every Anthropic-native adapter has a fallback `LocalFileMemoryAdapter`-style implementation, and the contract is the `MemoryPort` Protocol — Anthropic-side schema changes never touch Layer 2. The reward is a ~6-12 month feature lead over portable-only competitors. Our differentiation in Q4 (`spectra ask`) and Q6 (Skills-based plugin specialists) requires Anthropic-native primitives to be cost-defensible. A vendor-agnostic implementation of `spectra ask` would cost 5-10× more per call (no prompt cache, no Memory Store mount) and erase the unit economics that make the second-brain narrative possible.

**The wrong position is "vendor-agnostic to the bone."** That position would forbid us from using Memory Stores, would force us to build our own vector store + RAG layer, would multiply per-scan cost by 2-3×, and would still not produce a Bedrock-clean implementation because Bedrock has its own non-portable primitives (Bedrock Agents, Bedrock Knowledge Bases). Vendor-neutrality is a pre-2024 ideal; in 2026 every serious LLM platform has divergent native primitives, and the only honest answer is "pick one and adapt at the boundary."

---

## 7. Open product decisions for the founder

1. **Question:** Do we build a Spectra-operated control plane (SaaS) to unlock RBAC, audit-log mirroring, org Memory Stores, and a hosted leaderboard? · **Options:** A. CLI-only forever; emit audit/metrics into customer's stack; sell the OSS CLI + paid plugin packs · B. Hosted control plane in 2027 with WorkOS auth and a managed Postgres/Redis · C. Hybrid — CLI everywhere, optional control-plane handle for orgs that opt in · **Recommendation:** **C.** Q5 ships #38 webhooks and #16 BYO-LLM proxy so the CLI is fully self-hostable; Q7 (post-Q6) ships an opt-in `spectra-cloud` SKU for orgs that want hosted Memory Stores + leaderboard + audit-log mirroring. Reason: (A) leaves enterprise revenue on the table; (B) is too much surface to commit to before product-market fit signals from Q4 land.

2. **Question:** Pricing unit — per-scan, per-repo, or per-seat? · **Options:** A. Per-scan (matches Anthropic cost model; predictable for us, less for the customer) · B. Per-repo per month (CFO-friendly) · C. Per-seat (developers pay; CFOs hate it for tools that aren't core SDLC) · **Recommendation:** **B + per-org Memory Store add-on.** Per-repo monthly subscription with unlimited scans; per-org Memory Store priced separately as a $X/month add-on. Reason: portfolio-mode customers want predictable spend; per-scan creates user resistance to running scans. The schema for #25-#29 needs to know this before Q3 ships.

3. **Question:** Is Spectra an "AI-powered Semgrep" (more findings) or a "code-quality compass" (fewer, calibrated, prioritized findings)? · **Options:** A. Maximize findings count; compete with SAST tools on raw output · B. Minimize false positives; ship fewer but more confident findings; lean into the grade narrative · C. Tunable — shipping a `--fpr <0.1>` threshold lets the customer pick · **Recommendation:** **B.** The grade is the differentiator; finding-count is commodity. Q1 #2 (adversarial harness) and Q4 #60 (deterministic compliance mapping) only make sense in the (B) world. The self-scan is a warning: shipping noisy "info" findings (13 of 20 = "insufficient code provided") makes the grade look soft. Aggressive false-positive elimination is the brand.

4. **Question:** When do we go after the regulated-vertical wedge (HealthTech, Finance, Defense) versus the developer-productivity wedge (eng leaders, platform teams)? · **Options:** A. Developer-productivity in 2026, regulated-vertical in 2027 once SOC 2 and HIPAA mode land · B. Regulated-vertical first because they pay 5× and have larger budgets · C. Both — sales motion bifurcates · **Recommendation:** **A.** Q1-Q3 roadmap is product-led growth focused (developer + platform teams). Q4-Q6 unlocks regulated-vertical readiness (SOC 2 progress, HIPAA mode, Bedrock/Vertex). Reason: regulated buyers move slowly, want SOC 2 Type II (12-month observation), and won't sign before #11 / #12 / #14 / #62 / #63 are all real. Pre-revenue chase of regulated buyers burns 9 months for one logo.

5. **Question:** Do we open a public bug bounty program before $1M ARR? · **Options:** A. Open now with a clear scope + small payouts; build security reputation early · B. Wait until ARR > $1M; pay properly; manage volume · C. Private invite-only program until Q4 · **Recommendation:** **C.** Q1 #8 ships SECURITY.md + CNA so researchers have a defined channel. Q2-Q3, run a private invite-only program with 5-10 trusted researchers (free credits + name-on-website). Q4+, open public scope once Q1-Q3 fixes have landed and the adversarial harness gives us regression confidence. Reason: opening public scope before #1, #2, #3 land would invite a noisy first wave that crowds out the real signal.

---

*End of roadmap. The next deliverable is per-quarter milestone briefs (one document per quarter, owned by the engineering team-lead) that translate this scope into PR-sized work units.*
