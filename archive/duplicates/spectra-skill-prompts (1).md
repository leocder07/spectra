# Spectra — 4 Skill Creation Prompts

> **Usage:** Copy-paste each prompt into a fresh Claude session (with skill-creator loaded, or just Claude Code). Each prompt is self-contained and produces a complete skill folder with SKILL.md + reference files.

---

## SKILL 1: `ai-agent-patterns` (Priority: HIGH)

```
Create a comprehensive skill called "ai-agent-patterns" at /mnt/skills/user/ai-agent-patterns/

## What this skill does
This is a library of battle-tested LLM agent orchestration patterns for building multi-agent AI systems. It covers everything from single-agent prompt engineering to complex multi-agent pipelines with critique loops, meta-prompting, structured outputs, error recovery, and evaluation.

Think of it as the "Gang of Four Design Patterns" book — but for AI agents. Any time someone is building AI agents, multi-agent pipelines, or LLM-powered systems, this skill should activate.

## When to trigger (be aggressive)
- ANY mention of: "agent", "multi-agent", "LLM pipeline", "AI pipeline", "prompt engineering", "meta-prompting", "chain of thought", "structured output", "tool use", "function calling", "agent orchestration", "critique loop", "self-reflection", "RAG", "retrieval augmented"
- Building any system that calls LLM APIs (Anthropic, OpenAI, etc.)
- Designing prompt templates or agent architectures
- Evaluating or testing AI agent quality
- Debugging LLM outputs (hallucinations, format issues, quality)
- ANY AI/LLM coding task where patterns would help

## Structure
Create:
- SKILL.md (main file, <500 lines) — pattern catalog with when-to-use guidance
- references/meta-prompting.md — deep dive on meta-prompting pattern
- references/multi-agent-critique.md — deep dive on multi-agent + critique loops
- references/structured-outputs.md — structured output patterns (JSON, Zod, tool_use)
- references/error-recovery.md — retry, fallback, degradation patterns for LLM calls
- references/eval-harness.md — testing and evaluating agent quality
- references/token-optimization.md — context window management, budgeting, truncation

## Pattern Catalog (include ALL of these)

### Architecture Patterns
1. **Single Agent** — One LLM call with a well-crafted prompt. When: simple tasks, <1 dimension of analysis. Template: system prompt + user prompt + output schema.
2. **Pipeline (Sequential)** — Multiple agents in sequence, output of one feeds next. When: tasks that build on each other (plan → execute → review). Anti-pattern: sequential when agents are independent (use parallel).
3. **Fan-Out / Fan-In (Parallel)** — Multiple agents run simultaneously on same input, results merged. When: multi-dimension analysis (security + quality + architecture). ALWAYS use Promise.all/asyncio.gather. Include: merge strategy (dedup by key, cross-reference, priority scoring).
4. **Meta-Prompting** — An agent that generates prompts for other agents. When: inputs vary significantly (different repos, documents, domains). Key insight: the meta-prompter sees ONLY metadata (file tree, schema, summary) — NEVER the full content. This keeps it fast and focused on planning.
5. **Critique Loop (Self-Reflection)** — A dedicated agent validates other agents' outputs. When: accuracy matters (DD reports, security findings, medical). Use extended thinking for the critique agent. Pattern: generate → critique → filter/refine → output.
6. **Hierarchical (Manager → Workers)** — A coordinator agent delegates to specialist workers. When: complex tasks with clear sub-domains. The manager handles routing, workers handle execution.
7. **Debate Pattern** — Two agents argue opposing positions, a judge resolves. When: nuanced analysis where bias is a concern. Expensive but high quality.
8. **Iterative Refinement** — Agent produces output, gets feedback, produces better output. When: creative tasks (writing, code generation). Cap iterations (usually 2-3 max).

### Prompt Engineering Patterns
9. **System-User-Assistant Template** — Standard 3-role prompt structure. Include: persona definition, task description, output format, constraints, examples.
10. **Few-Shot with Exemplars** — Include 2-3 input/output examples in prompt. When: format is complex or non-obvious. Anti-pattern: too many examples (wastes tokens).
11. **Chain of Thought (CoT)** — "Think step by step" or structured reasoning. When: complex reasoning, math, multi-step logic. Variants: zero-shot CoT, few-shot CoT, structured CoT with XML tags.
12. **ReAct (Reason + Act)** — Interleave thinking and tool use. When: agents need to search, compute, or interact with external systems.
13. **Constitutional AI Pattern** — Define principles/rules the agent must follow. When: safety-critical outputs, brand voice enforcement. Pattern: principles → generate → check against principles → revise.

### Output Patterns
14. **Structured JSON Output** — Force JSON response with schema. Best practice: use tool_use/function_calling for guaranteed schema compliance. Fallback: prompt for JSON + Zod/JSON Schema validation + retry on failure.
15. **Streaming with Progress** — Stream responses for long operations. Pattern: emit status events during processing.
16. **Partial Results** — Return whatever completed even if some agents fail. When: resilience matters more than completeness. Include: clear "incomplete" markers.

### Error & Resilience Patterns
17. **Retry with Backoff** — Exponential backoff (1s, 2s, 4s) with jitter for rate limits (429). Max 3 retries. Different retry strategies for different error types.
18. **Fallback Chain** — Primary model → secondary model → cached/static response. When: availability matters. Example: Opus → Sonnet → Haiku → cached response.
19. **Circuit Breaker** — After N consecutive failures, stop calling the API for a cooldown period. Prevents cascade failures and wasted money.
20. **Graceful Degradation** — If critique agent fails → return unvalidated results with warning. If 1 of 4 parallel agents fails → return partial report. Always prefer partial results over total failure.
21. **Token Budget Management** — Allocate token budgets per agent. Monitor usage. Truncate context intelligently (keep structure, cut content). Never exceed budget — fail gracefully instead.

### Evaluation Patterns
22. **Golden File Testing** — Snapshot expected outputs, compare future runs. For LLM: normalize outputs (remove timestamps, UUIDs), compare semantic similarity, not exact match.
23. **A/B Prompt Testing** — Run same inputs through two prompt variants, compare quality. Automate with judge LLM or human review.
24. **Confidence Scoring** — Each finding gets a confidence score (0-1). Filter outputs below threshold. Calibrate threshold with labeled data.
25. **Red Team Testing** — Adversarial inputs to test robustness: prompt injection, edge cases, malicious content, empty inputs, massive inputs.

## Key Principles (enforce these throughout)
- ALWAYS validate LLM outputs with schemas (Zod, JSON Schema, Pydantic)
- NEVER trust LLM output without validation — treat it like user input
- ALWAYS set timeouts on LLM calls — they can hang
- ALWAYS count tokens BEFORE sending — don't discover budget issues mid-call
- PREFER parallel execution (Promise.all) over sequential when agents are independent
- META-PROMPTER gets metadata ONLY (file tree, schema, summary) — never full content
- CRITIQUE AGENT uses extended thinking — it needs to reason deeply about accuracy
- LOG everything — every prompt, every response, every token count, every duration
- GOLDEN FILES are your regression safety net — update them deliberately, never silently

## Tone
Write like a senior AI engineer at Anthropic or DeepMind explaining patterns to a strong mid-level engineer. Technical, precise, no fluff. Include TypeScript/Python code snippets for every pattern. Use the Spectra codebase (6-agent analysis pipeline) as the running example throughout.

## Anti-Patterns Section
Include a section on common anti-patterns:
- "The God Agent" — one massive prompt trying to do everything
- "Sequential when Parallel" — running independent agents one-by-one
- "Prompt Stuffing" — cramming everything into context when meta-prompting would be cleaner
- "No Validation" — trusting LLM JSON output without schema validation
- "Retry Everything" — retrying on hallucination errors (retrying won't help, need to re-prompt)
- "Token Ignorance" — not counting tokens before calls, leading to truncation or failures
```

