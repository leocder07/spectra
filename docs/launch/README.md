# Launch materials

`hn-post.md` and `twitter-thread.md` were refreshed 2026-06-12 to v0.9.1 with the Direction-C positioning (signed point-in-time audit, complementary to inline reviewers) and real, verifiable leaderboard numbers. Both carry two **[MEASURE FIRST]** markers — a false-positive rejection rate and a monorepo file-count ceiling — that must get a real value (or be cut) before posting; do not ship a guessed number. `blog-post-skeleton.md` and `awesome-list-submissions.md` still need a v0.9.1 pass. Nothing here is auto-published; the maintainer posts manually.

The `leaderboard.md` IS kept current — it is the live link from the README, so check that one first.

## What's here

- `hn-post.md` — Hacker News submission (Show HN format) with title, body, first comment, and reply variants
- `twitter-thread.md` — 8-tweet X/Twitter thread with reply-tweet variants
- `blog-post-skeleton.md` — outline for a longer technical write-up (~1,100 words target)
- `awesome-list-submissions.md` — checklist of awesome-* repos to PR

## How to use these drafts

1. Resolve the two **[MEASURE FIRST]** markers in `hn-post.md` / `twitter-thread.md`: run the seeded-bug benchmark to get a real false-positive rejection rate, and confirm the largest monorepo actually tested. If you cannot get a real number, cut the claim — do not guess.
2. Give `blog-post-skeleton.md` and `awesome-list-submissions.md` the same v0.9.1 + Direction-C pass the HN/X drafts already got.
3. Take screenshots: terminal output of a run, the HTML report's radar chart, the executive-summary panel, a verified receipt.
4. Edit the voice so it sounds like you. The drafts use Vivek's voice (Clear, Confident, Sharp, Warm).
5. Time the launch — HN post Tuesday/Wednesday morning US-east, X thread same hour, awesome-list PRs the day after.

## Pre-flight checklist before posting

- [x] `v0.9.1` tagged and on PyPI (https://pypi.org/project/spectra-ai/)
- [ ] Cut and push a `v1` tag so `uses: leocder07/spectra@v1` resolves: `git tag v1 && git push origin v1`
- [ ] `pip install spectra-ai==0.9.1` works in a clean venv on Python 3.12 and 3.13
- [ ] `spectra analyze .` works end-to-end on a fresh clone with `ANTHROPIC_API_KEY` exported
- [ ] Cache subcommands work: `spectra cache stats`, `spectra cache clear`, `spectra cache prune`
- [ ] GitHub Action `leocder07/spectra@v1` resolves and runs in a test repo (needs the `v1` tag above)
- [x] Repo description and topics set (`code-review`, `static-analysis`, `claude`, `multi-agent`, `sarif`, …)
- [x] Third-party confidential findings removed from the public repo (`.gitignore` guard in place)
- [ ] Resolve both `[MEASURE FIRST]` markers in the drafts (false-positive rate, monorepo ceiling)
- [ ] CHANGELOG `[Unreleased]`/latest entry reads cleanly — no internal jargon, no bare PR numbers
- [x] License present, MIT
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
