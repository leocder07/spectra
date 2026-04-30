# Spectra GitHub Action

Run Spectra on every pull request. 8 AI agents analyze your codebase across
6 dimensions — architecture, security, quality, documentation,
maintainability, performance — and post a single, idempotent PR comment
with the grade and top findings.

> **Note on this repo's own CI:** Spectra does not dogfood itself on its own
> pull requests. Exposing `ANTHROPIC_API_KEY` to a `pull_request` workflow
> means anyone who opens a PR could trigger LLM calls and exhaust the
> maintainer's token quota. The recipes below are for **your** repo, where
> you control who can open PRs (or use `pull_request_target` patterns).

## Quickstart

Add this to `.github/workflows/spectra.yml` in your repo:

```yaml
name: Spectra
on: pull_request
permissions: { contents: read, pull-requests: write }
jobs:
  spectra:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: spectra-ai/spectra@v1
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

That's it. Open a PR — Spectra will comment with a grade within ~3 minutes.

## Required setup

1. Get an API key from [console.anthropic.com](https://console.anthropic.com).
2. In your repo, go to **Settings > Secrets and variables > Actions > New repository secret**.
3. Name: `ANTHROPIC_API_KEY`. Value: your key.

The Action does not store, log, or transmit the key anywhere except the
Anthropic API.

## Permissions

The workflow file MUST grant:

```yaml
permissions:
  contents: read         # to check out PR code
  pull-requests: write   # to post/update the comment
```

If you set `comment-on-pr: "false"` you can drop `pull-requests: write`.

## Inputs

| Name                | Required | Default  | Description                                                                                                      |
| ------------------- | -------- | -------- | ---------------------------------------------------------------------------------------------------------------- |
| `anthropic-api-key` | yes      | —        | Your Anthropic API key. Pass via `${{ secrets.ANTHROPIC_API_KEY }}`.                                             |
| `path`              | no       | `.`      | Path or https URL to analyze. `.` analyzes the checked-out workspace directly (no re-clone).                     |
| `format`            | no       | `json`   | `json` (recommended for CI) or `html`.                                                                           |
| `quick-mode`        | no       | `false`  | When `true`, skip the CritiqueAgent stage. Roughly 3x faster, slightly less accurate.                            |
| `comment-on-pr`     | no       | `true`   | Post or update a PR comment with findings. No-op outside `pull_request` events.                                  |
| `python-version`    | no       | `3.12`   | Python version installed on the runner.                                                                          |
| `spectra-version`   | no       | (latest) | Pin a specific `spectra-ai` version (e.g. `0.1.0`).                                                              |
| `fail-on`           | no       | `critical` | Severity gate. Exit 1 when any finding sits at or above this level. One of `critical`, `high`, `medium`, `low`, `none`. |

## Outputs

| Name            | Description                                                       |
| --------------- | ----------------------------------------------------------------- |
| `grade`         | Letter grade — one of `A+` through `F`.                           |
| `score`         | Numeric score from 0 to 100.                                      |
| `findings-json` | Path on the runner to the raw JSON report (use as artifact path). |

## Comment behavior

The PR comment is **idempotent**. Spectra finds an existing comment by the
hidden marker `<!-- SPECTRA -->` and updates it in place rather than
spamming the timeline. Re-running the workflow on a new commit overwrites
the previous result.

<!-- TODO: screenshot of PR comment -->

## Recipes

### Quick mode for draft PRs

```yaml
- uses: spectra-ai/spectra@v1
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
    quick-mode: ${{ github.event.pull_request.draft }}
```

### Block PRs below a grade threshold

```yaml
- uses: spectra-ai/spectra@v1
  id: spectra
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}

- name: Enforce minimum score
  run: |
    SCORE=${{ steps.spectra.outputs.score }}
    awk "BEGIN { exit !(${SCORE} >= 75) }" \
      || { echo "::error::Score ${SCORE} is below 75"; exit 1; }
```

### Upload the JSON report as an artifact

```yaml
- uses: spectra-ai/spectra@v1
  id: spectra
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}

- uses: actions/upload-artifact@v4
  with:
    name: spectra-report
    path: ${{ steps.spectra.outputs.findings-json }}
```

## Cost

A typical analysis uses around 80–150K Anthropic tokens (Opus 4.7 +
Sonnet 4.5). Budget roughly $1–$3 per PR. Use `quick-mode: "true"` to
roughly halve token usage on draft PRs.

## Troubleshooting

- **Comment not posted** — check that the workflow grants
  `pull-requests: write` and that the secret name is exactly
  `ANTHROPIC_API_KEY`.
- **Timeout** — the default runner timeout is 15 minutes. Public repos
  with very large codebases may need `quick-mode: "true"`.

## Source

- Workflow: [`.github/workflows/spectra.yml`](../.github/workflows/spectra.yml)
- Action manifest: [`action.yml`](../action.yml)
- Example consumer: [`.github/workflows/example-usage.yml`](../.github/workflows/example-usage.yml)
