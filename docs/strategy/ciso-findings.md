# CISO Findings — What blocks enterprise adoption of Spectra v0.3.3

**Author:** CISO persona · 2026-04-29
**Scope:** Spectra Python CLI (`spectra-ai==0.3.3`) and the `spectra-ai/spectra@v1` GitHub Action, evaluated as a candidate tool for enterprise-wide rollout in a regulated organization (FinTech / HealthTech / Defense baseline).
**Method:** Static review of source (`git_adapter.py`, `anthropic_adapter.py`, `cache_adapter.py`, `report_adapter.py`), dependency surface (`pyproject.toml`), publish pipeline (`.github/workflows/publish.yml`), and ADR-010 (the existing token-abuse posture).

---

## TL;DR

Five things I would say in the first 30 minutes with the product team:

1. **You are a sub-processor under GDPR Article 28 the moment one of my engineers types `spectra analyze`. There is no Data Processing Addendum on your side, and no signal that the user's API call to Anthropic is governed by my org's enterprise plan vs. a personal pay-as-you-go account. That is a hard block for any regulated workload.**
2. **Zero authentication, zero authorization, zero audit log.** I cannot tell you who in my org scanned what repository, when, or whether the result was acted on. That is non-negotiable for SOC 2 CC6.1 / CC7.2 evidence.
3. **The HTML report is a confidentiality time bomb.** It contains file paths, code excerpts, severity calls, and a CSP nonce — but nothing prevents an analyst from emailing it to a personal address. No watermarking, no DLP hook, no classification label.
4. **The local SQLite cache is unencrypted, multi-tenant on shared developer machines, and persists code-derived findings indefinitely.** On a hot-desk laptop or a shared CI runner, that's a cross-tenant data leak waiting to happen.
5. **Your supply chain is your single biggest residual risk.** OIDC trusted publishing on PyPI is excellent, but you have no SLSA provenance attestation, no published SBOM for `spectra-ai` itself, no security disclosure policy, and no upper bound on dependency versions. One compromised release of `gitpython` and we ship an exfiltrator inside our SDLC.

I am not blocking adoption — but Spectra ships to my org as a **personal-use developer tool only** until items 1, 2, 3, 5 above have a roadmap with dates.

---

## 1. Data residency & code privacy

### Findings

- **No DPA / sub-processor declaration.** `pip install spectra-ai` causes proprietary source code to be transmitted to Anthropic's API. Nothing in the README, `LICENSE`, or anywhere in `docs/` declares Anthropic as a sub-processor, references the Anthropic enterprise terms, or surfaces a Data Processing Addendum that an enterprise procurement team can countersign. Under GDPR Article 28 my Data Controller obligation is to have a written contract with every processor — `pip install` is not that contract.
- **No region pinning.** `anthropic_adapter.py` constructs `anthropic.AsyncAnthropic(api_key=...)` with no `base_url` override and no region selector. Anthropic's Enterprise plan supports US/EU regional routing; Spectra has no path to expose that to the caller. For German banks and EU healthcare customers this is a residency violation by default.
- **Source code, full-fidelity, leaves the perimeter.** Specialists run with `effort=xhigh` against the actual file contents (see `_call_streaming`). MetaPrompter limits itself to the file tree (≤5K tokens, per CLAUDE.md), but the six specialists send code. There is no pre-flight redaction, no PII scrubber, no secret scanner, no opt-out for files matching a glob.
- **Cache stores findings text on local disk in cleartext.** `cache_adapter.py` writes `findings_json` (which routinely contains code excerpts and recommendations referencing source) into `~/.cache/spectra/cache.db`. No encryption at rest, no OS keychain integration, no FIPS-mode SQLite. WAL files (`-wal`, `-shm`) are also in cleartext.
- **HTML report is a sensitive artifact with no classification.** `report_adapter.py` renders file paths, line numbers, recommendation text, and aggregated SOC 2 / PCI / NIST mappings into a single self-contained HTML. There is a CSP nonce on output but no document-level classification banner, no watermark, no per-recipient unique tag, no expiration.
- **Anthropic data retention is opaque to the user.** Default Anthropic API has a 30-day abuse-detection retention window; ZDR (zero data retention) is enterprise-only and per-org. Spectra surfaces neither setting nor warning.
- **No way to operate against a self-hosted gateway.** Bedrock, Vertex AI, or an internal Anthropic-via-Cloudflare-Tunnel relay are the typical regulated-org accommodations. `anthropic_adapter.py` hardcodes the SDK constructor — no `base_url` plumbing.

