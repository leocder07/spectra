# ADR-007: GitHub Action as Primary CI Distribution

## Status

Accepted (2026-04-22)

## Context

Spectra ships as a Python CLI on PyPI (`spectra-ai`). That covers the local-developer use case — `pip install spectra-ai` then `spectra analyze <repo>`. But the highest-leverage use case is automated PR review: every pull request gets a grade, top critical findings, and a per-dimension breakdown posted as a comment, so reviewers see Spectra's analysis before they open the diff.

Three distribution shapes were on the table for CI:

1. **Document the CLI invocation; ask users to write their own workflow.** Maximum flexibility, minimum onboarding ergonomics. Every team writes the same boilerplate (set up Python, install package, run, parse JSON, post comment). The barrier-to-first-PR-comment is high.
2. **Ship a Docker image.** Self-contained, reproducible, but adds a ~600MB image build/pull on every workflow run. Slower than installing from PyPI on a warm cache. Forces us to maintain Docker image builds in CI, image registry hygiene, etc.
3. **Ship a composite GitHub Action.** Thin YAML wrapper that installs the PyPI package on the runner, runs the CLI, and posts the PR comment. Single place for the "install + run + comment" workflow logic. Versioning via git tags (`@v1`, `@v1.0.3`).

The PR comment behavior also has a design choice baked in: should the Action post a *new* comment per workflow run (timeline spam) or *update* a single comment in place (one source of truth per PR)?

## Decision

**Ship a composite GitHub Action at the repository root (`action.yml`), referenced as `leocder07/spectra@v1`.** The Action installs the `spectra-ai` PyPI package on the runner's Python and shells out to `spectra analyze`. PR commenting is **idempotent** — find-or-create one comment per PR via a hidden HTML marker.

### Composite Action shape

```yaml
# Caller's workflow:
- uses: leocder07/spectra@v1
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Internally (`action.yml`):

1. `actions/setup-python@v5` (pinned by SHA) installs the requested Python version with pip cache enabled.
2. `pip install --upgrade spectra-ai` (optionally version-pinned via the `spectra-version` input).
3. Run `spectra analyze "${TARGET}" --format json --output spectra-report.json`.
4. Parse `score_card.overall_grade` and `score_card.overall_score` into action outputs.
5. On `pull_request` events with `comment-on-pr: "true"`, use `actions/github-script@v7` (pinned by SHA) to find-or-update a comment marked with `<!-- SPECTRA -->`.

Outputs:
- `grade` — letter grade (`A+` through `F`).
- `score` — numeric score 0–100.
- `findings-json` — path to the raw JSON report on the runner (consumable by `actions/upload-artifact`).

### Idempotent comment pattern

Every PR comment Spectra posts begins with the literal string `<!-- SPECTRA -->`. On each run, the Action lists existing comments via the GitHub API, finds the one containing the marker, and:
- If found → `updateComment` with the new body.
- If not found → `createComment`.

This means a PR with 14 force-pushes still has exactly one Spectra comment, always reflecting the latest run. The marker is invisible in rendered Markdown but trivially detectable by string search — no need to track comment IDs in any external store.

### Why composite, not Docker or JavaScript

- **Composite** is just YAML. Reviewers can read the whole Action in one screen. No build pipeline.
- **Docker** would force us to maintain image builds for every Spectra release, and pull a multi-hundred-MB image on every workflow run. We'd own the registry hygiene.
- **JavaScript** Actions force us to maintain Node code with `node_modules` checked in. Spectra is a Python project; mixing in Node is friction without benefit.

The composite Action lets us delegate the heavy lifting (Python install, package install, network calls) to existing well-maintained Actions and a single CLI invocation.

### Local-path TODO

Today the CLI's URL validator only accepts `https://` URLs (a security choice from the original `GitAdapter` design). The Action works around this by inferring `https://github.com/$GITHUB_REPOSITORY.git` when the caller's `path` input is `.` (the default). This works for any repo the runner can clone — including private repos, since the runner's `GITHUB_TOKEN` is implicitly available to git.

The workaround has two costs:
- The runner re-clones the repo even though `actions/checkout` has already done so (~1–3s of waste).
- It fails for callers who actually want to analyze a directory that isn't `$GITHUB_REPOSITORY` (e.g. a subdirectory of a monorepo).

