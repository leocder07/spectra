---
type: context
project: spectra
created: 2026-02-14
tags: [type/context, project/spectra]
---

# Team & Tools Context

## Agent Team Structure

| Role | Persona | Owns |
|------|---------|------|
| architect-1 | Uncle Bob (Robert C. Martin) | `entities/`, `interfaces.ts` |
| pipeline-1 | Werner Vogels (AWS CTO) | `use-cases/`, `infrastructure/agents/`, adapters, decorators |
| interface-1 | Guillermo Rauch (Vercel) | `adapters/`, `templates/`, `README.md` |
| qa-1 | Kent Beck | `tests/`, `golden-files/` |
| team-lead ([[agents/profiles/vivek|Vivek]]) | CTO Coordinator | `CLAUDE.md`, `package.json`, `tsconfig`, `biome`, `main.ts` |

## Budget

- Starting: $5,500
- Target hourly: $66-75/hr
- Fast mode discount ends Feb 16

## Code Standards (Non-Negotiable)

- Functions: ≤20 lines, ≤3 params, complexity ≤10
- TypeScript strict (no `any`, no `as any`, no `@ts-ignore`)
- No `console.log` in src/ → use ProgressObserver
- All entities: `readonly` properties (immutable)
- Union types for enums (NOT TS enums)
- `Result<T, SpectraError>` for fallible ops
- Zod validation BEFORE merge
- Barrel exports via `index.ts`

## Agent Execution Rules

1. MetaPrompter NEVER gets full code (file tree only, ≤5K tokens)
2. Extended thinking: CritiqueAgent ONLY
3. 4 specialists ALWAYS parallel: `await Promise.all([...])`
4. Promise.race 30s timeout per agent
5. 2+ agents fail → abort with partial report
6. All LLM calls through decorator chain: Logging → Retry → Anthropic
