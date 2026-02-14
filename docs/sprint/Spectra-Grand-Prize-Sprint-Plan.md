# Spectra — Grand Prize Sprint Plan

> **SITUATION:** No code written. ~48 hours remain. Target: $50K First Place.
> **Hackathon:** "Built with Opus 4.6" — Cerebral Valley × Anthropic
> **Deadline:** Monday Feb 16, 2026 — 3:00 PM ET SHARP. No extensions.
> **Rule:** All code from scratch. Open source. Max 2 team members. Video required.

---

## What Judges Want (In Priority Order)

1. **FUNCTIONAL PROTOTYPE** — judges favor working demos over docs
2. **TECHNICAL INNOVATION** — creative use of Claude's capabilities
3. **IMPLEMENTATION QUALITY** — clean code in public GitHub repo
4. **POTENTIAL IMPACT** — solves a real problem people care about
5. **VIDEO** — this is the #1 submission artifact judges review

**Translation for Spectra:** Ship a working CLI that analyzes a real repo with 6 agents in ~90 seconds, producing a beautiful HTML report. Then make a jaw-dropping 2-minute video showing it live.

---

## Winning Edge: What Makes Spectra Stand Out

Against 500 participants, here's why Spectra can win:

1. **Multi-agent orchestration** — most projects will be single-agent. 6 agents in parallel is architecturally ambitious.
2. **Extended thinking on CritiqueAgent** — shows deep understanding of Opus 4.6 capabilities (also targets "Keep Thinking Prize")
3. **1M context window utilization** — full repo analysis uses what's new about Opus 4.6 (targets "Most Creative Exploration")
4. **Beautiful output** — HTML report with Mermaid diagrams is visually impressive in video
5. **Clean Architecture** — public GitHub repo shows exceptional code quality
6. **Real utility** — analyze any public repo with one command. Judges can try it themselves.

---

## Budget Reality (CORRECTED)

**Opus 4.6 actual pricing: $5/M input, $25/M output** (NOT $15/$75 from old docs)

| Component | Tokens | Cost/Run |
|-----------|--------|----------|
| MetaPrompter (in/out) | 7K | $0.09 |
| 4 Specialists (in/out) | 500K | $4.75 |
| CritiqueAgent + Extended Thinking | 250K | $3.00 |
| **TOTAL COGS/RUN** | | **~$7.84** |

**$500 credits ÷ $7.84 = ~63 full runs.** Enough for 40 dev/test runs + 20 demo runs + buffer.

---

## The 48-Hour Plan

### HOUR 0-2: Setup & Foundation (Saturday morning)

**Goal:** GitHub repo initialized, project scaffolded, dependencies installed, CLAUDE.md committed.

- [ ] Create public GitHub repo: `spectra-cli` (or similar)
- [ ] `npm init`, install all deps (@anthropic-ai/sdk, commander, chalk, ora, simple-git, tiktoken, handlebars, zod, boxen, cli-table3)
- [ ] Copy `tsconfig.json`, `biome.json`, `vitest.config.ts` from workspace
- [ ] Commit CLAUDE.md (this is planning, not prior code)
- [ ] Create directory structure: `src/{entities,use-cases,adapters,infrastructure/agents}`, `templates/`, `tests/`
- [ ] First commit: "Initial project setup"

### HOUR 2-8: Layer 1 + Layer 2 (Saturday midday)

**Goal:** All types, schemas, interfaces, and orchestration logic written. No LLM calls yet.

**architect-1 agent** (fast mode ON):
- [ ] `src/entities/enums.ts` — all union types (Severity, Dimension, Grade, AgentRole, etc.)
- [ ] `src/entities/errors.ts` — SpectraError hierarchy (SPEC-001 to SPEC-009), Result<T, E>
- [ ] `src/entities/index.ts` — all domain types + Zod schemas + barrel exports
  - AnalysisRequest, FileTree, AgentOutput, Finding, ScoreCard, AnalysisReport
  - Zod schemas for each agent's output format

**pipeline-1 agent** (fast mode ON):
- [ ] `src/use-cases/interfaces.ts` — LLMGateway, GitPort, TokenPort, ReportPort, ProgressObserver
- [ ] `src/use-cases/analyze-repository.ts` — Facade orchestrating 6 stages
- [ ] `src/use-cases/orchestrate-agents.ts` — Promise.allSettled with individual 30s timeouts
- [ ] `src/use-cases/manage-token-budget.ts` — Token allocation logic

**Commit every 30-60 minutes.**

### HOUR 8-16: Layer 4 Core — LLM + Agents (Saturday evening → night)

**Goal:** Anthropic adapter working, all 6 agents producing real output.