---

## SKILL 2: `hackathon-sprint` (Priority: HIGH)

```
Create a comprehensive skill called "hackathon-sprint" at /mnt/skills/user/hackathon-sprint/

## What this skill does
This is a hackathon execution skill — time-boxed decision making, scope management, demo preparation, and judge psychology. It helps you WIN hackathons by making the right build/cut/polish decisions under extreme time pressure (24-48 hours). It knows how hackathon judges think, what makes demos memorable, and how to manage scope when everything is on fire.

Think of it as having a YC-trained hackathon coach sitting next to you for 48 hours.

## When to trigger
- ANY mention of: "hackathon", "48 hours", "24 hours", "build sprint", "demo day", "hack day", "ship weekend", "buildathon", "code jam"
- Time-boxed build projects with a demo/presentation deadline
- Scope management under extreme time pressure
- Demo preparation, pitch scripting, presentation planning
- "What should I cut?", "Am I going to make it?", "What do judges care about?"
- Competition submissions (Claude Hackathon, ETHGlobal, MLH, devpost, etc.)

## Structure
Create:
- SKILL.md (main, <500 lines) — core sprint framework + decision trees
- references/scope-playbook.md — scope cut decision trees, MVP definitions
- references/demo-scripts.md — demo script templates, presentation frameworks
- references/judge-psychology.md — how judges think, scoring rubrics, what wins
- references/sprint-templates.md — hour-by-hour sprint plans for 24h/48h/weekend

## Core Framework: The Hackathon Sprint Operating System

### Phase 0: Pre-Sprint (1-2 hours before start)
- Define the ONE SENTENCE pitch: "[Product] does [what] for [who] in [how long]"
- List 3 "wow moments" the demo MUST show
- Define the Minimum Viable Demo (MVD) — the smallest thing that proves the concept
- Set 3 scope tiers: Tier 1 (must ship), Tier 2 (if time), Tier 3 (dream)
- Choose tech stack based on SPEED, not perfection (use what you know, not what's trendy)

### Phase 1: Foundation Sprint (25% of total time)
- Build the core data model / types / interfaces FIRST
- Get ONE end-to-end path working (ugly is fine, broken is not)
- Milestone: "I can show one thing working" — if not hit by 25%, CUT SCOPE
- Rule: NO polishing, NO edge cases, NO error handling yet

### Phase 2: Feature Sprint (40% of total time)
- Build features in priority order (Tier 1 only until all complete)
- Every 3 hours: "Can I demo what I have RIGHT NOW?" If no → something is wrong
- Rule: If a feature takes 2x estimated time, CUT IT. Move to Tier 2.
- Integration tests only — no unit tests during hackathon (controversial but correct)
- Checkpoint at 50% time: Scope review. Be honest. Cut ruthlessly.

### Phase 3: Demo Sprint (25% of total time)
- STOP building features at 75% time mark
- Polish the demo path ONLY — make it bulletproof
- Write the demo script (see demo-scripts reference)
- Add visual polish to demo-visible surfaces only (UI, CLI output, report)
- Prepare fallback plan: pre-recorded demo if live demo fails
- Rule: Last 10% of time = ONLY bug fixes and demo practice

### Phase 4: Submission (10% of total time)
- Record demo video (even if presenting live — you need backup)
- Write README with: one-liner, screenshot/gif, how to run, architecture overview
- Prepare 3 "judge questions" you expect and rehearse answers
- Submit 30 minutes early (things ALWAYS go wrong)

### Decision Trees (CRITICAL)

**"Should I build this feature?"**
1. Does it appear in the demo? → If NO, don't build it
2. Can I build it in <2 hours? → If NO, simplify or cut
3. Does it make the demo 2x more impressive? → If NO, it's Tier 2
4. Am I past 75% time? → If YES, only bug fixes

**"Should I fix this bug?"**
1. Does it break the demo path? → If YES, fix NOW (Priority 0)
2. Does it affect a non-demo feature? → If YES, skip
3. Is it a visual glitch? → Fix only if demo-visible
4. Is it an edge case? → Skip — handle with "we know about this, it's on the roadmap"

**"Am I going to make it?"**
Calculate at any point:
- Remaining features × avg time per feature = estimated time needed
- If estimated > remaining time × 0.7 → CUT SCOPE NOW (0.7 buffer for unknowns)
- If estimated > remaining time × 1.0 → EMERGENCY: cut to absolute minimum demo

### Scope Fallback Ladder (save these for emergencies)
Level 0: Full vision — all agents, all features, polished UI
Level 1: Drop least impressive feature — everything else works
Level 2: Reduce to core pipeline only — no extras, clean demo
Level 3: Hardcode parts of the pipeline — demo still looks real
Level 4: Pre-recorded demo with live Q&A — you built it, just can't demo live reliably
Level 5: Slide deck + code walkthrough — explain what you built, show code

### Judge Psychology
Include detailed section on:
- What judges ACTUALLY score (innovation > polish > completeness)
- The "3-second rule": judges decide in 3 seconds if they're interested
- Demo sins: apologizing for bugs, showing terminal for 5 minutes, no narrative arc
- Demo virtues: live analysis on THEIR data, before/after comparison, speed demonstration
- The "magic moment": identify the ONE thing that makes judges say "whoa"
- Scoring rubrics from major hackathons (Claude Hackathon, ETHGlobal, MLH, devpost)

### Sprint Anti-Patterns
- "Premature Optimization" — polishing before the core works
- "Architecture Astronaut" — perfect architecture in a 48hr sprint
- "Feature Creep" — adding Tier 2/3 features before Tier 1 is bulletproof
- "Solo Hero" — not sleeping, not eating, coding for 20 hours straight (you WILL make mistakes)
- "Demo Amnesia" — building for 46 hours, preparing demo for 2 hours
- "The Invisible Feature" — building something impressive that you can't SHOW

## Tone
Write like a veteran hackathon mentor who's coached 50+ winning teams. Urgent but calm. Direct. Every sentence should be actionable. Use imperative mood. Think YC office hours energy — "that's nice, but what ships in 48 hours?"

Include specific examples from the Spectra hackathon build:
- Spectra's Tier 1: CLI + 6 agents + HTML report + ScoreCard
- Spectra's scope cuts: drop CritiqueAgent if behind, static prompts if meta-prompting too slow
- Spectra's magic moment: analyze judges' OWN repo live, show findings in 90 seconds
```

