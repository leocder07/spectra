---
type: stack
project: spectra
created: 2026-02-14
tags: [type/context, project/spectra, domain/infra]
---

# Tech Stack

## Runtime & Language
- Node.js v20+
- TypeScript strict mode

## Core Dependencies
| Package | Version | Purpose |
|---------|---------|---------|
| @anthropic-ai/sdk | latest | Claude API |
| commander | ^12 | CLI framework |
| chalk | ^5 | Terminal colors |
| ora | ^8 | Spinners |
| simple-git | ^3 | Git operations |
| tiktoken | ^1 | Token counting (cl100k_base) |
| handlebars | ^4 | HTML report templates |
| zod | ^3 | Schema validation |
| boxen | ^7 | Box drawing |
| cli-table3 | ^0.6 | Table rendering |

## Dev Dependencies
- vitest — Test runner
- @biomejs/biome — Linter + formatter
- typescript, @types/node

## AI Models
| Model | Used By | Purpose |
|-------|---------|---------|
| Opus 4.6 | 4 specialists + CritiqueAgent | Deep analysis |
| Sonnet 4.5 | MetaPrompter | Planning (file tree only) |

## Design Patterns
- Clean Architecture (4 layers)
- Template Method (base-agent.ts)
- Decorator Chain (Logging → Retry → Anthropic)
- Facade (AnalyzeRepo orchestrates 6 stages)
- Result<T, E> pattern for errors
