# GitHub Action Distribution Flow

How `leocder07/spectra@v1` lands in a downstream repository, what runs on every PR, and the deliberate non-dogfood decision recorded in [ADR-010](../architecture/adr/ADR-010-no-self-dogfooding.md).

## End-to-end PR flow (sequence)

```mermaid
sequenceDiagram
    actor Dev as Downstream<br/>Developer
    participant Repo as Downstream Repo<br/>(consumer)
    participant GH as GitHub<br/>(workflow runner)
    participant Action as spectra-ai/<br/>spectra@v1<br/>(composite)
    participant PyPI as PyPI<br/>(spectra-ai package)
    participant CLI as spectra analyze
    participant Anth as Anthropic API<br/>(Claude Opus 4.7)
    participant API as GitHub REST API

    Dev->>Repo: open PR
    Repo->>GH: workflow_run on pull_request
    GH->>GH: actions/checkout@v4 (repo SHA)
    GH->>Action: uses: leocder07/spectra@v1<br/>with: anthropic-api-key, path=.

    rect rgb(245, 158, 11, 0.1)
        Note over Action,PyPI: Step 1 — install
        Action->>GH: actions/setup-python@v5 (Python 3.12, pip cache)
        Action->>PyPI: pip install --upgrade spectra-ai<br/>(or pinned spectra-version input)
        PyPI-->>Action: package installed
    end

    rect rgb(124, 58, 237, 0.1)
        Note over Action,CLI: Step 2 — run analysis
        Action->>CLI: spectra analyze "${path}" --format json --output spectra-report.json
        Note over CLI: ANTHROPIC_API_KEY=${{ inputs.anthropic-api-key }}
        CLI->>Anth: 8 agents · Opus 4.7 · cache R/W locally on the runner
        Anth-->>CLI: streamed responses
        CLI-->>Action: spectra-report.json (overall_grade, overall_score, findings[])
    end

    rect rgb(34, 197, 94, 0.1)
        Note over Action: Step 3 — parse outputs
        Action->>Action: jq .score_card.overall_grade<br/>jq .score_card.overall_score
        Action->>GH: outputs.grade · outputs.score · outputs.findings-json
    end

    rect rgb(239, 68, 68, 0.1)
        Note over Action,API: Step 4 — idempotent PR comment
        alt event = pull_request AND comment-on-pr = true
            Action->>API: GET /repos/.../issues/{pr}/comments
            API-->>Action: existing comments[]
            alt found "<!-- SPECTRA -->" marker
                Action->>API: PATCH .../comments/{id}<br/>(updateComment with new body)
            else not found
                Action->>API: POST .../issues/{pr}/comments<br/>(createComment with marker prefix)
            end
            API-->>Repo: comment posted/updated (one per PR, always)
        end
    end

    Action-->>GH: action complete
    GH-->>Dev: PR check status + grade + comment
```

## What the comment looks like

```html
<!-- SPECTRA -->
## Spectra · grade B+ (85.7 / 100)

| Dimension | Score | Grade |
|-----------|------:|:-----:|
| Architecture | 88 | A- |
| Security | 79 | C+ |
| Quality | 87 | A- |
| ...

### Top critical findings
1. Hard-coded API key in src/auth.py:42 ...
```

The first line — `<!-- SPECTRA -->` — is the load-bearing sentinel. It's invisible in rendered Markdown and unmistakable to a string-search comment scanner. Every re-run of the workflow finds the same comment and updates it in place. A PR with 14 force-pushes still has exactly one Spectra comment, always reflecting the latest run.

## Caller's workflow shape

```yaml
# .github/workflows/spectra.yml in a downstream repo
name: Spectra
on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write   # required only when comment-on-pr=true

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: leocder07/spectra@v1
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          # path: .            # default
          # format: json       # default
          # quick-mode: false  # default
          # comment-on-pr: true # default
          # spectra-version: "0.2.0"  # optional pin
```

## Action manifest — where the decisions live