### Required capabilities

- **Capability: DPA-grade legal pack** — Public-facing DPA, sub-processor list, Anthropic data flow diagram, Standard Contractual Clauses for non-EU transfers — needed by Procurement / DPO — effort: M
- **Capability: Region pinning + Bedrock/Vertex backends** — `--region eu-west-1`, `--provider bedrock|vertex|anthropic`, plumbed through `LLMGateway` Protocol — needed by EU banks, US Defense, AWS GovCloud customers — effort: L
- **Capability: Pre-flight redaction & file-exclude glob** — `.spectraignore` honoured before any byte hits the LLM; default-deny on `.env`, `*.pem`, `id_rsa*`, `*.sql.gz`; secret scanner pre-pass (gitleaks or truffleHog as a port) — needed by every enterprise — effort: M
- **Capability: Encrypted cache at rest** — SQLCipher or OS-keychain-wrapped DEK; `--no-cache` flag; `spectra cache shred` for verified deletion — needed by HIPAA / PCI customers, anyone with shared machines — effort: M
- **Capability: Report classification + watermarking** — `--classification confidential|restricted|public` renders a banner, embeds per-recipient watermark, optional expiration (HTML refresh redirect to a placeholder) — needed by FinTech, Defense — effort: S
- **Capability: ZDR mode flag + visible warning** — `--zdr` requires the API key to be from a ZDR-enabled Anthropic org; CLI refuses to start otherwise. Print a one-line banner stating "Source code will be sent to Anthropic; retention: 30 days (default) | 0 days (ZDR)" before every run — needed by everyone — effort: S
- **Capability: BYO-LLM proxy** — `SPECTRA_LLM_BASE_URL` env var so customers can route through their own observability/DLP gateway (Portkey, Helicone, internal proxy) — needed by enterprises with existing LLM gateways — effort: S

---

## 2. Authentication, authorization, audit

### Findings

- **There is no authentication.** Anyone with the binary and *an* Anthropic API key can scan any HTTPS-reachable repository. The product has no concept of identity.
- **There is no authorization.** No roles, no scopes, no per-repository ACLs. `spectra analyze https://github.com/competitor/their-repo` works exactly the same as `spectra analyze https://github.com/myorg/our-repo`.
- **There is no audit trail.** `cache_adapter.py` logs cache hits to a `hit_log` table — that's it. No structured audit log of who ran an analysis, on what source, with which API key (even hashed), with what outcome, against which model version. Compare to the SOC 2 CC7.2 / CC6.1 evidence requirement: "the entity authorizes, modifies, or removes access to … information assets."
- **The cache mixes scans across users on a shared host.** `default_cache_path()` returns `${XDG_CACHE_HOME:-~/.cache}/spectra/cache.db`. On a multi-user dev box, a CI runner (especially self-hosted), or a hot-desk Citrix VDI, two analysts share the same `cache.db`. Findings from analyst A's scan of a confidential repo can be read by analyst B with `sqlite3 cache.db`.
- **API key handling is narrow but binary.** `anthropic_adapter.py` constructor validates the key against placeholders — good. But the key is loaded from `ANTHROPIC_API_KEY` env var with no support for OS keychain, secret manager (AWS SM / Vault / Doppler), or short-lived OIDC-issued tokens.
- **No approval workflow.** A user cannot request a scan that requires a security engineer's sign-off before execution. There is no notion of a "scan request" or "scan job" outside the synchronous CLI invocation.
- **No session / scan ID.** A scan in flight has no globally unique correlation ID surfaced to the user. Forensics ("did this scan happen?") rely on cache log + Anthropic billing dashboard cross-referencing.

### Required capabilities