---

## SKILL 3: `typescript-cli-toolkit` (Priority: MEDIUM)

```
Create a comprehensive skill called "typescript-cli-toolkit" at /mnt/skills/user/typescript-cli-toolkit/

## What this skill does
Best practices for building professional TypeScript CLI tools — Commander.js patterns, chalk/ora UI components, npm packaging, zero-config detection, graceful error handling, config file management, progress indicators, and distribution via npm. This is the definitive reference for building CLI tools that feel as polished as Vite, Turborepo, or Next.js CLI.

NOTE: The original LUMEN docs recommended "python-cli-toolkit" (Typer + Rich), but Spectra has moved to TypeScript. This skill covers the TypeScript equivalent ecosystem.

## When to trigger
- ANY mention of: "CLI tool", "command line", "terminal app", "npm package", "CLI interface"
- Building tools with: Commander.js, Yargs, Oclif, Inquirer, chalk, ora, listr2
- Any TypeScript project that needs a CLI entry point
- "How do I parse arguments?", "How do I show progress?", "How do I publish to npm?"
- Building developer tools, code generators, analysis tools, dev scripts
- ANY project that runs from the terminal

## Structure
Create:
- SKILL.md (main, <500 lines) — quick reference for common CLI patterns
- references/commander-patterns.md — Commander.js command patterns, options, subcommands
- references/ui-components.md — chalk, ora, listr2, cli-table3, boxen, ink patterns
- references/npm-packaging.md — tsconfig, package.json, bin field, publishing checklist
- references/zero-config.md — auto-detection patterns, smart defaults, .rc file conventions
- references/error-handling.md — graceful errors, exit codes, help text, debug mode

## Core Patterns

### 1. Project Skeleton
Standard structure for a TypeScript CLI tool:
```
my-cli/
├── src/
│   ├── index.ts          # Entry point: #!/usr/bin/env node
│   ├── commands/          # One file per command
│   │   ├── analyze.ts
│   │   └── init.ts
│   ├── lib/               # Business logic (no CLI deps)
│   ├── ui/                # Terminal UI (chalk, ora, tables)
│   │   ├── progress.ts
│   │   ├── output.ts
│   │   └── errors.ts
│   └── utils/
│       ├── config.ts      # Config file loading (.spectra.yml)
│       └── detect.ts      # Auto-detection (language, framework)
├── package.json           # bin field, engines, publishConfig
├── tsconfig.json          # target: ES2022, module: NodeNext
└── biome.json
```

### 2. Commander.js Patterns
- Basic command with options and arguments
- Subcommands (my-cli analyze, my-cli init)
- Global options (--verbose, --quiet, --json, --no-color)
- Version flag from package.json
- Help text customization
- Action handlers with proper async/await error boundaries

### 3. Terminal UI Components
- chalk for colors (with NO_COLOR / FORCE_COLOR support)
- ora for spinners (start, succeed, fail, warn states)
- listr2 for multi-step task lists with concurrent tasks
- cli-table3 for formatted tables
- boxen for bordered boxes (scores, summaries)
- Progress bars for long operations
- Rule: detect TTY — if not interactive (piped), disable all UI chrome

### 4. Zero-Config Detection
- Auto-detect language from file extensions
- Auto-detect framework from package.json / requirements.txt / go.mod
- Auto-detect git remote from .git/config
- Cascading config: CLI flags > env vars > .spectra.yml > smart defaults
- Config file search: current dir → parent dirs → home dir

### 5. Error Handling
- NEVER show raw stack traces to users (catch at top level)
- Error format: "Error: [what happened]\n\n  [why it happened]\n\n  [what to do about it]"
- Exit codes: 0 (success), 1 (general error), 2 (usage error), 130 (Ctrl+C)
- Debug mode: --debug flag shows full stack traces, verbose logging
- Graceful Ctrl+C handling: cleanup temp files, show partial results

### 6. npm Publishing
- package.json: bin field, engines (node >= 18), files array
- tsconfig: declaration, outDir, sourceMap
- Build script: tsc + chmod +x dist/index.js
- npx support: package name should work with npx my-cli
- Publish checklist: README, LICENSE, .npmignore, version bump, npm publish

### 7. Output Formats
- Human mode (default): colors, spinners, tables, boxes
- JSON mode (--json flag): structured JSON to stdout, no UI chrome
- Quiet mode (--quiet): only errors to stderr
- Verbose mode (--verbose): debug information
- Rule: machine-readable output (JSON) goes to stdout. Human messages go to stderr.

## Spectra-Specific Examples
Use the Spectra CLI as the running example throughout:
- `spectra analyze <repo-url> [--mode deep|quick] [--output path] [--json]`
- Progress: ora spinners per pipeline stage, listr2 for parallel agents
- Output: boxen for ScoreCard, cli-table3 for findings summary
- Config: .spectra.yml for custom settings, auto-detect everything else

## Tone
Write like the Vercel/Sindre Sorhus school of CLI design — minimal, beautiful, zero-config defaults with power-user escape hatches. Every example should be copy-pasteable TypeScript. Opinionated about quality.
```

