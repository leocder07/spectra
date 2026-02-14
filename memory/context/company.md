# Company & Team Context

## Team Structure (Agent Teams)
| Role | Persona | Owns |
|------|---------|------|
| architect-1 | Uncle Bob (Robert C. Martin) | entities/, interfaces.ts |
| pipeline-1 | Werner Vogels (AWS CTO) | use-cases/, infrastructure/agents/, adapters, decorators |
| interface-1 | Guillermo Rauch (Vercel) | adapters/, templates/, README |
| qa-1 | Kent Beck | tests/, golden-files/ |
| team-lead (Vivek) | CTO Coordinator | CLAUDE.md, package.json, tsconfig, biome, main.ts |

## Tools & Stack
- **AI:** Anthropic Claude API (Opus 4.6 for specialists, Sonnet 4.5 for MetaPrompter)
- **Runtime:** Node.js v20+
- **CLI:** Commander.js v12, chalk v5, ora v8
- **Validation:** Zod v3
- **Git:** simple-git v3
- **Tokens:** tiktoken (cl100k_base encoding)
- **Reports:** Handlebars v4 + Mermaid
- **Testing:** Vitest
- **Linting:** Biome (strict)
- **Dev tool:** Claude Code (Agent Teams feature)

## Budget
- Starting: $5,500
- Target hourly: $66-75/hr
- Per-run cost: ~$6.75 (full) / ~$1.80 (quick)

## Key Patterns
- Clean Architecture (4 layers, strict dependency rule)
- Template Method (base-agent.ts)
- Decorator Chain (Logging → Retry → Anthropic adapter)
- Facade (AnalyzeRepo orchestrates 6 stages)
- Result<T, SpectraError> for fallible ops
