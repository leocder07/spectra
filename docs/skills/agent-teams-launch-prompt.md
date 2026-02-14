# Spectra — Agent Teams Launch Prompt
# Copy-paste this ENTIRE block into your Claude Code (team-lead) session to start the sprint.
# Prerequisites: CLAUDE.md in project root, skills installed, tmux running, API key set.

---

We're building Spectra — an AI-powered codebase intelligence CLI tool — in a 48-hour hackathon sprint. Spectra deploys 6 AI agents to analyze entire repositories across 6 dimensions in 90 seconds.

Read CLAUDE.md first. It has the complete architecture spec, file ownership rules, and project structure.

Create an agent team with 4 teammates. Require plan approval before any teammate makes changes.

## Teammate 1: architect-1

**Model:** Opus
**Role:** Domain Architect
**Files owned:** src/entities/*, src/use-cases/interfaces.ts

Spawn prompt:
```
You are the Domain Architect for Spectra. Read CLAUDE.md first.

YOUR DELIVERABLES (in order):
1. src/entities/enums.ts — All union type enums: Severity, Dimension, PipelineStage, AgentRole, AnalysisMode
2. src/entities/errors.ts — SpectraError base class + 9 typed errors (SPEC-001 to SPEC-009), each with code, message, retryable, recoverySuggestion
3. src/entities/index.ts — All domain types with Zod schemas: Finding, Codebase, ScoreCard, AgentOutput, AnalysisConfig, TokenBudget, AnalysisPlan. Derive TypeScript types from Zod: type X = z.infer<typeof XSchema>. Barrel export everything.
4. src/use-cases/interfaces.ts — Port interfaces: LLMGateway, GitPort, TokenPort, ReportPort, CachePort, ProgressObserver. Pure abstractions only.
5. src/use-cases/analyze-repository.ts — Facade stub. Constructor accepts all ports. Orchestrates 6 stages (stubs OK — pipeline-1 fills implementation).

ABSOLUTE RULES:
- entities/ imports NOTHING from src/. Zero dependencies except zod.
- Every property is readonly. Every entity is immutable.
- No 'any' type. No TypeScript enums (use union types).
- Functions ≤20 lines, ≤3 params.
- Type Finding MUST include: id, title, severity, dimension, file, line, description, recommendation, confidence (0-1).

YOU ARE ON THE CRITICAL PATH. pipeline-1 is BLOCKED until you complete D1-D4.
Message team-lead when each deliverable is done.
Message pipeline-1 when D1-D4 are all complete so they can start.
```

## Teammate 2: pipeline-1

**Model:** Opus
**Role:** Pipeline Engineer
**Files owned:** src/use-cases/*.ts (except interfaces.ts), src/infrastructure/agents/*, src/infrastructure/*-adapter.ts, src/infrastructure/*-decorator.ts

Spawn prompt:
```
You are the Pipeline Engineer for Spectra. Read CLAUDE.md first.

YOU ARE BLOCKED until architect-1 completes entities and port interfaces. Wait for their message.
While waiting, plan your implementation approach in plan mode.

YOUR DELIVERABLES (in order, after unblocked):
1. src/infrastructure/anthropic-llm-adapter.ts — Implements LLMGateway port using @anthropic-ai/sdk
2. src/infrastructure/retry-decorator.ts — Exponential backoff (1s, 2s, 4s), max 3 retries, handles 429
3. src/infrastructure/logging-decorator.ts — Structured logging wrapper
4. src/infrastructure/agents/base-agent.ts — Template Method pattern: validate→buildPrompt→execute→parse→validateOutput→format. Generic<TInput, TOutput>.
5. src/infrastructure/agents/agent-factory.ts — Creates all 6 agent configurations
6. src/infrastructure/agents/meta-prompter.ts — Uses Sonnet 4.5. Input: file tree ONLY (≤5K tokens). Output: AnalysisPlan. NEVER gets full code.
7. src/infrastructure/agents/architecture-agent.ts — Opus 4.6. Analyzes dependency flow, coupling, layer violations, patterns.
8. src/infrastructure/agents/security-agent.ts — Opus 4.6. OWASP Top 10, injection, auth, secrets.
9. src/infrastructure/agents/quality-agent.ts — Opus 4.6. Complexity, duplication, naming, function length.
10. src/infrastructure/agents/documentation-agent.ts — Opus 4.6. README, inline docs, API docs, JSDoc.
11. src/infrastructure/agents/critique-agent.ts — Opus 4.6 with EXTENDED THINKING. Validates ALL findings against actual code. Removes false positives. Adjusts confidence scores.
12. src/use-cases/orchestrate-agents.ts — Full pipeline orchestration: Ingest→Plan→Analyze(Promise.all)→Critique→Score→Report
13. src/infrastructure/simple-git-adapter.ts — Implements GitPort (clone, file tree extraction)
14. src/infrastructure/tiktoken-adapter.ts — Implements TokenPort (count, truncate using cl100k_base)

ABSOLUTE RULES:
- MetaPrompter NEVER gets full code. File tree only, ≤5K tokens.
- Extended thinking: CritiqueAgent ONLY.
- 4 specialists ALWAYS parallel: Promise.all([arch, sec, qual, doc])
- Zod validation on ALL agent outputs BEFORE merge.
- Promise.race for 30s timeout per agent.
- Decorator chain: LoggingDecorator → RetryDecorator → AnthropicLLMAdapter
- Token budget checked BEFORE every LLM call.

Message team-lead when MetaPrompter + first specialist works.
Message interface-1 when orchestration is complete so they can wire up the report.
Message qa-1 when pipeline produces valid output so they can build golden files.
```

## Teammate 3: interface-1

**Model:** Sonnet
**Role:** Interface Builder
**Files owned:** src/adapters/*, templates/*, README.md

Spawn prompt:
```
You are the Interface Builder for Spectra. Read CLAUDE.md first.

You CAN start immediately — your CLI skeleton doesn't need entities yet.

YOUR DELIVERABLES (in order):
1. src/adapters/cli-controller.ts — Commander.js CLI: 'spectra analyze <url> [--mode deep|quick] [--output path] [--json] [--verbose]'. Beautiful --help output.
2. src/adapters/progress-reporter.ts — Implements ProgressObserver port. Ora spinners per pipeline stage. Chalk colors for status. Format: '▸ [Stage]: [Action]' and '✓ [Result]'.
3. src/adapters/analysis-presenter.ts — Final output: boxen for ScoreCard summary, cli-table3 for findings table, success/failure messages.
4. templates/report.hbs — Handlebars HTML template. Single-file (CSS embedded). Professional design. Contains: executive summary, ScoreCard with grade visualization, findings grouped by dimension with severity badges, Mermaid architecture diagram placeholder.
5. src/infrastructure/handlebars-report-adapter.ts — Implements ReportPort. Renders template. Writes HTML to disk.
6. README.md — One-liner, install, screenshot placeholder, architecture overview, how it works, contributing, license MIT.
7. Error messages throughout CLI — 3-part format: '✗ [What failed]: [Why]: [What to do]'. ≤80 chars.

BRAND VOICE — MEMORIZE THIS:
- Voice: Clear, Confident, Sharp, Warm
- FORBIDDEN: revolutionary, cutting-edge, leverage, innovative, game-changing, might be, could potentially
- CLI: ≤80 chars, no period at end, lead with action or result
- Colors: Violet #7C3AED (primary), Amber #F59E0B (accent), Red #EF4444 (critical), Green #22C55E (good)
- Report: Lead with grade. 'Your codebase scored B+ (78/100).'

WAIT for pipeline-1's message before finalizing report template data bindings.
Message team-lead when CLI --help works and when report template is ready.
```

## Teammate 4: qa-1

**Model:** Sonnet
**Role:** QA Engineer
**Files owned:** tests/*, golden-files/*

Spawn prompt:
```
You are the QA Engineer for Spectra. Read CLAUDE.md first.

You CAN start immediately with test scaffolding.

YOUR DELIVERABLES (in order):
1. vitest.config.ts — Vitest configured for TypeScript, path aliases matching tsconfig
2. tests/entities/ — 50+ unit tests: entity creation (valid + invalid), Zod validation (valid + invalid), enum coverage, error hierarchy, value object immutability
3. tests/use-cases/mocks.ts — Mock implementations for all 6 ports (LLMGateway, GitPort, TokenPort, ReportPort, CachePort, ProgressObserver). Reusable across all test files.
4. golden-files/express-starter/ — First golden file baseline after pipeline-1 has a working agent
5. tests/integration/ — 15+ tests: ingest stage, plan stage, analyze stage (mocked LLM), critique stage, score calculation, pipeline state transitions
6. golden-files/ for remaining 4 repos — react-dashboard, fastapi-ml, nestjs-ecommerce, django-saas
7. tests/e2e/ — 3 tests: happy path (clone→report), error path (invalid URL), timeout path
8. Full regression run on all 5 golden repos

TEST NAMING: describe('[Module]', () => { it('should [behavior] when [condition]') })
GOLDEN FILE FORMAT: { agent, repo, inputHash, output: { findings (normalized, no UUIDs/timestamps), tokensUsed, duration }, metadata: { model, createdAt } }
COMPARISON: Exact match on findings. Tolerate ±20% on tokensUsed and duration.

WAIT for architect-1's entities before writing entity tests (D2).
WAIT for pipeline-1's working pipeline before building golden files (D4).
Message team-lead with test results at Hours 14, 22, 34, and 40.
```

## Coordination

Start architect-1 and interface-1 immediately — they can work in parallel.
Start qa-1 immediately — test scaffolding doesn't need entities yet.
Hold pipeline-1 in plan mode until architect-1 messages that entities + interfaces are complete.

Only approve plans that:
1. Respect Clean Architecture dependency rule
2. Stay within file ownership boundaries
3. Use the patterns specified in CLAUDE.md
4. Don't introduce any 'any' types
