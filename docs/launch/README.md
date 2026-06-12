# Launch materials

Drafts pegged to the v0.3.0 cycle (the cache + GitHub Action launch); the four content files (`hn-post.md`, `twitter-thread.md`, `blog-post-skeleton.md`, `awesome-list-submissions.md`) are kept here as templates and have not been refreshed for the v0.4.0 / v0.5.0 / v0.6.0 release waves. Nothing in this directory is auto-published; the maintainer manually posts (or doesn't) after refreshing voice + numbers for the actual release being announced.

The `leaderboard.md` IS kept current — it is the live link from the README, so check that one first.

## What's here

- `hn-post.md` — Hacker News submission (Show HN format) with title, body, first comment, and reply variants
- `twitter-thread.md` — 8-tweet X/Twitter thread with reply-tweet variants
- `blog-post-skeleton.md` — outline for a longer technical write-up (~1,100 words target)
- `awesome-list-submissions.md` — checklist of awesome-* repos to PR

## How to use these drafts

1. Run Spectra on 1-2 real, well-known repos (suggested: `pallets/flask`, `expressjs/express`, `tiangolo/fastapi`).
2. Search-and-replace every `[PLACEHOLDER: ...]` marker in the four content files with real numbers, real findings, real permalinks.
3. Take screenshots: terminal output during a warm cache run, the HTML report's radar chart, the executive summary panel.
4. Edit the voice so it sounds like you, not like the draft. The drafts use Vivek's voice (Clear, Confident, Sharp, Warm) — adjust to your own.
5. Time the launch — HN post Tuesday/Wednesday morning US-east, Twitter thread same hour, awesome-list PRs the day after.

## Pre-flight checklist before posting

- [ ] Tag v0.3.0 pushed to GitHub: `git tag v0.3.0 && git push origin v0.3.0`
- [ ] PyPI publish workflow succeeded; package visible on https://pypi.org/project/spectra-ai/
- [ ] `pip install spectra-ai==0.3.0` works in a clean venv on Python 3.12 and 3.13
- [ ] `spectra analyze .` works end-to-end on a fresh clone with `ANTHROPIC_API_KEY` exported
- [ ] Cache subcommands work: `spectra cache stats`, `spectra cache clear`, `spectra cache prune`
- [ ] GitHub Action `leocder07/spectra@v1` resolves and runs in a test repo
- [ ] Run Spectra on 1-2 real repos and update PLACEHOLDER markers in the drafts with actual outputs
- [ ] Update the GitHub repo description and topics (`code-review`, `static-analysis`, `claude`, `anthropic`, `multi-agent`)
- [ ] Ensure the README hero GIF / screenshot has been filled (no placeholder image at top)
- [ ] CHANGELOG entry for 0.3.0 reads cleanly — no internal jargon, no PR numbers without context
- [ ] License file present, MIT, with the right copyright holder
- [ ] `spectra-self-report.html` is fresh (regenerated against current codebase) so the README link works
- [ ] All forbidden brand-voice words removed from final post text (revolutionary, cutting-edge, game-changing, leverage, innovative, utilize, might be, could potentially, comprehensive solution, AI-powered)

## Ordering on launch day

Suggested sequence (US-east timing):

1. **08:00** — HN submission goes live, first comment posted within 5 minutes
2. **08:15** — Twitter thread posts
3. **08:30** — Update the personal GitHub profile README with a "shipping" pin if you have one
4. **+1 day** — Blog post (assuming HN post is still alive, otherwise wait)
5. **+1 day** — First awesome-list PR (one per day for the rest of the week)

## Voice rules (for any final edits)

- Voice: Clear, Confident, Sharp, Warm
- Forbidden: revolutionary, cutting-edge, game-changing, leverage, innovative, utilize, might be, could potentially, comprehensive solution, AI-powered
- Say "8 AI agents" instead of "AI-powered"
- Say "uses" instead of "utilize"
- Say "is" or "does" instead of "might be" / "could potentially"
- No exclamation marks in body copy. One in a tweet at most.
