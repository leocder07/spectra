# Spectra — Project Instructions for Claude Code

## What is Spectra?

Spectra deploys 6 AI agents (4 parallel specialists) to analyze entire repositories across 6 dimensions — architecture, security, quality, documentation, maintainability, performance — in 90 seconds, not 90 hours. CLI tool. TypeScript strict. Clean Architecture.

**Tagline:** "The full spectrum of your codebase."
**One-liner:** "6 AI agents analyze your entire repository in 90 seconds."

---

## Architecture — ABSOLUTE RULES (NEVER VIOLATE)

### The Dependency Rule

Source code dependencies ONLY point inward:

```
Layer 1 (entities/)         → imports NOTHING from src/
Layer 2 (use-cases/)        → imports ONLY from entities/
Layer 3 (adapters/)         → imports from entities/ + use-cases/
Layer 4 (infrastructure/)   → imports from all inner layers
```

**Violation = immediate rejection. No exceptions.**

### Code Standards

- Functions: ≤20 lines, ≤3 parameters, cyclomatic complexity ≤10
- No `any` type. No `as any`. No `@ts-ignore`.
- No `console.log` in src/ — use ProgressObserver port
- Every entity: `readonly` properties. Immutable.
- Fallible operations: `Result<T, SpectraError>` pattern
- All agent outputs: validated with Zod schema BEFORE merge
- TypeScript union types for enums: `type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info'`
- Export everything from barrel `index.ts` files

---

## 6 Agents (4 Parallel Specialists)

```
Stage 1: INGEST     → Clone repo, extract file tree (simple-git)
Stage 2: PLAN       → MetaPrompter (Sonnet 4.5, file tree ONLY ≤5K tokens, NEVER full code)
Stage 3: ANALYZE    → 4 Specialists in PARALLEL via Promise.all:
                       ArchitectureAgent + SecurityAgent + QualityAgent + DocumentationAgent (all Opus 4.6)
Stage 4: CRITIQUE   → CritiqueAgent (Opus 4.6, EXTENDED THINKING, validates ALL findings)
Stage 5: SCORE      → Calculate ScoreCard (weighted: Arch 25%, Sec 25%, Qual 20%, Doc 10%, Maint 10%, Perf 10%)
Stage 6: REPORT     → Render HTML via Handlebars + Mermaid
```

### Agent Hard Rules

1. MetaPrompter NEVER gets full code. File tree only, ≤5K tokens.
2. Extended thinking: CritiqueAgent ONLY. No other agent uses it.
3. 4 specialists ALWAYS run in parallel: `const [arch, sec, qual, doc] = await Promise.all([...])`
4. Every agent output validated against Zod schema BEFORE merge.
5. Promise.race for 30s timeout per agent.
6. If 2+ agents fail → abort with partial report. Don't hang.
7. All LLM calls through decorator chain: LoggingDecorator → RetryDecorator → AnthropicLLMAdapter

---

## Agent Teams — File Ownership

| Teammate | Owns | Does NOT Touch |
|----------|------|----------------|
| architect-1 | `src/entities/*`, `src/use-cases/interfaces.ts` | Everything else |
| pipeline-1 | `src/use-cases/*.ts` (except interfaces.ts), `src/infrastructure/agents/*`, `src/infrastructure/*-adapter.ts`, `src/infrastructure/*-decorator.ts` | entities/, adapters/, templates/ |
| interface-1 | `src/adapters/*`, `templates/*`, `README.md` | entities/, use-cases/, infrastructure/ |
| qa-1 | `tests/*`, `golden-files/*` | All src/ files |
| team-lead | `CLAUDE.md`, `package.json`, `tsconfig.json`, `biome.json`, `src/infrastructure/main.ts` | Implementation files |

**RULE: Only edit files in YOUR ownership. Need something from another domain? Send a message via Teammate tool.**

---

## Project Structure

