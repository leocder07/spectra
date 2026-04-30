# Sub-Processors

**Status:** Authoritative list — versioned in this repository.
**Version:** 0.1 (initial declaration, v0.5.0 baseline)
**Last reviewed:** 2026-04-29
**Owner:** Spectra Engineering (Vivek Kumar, Head of Engineering)

This document declares every Sub-Processor that Processes Customer Data on
Spectra's behalf, as required by the Data Processing Addendum
([`DPA.md`](./DPA.md), §5). It is the single source of truth for
Sub-Processor identity, purpose, region, retention, and the Customer's
ability to opt out.

Material changes to this list (additions, replacements, regional changes)
will be announced in [`CHANGELOG.md`](../../CHANGELOG.md) at least thirty
(30) days before they take effect.

---

## Current Sub-Processors

| Sub-processor       | Service     | Purpose                                            | Region                                                        | Retention                                                          | Customer can opt out                                  |
| ------------------- | ----------- | -------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------- |
| **Anthropic, PBC**  | Claude API  | LLM inference for the eight specialist agents      | United States (default); EU via Amazon Bedrock or Google Vertex AI (Q4 capability #14) | Per Anthropic's Commercial Terms — default 30 days, 0 days under ZDR | Yes — `--zdr` flag (Q2 capability #15, in flight)     |

---

## Notes

**Spectra has no other Sub-Processors.** No analytics provider, no error
reporter, no telemetry pipeline, no third-party logging service. The only
outbound network calls Spectra makes during a scan are:

1. To the Customer-specified Git host (`git clone --depth 1 --no-tags`),
   which is a Customer relationship and not a Spectra Sub-Processor.
2. To Anthropic's API for LLM inference, as declared above.

No Customer Data is transmitted to PyPI, GitHub Actions infrastructure,
or any other third party as part of normal Service operation. Spectra
does not aggregate Customer code across customers, persist it on Spectra
infrastructure, or transmit it outside the single Anthropic API call per
agent invocation. The local SQLite cache lives on the Customer's machine
under `${XDG_CACHE_HOME:-~/.cache}/spectra/$UID/cache.db`; no Spectra
process ever reads from a Customer's cache.

---

## Region detail

Today, every inference request is routed to Anthropic's default endpoint
(US). Customers requiring EU residency should use the Q4 capability #14
flag set when it ships:

```bash
spectra analyze <repo> --region eu-west-1 --provider bedrock
```

Until that capability lands, EU-residency customers should not transmit
Personal Data of EEA Data Subjects through Spectra without first executing
appropriate Standard Contractual Clauses with Anthropic for the US transfer.

---

## Retention detail

Anthropic's default API retention applies a thirty (30) day abuse-detection
window to API request and response bodies. Anthropic's Zero Data Retention
configuration (ZDR) sets that window to zero days and is available to
qualifying Anthropic enterprise organisations on a per-organisation basis.

Spectra does not enforce ZDR on the Customer's behalf today. Q2 capability
#15 ships a `--zdr` flag that fails closed if the configured Anthropic API
key is not associated with a ZDR-enabled organisation; once shipped, this
gives the Customer a deterministic enforcement point rather than a
trust-but-verify posture.

---

## Change procedure

Adding, replacing, or materially changing a Sub-Processor requires:

1. A pull request updating this file.
2. A `CHANGELOG.md` entry under the upcoming release.
3. Thirty (30) days' notice between the release that adds the
   Sub-Processor and the date Customer Data first reaches it.

Customers who object to a new Sub-Processor may exercise the rights in
[`DPA.md`](./DPA.md) §5 within the notice window.

---

*Cross-references: [`DPA.md`](./DPA.md) · [`DATA_FLOW.md`](./DATA_FLOW.md)
· [`SECURITY.md`](../../SECURITY.md).*