---

## SKILL 4: `prompt-engineering-lab` (Priority: MEDIUM)

```
Create a comprehensive skill called "prompt-engineering-lab" at /mnt/skills/user/prompt-engineering-lab/

## What this skill does
This is a systematic prompt engineering skill — template design, evaluation harnesses, A/B testing, meta-prompting patterns, structured output schemas, and chain-of-thought patterns. It turns prompt engineering from "vibe-based" into a rigorous, measurable discipline. Every prompt should have a template, a test, and a metric.

Think of it as the "Prompt Engineering as Software Engineering" handbook.

## When to trigger
- ANY mention of: "prompt", "system prompt", "prompt template", "prompt engineering", "improve this prompt", "prompt isn't working"
- Writing or improving prompts for Claude, GPT, or any LLM
- "The model keeps hallucinating", "The output format is wrong", "It's not following instructions"
- Designing structured output schemas (JSON, XML, function calling)
- Building evaluation harnesses for prompt quality
- Meta-prompting (prompts that generate prompts)
- A/B testing prompts, comparing prompt variants
- ANY task where prompt quality directly affects system quality

## Structure
Create:
- SKILL.md (main, <500 lines) — prompt engineering principles + quick reference
- references/prompt-templates.md — library of proven templates by task type
- references/meta-prompting.md — patterns for prompts that generate prompts
- references/structured-outputs.md — JSON schemas, XML tags, tool_use patterns
- references/eval-harness.md — how to test and measure prompt quality
- references/chain-of-thought.md — reasoning patterns (CoT, ReAct, Tree of Thought)
- references/anti-patterns.md — common prompt mistakes and fixes

## Core Principles (ENFORCE THESE)

### The 5 Laws of Prompt Engineering
1. **Specificity > Brevity** — A 500-word precise prompt beats a 50-word vague one. Every word should constrain the output space.
2. **Structure > Prose** — Use XML tags, numbered lists, headers. LLMs follow structured prompts more reliably than paragraph-form instructions.
3. **Examples > Descriptions** — One input/output example teaches more than three paragraphs of description.
4. **Constraints > Hopes** — "Output MUST be valid JSON with these exact fields" beats "Please try to output JSON."
5. **Measurement > Intuition** — If you can't measure whether prompt A is better than prompt B, you're guessing.

### Prompt Template Anatomy
Every prompt should have these sections (in this order):
```
<system_prompt>
  1. ROLE: Who is the model? (persona, expertise, constraints)
  2. CONTEXT: What does the model need to know? (background, data, history)
  3. TASK: What exactly should the model do? (step-by-step if complex)
  4. OUTPUT FORMAT: What should the response look like? (schema, examples)
  5. CONSTRAINTS: What must/must not the model do? (hard rules, boundaries)
  6. EXAMPLES: 1-3 input/output pairs (few-shot learning)
