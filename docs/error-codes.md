# Error codes

Every fallible operation in Spectra raises a `SpectraError` carrying a
stable code, so CI logs, brand-voice CLI messages, audit events, and SARIF
notifications speak the same language. The taxonomy lives in
[`src/spectra/entities/errors.py`](../src/spectra/entities/errors.py); this
document is the user-facing reference.

| Code | Category | Retryable | Max retries |
|------|----------|-----------|-------------|
| [SPEC-001](#spec-001) | Infrastructure | Yes | 2 |
| [SPEC-002](#spec-002) | Infrastructure | Yes | 3 |
| [SPEC-003](#spec-003) | Rate limit | Yes | 3 |
| [SPEC-004](#spec-004) | Budget | No | — |
| [SPEC-005](#spec-005) | Validation | Yes | 1 |
| [SPEC-006](#spec-006) | Timeout | No | — |
| [SPEC-007](#spec-007) | Pipeline | No | — |
| [SPEC-008](#spec-008) | Critique | No | — |
| [SPEC-009](#spec-009) | Report | No | — |
| [SPEC-010](#spec-010) | Cache | No (degrade) | — |
| [SPEC-011](#spec-011) | Security | No | — |
| [SPEC-012](#spec-012) | Config | No | — |
| [SPEC-013](#spec-013) | Policy | No | — |
| [SPEC-014](#spec-014) | Cost budget | No | — |

---

## SPEC-001

**Name:** Git clone failed
**When it fires:** `GitAdapter.prepare_workspace` cannot clone the
requested HTTPS URL — DNS lookup failed, the remote rejected the request,
the local filesystem ran out of room, or the operation exceeded the clone
timeout. Local-path inputs that fail validation share this code.
**What to do:** Verify the URL is reachable, your network can resolve
GitHub / GitLab, the destination has free space, and the repository is
public (or that your credentials helper is configured for private repos).
**Retryable:** Yes — the `RetryDecorator` automatically retries up to 2
times with exponential backoff (1s, 2s).

## SPEC-002

**Name:** Anthropic API unreachable
**When it fires:** The Anthropic SDK could not reach `api.anthropic.com`
— typically a network partition, a DNS failure, or a transient 5xx from
the upstream service.
**What to do:** Check your network egress, verify that
`https://api.anthropic.com` is reachable, and rerun. Persistent failures
usually indicate a corporate proxy that needs `HTTPS_PROXY` set.
**Retryable:** Yes — automatic retry up to 3 times (1s / 2s / 4s).

## SPEC-003

**Name:** Rate limited (429)
**When it fires:** Anthropic returned HTTP 429 — your account hit its
per-minute or per-day token / request quota. Spectra also surfaces this
when bursting 6 specialists in parallel against a low-tier key.
**What to do:** Wait for the quota window to reset, lower the parallelism
(`--quick` to skip the CritiqueAgent pass; or set per-role overrides to
cheaper models), or upgrade your Anthropic tier.
**Retryable:** Yes — automatic retry up to 3 times. The decorator honors
the `Retry-After` header when present.

## SPEC-004

**Name:** Token budget exceeded
**When it fires:** A single agent's prompt or response would push the
process over the configured token ceiling (the in-memory budget enforced
by `manage_token_budget`). Usually a symptom of an unusually large
repository or a prompt that grew past its cap.
**What to do:** Re-run with a smaller scope (use `.spectraignore` to
exclude vendored or generated directories), or open an issue if the
target repo is well within Spectra's documented limits.
**Retryable:** No — the failure is deterministic until inputs change.

## SPEC-005

**Name:** Agent output validation failed
**When it fires:** A specialist returned JSON that did not validate
against the Pydantic model for findings — usually a malformed code-fence,
a missing required field, or a hallucinated severity value.
**What to do:** Spectra retries the agent once automatically. If the
failure persists, rerun with `--verbose` to capture the raw output, then
file an issue with the offending agent + repo combo.
**Retryable:** Yes — exactly 1 retry; the decorator re-prompts the agent
once before giving up.

## SPEC-006

**Name:** Agent timeout (120s)
**When it fires:** A single agent (`asyncio.wait_for`) exceeded the
120-second per-call deadline. Most often a symptom of upstream Anthropic
slowness during a peak window or a prompt that triggered an unusually
long thinking pass.
**What to do:** Rerun. If the timeout is reproducible, file an issue —
include the dimension that timed out so we can profile the prompt.
**Retryable:** No — timeouts are explicitly non-retryable (the upstream
call is already inflight; another retry would compound the latency).

## SPEC-007

**Name:** 2+ agents failed
**When it fires:** Two or more of the six parallel specialists returned
errors during Stage 3 (ANALYZE). The pipeline aborts because a partial
score card with multiple missing dimensions is misleading.
**What to do:** Rerun with `--verbose` to surface each agent's underlying
error code. Single-agent failures degrade gracefully and are tagged in
the report; two or more is treated as a pipeline-level abort.
**Retryable:** No — the run already failed; rerun the entire pipeline.

## SPEC-008

**Name:** CritiqueAgent failed
**When it fires:** The CritiqueAgent (Stage 5) raised an unrecoverable
error — typically a Pydantic schema mismatch on its output, or repeated
upstream failures past the retry budget.
**What to do:** Rerun with `--quick` to skip the critique pass and ship
an unvalidated report (the SARIF / JSON output sets
`validation_status: non-validated:critique-skipped` so consumers see the
trust downgrade). Then file an issue with the captured logs.
**Retryable:** No — the critique pass is best-effort; failures abort the
stage but the upstream specialist findings are intact.

## SPEC-009

**Name:** Report render failed
**When it fires:** Stage 6 (REPORT) — the Jinja2 HTML template, the JSON
serializer, or the SARIF builder raised. Usually a code bug; not a user
issue.
**What to do:** Rerun with `--format json` to bypass the HTML template,
inspect the raw report, and file an issue with the captured error.
**Retryable:** No — render failures are deterministic until the template
or input report changes.

## SPEC-010

**Name:** Cache I/O failed
**When it fires:** The SQLite cache adapter could not read, write, or
verify a row — disk I/O failure, a corrupt page, or an HMAC mismatch on
a tampered row. Also raised during cache initialisation when the keyring
is unavailable for the per-user MAC secret.
**What to do:** Nothing — Spectra logs the failure once and degrades to
no-cache for the rest of the run. Repeated failures across runs warrant
`spectra cache shred` (drops the corrupt cache.db and the keyring entry,
then cold-starts on the next run).
**Retryable:** No — cache failures are never fatal. The pipeline always
proceeds without the cache.

## SPEC-011

**Name:** Secret detected in workspace
**When it fires:** The pre-flight scan found one or more potential
secrets (AWS access key, GitHub PAT, Anthropic key, bearer token, Slack
webhook, RSA / OpenSSH private key, or anything matching the `.env*`
heuristic).
**What to do:** Either remove the secrets and rerun, add the offending
file to `.gitignore` / `.spectraignore`, or rerun with `--allow-secrets`
to acknowledge and proceed (the CLI logs each detection at WARN even
when bypassed).
**Retryable:** No — block-by-default; explicit override required.

## SPEC-012

**Name:** Policy or waiver file invalid
**When it fires:** `.spectra-policy.yml`, `.spectra-waivers.yml`, or
`.spectra-approvers.yml` did not parse (malformed YAML, schema mismatch,
unknown check name, or signature verification failed on an approver
roster).
**What to do:** Validate the file against the schema in
[docs/guides](../docs/guides) and fix the malformed entry. Spectra
prints the parsing error inline so the offending key is named.
**Retryable:** No — config errors are deterministic until the file is
fixed.

## SPEC-013

**Name:** Policy gate failed
**When it fires:** `.spectra-policy.yml` parsed cleanly but at least one
configured check (`severity_gate`, `min_score_overall`, `forbidden_rule_id`,
etc.) returned a violation against the final report.
**What to do:** Either fix the violations the policy flagged, file a
waiver via `spectra waive` (signed, with an expiry date), or relax the
policy. The CLI prints every violation in one block before exiting.
**Retryable:** No — governance is intentional; rerun once the violations
are resolved.

## SPEC-014

**Name:** Cost budget exceeded
**When it fires:** The cumulative spend for the run (per-agent USD
ledger maintained by `cost_tracker`) crossed the cap configured by
`--max-cost-usd` or `--max-cost-per-hour`. The gate fires before the
next agent call, so the cap is honored even if the next call would have
been the most expensive.
**What to do:** Rerun with `--max-cost-usd <higher>`, or split the
analysis into smaller scopes (use `.spectraignore` to exclude
vendored / generated directories). The CLI prints the per-agent
breakdown so you can see which dimension dominated the spend.
**Retryable:** No — operator policy; the cap stays in force until the
flag is changed.
