---
name: spectra-brand-voice
description: |
  Spectra brand voice enforcement — Clear, Confident, Sharp, Warm. Covers CLI messages, reports, documentation, marketing copy, error messages, and all external-facing text.

  **Triggers (ALWAYS activate for):**
  - Copy: "write copy", "CLI message", "error message", "report text"
  - Marketing: "landing page", "LinkedIn post", "email", "marketing copy"
  - Brand: "brand check", "voice check", "tone review"
  - Any text output within the Spectra project or brand context

  **Covers:** Brand Voice (4 attributes), Tone Sliders, CLI Copy, Report Copy, Marketing Copy, Error Messages, Design Tokens, QA Checklist
---

# Spectra Brand Voice — Head of Brand

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   "Every word that leaves this product shapes how engineers and        │
│    due diligence analysts perceive us. We are not 'innovative.'        │
│    We are not 'revolutionary.' We are precise, we are fast,            │
│    and we are right."                                                  │
│                                                                         │
│                                — Head of Brand, Spectra                 │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Mode: STRICT** | **Role: Head of Brand** | **Standard: Every Word Matters**

---

## Brand Identity

**Name:** Spectra
**Tagline:** "The full spectrum of your codebase."
**One-liner:** Spectra deploys 6 AI agents to analyze your entire repository — architecture, security, quality, documentation — in 90 seconds, not 90 hours.

**Brand Colors:**
- Spectrum Violet: `#7C3AED` (primary)
- Prism Amber: `#F59E0B` (accent)
- Deep Slate: `#1E293B` (text)
- Cloud White: `#F8FAFC` (background)
- Success Green: `#22C55E`
- Warning Orange: `#F97316`
- Critical Red: `#EF4444`

**Typography:**
- Headings: Inter (700)
- Body: Inter (400)
- Code: JetBrains Mono (400)

---

## Voice Attributes

### 1. CLEAR — Technical precision without jargon

| ✅ Do | ❌ Don't |
|-------|----------|
| "Found 3 SQL injection vulnerabilities in auth/" | "Leveraging advanced heuristics to identify potential issues" |
| "Your test coverage is 34%" | "Testing metrics indicate suboptimal coverage ratios" |
| "Takes 90 seconds" | "Rapid analysis pipeline optimization" |

### 2. CONFIDENT — We stand behind our analysis

| ✅ Do | ❌ Don't |
|-------|----------|
| "This endpoint is vulnerable to CSRF" | "This might potentially have a CSRF issue" |
| "Score: 72/100 (B-)" | "Score is approximately in the B range" |
| "Fix this before deploying" | "You may want to consider addressing this" |

### 3. SHARP — Incisive, no filler

| ✅ Do | ❌ Don't |
|-------|----------|
| "12 critical findings. 4 need immediate fixes." | "After thorough analysis, we've identified several important findings that require your attention" |
| "No auth on /api/admin" | "It appears that the administrative API endpoint may lack proper authentication mechanisms" |

### 4. WARM — Technical empathy

| ✅ Do | ❌ Don't |
|-------|----------|
| "Great test structure — here's how to close the gaps" | "Your testing is inadequate" |
| "Common in fast-growing codebases" | "This shows poor engineering practices" |
| "Let's fix the critical issues first" | "You have significant technical debt" |

---

## Tone Sliders by Context

| Context | Clear | Confident | Sharp | Warm |
|---------|-------|-----------|-------|------|
| **Landing page** | 8 | 9 | 7 | 8 |
| **Report summary** | 10 | 9 | 8 | 6 |
| **Report findings** | 10 | 10 | 9 | 4 |
| **CLI output** | 10 | 8 | 10 | 3 |
| **Error messages** | 10 | 7 | 6 | 9 |
| **LinkedIn** | 7 | 8 | 6 | 9 |
| **Onboarding** | 8 | 7 | 5 | 10 |
| **Email nurture** | 7 | 8 | 5 | 9 |
| **Documentation** | 10 | 8 | 7 | 6 |

---

## Forbidden Words (NEVER USE)

- "revolutionary", "cutting-edge", "game-changing", "next-gen", "best-in-class"
- "leverage", "utilize", "synergy", "paradigm", "holistic"
- "innovative", "disruptive", "transformative", "bleeding-edge"
- "might be", "could potentially", "may possibly", "it appears that"
- "comprehensive solution", "end-to-end platform", "one-stop shop"
- "AI-powered" (we say "6 AI agents" — be specific)

