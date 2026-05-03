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

## Known supply-chain risks

We track risks in our runtime dependency tree that do not yet warrant a hard pin
or a fork, but that maintainers and security reviewers should be aware of.

### `pysqlcipher3` — Python bindings unmaintained since 2019

- **What it is.** `pysqlcipher3` provides Python bindings to `libsqlcipher`,
  the actively maintained C library that backs SQLCipher (a transparent
  AES-256 extension for SQLite). The C library ships regular releases. The
  Python wheel bindings have not shipped a new release since 2019.
- **How Spectra uses it.** At-rest encryption for the local cache database
  only (Q2 #13). The cache stores per-file findings, per-batch findings, and
  full-report write-back rows; it never stores credentials.
- **Opt-in install.** Since v0.8.1 `pysqlcipher3` is an `[encryption]` extra,
  not a runtime dependency. The default `pip install spectra-ai` works on a
  clean macOS without `brew install sqlcipher`; operators who want at-rest
  encryption install with `pip install "spectra-ai[encryption]"`.
- **Failure mode is graceful, not fatal.** When `import pysqlcipher3` fails
  (missing wheel on Windows, libsqlcipher unavailable on the platform, etc.),
  `SqliteCacheAdapter` degrades to plain SQLite plus a `WARN` on the
  ProgressObserver. The cache stays functional and the per-row HMAC integrity
  check (ADR-012) remains active — only at-rest confidentiality is lost.
- **Mitigation roadmap.** We monitor `sqlcipher3-binary` (community fork,
  actively maintained) for production-readiness. When the fork has a stable
  release with maintainers we can reach and a track record on the platforms
  we support (macOS, Linux, Windows), we will switch in a single Renovate PR
  + CHANGELOG entry. Until then, the fallback path above is the documented
  safe behavior.

## Hall of Fame

Researchers who report a confirmed vulnerability through this policy and follow coordinated disclosure are listed here, with permission.

<!-- Format: - <name or handle> — <CVE or advisory> — <release fixed in> -->
_(empty — be the first)_

---

Thank you for helping keep Spectra and its users safe.