- **Capability: Identity-aware CLI** — `spectra login` (OIDC device flow against Okta/Azure AD/Auth0); every subsequent `spectra` invocation includes `Authorization: Bearer <jwt>` to a Spectra control plane — needed by every >100-engineer org — effort: L
- **Capability: Audit log (structured, append-only)** — JSON Lines events on a per-scan basis: `actor.sub`, `repo_url`, `repo_signature`, `started_at`, `finished_at`, `model_versions`, `findings_count`, `critical_count`, `degraded`, `request_id`. Sink: file (default) | syslog | Splunk HEC | OTLP — needed for SOC 2 CC7.2 — effort: M
- **Capability: RBAC (analyst / reviewer / admin)** — Role enforced by the control plane; analyst can request, reviewer can sign off, admin can export evidence — needed by regulated orgs — effort: L
- **Capability: Per-user cache isolation** — Cache path keyed by `os.geteuid()` + per-actor namespace; or move to a scoped tmpfs; or encrypt rows under a per-user DEK — needed for shared CI runners, multi-user hosts — effort: S
- **Capability: Secret backend abstraction** — `SecretBackend` Port: `EnvBackend` (default) | `KeychainBackend` (macOS/Windows DPAPI/libsecret) | `VaultBackend` | `AwsSmBackend` — needed by orgs with existing secret managers — effort: M
- **Capability: Scan request workflow** — `spectra request` opens a request, security engineer approves via webhook, CLI then proceeds; integrates with ServiceNow / Jira — needed by orgs with formal change management — effort: L
- **Capability: Globally unique scan ID + signed receipt** — Every scan emits a UUIDv7 + Ed25519-signed JSON receipt. Receipt embeds inputs hash, model versions, finding hashes, timestamp — needed for non-repudiation, compliance evidence — effort: M

---

## 3. Compliance frameworks

### Findings

- **The report claims SOC 2 / PCI / NIST mapping but the mapping is heuristic, not certifiable.** `report_adapter.py` matches finding *text* against keyword lists per control. That is a sales/triage aid, not an audit artifact. CC6.7 ("data transmission security") matches on the substring "encryption" — that is a false positive generator and a false negative omitter. The output cannot be entered as evidence in a SOC 2 audit; it is at best a discussion starter for the auditor.
- **Spectra has no SOC 2 attestation of its own.** Anyone running `spectra` is sending source code to a service whose vendor (Spectra) has not been independently attested. SOC 2 Type II for the *Spectra service itself* (not the repos it analyses) is the question.
- **HIPAA: no BAA, no PHI handling story.** If a customer's repository contains code that processes PHI (database schemas, claim-form parsing, FHIR adapters), the source code itself may be PHI-adjacent depending on context. No BAA is offered. No `--phi` mode that forces ZDR + EU region.
- **PCI DSS Requirement 6.3.2 ("software inventory maintained")** — Spectra reports do not produce a CycloneDX or SPDX SBOM of the analysed repository. The `dd-compliance` section enumerates dependency *findings* — not the dependency tree itself. PCI auditors want SBOM, not narrative.
- **NIST 800-53 / CSF 2.0:** the report's NIST CSF mapping covers six functions with two controls each. NIST CSF 2.0 has dozens of categories and over 100 sub-categories. The current mapping is an introduction, not a control catalog.
- **SLSA provenance: missing.** `publish.yml` uses OIDC trusted publishing — that gives identity to the publisher, but it does not generate SLSA Build Level 3 provenance attestations (`actions/attest-build-provenance`). PyPI now supports verifying attestations; Spectra ships none.
- **SBOM of Spectra itself: not published.** No `sbom.cdx.json` in releases, no `pip install spectra-ai && spectra sbom`. For a tool sitting in our SDLC pipeline, this is a hard SOC 2 / FedRAMP gate.
- **No dependency upper bounds.** `pyproject.toml` pins `anthropic>=0.40` etc — the next breaking release of `anthropic` ships into our environment automatically. PCI 6.3.3 ("patches applied timely") cuts both ways: uncontrolled upgrades are themselves a control failure.

### Required capabilities

