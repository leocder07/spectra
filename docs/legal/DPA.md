# Data Processing Addendum (Template)

**Status:** Template — requires legal review before customer use.
**Version:** 0.1 (initial draft, v0.5.0 baseline)
**Last reviewed:** 2026-04-29
**Owner:** Spectra Engineering (Vivek Kumar, Head of Engineering)

This Data Processing Addendum ("DPA") is a template that supplements a master
agreement (the "Agreement") between the customer ("Customer", acting as Data
Controller) and Spectra ("Spectra", acting as Data Processor) for use of the
`spectra-ai` Python CLI and the `spectra-ai/spectra` GitHub Action
(collectively, the "Service"). It is drafted to be GDPR Article 28 compatible
and to align with SOC 2 (Privacy / Confidentiality) and ISO 27001 A.5.19 /
A.5.34 expectations.

This document is **not** legal advice. Spectra is not a law firm. Customers
should have their own counsel review this template, negotiate the open
brackets, and execute it as a binding agreement before treating it as one.

---

## 1. Definitions

For the purposes of this DPA:

- **"Customer Data"** means (a) the contents of the source code repository
  the Customer instructs the Service to analyze (file contents transmitted in
  prompts to the LLM, plus the file-tree metadata used for planning);
  (b) the findings, scores, and reports produced from that analysis;
  (c) the local SQLite cache entries derived from (a) and (b); and
  (d) the audit log entries (see Capability #12, planned for Q2) emitted
  for each scan. Customer Data does not include data Spectra never
  receives — see §2 ("Scope of Processing — what we do not process").

- **"Sub-Processor"** means a third party engaged by Spectra to Process
  Customer Data on Spectra's behalf. As of the version of this DPA listed
  above, the sole Sub-Processor is **Anthropic, PBC** ("Anthropic"). The
  current list is maintained in [`SUBPROCESSORS.md`](./SUBPROCESSORS.md).

- **"Process" / "Processing"** has the meaning given in GDPR Article 4(2):
  any operation performed on Customer Data, including transmission to a
  Sub-Processor for inference.

- **"Data Subject"**, **"Personal Data"**, **"Controller"**, **"Processor"**,
  and **"Supervisory Authority"** have the meanings given in GDPR Articles
  4 and 51.

- **"Service"** means the `spectra-ai` Python CLI distributed via PyPI and
  the `spectra-ai/spectra` GitHub Action distributed via the GitHub
  Marketplace, executed on infrastructure controlled by the Customer.

- **"ZDR"** means Anthropic's Zero Data Retention configuration, available
  to qualifying Anthropic enterprise customers and enabled per-organization
  on the Anthropic side.

---

## 2. Scope of Processing

### What Spectra processes

Spectra Processes Customer Data only to deliver the Service. Specifically:

- **Repository contents at the analysed `HEAD`.** The six specialist
  agents transmit file contents — restricted to the working tree at the
  commit the Customer scans — to Anthropic over TLS for LLM inference.
  The MetaPrompter agent receives only the file tree (paths and sizes),
  capped at 5,000 tokens, and never receives file bodies.
- **Findings and reports.** Spectra renders the Anthropic responses into
  HTML, JSON, and SARIF reports written to the Customer's filesystem.
- **Local cache.** Spectra writes a per-user SQLite cache under
  `${XDG_CACHE_HOME:-~/.cache}/spectra/$UID/cache.db` (mode `0600`,
  per-row HMAC, namespaced by effective UID — Capability #3, shipped in
  v0.5.0). The cache stores findings, batch outputs, and a hit log keyed
  by content + dimension + model + prompt + schema + Spectra version.
- **Audit log entries** (Q2 capability #12, in flight): per-scan JSON
  Lines records containing actor identity, repository signature, model
  versions, finding counts, and timing. Sink is Customer-controlled
  (file, syslog, OTLP, Splunk HEC).

### What Spectra does not process

Spectra is a CLI; it has no server, no telemetry beacon, and no centralized
data plane. Specifically, Spectra does not:

- **Read git history beyond `HEAD`.** Repository clones use `--depth 1`
  and `--no-tags`; commit history, blame, branches, and tags are not
  transmitted to Anthropic or read into the cache.
- **Persist repository bytes after the run.** The cloned working tree is
  written to a temporary directory and removed when the pipeline completes.
  Only the cache (derived findings) and the report (Customer-controlled
  output path) survive the run.
- **Aggregate Customer Data across customers or runs of other customers.**
  There is no multi-tenant data store. Each Customer's cache lives on the
  Customer's own filesystem.
- **Transmit Customer Data to any third party other than Anthropic.** No
  analytics, no error reporters, no telemetry providers. The only
  outbound network call is to Anthropic; the only inbound clone source is
  the Customer-specified Git URL (or a local path).
- **Read environment variables, files outside the workspace, or any host
  state beyond what is required to clone and analyze the named repository.**

---

## 3. Data Subject Rights

Spectra is a developer CLI; it does not maintain user accounts, customer
records, or a centralised database of Data Subjects. Most Customer Data is
source code, which only incidentally contains Personal Data (e.g., committer
names in source comments, sample data in fixtures, hard-coded test emails).

For Data Subject requests under GDPR Articles 15 — 22:

- **Access, rectification, erasure of repository contents** are exercised
  by the Customer against their own source-control system (GitHub, GitLab,
  internal Git host); Spectra is not the system of record for repository
  contents.
- **Erasure of Spectra-derived artifacts** (cache, reports, audit log) is
  exercised locally on the Customer's machine: `spectra cache clear` (full
  reset), `spectra cache prune` (stale rows), `spectra cache shred`
  (verified per-row deletion — Q2 capability #13, in flight). Report files
  are removed by deleting the output path.
- **Erasure of data already transmitted to Anthropic** is governed by
  Anthropic's own data retention policy (default 30 days, 0 days under
  ZDR — see §4) and Anthropic's data-subject request process.
- **Vulnerability and security reports about the Service itself** are
  routed via GitHub Private Vulnerability Reporting per
  [`SECURITY.md`](../../SECURITY.md). PVR is the only supported channel.

The Customer is responsible for upstream Data Subject communications;
Spectra will assist within commercially reasonable limits and within five
(5) business days of a written request from the Customer.

---

## 4. Data Retention

Retention of Customer Data is split across three locations, each governed
by a different policy:

- **Local cache (Customer machine).** Spectra retains cache entries
  indefinitely until the Customer explicitly invokes `spectra cache clear`,
  `spectra cache prune`, or (Q2 capability #13) `spectra cache shred`. The
  Customer controls the host filesystem; Spectra does not.
- **Local reports (Customer machine).** Reports are written to the path
  the Customer specifies (`--output`, default `spectra-report.html`).
  Spectra writes once and never reads them back; deletion is the
  Customer's responsibility.
- **Anthropic API retention.** Repository contents and findings transmitted
  to Anthropic are retained per the Anthropic Commercial Terms of Service
  in force at the time of the API call. As of this DPA's effective date,
  Anthropic's default retention is thirty (30) days for abuse-detection
  purposes; Anthropic's Zero Data Retention configuration (ZDR), available
  to qualifying enterprise organisations, sets retention to zero days.
  Spectra will surface ZDR enforcement via the `--zdr` flag (Q2 capability
  #15, in flight); use of `--zdr` will fail closed if the Customer's
  Anthropic API key is not associated with a ZDR-enabled organisation.

Spectra does not host, mirror, or replicate Customer Data on infrastructure
under Spectra's control. There is no Spectra-side retention to expire.

---

## 5. Sub-Processors

Spectra engages the Sub-Processors listed in
[`SUBPROCESSORS.md`](./SUBPROCESSORS.md), which is hereby incorporated by
reference. As of this DPA's effective date, the only Sub-Processor is
Anthropic, PBC, which performs LLM inference for the six specialist
agents, the MetaPrompter agent, and the CritiqueAgent.

Spectra will give the Customer at least thirty (30) days' prior written
notice (via update to `SUBPROCESSORS.md` and a release note in
[`CHANGELOG.md`](../../CHANGELOG.md)) of any intended addition or
replacement of a Sub-Processor. The Customer may object to the new
Sub-Processor in writing within that notice period; if the parties cannot
resolve the objection, the Customer may terminate the affected portion of
the Service for cause without penalty.

---

## 6. International Transfers

The Service is a CLI; it executes on infrastructure controlled by the
Customer, in the geographic location the Customer chooses to run it. The
only outbound transfer is to Anthropic's API for LLM inference.

Anthropic operates from the United States and offers regional routing
options (including EU regions via Amazon Bedrock and Google Vertex AI) to
qualifying enterprise customers. Spectra is implementing region pinning
and alternate Anthropic backends as part of Q4 capability #14 (`--region`
and `--provider bedrock|vertex|anthropic` flags); until that capability
ships, all inference traffic is routed through Anthropic's default endpoint.

Where Customer Data includes Personal Data of EEA, UK, or Swiss Data
Subjects and is transferred to Anthropic in the United States, the
Customer and Anthropic are responsible for executing the appropriate
Standard Contractual Clauses (EU 2021/914), the UK International Data
Transfer Addendum, and any equivalent mechanisms in force. Spectra is
not a party to those clauses but will not impede their operation.

---

## 7. Security Measures

Spectra implements technical and organisational measures appropriate to
the risk of Processing, as described in [`SECURITY.md`](../../SECURITY.md).
The v0.5.0 release in particular introduced the following hardening that
this DPA relies upon:

- **Per-row HMAC and per-`$UID` cache namespace** (Capability #3): the
  local cache is keyed under `~/.cache/spectra/$UID/cache.db` with file
  mode `0600` and a per-row HMAC, eliminating cross-tenant reads on
  shared developer hosts and CI runners.
- **Secret pre-flight scan** (Capability #6): a curated regex pass blocks
  `.env`, RSA/OpenSSH keys, AWS / GitHub / Anthropic / Slack credentials,
  and bearer tokens from reaching any prompt or cache key. Bypass requires
  the explicit `--allow-secrets` flag, and bypassed runs log every match
  at WARN level. Detection raises `SPEC-011`.
- **Prompt-injection isolation** (Capability #1): per-file delimiter
  nonces and an adversarial CritiqueAgent prompt prevent instructions
  embedded in analyzed code from rewriting Spectra's own prompts.
- **`.gitignore` honoured by default** plus `.spectraignore` for
  Spectra-specific exclusions; both apply before any byte reaches a prompt.
- **SLSA L3 build provenance and Sigstore-signed wheels** for every PyPI
  release; verification commands are in [`README.md`](../../README.md)
  ("Verifying releases").
- **Decorator chain** for all LLM calls (LoggingDecorator → RetryDecorator
  → AnthropicAdapter); no agent issues a raw Anthropic call.
- **Cache failures are never fatal** (SPEC-010): cache I/O errors degrade
  to no-cache for the rest of the run rather than aborting.

Spectra will not materially weaken these measures during the term of the
Agreement without written notice to the Customer.

---

## 8. Audit Rights

Once Capability #12 (the structured audit log, in flight for Q2) ships,
the Customer may at any time, on no less than thirty (30) days' notice
and no more than once per twelve-month period (except in the event of a
confirmed Personal Data breach), request:

- **Scan audit log excerpts** for runs the Customer initiated, in JSON
  Lines format, scoped to a defined time window and actor identity.
- **A configuration snapshot** of the Spectra binary version, model
  versions, prompt versions, and schema version active during the period
  (the same four-tuple bound by `bind_run_context` at the composition
  root).
- **Sub-processor changes** during the period, as recorded in the
  versioned [`SUBPROCESSORS.md`](./SUBPROCESSORS.md) and the
  [`CHANGELOG.md`](../../CHANGELOG.md).

Spectra will respond to written audit requests within ten (10) business
days. Spectra is not obligated to provide on-site physical audits of the
Customer's own infrastructure, since the Service runs on the Customer's
infrastructure.

Independent third-party attestation of Spectra's organisational controls
(SOC 2 Type II for the Spectra organisation itself — roadmap capability
#63) is on the long-range roadmap and is gated on annual recurring
revenue thresholds. Spectra will share the attestation report under NDA
once available.

---

## 9. Termination

On termination of the Agreement, the Customer may exercise the following
local actions to remove Customer Data from systems under the Customer's
control:

- **`spectra cache shred`** (Q2 capability #13, planned for v0.6.0):
  performs verified per-row deletion of all cache entries for the current
  user, returning a count of rows shredded.
- **`spectra cache clear`** (shipped): drops all cache entries.
- **Filesystem deletion** of the cache directory and any report files.

For Customer Data already transmitted to Anthropic, deletion is governed
by Anthropic's data retention policy and any ZDR configuration in force
on the Customer's Anthropic account. Spectra will, on written request,
provide the Customer with the timestamp range of API calls Spectra
initiated on the Customer's behalf so the Customer can scope an Anthropic
deletion request precisely.

Spectra has no centralised store of Customer Data to delete; there is
nothing on the Spectra side to confirm deletion of.

---

## 10. Liability and General Provisions

This DPA is subordinate to the Agreement; in the event of conflict, the
Agreement governs except where this DPA is required to comply with
applicable Data Protection Law, in which case this DPA prevails.

Governing law and jurisdiction default to **Delaware, USA** unless the
Agreement specifies otherwise. (Open question: confirm with the customer
the appropriate governing law and exclusive jurisdiction; Delaware is a
reasonable starting default for a US-incorporated processor.)

This DPA may be amended only in writing, signed by both parties, with
the exception of updates to [`SUBPROCESSORS.md`](./SUBPROCESSORS.md),
which are governed by §5 above.

---

## Disclaimer

**This DPA is a template, not a binding agreement.** Spectra is an
engineering organisation, not a law firm. The bracketed and italicised
items in this template — governing law, jurisdiction, Customer entity
name, Service definition scope, indemnity carve-outs that may belong in
the master Agreement — require negotiation and review by the Customer's
legal counsel before this template is treated as enforceable.

Spectra publishes this template so that procurement and legal teams have
a starting position rather than a blank page. Use it as a draft;
do not use it as a substitute for legal advice. If your organisation
requires a counter-signed DPA before procurement can complete, please
open a private conversation with Spectra via GitHub Private Vulnerability
Reporting (linked from [`SECURITY.md`](../../SECURITY.md)) or the
contact path documented in the Agreement.

---

*Cross-references: [`SUBPROCESSORS.md`](./SUBPROCESSORS.md) ·
[`DATA_FLOW.md`](./DATA_FLOW.md) · [`SECURITY.md`](../../SECURITY.md) ·
Roadmap capabilities #11 (this pack), #12 (audit log), #13 (cache shred),
#14 (region pinning), #15 (ZDR).*
