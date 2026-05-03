# ADR-027: Deterministic Compliance Mapping

## Status

Proposed (2026-05-04) — implements Q4 capability **#60** (deterministic
compliance mapping) and retires the v0.7.0 "compliance positioning,
not auditor-grade evidence" banner. See
[`q4-plan.md`](../../strategy/q4-plan.md).

## Context

v0.6.0 shipped a compliance section in the HTML report mapping findings
to SOC 2 / OWASP Top 10 / PCI DSS controls. The mapping was a keyword
heuristic: "if the finding contains tokens X, Y, or Z it implicates
control C." The v0.7.0 self-scan and the M8 trust-and-compliance pack
both flagged this as the weakest claim in the report — keyword
matching is not auditor-grade evidence, and the report's own banner
acknowledged it: *"Compliance positioning, not auditor-grade evidence."*

The product-roadmap commits to retiring that banner in Q4: *"Q4:
replace the keyword mapping with rule-traceable mapping (each control
links to deterministic CWE/CVE/pattern matches). Drop (a) — toning
down without fixing means we lose the meeting-landing power of the
compliance section without gaining audit-grade defensibility."*

Three load-bearing questions:

1. **What does "deterministic" mean operationally?** A mapping is
   deterministic if (a) the same finding maps to the same control(s)
   on every scan, (b) the trace from finding → control is human-
   verifiable, and (c) the rule that produced the trace is itself
   reviewable (not buried in agent prompt text). Keyword matching
   fails (a) when the model paraphrases; fails (b) because the trace
   is implicit; fails (c) because the keyword list lives in agent
   prompts.
2. **What is the source of truth for the trace?** Two candidates: the
   CWE catalogue (machine-readable, MITRE-curated, ~1100 weakness
   classes) and the framework's own control text (SOC 2 CC6.1 prose,
   etc.). The mapping must compose: each control row in the report
   needs to cite both the framework's control ID *and* the CWE
   evidence that justifies the link.
3. **Who maintains the rulebook over time?** SOC 2 / PCI / HIPAA
   change yearly; CWE adds entries quarterly. A mapping committed to
   the repo as a static YAML is brittle if maintenance is implicit.
   Maintenance must be explicit, signed, and reviewable.

## Decision

**Mapping moves from agent-prompt-keyword to a per-framework rulebook
that traces every control to one or more CWE entries plus an optional
file-pattern disambiguator.**

**Layer 2 surface:**

```python
# src/spectra/use_cases/interfaces.py

class ComplianceMapper(Protocol):
    """Map a finding to the compliance controls it implicates."""

    def map(self, finding: Finding) -> tuple[ComplianceControl, ...]: ...
    def explain(self, finding: Finding, control: ComplianceControl) -> str:
        """Return the human-readable trace: CWE family + file-pattern + matcher."""
        ...
```

**Layer 1 entity:**

```python
# src/spectra/entities/compliance.py

class ComplianceControl(BaseModel):
    model_config = ConfigDict(frozen=True)
    framework: Literal["SOC2", "PCI-DSS", "HIPAA", "OWASP-Top-10", "ISO-27001"]
    control_id: str          # "CC6.1", "10.2.1", "164.312(a)(1)", "A1:2021", "A.9.4.2"
    cwe_ids: tuple[str, ...] # CWE source(s) — MITRE ID format, e.g. "CWE-284"
    cve_ids: tuple[str, ...] # CVE evidence (when applicable)
    severity_match: float    # 0.0-1.0 mapper confidence
```

**Layer 4 adapter — `RulebookComplianceMapper`** reads
`docs/compliance/<framework>.yml` rule packs:

```yaml
# docs/compliance/soc2.yml

framework: "SOC2"
schema_version: "1.0"
controls:
  - control_id: "CC6.1"
    description: |
      Access to system resources, including physical and logical access,
      is restricted to authorized users.
    cwe_traceable:
      - "CWE-284"   # Improper Access Control
      - "CWE-285"   # Improper Authorization
      - "CWE-862"   # Missing Authorization
    trigger:
      finding_dimension: "security"
      file_patterns:
        - "**/auth/**"
        - "**/permissions/**"
        - "**/middleware/auth*"
    severity_floor: "high"   # only "high" or "critical" findings map
```

**Mapping rule:** A finding maps to a control only when **both**:

1. The finding's CWE assignment intersects the control's
   `cwe_traceable` set, AND
2. The finding's file path matches one of the control's
   `file_patterns`.

Pure keyword matches are explicitly rejected at rule-parse time. A
rulebook YAML that contains a `keyword_match:` field fails to load
with a clear error (the v0.7.0 shape is not loadable under the new
schema).

**Report row format change:**

Old (v0.7.0):
```
SOC 2 CC6.1 — 3 findings (keyword: "auth", "permission", "rbac")
[compliance positioning, not auditor-grade evidence]
```

New (Q4 v0.10.0):
```
SOC 2 CC6.1 — 3 findings (2 ↦ CWE-284, 1 ↦ CWE-862)
Auditor-grade trace: every finding cites a CWE family and a file pattern.
```

The deferred banner is removed.

**Rulebook signing.** Every rulebook YAML in `docs/compliance/` is
signed by the same Sigstore identity that signs the wheels. A rulebook
PR that lands an unsigned YAML, or a YAML whose signature does not
verify, fails CI. Customers verify the bundled rulebook signatures on
install (the verification surface mirrors the `gh attestation verify`
flow we already use for the wheel).

