---
type: decision
project: spectra
status: pending-review
impact: critical
created: 2026-02-14
tags: [type/decision, project/spectra, priority/p0, pinned]
---

# ADR-001: Pre-Sprint Verification Findings

## Context
Ran 5 parallel verifications using Uncle Bob, PM Head, Competitive Intelligence, YC Partner, and Brand/GTM skills against all Spectra documentation. Results below.

---

## ARCHITECTURE (Uncle Bob): Grade B+ (85/100)

### What's Strong
- Clean Architecture compliance: A (95)
- SOLID principles: A- (88)
- Pattern selection: A (92)
- Domain model: A (93)

### Critical Fixes Before Sprint
1. **Promise.race timeout is ambiguous** — spec says "30s per agent" but also "Promise.all". Use Promise.allSettled with individual 30s timeouts via AbortController per agent.
2. **Agent failure semantics undefined** — "2+ fail → abort" needs state machine: what's a "partial report"? Which dimensions survive?
3. **Token budget allocation unspecified** — MetaPrompter 5K, but how do remaining tokens split across 4 agents + Critique?
4. **Error recovery unclear** — SPEC-005 Zod validation fail: retry parse? Retry LLM call? Both?

### Architecture Verdict
Excellent design, but 4 ambiguities will cause 8-10 hours of thrashing if not clarified before sprint.

---

## PRODUCT STRATEGY (PM Head): NEEDS MAJOR FIXES

### Top 3 Changes Required

**1. Fix Pricing (Urgent)**
- Pro at $49/50 analyses = -2,194% gross margin at current COGS
- Recommended: Pro $99/20 analyses, Team $299/unlimited
- Current COGS makes ALL tiers unprofitable

**2. Change North Star Metric**
- WAA (Weekly Active Analyses) is vanity
- Better: "% of paying users who completed ≥2 analyses in past 30 days"
- 20% W1 retention is a CHURN signal, not success

**3. Build Platform Layer (Not Just CLI)**
- CLI = feature (gets copied by GitHub in 6 months)
- Platform = moat (trend data, remediation tracking, team workflows)
- Must move CI/CD + dashboard to Phase 1, not Phase 2

### Revenue Reality Check
- Year 1 projection ($1.2M ARR) is 4x overstated
- Realistic: $180K Y1, $1.8M Y2, $4-6M Y3
- Need 400 customers at realistic ARPU, not 100

---

## COMPETITIVE LANDSCAPE: CLAIMS OUTDATED

### Major Corrections (Feb 2026 verified)
| Claim | Reality |
|-------|---------|
| "CodeRabbit is PR-only" | **FALSE** — has agentic workflows, 9K+ orgs |
| "SonarQube can't add AI" | **FALSE** — shipped Remediation Agent, Foundation Agent, MCP Server |
| "Snyk can't expand" | **FALSE** — launched "Evo" multi-agent orchestration |
| "Semgrep can't add LLM" | **FALSE** — AI-powered detection in private beta |
| "No multi-agent competitor" | **FALSE** — multiple competitors moving to multi-agent |

### Missing Competitors
- GitHub Copilot Code Review (15M+ users, embedded advantage)
- JetBrains Qodana (enterprise entrenched)
- CodeScene (architecture visualization specialist)
- Amazon CodeGuru + Q (AWS ecosystem)
- Open source: PR-Agent, DeepSWE, LibVulnWatch

### Actual White Space (Still Valid)
No competitor combines ALL of: 6 dimensions + extended thinking critique + full-repo context + <2min + zero config. But window is 6-12 months max.

### Moat Assessment
| Layer | Realistic Strength |
|-------|-------------------|
| Prompt IP | Medium (3-6 months) |
| Golden Files | Medium (6-12 months) |
| Aggregate Data | NONE (pre-launch) |
| Brand | NONE (pre-launch) |
| Network Effects | NONE (not applicable) |
| Enterprise Lock-in | WEAK (CLI, low switching) |
| Process Power | Medium (extended thinking) |

---

## YC APPLICATION (YC Partner): NEED MORE INFO → Lean PASS

### Scores
| Category | Score |
|----------|-------|
| Founder | 8/10 |
| Market | 6/10 |
| Product | 7/10 |
| Traction | 3/10 |
| Timing | 4/10 |

### What Would Get to YES
1. 50-100 paying customers + $20K+ MRR
2. Defensible wedge use case (not generic "analyze code")
3. Clear answer for why GitHub/CodeRabbit/Snyk won't win
4. Path to 70%+ gross margin at $10M ARR

### Top Interview Questions to Prep For
1. "CodeRabbit has agentic workflows, SonarQube has AI agents — why Spectra?"
2. "Your COGS is $22.50/run. Walk me through getting to $1.50."
3. "20 repos tested — where's your retention data?"
4. "If GitHub ships this feature natively, what do you do?"

---

## BRAND & GTM (Brand Studio): Brand 7/10, GTM 5/10

### Brand Fixes
- Positioning is generic ("analyze code") — need use-case specific
- Recommended: "Know your code's actual health in 90 seconds"
- Voice framework solid but needs channel guidance + error voice

### GTM Fixes
- Growth loops: 1 of 3 is real (viral reports, IF reports are actionable)
- README badges won't work pre-launch (no trust signal)
- Benchmarks need 500+ repos (month 6+ feature)
- Missing: GitHub Action (retention driver), team dashboard, pricing model
- Launch sequencing wrong: README first, seed beta, THEN PH/HN

### Realistic 90-Day Metrics
| Metric | 30d | 60d | 90d |
|--------|-----|-----|-----|
| Downloads | 5K | 15K | 30K |
| Active installs | 1K | 3K | 5-7K |
| GitHub stars | 50-100 | 500+ | 1K+ |
| MRR | $0 | $500-1K | $2-5K |

---

## ACTION ITEMS: Pre-Sprint Must-Dos

### P0 (Before Sprint Starts)
1. Clarify Promise.allSettled + individual 30s timeout pattern in CLAUDE.md
2. Define agent failure state machine (partial report semantics)
3. Define token budget allocation formula
4. Update competitive claims (CodeRabbit, SonarQube, Snyk have ALL added AI)
5. Decide hackathon pricing (or skip pricing for hackathon MVP)

### P1 (During Sprint)
6. Build GitHub Action MVP (basic: comment on PR with top findings)
7. Write 2500-word README with demo screenshots
8. Prepare 2-3 OSS repo analysis blog posts for launch

### P2 (Post-Hackathon)
9. Rework pricing tiers ($99 Pro, $299 Team)
10. Build persistent report URLs (spectra.dev/report/{uuid})
11. Add team dashboard for Phase 2
12. Prepare sharp YC interview answers for competitive questions