A `feat/cli-local-path` worktree is teaching the CLI to accept local filesystem paths as a separate work stream. When that lands, the Action will pass `${{ github.workspace }}` directly and skip the inference. The `# TODO(spectra-ai)` comment in `action.yml` tracks this.

## Consequences

### Positive

- **One-line install for CI consumers.** `uses: leocder07/spectra@v1` covers 95% of users. Recipes in `docs/github-action.md` cover the rest (gating PRs by score, uploading reports as artifacts, draft-mode quick analysis).
- **Single source of truth per PR.** The idempotent comment pattern means re-running the workflow doesn't create timeline noise. Reviewers always see the latest result inline.
- **PyPI is the only canonical artifact.** No Docker registry to maintain. Releases happen via PyPI; the Action consumes whatever is published. Version pinning via `spectra-version` input gives consumers an escape hatch.
- **Dogfood loop closed.** `.github/workflows/spectra.yml` runs the Action on Spectra itself for every PR. We see breakage immediately and consume our own UX.
- **Action versioning is conventional.** `@v1` tracks the major version. `@v1.0.3` pins exactly. Standard git-tag semantics, no custom version policy.

### Negative

- **The Action lives in the same repo as the CLI.** Convenient for synchronization but means every CLI commit triggers Action publishing concerns (we have to be deliberate about what the `v1` tag points at).
- **PyPI installation cost is paid per run.** Even with `actions/setup-python`'s pip cache, cold-runner installs add ~10s to the workflow. A pre-built Docker image would amortize this, but at the cost of image hygiene.
- **The CLI's URL validator forces a re-clone.** See "Local-path TODO" above. Acceptable as a temporary cost.
- **`comment-on-pr: true` requires `pull-requests: write`.** Documented prominently, but is one more thing for users to get right in their workflow file. Users who only want the score (no comment) can drop the permission.
- **`anthropic-api-key` secret management is the user's problem.** We document the setup but cannot prevent accidental leakage. The Action does not log the key.

### Neutral

- The CLI and the Action stay strictly decoupled — the Action only consumes the CLI's stable `--format json` contract (`score_card.overall_grade`, `score_card.overall_score`, `findings[]`). No private interfaces. The CLI can ship breaking changes only at major version boundaries; the Action's `@v1` tag follows.

## Alternatives Considered

| Alternative | Verdict |
|-------------|---------|
| **No Action; document the workflow snippet for users to copy.** | Rejected. Every team would write the same boilerplate (install, run, parse, comment). The Action exists specifically to remove that work. |
| **Docker-based Action.** | Rejected. ~600MB pull cost per run, image registry maintenance burden, slower than warm-cache pip install. We'd revisit only if the install cost became a real bottleneck. |
| **JavaScript Action.** | Rejected. Spectra is Python; introducing Node tooling and `node_modules` for an Action wrapper is friction without benefit. The composite shape lets us call the CLI directly. |
| **Post a new comment per workflow run.** | Rejected. Spams the PR timeline. Reviewers want one place to see the latest result. The `<!-- SPECTRA -->` marker pattern is the standard solution. |
| **Use a third-party "PR comment" Action.** | Rejected. We control the find-or-update logic via `actions/github-script` (Anthropic-pinned, well-known). Adding another dependency for a 30-line script is overkill. |
| **Ship the Action in a separate repo.** | Rejected for v1. Same-repo Action keeps versioning aligned with the CLI it wraps. We can split later if the Action grows independently. |

## References

- Code: [`action.yml`](../../../action.yml) (the composite Action manifest)
- Code: [`.github/workflows/spectra.yml`](../../../.github/workflows/spectra.yml) (dogfood workflow)
- Docs: [`docs/github-action.md`](../../github-action.md) (consumer-facing setup guide)
- TODO: `# TODO(spectra-ai): teach the CLI to accept a local filesystem path.` in `action.yml` — tracked by the `feat/cli-local-path` work stream
- Related: [ADR-002](ADR-002-parallel-agent-pipeline.md) — the pipeline the Action invokes via `spectra analyze`

---

*Last updated: 2026-04-29.*