**CWE assignment lives on the `Finding` entity.** Specialist agent
prompts are extended to require a `cwe: list[str] | None` field on
every security/quality finding (other dimensions are exempt). The
existing Pydantic validator rejects findings without a valid
`CWE-NNNN` format when the dimension is `security`. This is the only
agent-prompt change required for #60.

**Migration of the v0.7.0 catalogue.** The 32 keyword groups in the
v0.7.0 mapper translate to ~80 control rules across the five
frameworks (some keyword groups split across multiple controls). The
migration is a one-shot script (`scripts/migrate_compliance_v07.py`)
producing the YAML packs; reviewed by hand before commit.

**Rulebook ownership for Q4** is open-source-first: we ship one
official pack per framework; customers extend via a sibling rule
file (`docs/compliance/<framework>.<org>.yml`) that the mapper
loads alongside the official pack. Vertical-specific paid packs
(HealthTech-HIPAA, FinTech-PCI) are deferred to Q5+ pending the
go-to-market call (see q4-plan.md §"Open questions" #3).

## Consequences

### Positive

- **The Q1 deferred banner retires.** v0.10.0 reports do not carry the
  "positioning, not evidence" caveat because the trace is
  deterministic and human-verifiable.
- **Auditor-grade defensibility.** A SOC 2 auditor can take a report
  row, click through to the CWE source, click through to the file
  pattern, click through to the actual finding — every step is
  inspectable.
- **Sales-defensible for regulated buyers.** First HIPAA-curious
  customer can run the report, see HIPAA-controls mapping that traces
  to CWE evidence, and has something to bring to their auditor.
- **CWE assignment becomes a quality signal in its own right.** A
  finding without a CWE assignment is itself a quality bug we can
  surface in the report's QC section ("3 security findings missing CWE
  classification").

### Negative

- **Specialist prompt change has rollout risk.** Adding the `cwe:` field
  to security/quality findings can lower the model's pass rate on the
  Pydantic validation. Mitigation: ship the prompt change behind a
  feature flag for one release; gate on validation pass-rate stays
  ≥97% on the leaderboard set.
- **Rulebook maintenance is real engineering ongoing-cost.** SOC 2
  Trust Services Criteria revisions, PCI DSS major-version transitions,
  CWE catalogue additions all require rulebook updates. Mitigation:
  the rulebook YAML schema is small and the update path is a normal
  PR; quarterly review cadence in the engineering calendar.
- **Removing the keyword fallback removes some coverage.** Some
  v0.7.0 mappings (e.g. "anything that mentions logging implicates SOC
  2 CC7.2") are too broad to encode as CWE+file-pattern. The
  v0.10.0 report will show fewer mapped controls per finding, not
  more. The trade is honest mapping over loose mapping.

### Neutral

- The compliance section continues to be opt-in (`--include-compliance`
  flag from v0.6.0+). Operators who want only the technical findings
  see no change.

## Alternatives considered

### A. Keep the keyword mapper; just relabel

Move the banner to a footnote, add CWE references in the footer, leave
the matching logic intact.

**Rejected.** The product-roadmap explicitly rejects this option:
*"toning down without fixing means we lose the meeting-landing power
of the compliance section without gaining audit-grade defensibility."*
Customers either trust the mapping or they don't; cosmetic relabelling
doesn't move the trust needle.

### B. Pure CWE mapping, drop file patterns

Map every finding to controls based on CWE alone; drop the file-pattern
disambiguator.

**Rejected.** False-positive rate becomes unacceptable (CWE-79 — XSS —
maps to ~12 SOC 2 controls if you take the catalogue literally, but
only 2-3 are meaningful for any given finding). File patterns scope
the mapping to "the part of the codebase where this control actually
applies."

### C. LLM-as-mapper (CritiqueAgent maps findings to controls)

Have CritiqueAgent classify each finding's compliance implications.

**Rejected.** Same problem as the v0.7.0 keyword approach — the trace
is opaque, the output is non-deterministic, and "the LLM said so" is
not auditor-grade. We use the LLM to *find* issues; we use the
deterministic mapper to *classify* them.

### D. Punt to a third-party compliance vendor (Vanta, Drata, Secureframe)

Skip the in-product mapping entirely; ship the technical findings and
let customers' compliance vendors do the mapping in their own tooling.

**Rejected.** The compliance section is a sales-meeting-landing
feature, not a back-office function. Customers ask for it in the demo;
shipping without it costs deals. The third-party vendors map at the
control-evidence level (collected screenshots, policy docs); they do
not map per-finding from a code analyzer. The two surfaces are
complementary, not substitutes.

## References

- [`q4-plan.md`](../../strategy/q4-plan.md) §#60 — capability spec
- [`product-roadmap.md`](../../strategy/product-roadmap.md) §Conflict on
  compliance evidence — original "drop or fix" call
- v0.6.0 self-scan compliance findings — driving signal
- MITRE CWE catalogue — `https://cwe.mitre.org/`
- SOC 2 Trust Services Criteria 2017 (current as of Q4) — control
  source text
- PCI DSS v4.0 — control source text
- OWASP Top 10 2021 — control source text
- Sigstore — rulebook signing identity
