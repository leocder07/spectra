---
type: pattern
project: spectra
created: 2026-02-14
tags: [type/pattern, project/spectra, domain/backend]
---

# Clean Architecture — 4-Layer Pattern

## The Dependency Rule (ABSOLUTE)

```
Layer 1 (entities/)         → imports NOTHING from src/
Layer 2 (use-cases/)        → imports ONLY from entities/
Layer 3 (adapters/)         → imports from entities/ + use-cases/
Layer 4 (infrastructure/)   → imports from all inner layers
```

**Violation = immediate rejection. No exceptions.**

## Key Patterns Used

- **Template Method** in `base-agent.ts`: validate → build → execute → parse → validate → format
- **Decorator Chain**: LoggingDecorator → RetryDecorator → AnthropicLLMAdapter
- **Facade**: `AnalyzeRepo` orchestrates all 6 pipeline stages
- **Result<T, SpectraError>**: All fallible operations return Result types
- **Port/Adapter**: Interfaces in use-cases, implementations in infrastructure