- **Capability: SOC 2 Type II for Spectra service** — Drata / Vanta / Secureframe + audit firm; 12-month observation window; CC1–CC9 + Confidentiality + (if BAA offered) Privacy — needed for any enterprise sale — effort: L
- **Capability: SBOM-in-report (CycloneDX 1.5)** — Every report includes a `sbom.cdx.json` of the analysed repo (lockfile-driven, language-aware) — needed for PCI 6.3.2, EO 14028 — effort: M
- **Capability: SBOM-of-Spectra (CycloneDX 1.5 + SPDX 2.3)** — Generated at build time, attached to the GitHub release and PyPI distribution — needed by procurement teams that gate ingest on SBOM availability — effort: S
- **Capability: SLSA Build L3 provenance** — Add `actions/attest-build-provenance@v1` to `publish.yml`; document verification with `gh attestation verify` — needed by orgs adopting Sigstore / SLSA framework — effort: S
- **Capability: HIPAA mode + BAA** — `--hipaa` enforces ZDR + region pin + no-cache + SARIF-only output (no HTML excerpts); BAA template available on request — needed by HealthTech — effort: M
- **Capability: Auditor evidence pack** — `spectra evidence --framework soc2 --period 2026-Q1` produces an auditor-ready PDF with audit log excerpts, configuration snapshot, finding statistics — needed for SOC 2 audits — effort: M
- **Capability: Replace heuristic compliance mapping with explicit, source-traceable rules** — Each control maps to a deterministic rule (CWE / CVE / pattern), not keyword guess — needed for honest compliance positioning — effort: L
- **Capability: Dependency upper bounds + Renovate config** — Pin `anthropic<1.0`, `gitpython<4`, etc.; Renovate-driven update PRs with a 7-day soak period — needed for PCI 6.3.3, ISO 27001 A.12.6.1 — effort: S

#### Compliance-mapping table (representative — not exhaustive)

| Capability | SOC 2 CC | ISO 27001 | PCI-DSS 4.0 | HIPAA Security Rule | NIST CSF 2.0 |
|---|---|---|---|---|---|
| Identity-aware CLI + RBAC | CC6.1, CC6.3 | A.5.15, A.8.2 | 7.1, 7.2 | 164.308(a)(4), 164.312(a) | PR.AA-01, PR.AA-05 |
| Audit log (append-only, exportable) | CC7.2, CC7.3, CC4.1 | A.8.15, A.8.16 | 10.2, 10.3 | 164.312(b) | DE.CM-01, DE.AE-02 |
| Encrypted cache at rest | CC6.1, CC6.7 | A.8.24 | 3.5, 3.6 | 164.312(a)(2)(iv) | PR.DS-01 |
| Pre-flight redaction / `.spectraignore` | CC6.7, Confidentiality | A.5.34, A.8.10 | 3.4, 4.2 | 164.312(e)(1) | PR.DS-02 |
| DPA + sub-processor list | Privacy | A.5.19, A.5.34 | 12.8 | 164.308(b)(1), 164.314(a) | GV.SC-01 |
| Region pinning / Bedrock backend | Confidentiality, Privacy | A.5.34 | n/a | 164.308(a)(8), 164.314(b) | GV.SC-05 |
| SBOM-of-analysed-repo (CycloneDX) | CC9.2 | A.5.21, A.8.8 | 6.3.2 | 164.308(a)(8) | ID.AM-02, ID.SC-04 |
| SBOM-of-Spectra-itself | CC9.2 | A.5.21 | 6.3.2 | 164.308(b)(1) | GV.SC-04 |
| SLSA L3 provenance | CC8.1, CC9.2 | A.8.30, A.8.31 | 6.5.6 | 164.308(a)(1)(ii) | ID.SC-05, PR.PS-04 |
| Report classification + watermark | Confidentiality | A.5.12, A.5.13 | 9.4 | 164.310(d), 164.312(c) | PR.DS-05 |
| Signed scan receipt | CC7.2, CC8.1 | A.5.34, A.8.34 | 10.5 | 164.312(c)(2) | PR.DS-06 |
| ZDR-mode enforcement | Privacy, Confidentiality | A.5.34 | 3.5 | 164.314(a)(2)(i) | GV.SC-07 |
| Vulnerability disclosure policy | CC7.4, CC9.2 | A.5.5, A.5.7 | 6.3.1 | 164.308(a)(6) | RS.CO-01, ID.RA-02 |