</system_prompt>
```

### Template Library (include ALL of these)

#### Analysis Templates
- **Code Review Agent** — Reviews code for specific dimension (architecture, security, quality). Includes: severity enum, finding schema, evidence requirement, confidence scoring.
- **Document Analysis** — Extracts structured information from documents. Includes: extraction schema, confidence per field, source citation.
- **Comparison/Evaluation** — Compares two things across criteria. Includes: rubric, scoring, winner declaration, reasoning.

#### Generation Templates
- **Content Generation** — Generates text following specific voice/style. Includes: voice attributes, examples, forbidden words, length constraints.
- **Code Generation** — Generates code following specific patterns/standards. Includes: language, framework, patterns to use, patterns to avoid, test requirements.
- **Plan Generation** — Generates structured plans (sprints, roadmaps, architectures). Includes: decomposition framework, priority scoring, dependency mapping.

#### Meta-Prompting Templates
- **The Planner** — Given metadata about input, generates a custom analysis plan. Key: planner sees ONLY metadata (structure, schema, summary), never raw content. Outputs: focus areas, token allocation, agent-specific instructions.
- **The Prompt Generator** — Given a task description, generates an optimized prompt. Uses: few-shot examples of good prompts, prompt quality rubric, self-critique step.
- **The Schema Designer** — Given desired output, generates a Zod/JSON schema. Includes: field descriptions, validation rules, examples.

### Structured Output Patterns

#### Method 1: XML Tags (Most Reliable)
```xml
<output>
  <findings>
    <finding severity="high" confidence="0.9">
      <title>SQL Injection in auth handler</title>
      <file>src/auth/login.ts</file>
      <line>42</line>
      <description>...</description>
    </finding>
  </findings>
  <score>72</score>