**pipeline-1 agent** (fast mode ON):
- [ ] `src/infrastructure/anthropic-llm-adapter.ts` — implements LLMGateway
- [ ] `src/infrastructure/retry-decorator.ts` — exponential backoff
- [ ] `src/infrastructure/logging-decorator.ts` — structured logging
- [ ] `src/infrastructure/simple-git-adapter.ts` — clone + file tree extraction
- [ ] `src/infrastructure/tiktoken-adapter.ts` — token counting
- [ ] `src/infrastructure/agents/base-agent.ts` — Template Method pattern
- [ ] `src/infrastructure/agents/agent-factory.ts` — creates all agent configs
- [ ] `src/infrastructure/agents/meta-prompter.ts` — Sonnet 4.5, file tree → analysis plan
- [ ] `src/infrastructure/agents/architecture-agent.ts` — Opus 4.6
- [ ] `src/infrastructure/agents/security-agent.ts` — Opus 4.6
- [ ] `src/infrastructure/agents/quality-agent.ts` — Opus 4.6
- [ ] `src/infrastructure/agents/documentation-agent.ts` — Opus 4.6
- [ ] `src/infrastructure/agents/critique-agent.ts` — Opus 4.6, EXTENDED THINKING

**Critical milestone: Hour 12** — MetaPrompter + at least 1 specialist producing valid output on a test repo.

**Critical milestone: Hour 16** — All 4 specialists running in parallel + CritiqueAgent validating.

### HOUR 16-22: Layer 3 — CLI + Report (Sunday morning)

**Goal:** Working CLI command and beautiful HTML report.

**interface-1 agent**:
- [ ] `src/adapters/cli-controller.ts` — Commander.js with `spectra analyze <repo>` command
- [ ] `src/adapters/progress-reporter.ts` — Ora spinners + chalk colors
- [ ] `src/adapters/analysis-presenter.ts` — Terminal ScoreCard output
- [ ] `src/infrastructure/handlebars-report-adapter.ts` — HTML report generation
- [ ] `templates/report.hbs` — Beautiful HTML with Mermaid diagrams, findings, scores

**interface-1 agent**:
- [ ] `src/infrastructure/main.ts` — Composition root (DI wiring)
- [ ] Wire everything together

**Critical milestone: Hour 20** — `npx spectra analyze <repo>` works end-to-end on a real repo.

### HOUR 22-28: Integration + Polish (Sunday midday)

**Goal:** Reliable pipeline, beautiful output, handles edge cases.

- [ ] Test on 3-5 public repos (express-starter, react project, Python project)
- [ ] Fix any broken agent outputs / Zod validation failures
- [ ] Polish HTML report (colors, layout, Mermaid diagrams)
- [ ] Polish CLI output (spinners, progress messages, ScoreCard display)
- [ ] Handle error cases gracefully (timeout, API failure, bad repo URL)
- [ ] Add `--quick` flag (skip CritiqueAgent for faster analysis)

### HOUR 28-34: Testing + README + Demo Prep (Sunday evening)

**Goal:** Integration tests passing, README written, demo script ready.

**qa-1 agent**:
- [ ] Integration tests for pipeline stages
- [ ] Golden file for 1 test repo (express-starter)
- [ ] Architecture rule tests (dependency rule enforcement)

**interface-1 agent**:
- [ ] Write killer README.md:
  - Problem statement (40+ hours → 90 seconds)
  - Architecture diagram (6-agent pipeline)
  - Quick start (`npx spectra analyze <repo>`)
  - Demo screenshots / GIF
  - How it uses Opus 4.6 (1M context, extended thinking)
  - ScoreCard explanation
- [ ] Prepare demo script (what to show in video)

### HOUR 34-40: Video Recording (Sunday night → Monday morning)

**Goal:** 2-minute video that wins. This is THE most important artifact.

**Video Structure (2 minutes):**

[0:00-0:10] **Hook**
"I'm Vivek. I built a 6-agent system that analyzes your entire codebase in 90 seconds. Let me show you."

[0:10-0:40] **Live Demo**
- Terminal: `npx spectra analyze https://github.com/expressjs/express`
- Show 6 agents spinning up in parallel (beautiful Ora spinners with agent names)
- Show MetaPrompter planning, 4 specialists executing, CritiqueAgent thinking
- Show real-time token/cost counter

[0:40-1:00] **The Report**
- Open HTML report in browser
- Show ScoreCard (6 dimensions, grades, colors)
- Click into a finding: file, line number, code snippet, recommendation
- Show Mermaid architecture diagram