| Concern | Location in `action.yml` | Note |
|---------|--------------------------|------|
| Required input | `inputs.anthropic-api-key` (`required: true`) | Caller must wire from `${{ secrets.* }}` |
| Optional path | `inputs.path` (`default: "."`) | CLI now accepts local paths directly (no clone-URL workaround needed) |
| Format | `inputs.format` (`default: json`) | JSON is recommended for CI parsing |
| Quick mode | `inputs.quick-mode` (`default: false`) | Skips CritiqueAgent; ~60s vs ~3min |
| Idempotency | `inputs.comment-on-pr` + `<!-- SPECTRA -->` marker | Single comment per PR |
| Python version | `inputs.python-version` (`default: 3.12`) | Spectra requires 3.12+ |
| Pinning | `inputs.spectra-version` (default: latest) | Caller can pin to a known-good release |
| Outputs | `outputs.grade`, `outputs.score`, `outputs.findings-json` | Other workflow steps can gate on these |
| 3rd-party Action SHAs | `actions/setup-python@0b93645…`, `actions/github-script@…` | Pinned by SHA, not by tag |

## Why this repo does NOT run its own Action on its own PRs

Most projects close the dogfood loop by running their own GitHub Action on their own pull requests. Spectra deliberately does **not**. The decision and its rationale are in [ADR-010](../architecture/adr/ADR-010-no-self-dogfooding.md). The short version:

```mermaid
flowchart LR
    classDef bad fill:#fee2e2,stroke:#7f1d1d,color:#1e293b
    classDef good fill:#dcfce7,stroke:#166534,color:#1e293b

    A[Attacker forks the repo] --> B[Edits .github/workflows/spectra.yml]
    B --> C[Opens a PR with the modified workflow]
    C --> D{pull_request_target<br/>or pull_request?}
    D -- "either" --> E[Workflow runs with secrets.ANTHROPIC_API_KEY]:::bad
    E --> F[Modified workflow exfiltrates the key<br/>to attacker-controlled endpoint]:::bad

    G[Solution] --> H[No spectra workflow on PR events]:::good
    H --> I[Downstream consumers wire it in their own repos<br/>with their own secrets]:::good
```

The `pull_request` event scopes secrets carefully (read-only token, no env secrets exposed to forked-PR runs by default), but the surface area is non-trivial — and an organization API key attached to the *publisher* repository is a tier-1 incident if leaked. Removing the self-analysis workflows (`spectra.yml`, `spectra-analyze.yml`, `example-usage.yml`) eliminates the entire class of attack with no functional loss: we still test the Action in CI on push events to maintained branches, just not on untrusted PRs.

The Action itself is published, exercised externally, and supported normally — only the *self-application* is gone.

## Reference flow — Action component diagram

```mermaid
flowchart TB
    classDef external fill:#fef3c7,stroke:#92400e,color:#1e293b
    classDef action fill:#ede9fe,stroke:#7C3AED,color:#1e293b
    classDef cli fill:#dcfce7,stroke:#166534,color:#1e293b

    subgraph Runner["GitHub-hosted runner"]
        direction TB
        SetupPy["actions/setup-python@v5<br/>(Python 3.12, pip cache)"]:::action
        Install["pip install spectra-ai"]:::action
        Run["spectra analyze . --format json --output spectra-report.json"]:::cli
        Parse["jq parse: grade, score, findings-json"]:::action
        Comment["actions/github-script@v7<br/>find-or-update <!-- SPECTRA --> comment"]:::action
    end

    PyPI["PyPI · spectra-ai"]:::external
    Anthropic["Anthropic API<br/>Claude Opus 4.7"]:::external
    GHAPI["GitHub REST API<br/>issues/comments"]:::external

    SetupPy --> Install
    Install -.fetches.-> PyPI
    Install --> Run
    Run -.HTTPS streaming.-> Anthropic
    Run --> Parse
    Parse --> Comment
    Comment -.PATCH/POST.-> GHAPI
```

## References

- Action manifest: [`action.yml`](../../action.yml)
- ADR — distribution decision: [ADR-007](../architecture/adr/ADR-007-github-action-distribution.md)
- ADR — non-dogfood decision: [ADR-010](../architecture/adr/ADR-010-no-self-dogfooding.md)

---

*Last updated: 2026-04-29 — initial diagram covering the v1 composite Action, the idempotent comment pattern, and the non-dogfood rationale.*