</output>
```
When: complex nested outputs, when you need the model to self-organize

#### Method 2: tool_use / Function Calling (Guaranteed Schema)
When: you need GUARANTEED schema compliance, API integrations
How: define the tool schema, model calls the "tool" with structured arguments
Pros: guaranteed valid JSON. Cons: slightly less flexible.

#### Method 3: JSON with Validation (Good Middle Ground)
When: you want JSON but can handle retries
How: instruct "respond ONLY with valid JSON matching this schema", validate with Zod, retry on failure (max 2x)

### Evaluation Harness

#### Testing Prompts Systematically
1. **Define test cases** — 5-10 representative inputs covering normal + edge cases
2. **Define expectations** — for each test case, what MUST appear, what MUST NOT appear
3. **Run prompt** — execute each test case 3x (LLMs are non-deterministic)
4. **Score** — binary pass/fail per expectation, aggregate to pass rate
5. **Compare** — run test cases with prompt variant A and B, pick winner
6. **Iterate** — modify prompt based on failures, re-test

#### Quality Metrics
- **Format compliance** — does output match schema? (0 or 1)
- **Accuracy** — are facts correct? (requires human eval or golden file)
- **Precision** — of things flagged, how many are real? (false positive rate)
- **Recall** — of real issues, how many were found? (false negative rate)
- **Consistency** — across 3 runs, how similar are outputs? (jaccard similarity)
- **Token efficiency** — useful content per token generated (findings per 1K tokens)

### Chain of Thought Patterns

#### Zero-Shot CoT
Just add "Think step by step" or "Let's work through this systematically."
When: simple reasoning tasks. Surprisingly effective for 50% of use cases.

#### Structured CoT
```
Think through this in exactly these steps:
Step 1: Identify the primary language and framework
Step 2: Map the dependency graph between modules
Step 3: For each module, assess coupling to other modules
Step 4: Identify violations of the Dependency Inversion Principle
Step 5: Rank findings by severity
```
When: complex multi-step analysis. Each step constrains the next.

#### Extended Thinking (Anthropic-specific)
Use for: critique agents, validation tasks, complex reasoning
The model's internal thinking is hidden from the user but improves output quality significantly.
When to use: any task where accuracy matters more than speed.

### Anti-Patterns (WARN AGAINST)
- "The Novel" — 3000-word prompt when 300 focused words would work better
- "The Vague Ask" — "Analyze this code" (analyze for what? what output format? what depth?)
- "The Optimist" — "Please output valid JSON" (use schema validation, not politeness)
- "The Copy-Paster" — same prompt for every input (use meta-prompting to adapt)
- "The Untested" — deploying a prompt without running 5+ test cases
- "The Over-Constrained" — so many rules the model can't produce useful output
- "The Token Waster" — including irrelevant context that doesn't help the task

## Spectra Examples
Use Spectra's 6-agent pipeline as examples throughout:
- MetaPrompter: meta-prompting pattern — reads file tree only, generates custom analysis plans
- SecurityAgent: analysis template — structured findings with severity + evidence
- CritiqueAgent: critique loop pattern — extended thinking validates all findings
- Golden file testing: eval harness pattern — snapshot outputs, detect regression
- ScoreCard schema: structured output pattern — Zod schema for 6 dimensions + grades

## Tone
Write like a senior prompt engineer at Anthropic writing an internal best practices guide. Precise, measurable, no hand-waving. Every pattern should have: when to use, template, example input, example output, common mistakes. Think engineering discipline, not art.
```

