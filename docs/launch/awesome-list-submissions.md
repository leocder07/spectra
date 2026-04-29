# Awesome-list submissions — Spectra v0.3.0

When launching, open PRs to these in order. The first three are the highest-traffic; the last two are smaller but well-curated and tend to convert better.

- [ ] [awesome-claude-code](https://github.com/anthropics/awesome-claude-code) — under "Tools / CI"
- [ ] [awesome-python](https://github.com/vinta/awesome-python) — under "Code Analysis"
- [ ] [awesome-static-analysis](https://github.com/analysis-tools-dev/static-analysis) — Python section
- [ ] [awesome-code-review](https://github.com/joho/awesome-code-review) — Tools section
- [ ] [awesome-github-actions](https://github.com/sdras/awesome-actions) — Code Quality section

## Standard submission line (one sentence each — keep verbatim across lists)

> [Spectra](https://github.com/leocder07/spectra) — 8 AI agents analyze any repository in parallel across architecture, security, quality, documentation, maintainability, and performance. Drops into PR CI via the `spectra-ai/spectra@v1` GitHub Action. Python CLI on PyPI.

## Per-list adjustments

- **awesome-claude-code** — emphasize the multi-agent pattern and Opus 4.7. Lead with: "8-agent orchestration on Claude Opus 4.7 with adaptive thinking on the critique pass."
- **awesome-python** — pure tool description. The "Python CLI on PyPI" tail is the part that matters there.
- **awesome-static-analysis** — note that this is *semantic* analysis to differentiate from rule-based entries. Add: "Complements rule-based analyzers; finds issues you didn't think to write a rule for."
- **awesome-code-review** — emphasize the PR-CI workflow and the `min-score` quality gate. They care about workflow integration.
- **awesome-github-actions** — lead with the YAML snippet, not the description.

## Pre-PR checklist for each list

- [ ] Read the list's CONTRIBUTING.md (or the equivalent contribution guide in README) before opening the PR
- [ ] Confirm the requested category exists and is the right fit — wrong category = closed PR
- [ ] Match the list's existing entry format exactly (some require alphabetical, some thematic, some date-ordered)
- [ ] Confirm the project meets the list's age/star/license bar (some require N stars or M months on GitHub)
- [ ] One PR per list; don't batch
- [ ] Title: `Add Spectra — 8-agent code analysis tool` (or the list's preferred convention)
- [ ] Body: one paragraph, link to README, link to PyPI, mention MIT license

## Other surfaces worth a single-line submission (lower priority, optional)

- [ ] [awesome-ai-tools](https://github.com/mahseema/awesome-ai-tools) — Code Analysis subsection
- [ ] [awesome-developer-experience](https://github.com/jondot/awesome-devenv) — if it has a CI section
- [ ] Hacker News `/show` (separate from the main HN post — drives a different audience)
- [ ] Reddit r/Python — only if the HN post lands well; otherwise skip
- [ ] Reddit r/programming — same constraint
- [ ] Lobste.rs — needs an invite; only if you have one and the post quality clears the bar

## Timing

- Open the awesome-list PRs **the day after** the HN/Twitter launch, not before. List maintainers Google the project before merging — they want to see it has traction.
- Stagger the submissions one per day — opening five PRs in an hour reads as spam.
- If the HN post flops, still open the awesome-list PRs. The traffic from those is small but durable.