[1:00-1:20] **Technical Innovation**
- "6 agents running in parallel on Opus 4.6"
- "CritiqueAgent uses extended thinking to validate every finding"
- "1M context window lets us analyze the full repository, not just snippets"
- Show architecture: Clean Architecture, 4 layers, zero dependency violations

[1:20-1:40] **Why It Matters**
- "Code reviews take 40+ hours. Spectra does it in 90 seconds."
- "6 dimensions: architecture, security, quality, docs, maintainability, performance"
- "Less than 5% false positive rate thanks to extended thinking validation"

[1:40-2:00] **Close**
- "One command. 6 agents. 90 seconds. Your entire codebase."
- Show terminal: `npm install -g spectra && spectra analyze <your-repo>`

### HOUR 40-44: Final Polish + Submission Prep (Monday morning)

- [ ] Final bug fixes
- [ ] Clean up GitHub repo (remove debug code, ensure all commits are clean)
- [ ] Verify README renders properly on GitHub
- [ ] Test `npx` installation flow
- [ ] Verify video quality and timing
- [ ] Write project description for submission
- [ ] Final commit and push

### HOUR 44-46: Submit (Monday before 3 PM ET)

- [ ] Submit video + GitHub repo + project description
- [ ] Double-check everything is public / accessible
- [ ] **Submit 2 hours early** (submit by 1 PM ET for safety)

---

## Scope Tiers (Decision Framework)

### Tier 1: MUST SHIP (Hours 0-22)
- Working CLI: `spectra analyze <repo>`
- 6 agents producing real output
- HTML report with ScoreCard
- Extended thinking on CritiqueAgent
- Clean Architecture in codebase

### Tier 2: IF TIME (Hours 22-34)
- Mermaid architecture diagrams in report
- 3+ test repos working reliably
- `--quick` mode (skip critique)
- Polished error handling
- Integration tests

### Tier 3: DREAM (Hours 34-40)
- Terminal ScoreCard with box drawing
- Cost tracking per analysis
- GitHub Action template in README
- Multiple output formats (JSON, Markdown)

### CUT TRIGGERS
- **Hour 16:** If MetaPrompter + 2 specialists aren't working → drop to 3 agents
- **Hour 22:** If HTML report isn't rendering → use terminal-only output + Markdown
- **Hour 28:** If < 3 repos work reliably → use 1 repo for demo, note "tested on X repos" in README
- **Hour 34:** If video script isn't ready → record simpler demo, focus on the live analysis

---

## Key Winning Strategies

### 1. The Video Is Everything
Judges see video first. Make it sharp, fast, impressive. No filler. Show live analysis on a real repo. The moment agents spin up in parallel is your "wow moment."

### 2. Let Judges Try It Themselves
If `npx spectra analyze <their-repo>` works, that's 10x more impressive than any video. Make the install flow bulletproof.

### 3. Show Opus 4.6 Capabilities
- 1M context window → full repo analysis (not just file-by-file)
- Extended thinking → CritiqueAgent validates findings (reduces false positives)
- Multi-agent → 6 specialized agents working in parallel
- These are exactly what judges from Anthropic want to see being used

### 4. Clean GitHub Repo
Public repo = judges will read your code. Clean Architecture + TypeScript strict + meaningful commits = implementation quality score.

### 5. Target Multiple Prizes
Grand prize is primary, but Spectra also qualifies for:
- "Keep Thinking Prize" — CritiqueAgent uses extended thinking
- "Most Creative Opus 4.6 Exploration" — 6-agent system using 1M context

---

## Anti-Patterns to Avoid

- ❌ Spending more than 30 min on any single bug (skip it, come back later)
- ❌ Perfecting prompts (good enough > perfect — iterate if time allows)
- ❌ Writing extensive tests before core pipeline works
- ❌ Making the report perfect before all agents produce output
- ❌ Recording video before the demo is stable
- ❌ Submitting at the last minute (submit 2 hours early)
- ❌ Building features not visible in the demo video

---

## Agent Teams Configuration

```
# Fast mode ON for critical path
architect-1: fast mode, Layer 1 (entities + interfaces)
pipeline-1: fast mode, Layer 4 (agents + adapters + orchestration)
interface-1: normal mode, Layer 3 (CLI + report + main.ts)
qa-1: normal mode, tests + README

# Parallel execution
Hour 0-8: architect-1 + pipeline-1 in parallel
Hour 8-16: pipeline-1 (agents) solo (blocked on entities from architect-1)
Hour 16-22: interface-1 + qa-1 join (blocked on working agents)
Hour 22+: all 4 agents on polish/testing/README
```

---

*Clock is ticking. Every hour counts. Ship > Perfect.*
