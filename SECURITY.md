# Security Policy

Spectra takes the security of the CLI, the GitHub Action, and the supply chain that produces them seriously. This document describes which versions we patch, how to report a vulnerability, our disclosure timeline, and what is in and out of scope.

## Supported versions

We patch only the latest minor release. Older minors receive security fixes only if a critical vulnerability has no available workaround and the migration path is non-trivial.

| Version | Supported          |
| ------- | ------------------ |
| 0.4.x   | Yes                |
| < 0.4   | No — please upgrade |

The `pip install spectra-ai` install path always resolves to a supported version.

## Reporting a vulnerability

Please **do not open a public GitHub issue** for security reports.

Use GitHub Private Vulnerability Reporting (PVR):

> https://github.com/leocder07/spectra/security/advisories/new

PVR routes the report directly and privately to the maintainers, gives us a working draft advisory, and lets us request a CVE through GitHub's CNA when the report is confirmed. No email channel is offered — PVR is the single supported path so reports do not get lost in spam filters.

When you file, please include:

- Affected version(s) and install method (PyPI, source, GitHub Action)
- A minimal reproduction (commands, sample repo URL, redacted logs)
- Impact assessment (what an attacker gains, prerequisites)
- Suggested remediation, if you have one

We acknowledge new reports within **2 business days**.

## Disclosure timeline

| Stage                              | Target              |
| ---------------------------------- | ------------------- |
| Acknowledge receipt                | 2 business days     |
| Initial triage + severity          | 5 business days     |
| Fix landed in `main`               | 30 days (default)   |
| Coordinated public disclosure      | 90 days (default)   |
| Accelerated disclosure             | < 7 days, if actively exploited in the wild |

If a fix is not feasible within 90 days, we will coordinate an extension with the reporter. Spectra follows responsible disclosure norms — reporters who follow this process are credited in the Hall of Fame below (opt-in).

## CVE assignment

Spectra requests CVEs through **GitHub's CNA** (CVE Numbering Authority). When a report is confirmed and a fix is in flight, the maintainers reserve a CVE via the draft advisory, then publish the CVE alongside the fixed release.

## Scope

In scope (we will accept reports against these):

- The `spectra-ai` Python CLI (this repo, `src/spectra/**`)
- The Spectra GitHub Action (`action.yml` and the workflow it composes)
- Build / release artifacts on PyPI under the `spectra-ai` project
- Composition-root configuration (`src/spectra/infrastructure/main.py`) and the cache subsystem
- Prompt-injection paths inside the agent pipeline that allow tool / plan tampering
- Any path by which an analyzed repo can exfiltrate or corrupt host state outside of the repo workspace

## Out of scope

Reports on the following will be closed as out of scope unless they include a Spectra-specific exploit path:

- The Anthropic API itself (report directly to Anthropic)
- Third-party integrations Spectra calls out to (GitHub API, Git itself, PyPI mirrors)
- Forks of Spectra under other accounts
- Social engineering of maintainers or contributors
- Denial-of-service via large or pathological repositories (already constrained by token budgets and per-agent timeouts)
- Transitive dependency CVEs that have no exploit path through Spectra's actual usage of that dependency
- Findings that require an attacker to already have full local shell access on the user's machine
- Self-XSS in HTML reports the user opens locally from a trusted source repo

## Hardening features already shipped

For context, when assessing whether a finding is in scope:

- SLSA L3 build provenance and Sigstore-signed wheels (see README → Verifying releases)
- Pinned dependency upper bounds + `requirements.lock` for deterministic installs
- No `Any` types, no `# type: ignore`, strict mypy on the entire src tree
- Cache I/O failures degrade gracefully — never fatal (SPEC-010)
- All LLM calls go through a logging + retry decorator chain; no raw API access

## Hall of Fame

Researchers who report a confirmed vulnerability through this policy and follow coordinated disclosure are listed here, with permission.

<!-- Format: - <name or handle> — <CVE or advisory> — <release fixed in> -->
_(empty — be the first)_

---

Thank you for helping keep Spectra and its users safe.