---

## How to Use These Prompts

### Option A: Claude Code (recommended)
```bash
# Paste each prompt into Claude Code
# It will create the skill folder at the specified path
```

### Option B: Claude.ai with skill-creator
```
1. Start a new Claude chat
2. Say: "I want to create a new skill. Here's the full spec:"
3. Paste the prompt
4. Claude will generate SKILL.md + reference files
5. Download and place in /mnt/skills/user/<skill-name>/
```

### Option C: Sequential in one session
```
1. "Create skill 1: ai-agent-patterns" → paste prompt
2. Wait for completion
3. "Now create skill 2: hackathon-sprint" → paste prompt
4. Repeat for 3 and 4
```

### Skill Loading Order for Spectra
After all 4 are created, your skill stack for Spectra development is:

| Priority | Skill | Purpose |
|----------|-------|---------|
| P0 | uncle-bob-master | Clean Code + SOLID + Architecture |
| P0 | ai-agent-patterns | Multi-agent pipeline patterns |
| P0 | hackathon-sprint | 48hr execution framework |
| P1 | spectra-architect | Spectra-specific architecture |
| P1 | spectra-agent-orchestrator | Spectra agent pipeline |
| P1 | prompt-engineering-lab | Prompt quality + eval |
| P2 | typescript-cli-toolkit | CLI UX patterns |
| P2 | spectra-brand-voice | Brand enforcement |
| P2 | cto-delegation | Strategic planning |
| P2 | startup-brand-studio | GTM + brand |