```
spectra/
├── CLAUDE.md                          # This file (auto-loaded)
├── package.json
├── tsconfig.json                      # strict: true
├── biome.json
├── src/
│   ├── entities/                      # Layer 1 — ZERO dependencies
│   │   ├── index.ts                   # All types + Zod schemas + barrel export
│   │   ├── enums.ts                   # Union type enums
│   │   └── errors.ts                  # SpectraError hierarchy (SPEC-001 to SPEC-009)
│   ├── use-cases/                     # Layer 2 — entities/ only
│   │   ├── interfaces.ts              # Port interfaces (LLMGateway, GitPort, etc.)
│   │   ├── analyze-repository.ts      # Facade — orchestrates 6 stages
│   │   ├── orchestrate-agents.ts      # Agent parallel execution
│   │   └── manage-token-budget.ts     # Token counting + allocation
│   ├── adapters/                      # Layer 3
│   │   ├── cli-controller.ts          # Commander.js entry point
│   │   ├── progress-reporter.ts       # Ora + chalk (implements ProgressObserver)
│   │   └── analysis-presenter.ts      # Final output formatting
│   └── infrastructure/                # Layer 4
│       ├── main.ts                    # Composition root (DI wiring)
│       ├── anthropic-llm-adapter.ts   # Implements LLMGateway
│       ├── retry-decorator.ts         # Exponential backoff (1s/2s/4s, max 3)
│       ├── logging-decorator.ts       # Structured logging
│       ├── simple-git-adapter.ts      # Implements GitPort
│       ├── tiktoken-adapter.ts        # Implements TokenPort
│       ├── handlebars-report-adapter.ts # Implements ReportPort
│       └── agents/
│           ├── base-agent.ts          # Template Method: validate→build→execute→parse→validate→format
│           ├── agent-factory.ts       # Creates all 6 agent configs
│           ├── meta-prompter.ts       # Sonnet 4.5, planning only
│           ├── architecture-agent.ts  # Opus 4.6, architecture dimension
│           ├── security-agent.ts      # Opus 4.6, security dimension
│           ├── quality-agent.ts       # Opus 4.6, quality dimension
│           ├── documentation-agent.ts # Opus 4.6, documentation dimension
│           └── critique-agent.ts      # Opus 4.6, EXTENDED THINKING
├── templates/
│   └── report.hbs                     # Handlebars HTML report template
├── tests/
│   ├── entities/                      # Unit tests
│   ├── use-cases/                     # Use case tests with mocked ports
│   ├── integration/                   # Pipeline stage integration tests
│   └── e2e/                           # Full CLI end-to-end tests
└── golden-files/                      # Snapshot baselines for 5 test repos
    ├── express-starter/
    ├── react-dashboard/
    ├── fastapi-ml/
    ├── nestjs-ecommerce/
    └── django-saas/
```

---

## Error Codes

| Code | Category | Retryable | Description |
|------|----------|-----------|-------------|
| SPEC-001 | Infrastructure | Yes (2x) | Git clone failed |
| SPEC-002 | Infrastructure | Yes (3x) | Anthropic API unreachable |
| SPEC-003 | Rate Limit | Yes (3x) | Anthropic 429 rate limited |
| SPEC-004 | Budget | No | Token budget exceeded |
| SPEC-005 | Validation | Yes (1x) | Agent output failed Zod schema |
| SPEC-006 | Timeout | No | Agent exceeded 30s timeout |
| SPEC-007 | Pipeline | No | 2+ agents failed |
| SPEC-008 | Critique | No | CritiqueAgent failed |
| SPEC-009 | Report | No | Template render failed |

---

## ScoreCard Weights

| Dimension | Weight | Agent |
|-----------|--------|-------|
| Architecture | 25% | ArchitectureAgent |
| Security | 25% | SecurityAgent |
| Quality | 20% | QualityAgent |
| Documentation | 10% | DocumentationAgent |
| Maintainability | 10% | QualityAgent (secondary) |
| Performance | 10% | ArchitectureAgent (secondary) |

Grades: A (90-100), B (75-89), C (60-74), D (40-59), F (0-39)

---

## Brand Voice (User-Facing Text)

**Voice:** Clear, Confident, Sharp, Warm
**FORBIDDEN words:** revolutionary, cutting-edge, game-changing, leverage, innovative, utilize, might be, could potentially, comprehensive solution, AI-powered (say "6 AI agents" instead)

### CLI Messages
- ≤80 characters per line, no period at end
- Progress: `▸ [Stage]: [Action]`
- Success: `✓ [Result]`
- Error: `✗ [What failed]: [Why]: [What to do]`

### Colors
- Primary: Spectrum Violet `#7C3AED`
- Accent: Prism Amber `#F59E0B`
- Critical: Signal Red `#EF4444`
- Good: Growth Green `#22C55E`

---

## Skills to Load

Read these BEFORE writing code (when relevant to your task):

- `/mnt/skills/user/uncle-bob-master/SKILL.md` — ALL code tasks
- `/mnt/skills/user/spectra-architect/SKILL.md` — Architecture decisions (if installed)
- `/mnt/skills/user/spectra-agent-orchestrator/SKILL.md` — Agent pipeline work (if installed)
- `/mnt/skills/user/spectra-brand-voice/SKILL.md` — Any user-facing text (if installed)

---

## Key Dependencies

```json
{
  "@anthropic-ai/sdk": "latest",
  "commander": "^12",
  "chalk": "^5",
  "ora": "^8",
  "simple-git": "^3",
  "tiktoken": "^1",
  "handlebars": "^4",
  "zod": "^3",
  "boxen": "^7",
  "cli-table3": "^0.6"
}
```

Dev: `vitest`, `typescript`, `@biomejs/biome`, `@types/node`