(Mapping is a working draft — would be hardened with the customer's auditor of record before publication.)

---

## 4. Governance & policy

### Findings

- **No policy primitive in the product.** The CLI scans on demand. There is no concept of "this org requires every PR to main to pass a Spectra scan" — that has to be wired by the customer in their own CI, with no help from Spectra (no Action input for `--policy`, `--severity-gate critical`, `--required-dimensions security`, etc.).
- **No risk-based exception model.** A team that has earned the right to ship without a Spectra check has no first-class way to register that exception. The org has to manage that out-of-band in their Actions config.
- **No severity gating built in.** The Action does not ship with a "fail on critical" knob. Customers reverse-engineer this from the JSON output today. That is a footgun: a misparsed `jq` filter ships a critical to production silently.
- **No findings triage / ownership / SLA model.** Each finding has a severity and a recommendation. There is no `owner`, no `due_at`, no `sla_breach`, no `last_reviewed_at`. A finding from yesterday's scan is indistinguishable from a finding from six months ago.
- **No suppression / waiver mechanism.** A known-accepted-risk finding will reappear on every scan. There is no `.spectra-waivers.yml` file with `{finding_hash, justification, approver, expires_at}`.
- **No custom rule library.** Internal policies — "we do not use `eval()` anywhere," "all DB calls must use the repository pattern," "no `print()` in `src/`" — cannot be added to Spectra. The org is stuck with the six built-in dimensions; their internal security policy lives in a separate static-analysis tool.
- **The `--quick` flag silently degrades CritiqueAgent.** ADR-008 / CritiqueAgent is the validation pass. Skipping it on PR for cost reasons is reasonable; doing it without a clear "this scan is non-validated" stamp on the report is a governance gap.

### Required capabilities

- **Capability: `.spectra-policy.yml` (org-level + repo-level)** — Declarative policy: severity gating, required dimensions, allowed waiver authors, max age of waiver, model-version pin — needed by any org enforcing pre-merge Spectra — effort: M
- **Capability: Waiver file with cryptographic approver signature** — `.spectra-waivers.yml` with finding-hash → `{approver_email, justification, expires_at, sig}`; CLI verifies sig against trusted keyring — needed for SOC 2 evidence of accepted-risk decisions — effort: M
- **Capability: Severity-gate Action input** — `with: fail-on: critical|high|medium`; documented exit codes; SARIF output already present (verify) — needed by every CI integration — effort: S
- **Capability: Custom-rule plugin** — `spectra rules add` lets a security team define org-specific patterns (regex / AST / Semgrep-style); rules run as a 7th specialist — needed by mature security teams — effort: L
- **Capability: Findings ownership & SLA fields** — Pydantic model gains `owner`, `due_at`, `sla`; report renders SLA breach badges; integration with Jira/Linear for ticket creation — needed by orgs with formal triage — effort: M
- **Capability: Run mode banner** — `--quick` and `--no-critique` runs prominently stamp "NON-VALIDATED" on the HTML report; SARIF emits a `tool.notification` reflecting the degraded state — needed for honesty — effort: S
- **Capability: Per-team scan budget** — Org admin sets per-team monthly scan / token / dollar budgets via control plane — needed by FinOps + governance — effort: M

---

## 5. Vendor risk & supply chain

### Findings

- **Eight runtime dependencies, all `>=` lower bounds, no upper.** `anthropic`, `typer`, `rich`, `pydantic`, `gitpython`, `tiktoken`, `jinja2` — each one is a transitive risk. `gitpython` in particular has a long CVE history (CVE-2022-24439, CVE-2023-40267, CVE-2023-41040). With no upper bound in `pyproject.toml`, a transitive dependency of `gitpython` can land in our environment without a release of Spectra.
- **No `requirements.lock` shipped to consumers.** A `requirements.lock` exists in the repo (per the `ls`), but `pip install spectra-ai` resolves dependencies on the consumer side at install time. SOC 2 CC8.1 expects deterministic builds.
- **PyPI publish: OIDC trusted publishing is good, but the GitHub repo is the high-value target now.** A maintainer account compromise → push a tag → publish to PyPI without ever touching a token. Mitigations *not* in `publish.yml`:
  - No required reviewer on `release` environment (the `environment: name: pypi` declaration is necessary but the protection rules are configured on GitHub, not in the YAML — verify they exist and require human approval).
  - No `tags-ignore` filter for unsigned tags.
  - No `git verify-tag` step before build.
  - No SLSA provenance attestation step.
- **Maintainer 2FA / hardware key requirement: not documented.** PyPI now mandates 2FA for project maintainers; GitHub mandates 2FA for organization members on public projects. Neither is documented as enforced for this org. A SECURITY.md does not appear in the repo root listing.
- **No `SECURITY.md` / vulnerability disclosure policy.** Where does a researcher report a Spectra vulnerability? No `security@`, no `SECURITY.md`, no `security.txt`. CVE coordination posture: zero.
- **No code signing of the wheel.** PyPI accepts unsigned wheels; Sigstore signing (`cosign sign-blob` + Rekor transparency log) is supported but not used.
- **The composite Action manifest itself (`action.yml`) is a script.** A consumer pinning `spectra-ai/spectra@v1` and not `@<sha>` is one tag-move away from running attacker-controlled steps in their CI.
- **Cache hash function is BLAKE2b digest_size=16 (128 bits).** Fine for cache keying, not adequate for any tamper-evidence purpose. Should not be repurposed for receipt signing.
- **Good things to keep:** `git_adapter.py` is genuinely defense-in-depth: SSRF resolver-fail-closed, hardened git env, symlink rejection at every parent, depth=1, no submodules, 60s timeout. ADR-010 (no self-dogfood) shows mature reasoning about secret-leak vectors. These are signals of a serious security posture; the gaps above are *unfilled*, not *unaware*.

### Required capabilities

- **Capability: Dependency upper bounds + lockfile shipped to consumers** — Add `<` bounds in `pyproject.toml`; ship `requirements.lock` inside the wheel as `spectra/_lockfile.txt`; document `pip install --require-hashes` flow — needed for SOC 2 CC8.1 / PCI 6.3.3 — effort: S
- **Capability: SECURITY.md + vulnerability disclosure policy** — `security@spectra-ai.dev` mailbox or HackerOne / GitHub Security Advisory; 90-day disclosure window; CVE assignment via GitHub's CNA — needed for ISO 27001 A.5.7 — effort: S
- **Capability: SLSA L3 build provenance** — `actions/attest-build-provenance@v1` in `publish.yml`; `gh attestation verify` documented for consumers; `cosign verify-blob` for signed wheels — needed for SLSA-conscious enterprises — effort: S
- **Capability: Pin Action to commit SHA in docs** — Documentation defaults to `spectra-ai/spectra@<40-char-sha>`, with `@v1` flagged as "convenience tag, not for high-assurance environments" — needed for high-assurance CI — effort: S
- **Capability: Maintainer security baseline** — Documented requirement: hardware-key 2FA for all maintainers, branch protection on `main` requires 2 reviewers + signed commits, `release` environment requires manual approval from a different maintainer — needed for SLSA L3 source — effort: S
- **Capability: Publish a tamper-evident release manifest** — Per release: `RELEASE.json` containing SHA-256 of every artefact, signed with the repo's Sigstore identity — needed by orgs with binary-allowlist policies — effort: M
- **Capability: Dependabot / Renovate enabled and visible** — Already mentioned in `anthropic_adapter.py` docstring ("Dependabot monitors weekly") — confirm `.github/dependabot.yml` exists and ship a public security advisory dashboard — needed for ISO 27001 A.8.8 evidence — effort: S
- **Capability: Reproducible build attestation** — `python -m build --sdist --wheel` + checksum the result against the published one; document a one-line reproducibility check for consumers — needed by Defense, regulated finance — effort: M

---

## Top 15 capabilities ranked by "blocks enterprise check"

| # | Capability | Frameworks satisfied | Effort | Risk if not built |
|---|---|---|---|---|
| 1 | DPA + sub-processor declaration + Anthropic flow diagram | GDPR Art. 28, SOC 2 Privacy, ISO 27001 A.5.19 | M | Procurement blocks the purchase. Hard stop. |
| 2 | Audit log (append-only, structured, exportable) | SOC 2 CC7.2 / CC7.3, HIPAA 164.312(b), ISO 27001 A.8.15 | M | Cannot pass any SOC 2 audit; no incident forensics. |
| 3 | Identity-aware CLI + RBAC (analyst/reviewer/admin) | SOC 2 CC6.1 / CC6.3, HIPAA 164.308(a)(4), NIST PR.AA-01 | L | Anyone can scan anything — insider risk and competitive-intel exposure. |
| 4 | Pre-flight redaction + `.spectraignore` + secret scanner pre-pass | SOC 2 Confidentiality, HIPAA 164.312(e), PCI 3.4 | M | `.env` files, RSA keys, customer PII shipped to Anthropic. |
| 5 | Encrypted cache at rest + per-user isolation | SOC 2 CC6.1 / CC6.7, HIPAA 164.312(a)(2)(iv), ISO 27001 A.8.24 | M | Cross-tenant leak on shared dev hosts and CI runners. |
| 6 | Region pinning + Bedrock/Vertex backends + ZDR enforcement | GDPR, SOC 2 Privacy, HIPAA 164.314 | L | EU customers cannot use the product. Health customers cannot use the product. |
| 7 | SOC 2 Type II for Spectra (the service / company) | SOC 2 (entire framework) | L | Most enterprise procurement RFPs require this on the vendor's side. |
| 8 | SBOM-of-analysed-repo (CycloneDX 1.5) baked into the report | PCI 6.3.2, NIST ID.AM-02, EO 14028 | M | The report's compliance section is positioning, not evidence. |
| 9 | Vulnerability disclosure policy (`SECURITY.md` + CNA) | ISO 27001 A.5.7, SOC 2 CC7.4, NIST RS.CO-01 | S | No defined channel — researchers post on Twitter; we find out from customers. |
| 10 | Dependency upper bounds + shipped lockfile + Renovate | SOC 2 CC8.1, PCI 6.3.3, ISO 27001 A.12.6 | S | One bad `gitpython` release ships a backdoor through our SDLC. |
| 11 | SLSA L3 provenance + Sigstore-signed wheels | SOC 2 CC8.1, NIST ID.SC-05 / PR.PS-04 | S | Tag-move attack on the repo silently propagates to every consumer. |
| 12 | `.spectra-policy.yml` + waiver file with signed approver | SOC 2 CC3.4 / CC8.1, ISO 27001 A.5.36 | M | Severity-gate enforcement is reverse-engineered per customer. |
| 13 | Report classification + watermark + expiration | SOC 2 Confidentiality, ISO 27001 A.5.12 / A.5.13 | S | A leaked report = a leaked roadmap of every weakness in the codebase. |
| 14 | Signed scan receipt + globally unique scan ID | SOC 2 CC7.2 / CC8.1, NIST PR.DS-06 | M | Non-repudiation gap; auditor cannot tie a finding back to a specific run. |
| 15 | Honest "non-validated" stamp on `--quick` runs + SBOM-of-Spectra itself | SOC 2 (Honesty in marketing), CC9.2, EO 14028 | S | We tell auditors the report passed Critique when it did not. |

---

## Compliance mapping table

| Capability | SOC 2 CC | ISO 27001 | PCI-DSS 4.0 | HIPAA | NIST CSF |
|---|---|---|---|---|---|
| Identity-aware CLI + RBAC | CC6.1, CC6.3 | A.5.15, A.8.2 | 7.1, 7.2 | 164.308(a)(4), 164.312(a) | PR.AA-01, PR.AA-05 |
| Audit log | CC7.2, CC7.3, CC4.1 | A.8.15, A.8.16 | 10.2, 10.3 | 164.312(b) | DE.CM-01, DE.AE-02 |
| Encrypted cache at rest | CC6.1, CC6.7 | A.8.24 | 3.5, 3.6 | 164.312(a)(2)(iv) | PR.DS-01 |
| Pre-flight redaction | CC6.7, Confidentiality | A.5.34, A.8.10 | 3.4, 4.2 | 164.312(e)(1) | PR.DS-02 |
| DPA + sub-processor list | Privacy | A.5.19, A.5.34 | 12.8 | 164.308(b)(1) | GV.SC-01 |
| Region pinning / BYO-LLM proxy | Confidentiality, Privacy | A.5.34 | 4.2.1 | 164.314(b) | GV.SC-05 |
| SBOM-of-analysed-repo | CC9.2 | A.5.21, A.8.8 | 6.3.2 | 164.308(a)(8) | ID.AM-02, ID.SC-04 |
| SBOM-of-Spectra-itself | CC9.2 | A.5.21 | 6.3.2 | 164.308(b)(1) | GV.SC-04 |
| SLSA L3 provenance | CC8.1, CC9.2 | A.8.30, A.8.31 | 6.5.6 | 164.308(a)(1)(ii) | ID.SC-05 |
| Report classification + watermark | Confidentiality | A.5.12, A.5.13 | 9.4 | 164.310(d) | PR.DS-05 |
| Signed scan receipt | CC7.2, CC8.1 | A.5.34, A.8.34 | 10.5 | 164.312(c)(2) | PR.DS-06 |
| ZDR enforcement | Privacy | A.5.34 | 3.5 | 164.314(a) | GV.SC-07 |
| `SECURITY.md` + CNA | CC7.4, CC9.2 | A.5.5, A.5.7 | 6.3.1 | 164.308(a)(6) | RS.CO-01 |
| Policy + waiver with signed approver | CC3.4, CC8.1 | A.5.36 | 6.5.4 | 164.308(a)(1)(ii)(B) | GV.PO-01 |
| Custom-rule plugin (org policies) | CC5.1, CC5.3 | A.8.27, A.8.28 | 6.2.4 | 164.308(a)(1)(ii) | PR.IR-01 |
| Per-user cache isolation | CC6.1 | A.8.24 | 7.1 | 164.312(a)(1) | PR.AA-04 |
| Severity-gate Action input | CC8.1 | A.8.32 | 6.5 | n/a | DE.AE-04 |
| Auditor evidence pack | All CC | A.5.35 | 12.10.5 | 164.308(a)(8) | DE.AE-08 |
| Maintainer 2FA + signed commits | CC6.1, CC8.1 | A.5.16, A.8.30 | 6.5.6 | 164.308(a)(4) | PR.AA-03 |
| HIPAA mode + BAA | Privacy | A.5.34 | n/a | 164.308(b), 164.314(a) | GV.SC-01 |

---

## Open questions for the Head of Product + CTO + Red Team

1. **Anthropic relationship — direct ISV agreement or per-customer pass-through?** If Spectra is going to declare itself a processor with Anthropic as a sub-processor, do we sign a joint-marketing / ISV agreement with Anthropic that we can put in front of customers? Or do we stay pass-through and require every customer to use their *own* Anthropic enterprise contract (in which case `--zdr` and `--region` are *enforcement* hooks, not *implementation*)?
2. **Control plane: yes or no?** Capability #2 (audit log) and #3 (identity-aware CLI) implicitly assume a Spectra-operated control plane. Building one is a significant scope expansion: it turns Spectra from a CLI into a SaaS. Alternative: stay CLI-only, ship audit events as JSON Lines to whatever sink the customer points us at, and let the customer's SIEM / IAM be the source of truth. The CTO needs to make that call before #2 / #3 / #14 are designed.
3. **Where does compliance data accuracy land on the roadmap vs. compliance positioning?** The current `report_adapter.py` keyword-mapping for SOC 2 / PCI / NIST is a sales aid — useful for landing the meeting, indefensible in an audit. Do we (a) tone down the marketing claim until rules are deterministic, (b) ship a clearly-labelled "indicative mapping — not audit evidence" disclaimer, or (c) invest engineering into deterministic rule-driven mapping (capability #8 in the top-15)? The Red Team will surface this as a misrepresentation risk.
4. **Custom rules: 7th specialist or post-processing pass?** The custom-rule capability is the most common enterprise ask after "audit log." Architecturally it can be a parallel 7th `SpecialistAgent` (slots cleanly into `asyncio.gather`, but expensive on tokens) or a deterministic Semgrep-style post-pass on the cloned repo (cheap, but doesn't get LLM judgement). The CTO and Red Team should weigh whether mixing deterministic + LLM in one report devalues the LLM findings.
5. **The Spectra repo itself: are we comfortable being our own threat model?** ADR-010 chose to remove dogfood workflows because the publisher repo's API key is a high-value target. The same logic applies to maintainer credentials, the `release` environment, and any future Sigstore signing identity. Do we commit to: (a) hardware-key 2FA for every maintainer with publish rights, (b) two-person rule on the `release` environment, (c) public security advisory mailbox staffed within 24h of inbound? These are foundational and should be in place *before* Spectra ships to its first regulated customer — not as a response to that customer's questionnaire.

---

*End of CISO findings. Next steps: route capabilities #1–#5 to the v0.4 roadmap; gate v1.0 on capabilities #6–#15. Re-evaluate on every minor release.*
