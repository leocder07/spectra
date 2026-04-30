# 07 — Security Architecture

**Status:** Stable + Q2 designed · **Baseline:** v0.5.0 · **Last revised:** 2026-04-30

## Purpose

State the threat model, document the v0.5.0 hardening that closed every Red Team critical/high, and describe the Q2-designed capabilities that make Spectra defensible as a CI gate in regulated workflows.

## Audience

Security reviewers, CISOs in procurement, engineers touching anything secret-adjacent.

## Threat model

| Threat | Asset | Mitigation |
|--------|-------|------------|
| Prompt injection in analyzed code moves the grade | Spectra grade output | Per-file random-nonce data fences + CritiqueAgent adversarial check + 20-plant adversarial harness (ADR-011) |
| Secret in source code leaks into Anthropic prompt | Customer secret material | Pre-flight `RegexSecretScanner` + `.gitignore` honor + `.spectraignore` (v0.5.0, roadmap #6) |
| Cache poisoning on a shared host moves the grade | Cache integrity | Per-`$UID` directory namespace (mode 0700 / 0600) + per-row blake2b HMAC (ADR-012) |
| Supply-chain compromise of the published wheel | Distribution integrity | SLSA L3 attestation + Sigstore keyless signing (roadmap #7) |
| Malicious markdown in a finding breaks PR comments | GitHub PR rendering | Markdown-safe PR comment renderer with field allowlist (roadmap #4) |
| Buyer treats indicative analysis as compliance evidence | Customer trust | Indicative-analysis disclaimer banner on every report (roadmap #61) |
| Hostile loop drains Anthropic budget | Cost | Q2-designed `--max-cost-usd` per-run + per-hour rolling cap (ADR-013, roadmap #5) |
| Stolen laptop is a notifiable event for HIPAA | Cache contents | Q2-designed encrypted cache at rest (SQLCipher) + `spectra cache shred` (roadmap #13) |
| Audit gap blocks SOC 2 / ISO 27001 procurement | Auditability | Q2-designed `AuditPort` + JSON-Lines/OTLP/CloudWatch sinks (ADR-018) |
| Forged Spectra grade in a third-party report | Verifiability | Q2-designed Ed25519-signed scan receipt (roadmap #57) |

## v0.5.0 — what shipped

### 1. Prompt-injection isolation (ADR-011)

![Prompt-injection defence in depth](./diagrams/07-prompt-injection-defense.svg)

Source: [`diagrams/07-prompt-injection-defense.puml`](./diagrams/07-prompt-injection-defense.puml)

Three concurrent defences, none alone sufficient:

1. **Per-call nonce-fenced data sections** ([`specialist_agent.build_prompt`](../../src/spectra/infrastructure/agents/specialist_agent.py)). `secrets.token_urlsafe(16)` per `BatchPrompt` — unguessable. The same nonce appears in the open fence, the close fence, and the system-prompt reinforcement. The architectural contract: anything between the markers is DATA, not INSTRUCTION; the model can verify the boundary in-context.
2. **Pre-flight regex flag list** ([`injection_scanner.scan_files_for_injection`](../../src/spectra/use_cases/injection_scanner.py)). Curated markers: `IGNORE PRIOR INSTRUCTIONS`, `<system>`, `</analyzed_code>`, `assistant:`, `human:`, `<<<SPECTRA-DATA-`. Matches are NEVER stripped — that would mask the attack from the user and from the CritiqueAgent. Bounded ≤200ms on 10MB by contract; CI gate at 500ms.
3. **CritiqueAgent `<adversarial_input_check>`** ([`critique_agent._SYSTEM_PROMPT`](../../src/spectra/infrastructure/agents/critique_agent.py)). The agent receives `flagged_files` as structured evidence; uses adaptive thinking to inspect the listed files plus any specialist finding whose text smells like attacker bytes; emits a single `compromised_findings` entry on detection.

The orchestrator materialises the entry into a `Finding(rule_id="SPEC-PROMPT-INJECTION-DETECTED", severity="critical", confidence=1.0)` and flips `AnalysisReport.is_compromised=True`. The renderer surfaces a banner; `PipelineState` transitions to `compromised`.

**Adversarial harness** ([`golden_files/adversarial/`](../../golden_files/), 20 plant repos). Each plant has a known injection in a known location and an expected outcome. The Q1 release gate is **catch-rate ≥80%**; v0.5.0 measured **100% (20/20)**. The harness is the regression contract; updating the marker list is allowed without a major version bump but requires the harness to remain green.

### 2. Per-row HMAC + per-`$UID` cache namespace (ADR-012)

See [06 — Cache Architecture](./06-cache-architecture.md) for the full design. Summary:

- Cache moves to `${XDG_CACHE_HOME:-~/.cache}/spectra/$UID/` (mode 0700; cache.db mode 0600).
- 32-byte HMAC secret in OS keyring (service `spectra-cache-hmac`, account `$UID`).
- Every persisted row carries `mac BLOB` = `blake2b(secret, key_parts, payload)`.
- `get_*` recomputes + `compare_digest`; mismatch deletes the row + logs SPEC-010.
- Legacy `~/.cache/spectra/cache.db` (no `$UID/`) is dropped on first run with a one-time INFO message.
- New `spectra cache doctor` subcommand verifies per-table MAC integrity.

### 3. Secret pre-flight + `.gitignore` honor + `.spectraignore` (roadmap #6)

![Pre-flight stage](./diagrams/07-secret-preflight-flow.svg)

Source: [`diagrams/07-secret-preflight-flow.puml`](./diagrams/07-secret-preflight-flow.puml)

New Stage 1.5 between INGEST and PLAN ([`use_cases/preflight.py`](../../src/spectra/use_cases/preflight.py)). Composition order is load-bearing:

1. `WorkspaceFilterPort.filter_files` — `.gitignore` (root + nested) + `.spectraignore`. Bypassing `.gitignore` is opt-in via `--no-gitignore`; `.spectraignore` is always honoured.
2. `SecretScannerPort.scan` — runs only against the filtered list. **A `.gitignore`-excluded `.env` is never scanned.** Defeating that guarantee would fail user expectations.

[`infrastructure/regex_secret_scanner.py`](../../src/spectra/infrastructure/regex_secret_scanner.py) — Tier-S patterns:

| Pattern | Regex |
|---------|-------|
| `aws_access_key` | `\bAKIA[0-9A-Z]{16}\b` |
| `github_pat` | `\bghp_[A-Za-z0-9]{36}\b` |
| `anthropic_key` | `\bsk-ant-[A-Za-z0-9_-]{32,}\b` |
| `bearer_token` | `\bBearer [A-Za-z0-9._-]{20,}\b` |
| `slack_webhook` | `https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+` |
| `private_key` | `-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY-----` |
| `dotenv_value` | `^[A-Z][A-Z0-9_]*=.{12,}$` (only inside `.env*` files) |

Operational guarantees: per-file decode errors swallowed; missing files yield no matches; 1 MB read cap per file; pattern set compiled once at construction.

Default behaviour: matches abort the run with `SPEC-011 SecretDetectedError` carrying the tuple of `SecretFinding`. `--allow-secrets` downgrades to a WARN line per finding.

### 4. Markdown-safe PR comment renderer (roadmap #4)

[`adapters/pr_comment_renderer.py`](../../src/spectra/adapters/pr_comment_renderer.py). Field allowlist: `title`, `severity`, `dimension`, `file_path`, `line_start`, `line_end`, `summary`. `recommendation`, `code_snippet`, `references` are dropped — nothing the LLM produces is rendered without scrubbing.

Hardening:
- HTML-escape on every text field.
- Backticks in titles replaced with U+02CB (modifier letter grave accent) so codeblock fences cannot be broken.
- `![](...)` image syntax and `<http...>` autolinks stripped from summaries.
- File paths rendered in inline code with `[`/`]`/`(`/`)` escaped.
- `<!-- SPECTRA -->` sentinel preserved as the idempotent-update marker for the GitHub Action.

### 5. Indicative-analysis disclaimer (roadmap #61)

[`entities/disclaimer.py`](../../src/spectra/entities/disclaimer.py) — single source of truth. Same wording across HTML, JSON, SARIF.

- HTML: full-width amber banner, sticky, ARIA-labelled, dismissible via CSP-safe `data-action="dismiss-disclaimer"` event delegation in the nonce-protected `<script>`. Dismissal stored in `sessionStorage`.
- JSON: top-level `disclaimer: { text, url }` field.
- SARIF: `runs[0].invocations[0].notifications[]` carrying the disclaimer text + `descriptor.helpUri`.
- Copy-scrub guardrail test prevents `compliance evidence` / `audit-grade` / `auditor-ready` from regressing into src/templates/README.

### 6. Supply-chain Q1 bundle (roadmap #7-#10)

- `actions/attest-build-provenance@v2` — SLSA L3 attestation per artifact.
- `sigstore-python` keyless signing on every release wheel; `.sigstore` bundles attached to the GitHub Release.
- `SECURITY.md` with supported-versions table, GitHub Private Vulnerability Reporting as the single intake, 90-day default disclosure (≤7d if exploited).
- `pyproject.toml` conservative upper bounds on every runtime + dev dep; `requirements.lock` regenerated via `uv pip compile`; `renovate.json` weekly schedule, grouped minor+patch, separate-PR majors.
- `scripts/register_pypi_squats.sh` reserves 8 high-risk PyPI variants.

See [10 — Deployment & Release](./10-deployment-and-release.md) for the publish pipeline.

## Q2 designed — in flight

### 7. Audit log + identity (ADR-018)

`AuditPort` with three adapter implementations: `JsonlAuditAdapter` (default, `${XDG_STATE_HOME:-~/.local/state}/spectra/audit.jsonl`), `OtlpAuditAdapter` (OpenTelemetry Logs), `CloudWatchAuditAdapter` (optional extra `pip install spectra-ai[aws]`).

Identity resolved once per process at startup with explicit precedence: `SPECTRA_USER_ID` env > OIDC token in CI > `git config user.email` > hostname fallback. Confidence label flows into every audit event. We deliberately do not require OIDC — Spectra is CLI-only.

Every state transition emits a structured `AuditEvent`. Privacy boundary enforced at the adapter: `payload` keys named `code`, `content`, `secret`, `key`, `token`, `body` are refused. Tests verify the refusal.

| What we log | What we never log |
|-------------|-------------------|
| `repo_signature`, `finding_signature`, `actor`, `cost_usd`, `tokens_*`, MAC fingerprint (first 8 chars) | Repo URL, file paths, code excerpts, finding text, secret material, full MAC, API keys |

### 8. `--max-cost-usd` budget enforcement (ADR-013, roadmap #5)

Per-run hard cap + per-hour rolling cap. Backed by a new `CostTrackerPort` + SQLite `cost_window` table. `task_budget` becomes per-agent (not Critique-only). Violation → new `PipelineState` transition `budget_exceeded` → graceful exit with partial report.

### 9. Encrypted cache at rest (roadmap #13)

`SqlcipherCacheAdapter` sibling of `SqliteCacheAdapter`. Same `CachePort`. New extra `pip install spectra-ai[encrypted-cache]`. `spectra cache shred` zeroes the encryption key and removes the database. Targets HIPAA "stolen laptop is not a notifiable event" use case.

### 10. `.spectra-policy.yml` + signed `.spectra-waivers.yml` (roadmap #17)

Declarative policy at the org and repo level. `Policy` entity carries severity gate, max-cost cap, and tuple of `PolicyRule`. `Waiver` is per-(rule_id, file_path) suppression with an Ed25519 signature and an `expires` date. Replaces ad-hoc CI YAML duplication; foundation for portfolio enforcement.

### 11. Severity-gate + non-validated stamp (roadmap #20)

`spectra-action` input `severity-gate=critical|high|medium|low` exits non-zero when any finding meets or exceeds the gate. `--quick` runs (CritiqueAgent skipped → injection detection skipped) stamp the report with `validation_status="non-validated"` so downstream consumers can refuse to gate on unvalidated grades.

### 12. Dual-mode classification (ADR-018 + roadmap)

`AnalysisReport.classification: Literal["confidential", "public"]`. Default `confidential` — full report. `public` — file paths and finding text redacted; only the score card and the disclaimer emitted. Compromised runs refuse public-mode emission entirely.

### 13. Ed25519-signed scan receipt (roadmap #57)

`Receipt` entity = UUIDv7 scan_id + Ed25519 signature over `(repo_signature || score_card_canonical_json)`. Verifiable by any third party with the Spectra signing key (rotated quarterly; archived public keys served from a static endpoint).

### 14. DPA + sub-processor declaration (roadmap #11)

Legal pack, not engineering. Signable Data Processing Agreement; named sub-processor list (today: Anthropic only). Anthropic data flow diagram (re-uses [08 — Data Flow & Privacy](./08-data-flow-and-privacy.md)).

## Identity & secret material

- **API key** never logged, never serialised. Validated at adapter construction; rejected if empty / placeholder.
- **Cache HMAC secret** lives in the OS keyring; loaded once per process; never written to disk; never appears in error messages. The wrapping `CacheSecret` value object exists to keep the use case layer free of raw `bytes` plumbing.
- **OIDC token** (Q2) is fetched once at startup for identity resolution and discarded.
- **Ed25519 signing key** (Q2) is fetched from the keyring at signing time; never serialised.

## Verifying releases

Documented in the README's "Verifying releases" section:

```bash
# SLSA build provenance
gh attestation verify spectra_ai-<ver>.whl --repo leocder07/spectra

# Sigstore keyless signature
python -m sigstore verify identity \
  --bundle spectra_ai-<ver>.whl.sigstore \
  --cert-identity https://github.com/leocder07/spectra/.github/workflows/publish.yml@refs/tags/v<ver> \
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  spectra_ai-<ver>.whl
```

## Invariants and key decisions

- **Boundary, not best-effort.** The injection nonce is required for every batch — no opt-out flag.
- **Block by default.** Secret pre-flight aborts unless `--allow-secrets` is passed; `--allow-secrets` is intentionally noisy with a WARN per finding.
- **HMAC + namespace, not encryption.** v0.5.0 ships integrity + isolation; encryption-at-rest is Q2.
- **Disclaimer is a constant, not a template.** Single source of truth in `entities/disclaimer.py` keeps the four output channels in lock-step.
- **The harness is the SLA.** Adversarial catch-rate is the public number; the marketing leaderboard work in the roadmap is gated on it.

## Open questions

1. Should `SecretScannerPort.scan` return early on the first match? Today it walks the whole tree to enumerate every secret for the WARN-line output under `--allow-secrets`. The cost of walking is bounded by the `1MB` per-file cap.
2. The injection marker list lives in `injection_scanner.py:21`. ADR-011 explicitly allows updates without a major version bump. The harness is the contract; document the update process and require a harness pass in the PR template.
3. Q2 audit-log retention: the `JsonlAuditAdapter` defaults to 365d via `logrotate`. Should we ship our own rotation (and survive systems without `logrotate`) or remain platform-default? Today's design defers to platform; revisit if a Windows customer hits the gap.