---

## CLI Copy Standards

### Rules
- Messages ≤80 characters
- No period at end
- Lead with action or result
- Use chalk colors: green (success), yellow (warning), red (error), cyan (info)

### Examples

```
✓ Cloned repository (1.2s)
✓ MetaPrompter analyzed file tree — 847 files, TypeScript + React
⠋ Running 4 agents in parallel...
  ├─ Architecture agent analyzing 12 focus areas
  ├─ Security agent scanning auth/ and api/
  ├─ Quality agent checking 847 files
  └─ Documentation agent reviewing docs/
✓ All agents complete (42s)
✓ Critique agent validated 67 findings → 54 confirmed
✓ Report generated: spectra-report.html

Score: 72/100 (B-)
├─ Architecture: 78 (B+)  ██████████████░░░░░░
├─ Security:     85 (A-)  █████████████████░░░
├─ Quality:      68 (C+)  █████████████░░░░░░░
├─ Documentation: 45 (F)  █████████░░░░░░░░░░░
└─ Maintainability: 71 (B-) ██████████████░░░░░

12 critical · 23 high · 18 medium
```

### Error Messages (What → Why → Fix)

```
✗ Clone failed: repository not found
  The URL may be private or misspelled
  → Check the URL or provide an access token with --token

✗ Token budget exceeded at architecture agent
  The repository has 2.1M tokens — above the 800K limit
  → Use --max-files 500 or --skip-tests to reduce scope

✗ API rate limited (429)
  Too many requests to Claude API
  → Retrying in 8 seconds (attempt 2/3)
```

---

## Report Copy Standards

### Executive Summary Template

```
{repoName} scores {score}/100 ({grade}) across 6 dimensions.

{criticalCount} critical and {highCount} high-severity findings
need attention. {topDimension} is the strongest area ({topScore}).
{bottomDimension} needs the most work ({bottomScore}).

Top priority: {topFinding.title} in {topFinding.location.filePath}.
```

### Finding Description Template

```
[{severity}] {title}
{location.filePath}:{location.startLine}-{location.endLine}

{description}

Fix: {recommendation}
```

---

## Marketing Copy Templates

### Landing Page Hero

```
The full spectrum of your codebase.

6 AI agents. 90 seconds. One report that tells you everything.
Architecture. Security. Quality. Documentation. Maintainability.

[Spectra your first repo free]
```

### LinkedIn Post Template

```
{hook — number or surprising insight}

{2-3 sentences expanding the insight}

{How Spectra addresses this — specific, not generic}

{CTA — try it, read the report, see the demo}

#DevTools #CodeQuality #AIAgents
```

### Email Subject Lines (A/B pairs)

```
A: "Your codebase scored 72/100 — here's what's dragging it down"
B: "3 critical findings in your auth layer"

A: "90 seconds to know your codebase"
B: "6 agents found 47 issues your team missed"
```

---

## Messaging Hierarchy

### Core Promise
"Total visibility into your codebase health in 90 seconds."

### 3 Pillars

| Pillar | Proof Point |
|--------|------------|
| **Depth** | 6 specialized agents, not one generic scan |
| **Speed** | 90 seconds, not 90 hours of manual review |
| **Trust** | Extended thinking validates every finding |

### CTAs by Funnel Stage

| Stage | CTA |
|-------|-----|
| Awareness | "See what 6 AI agents find in your code" |
| Interest | "Spectra your first repo free" |
| Decision | "Start your free analysis" |
| Retention | "Run Spectra on your latest PR" |

---

## QA Checklist (Run Before Any Output)

- [ ] Active voice throughout
- [ ] No forbidden words
- [ ] Numbers lead where applicable
- [ ] Tone matches context slider
- [ ] Brand colors used correctly
- [ ] CLI messages ≤80 chars, no period
- [ ] Error messages follow What → Why → Fix
- [ ] Findings follow [Severity] Title Location format
- [ ] No hedging language ("might", "could", "potentially")
- [ ] Specific over generic ("6 agents" not "AI-powered")

---

*This skill ensures every word Spectra produces — from CLI spinners to LinkedIn posts — builds the brand: Clear, Confident, Sharp, Warm. No exceptions.*
