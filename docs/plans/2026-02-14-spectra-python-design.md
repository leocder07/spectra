# Spectra Python Rewrite — Environment & Architecture Design

> Approved: Feb 14, 2026 | Approach A: Full Plugin + Agent Teams + Skills

---

## Decision Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python 3.12+ | Founder's AI stack is Python-native (OpenAI SDK, LangChain, Pinecone) |
| CLI Framework | Typer + Rich | Already specified in tech-dashboard.jsx L62 |
| Validation | Pydantic v2 (frozen) | Direct Zod equivalent, Rust core, great errors |
| Async | asyncio + httpx | Native async, Anthropic SDK supports async |
| Templating | Jinja2 | Already specified in tech-dashboard.jsx L61/L94 |
| Diagrams | Excalidraw MCP | Replaces Mermaid for architecture visualization |
| Git | GitPython | Already specified in tech-dashboard.jsx L47/L94 |
| Tokens | tiktoken | Same library, Python package |
| File I/O | pathlib | Already specified in tech-dashboard.jsx L94 |
| Linting | ruff + mypy --strict | Replaces biome + tsconfig strict |
| Testing | pytest + pytest-asyncio | Replaces vitest |
| Distribution | PyPI + pipx | Matches G13 gap item |
| Analysis Agents | 8 (full Master Prompt) | MetaPrompter + 6 specialists + CritiqueAgent |
| Build Team | 4 teammates (Agent Teams) | architect-1, pipeline-1, interface-1, qa-1 |
| Product Name | Spectra | "The full spectrum of your codebase" |

---

## 1. Plugin Structure

```
.claude-plugin/
├── plugin.json
├── skills/
│   ├── spectra-architect/
│   │   └── SKILL.md
│   ├── spectra-orchestrator/
│   │   └── SKILL.md
│   ├── spectra-brand-voice/
│   │   └── SKILL.md
│   └── spectra-hackathon/
│       └── SKILL.md
├── agents/
│   ├── architect-1.md
│   ├── pipeline-1.md
│   ├── interface-1.md
│   └── qa-1.md
└── hooks/
    ├── dependency-guard.sh
    └── no-any-types.sh
```

### plugin.json

```json
{
  "name": "spectra",
  "description": "Spectra codebase intelligence CLI - development toolkit",
  "version": "0.1.0",
  "skills": [
    "skills/spectra-architect",
    "skills/spectra-orchestrator",
    "skills/spectra-brand-voice",
    "skills/spectra-hackathon"
  ],
  "agents": [
    "agents/architect-1.md",
    "agents/pipeline-1.md",
    "agents/interface-1.md",
    "agents/qa-1.md"
  ]
}
```

---

## 2. Skills Design

### Skill 1: spectra-architect

**Triggers:** entity creation, interface definition, architecture decisions, layer boundary work

**Content covers:**
- Clean Architecture 4-layer dependency rule (Python imports)
- Domain model: Pydantic frozen models for Finding, ScoreCard, Codebase, AnalysisReport
- Literal types for enums: `Severity = Literal['critical', 'high', 'medium', 'low', 'info']`
- 6 Protocol interfaces: LLMGateway, GitPort, FilePort, TokenPort, ReportPort, ProgressObserver
- Error taxonomy: SPEC-001 to SPEC-009 with retry policies
- 8 design patterns mapped to Python (ABC for Template Method, Protocol for ports, etc.)
- ScoreCard weights: Arch 25%, Sec 25%, Qual 20%, Doc 10%, Maint 10%, Perf 10%
- Finding dedup: `__hash__` + `__eq__` on (file_path, line_start, dimension) tuple
- Token budget: 800K total, MetaPrompter 5K, 6 specialists shared pool, CritiqueAgent 200K reserved

### Skill 2: spectra-orchestrator

**Triggers:** agent implementation, pipeline work, LLM calls, parallel execution

**Content covers:**
- Agent lifecycle (ABC Template Method): validate_input → build_prompt → execute_llm → parse_output → validate_output → format_result
- Prompt templates for all 8 analysis agents
- Parallel execution: `asyncio.gather(return_exceptions=True)` with `asyncio.wait_for(timeout=30)` per agent
- Decorator chain: LoggingDecorator → RetryDecorator → AnthropicAdapter
- Retry policy: 3 retries, exponential backoff 1s/2s/4s, max 30s per agent
- Agent failure state machine: 0 fail=normal, 1 fail=reweight scorecard, 2+ fail=abort with partial report, CritiqueAgent fail=mark "unvalidated"
- MetaPrompter: Sonnet 4.5, file tree only (never full code), ≤5K tokens
- CritiqueAgent: Opus 4.6, extended thinking enabled, validates ALL findings
- Async patterns: `asyncio.gather()` replaces `Promise.all`, `asyncio.wait_for()` replaces `Promise.race`

### Skill 3: spectra-brand-voice

**Triggers:** user-facing text, CLI messages, report copy, README

**Content covers:**
- Voice: Clear, Confident, Sharp, Warm
- Forbidden words: revolutionary, cutting-edge, game-changing, leverage, innovative, etc.
- CLI copy: ≤80 chars, no period, prefixes ▸/✓/✗
- Rich markup conventions for terminal output
- Color palette: Violet #7C3AED, Amber #F59E0B, Red #EF4444, Green #22C55E
- Error format: What → Why → Fix

### Skill 4: spectra-hackathon

**Triggers:** sprint planning, prioritization, scope decisions

**Content covers:**
- 48hr sprint plan (3 sprints: Foundation 12h, Pipeline 12h, Test+Ship 10h)
- Scope tiers: Tier 1 MUST SHIP, Tier 2 IF TIME, Tier 3 DREAM
- Cut triggers at hours 16, 22, 28, 34
- Budget: $500 credits, ~$7.84/run, ~63 full runs
- Anti-patterns: don't spend >30min on any bug, don't perfect prompts, don't test before pipeline works
- Video script structure (2 minutes)

---

## 3. Agent Team Design

### Team Configuration

| Agent | Model | File Ownership | Skills | Notes |
|-------|-------|----------------|--------|-------|
| architect-1 | Opus 4.6 | `src/spectra/entities/`, `src/spectra/use_cases/interfaces.py` | spectra-architect, uncle-bob-master | Starts immediately |
| pipeline-1 | Opus 4.6 | `src/spectra/use_cases/*.py` (except interfaces.py), `src/spectra/infrastructure/` | spectra-orchestrator, spectra-architect | Waits for entities |
| interface-1 | Sonnet 4.5 | `src/spectra/adapters/`, `templates/`, `README.md` | spectra-brand-voice | Starts immediately |
| qa-1 | Sonnet 4.5 | `tests/`, `golden_files/` | TDD | Waits for entities |

### Coordination Flow

```
Hour 0-2:   architect-1 → entities + interfaces
            interface-1 → CLI shell + report template skeleton (mock data)

Hour 2-8:   pipeline-1  → use cases + adapters + retry/logging decorators
            architect-1 → review/refine entities based on pipeline needs
            qa-1        → test fixtures + golden file structure

Hour 8-16:  pipeline-1  → all 8 agent implementations + agent factory
            interface-1 → Rich progress reporter + analysis presenter

Hour 16-22: pipeline-1  → composition root (main.py) wiring
            interface-1 → Jinja2 HTML report template + Excalidraw diagrams
            qa-1        → integration tests

Hour 22+:   All agents on polish, testing, README, bug fixes
```

### Agent Frontmatter

**architect-1.md:**
```yaml
---
name: architect-1
description: Domain entities, interfaces, and Clean Architecture Layer 1-2 for Spectra
model: claude-opus-4-6
tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
skills:
  - spectra-architect
  - uncle-bob-master
---

You are architect-1, responsible for Spectra's domain layer.

## File Ownership
You ONLY edit files in:
- src/spectra/entities/
- src/spectra/use_cases/interfaces.py

## Rules
- All models use Pydantic BaseModel with frozen=True
- Use Literal types for enums, never Python Enum class
- Every entity must be immutable and hashable
- Protocol classes for all port interfaces
- Zero imports from use_cases/, adapters/, or infrastructure/
```

**pipeline-1.md:**
```yaml
---
name: pipeline-1
description: Use cases, infrastructure adapters, and all 8 analysis agents for Spectra
model: claude-opus-4-6
tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
skills:
  - spectra-orchestrator
  - spectra-architect
---

You are pipeline-1, responsible for Spectra's business logic and infrastructure.

## File Ownership
You ONLY edit files in:
- src/spectra/use_cases/ (except interfaces.py — owned by architect-1)
- src/spectra/infrastructure/

## Rules
- Use cases import ONLY from entities/
- Infrastructure implements Protocol interfaces from use_cases/interfaces.py
- All LLM calls through decorator chain: logging → retry → anthropic
- Agents use ABC Template Method pattern
- Parallel execution via asyncio.gather(return_exceptions=True)
- 30s timeout per agent via asyncio.wait_for()
```

**interface-1.md:**
```yaml
---
name: interface-1
description: CLI interface, Rich terminal output, and Jinja2 HTML report for Spectra
model: claude-sonnet-4-5-20250929
tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
skills:
  - spectra-brand-voice
---

You are interface-1, responsible for Spectra's user-facing layer.

## File Ownership
You ONLY edit files in:
- src/spectra/adapters/
- templates/
- README.md

## Rules
- Follow brand voice: Clear, Confident, Sharp, Warm
- CLI messages ≤80 chars, no period, use ▸/✓/✗ prefixes
- Rich Console for all terminal output (never print())
- Jinja2 for HTML report
- Colors: Violet #7C3AED, Amber #F59E0B, Red #EF4444, Green #22C55E
```

**qa-1.md:**
```yaml
---
name: qa-1
description: Test suite, golden files, and quality assurance for Spectra
model: claude-sonnet-4-5-20250929
tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
skills:
  - superpowers:test-driven-development
---

You are qa-1, responsible for Spectra's test coverage and quality.

## File Ownership
You ONLY edit files in:
- tests/
- golden_files/

## Rules
- pytest + pytest-asyncio for all tests
- AsyncMock for LLMGateway in unit tests
- Golden files for 5 reference repos
- Test structure mirrors src/ structure
- Never import from infrastructure/ in unit tests (use mocked ports)
```

---

## 4. Hooks

### dependency-guard.sh (PreToolUse on Write/Edit)

Checks that:
- `entities/` files never import from `use_cases/`, `adapters/`, or `infrastructure/`
- `use_cases/` files never import from `adapters/` or `infrastructure/`
- `adapters/` files never import from `infrastructure/`

### no-any-types.sh (PreToolUse on Write/Edit)

Checks that src/ files don't contain:
- `from typing import Any`
- `: Any`
- `# type: ignore`

---

## 5. Python Project Structure

```
spectra/
├── CLAUDE.md
├── pyproject.toml
├── src/
│   └── spectra/
│       ├── __init__.py
│       ├── entities/
│       │   ├── __init__.py        # __all__ barrel export
│       │   ├── enums.py           # Literal type aliases
│       │   ├── errors.py          # SpectraError hierarchy
│       │   └── models.py          # Pydantic frozen models
│       ├── use_cases/
│       │   ├── __init__.py
│       │   ├── interfaces.py      # Protocol classes (ports)
│       │   ├── analyze_repository.py  # Facade
│       │   ├── orchestrate_agents.py  # asyncio.gather parallel execution
│       │   └── manage_token_budget.py
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── cli_controller.py  # Typer app
│       │   ├── progress_reporter.py   # Rich Progress (implements ProgressObserver)
│       │   └── analysis_presenter.py  # Rich Console output
│       └── infrastructure/
│           ├── __init__.py
│           ├── main.py            # Composition root (DI wiring)
│           ├── anthropic_adapter.py   # Implements LLMGateway
│           ├── retry_decorator.py     # Exponential backoff
│           ├── logging_decorator.py   # Structured logging
│           ├── git_adapter.py         # GitPython (implements GitPort)
│           ├── tiktoken_adapter.py    # Token counting (implements TokenPort)
│           ├── report_adapter.py      # Jinja2 (implements ReportPort)
│           └── agents/
│               ├── __init__.py
│               ├── base_agent.py      # ABC Template Method
│               ├── agent_factory.py
│               ├── meta_prompter.py   # Sonnet 4.5
│               ├── architecture_agent.py  # Opus 4.6
│               ├── security_agent.py      # Opus 4.6
│               ├── quality_agent.py       # Opus 4.6
│               ├── documentation_agent.py # Opus 4.6
│               ├── dependency_agent.py    # Opus 4.6 (supply chain, SBOM)
│               ├── performance_agent.py   # Opus 4.6 (hotspots, N+1)
│               └── critique_agent.py      # Opus 4.6, EXTENDED THINKING
├── templates/
│   └── report.html.j2
├── tests/
│   ├── conftest.py
│   ├── entities/
│   ├── use_cases/
│   ├── integration/
│   └── e2e/
└── golden_files/
    ├── express-starter/
    ├── react-dashboard/
    ├── fastapi-ml/
    ├── nestjs-ecommerce/
    └── django-saas/
```

---

## 6. Key Python Equivalents

| TypeScript | Python |
|-----------|--------|
| `interface LLMGateway` | `class LLMGateway(Protocol)` |
| `type Severity = 'critical' \| 'high'` | `Severity = Literal['critical', 'high']` |
| Zod schema | `class Finding(BaseModel, frozen=True)` |
| `Result<T, E>` | `@dataclass(frozen=True) class Result(Generic[T, E])` |
| `Promise.all([...])` | `asyncio.gather(*tasks)` |
| `Promise.race([task, timeout(30_000)])` | `asyncio.wait_for(task, timeout=30)` |
| `Promise.allSettled([...])` | `asyncio.gather(*tasks, return_exceptions=True)` |
| `readonly` properties | `frozen=True` on Pydantic model |
| barrel `index.ts` | `__init__.py` with `__all__` |
| `tsconfig strict: true` | `mypy --strict` |
| `biome check` | `ruff check` |
| `vitest` | `pytest` |
| `as const` | `Final[]` or `Literal[]` |
| `@ts-ignore` | `# type: ignore` (FORBIDDEN in src/) |

---

## 7. Gap Resolution Map

| Gap | How Resolved |
|-----|-------------|
| G01: Finding dedup | spectra-architect skill: `__hash__` on (file_path, line_start, dimension) |
| G02: Severity weights | spectra-architect skill: weight table in domain model |
| G03: ProgressObserver freq | Resolved per dashboard |
| G04: Rate limit retry | spectra-orchestrator skill: 3x retry, 1s/2s/4s backoff |
| G05: Token counter drift | pipeline-1: tiktoken with 5% safety margin |
| G06: Parallel timeout | spectra-orchestrator: `asyncio.wait_for(30)` per agent in `gather(return_exceptions=True)` |
| G07: Meta-prompt budget | spectra-architect: 5K token max, file tree only |
| G08: Degraded partial merge | spectra-orchestrator: failure state machine (0/1/2+ fail thresholds) |
| G09: Score dimension weights | spectra-architect: Arch 25%, Sec 25%, Qual 20%, Doc 10%, Maint 10%, Perf 10% |
| G10: File hotspot formula | pipeline-1: risk = (findings_count * avg_severity_weight) / file_loc |
| G11: LLM mock strategy | qa-1: `AsyncMock` for LLMGateway Protocol, fixture returns golden file data |
| G12: Golden file structure | qa-1: 5 repos with expected Finding lists + ScoreCard snapshots |
| G13: PyPI packaging | interface-1: `pyproject.toml` with `[project.scripts] spectra = "spectra.infrastructure.main:cli"` |
| G14: Docker optimization | Deferred |

---

## 8. Existing Skills to Use

| Skill | When |
|-------|------|
| uncle-bob-master | All code — SOLID, clean code, naming |
| superpowers:test-driven-development | qa-1 writing tests |
| superpowers:systematic-debugging | When pipeline breaks |
| superpowers:dispatching-parallel-agents | Launching build team agents |
| superpowers:writing-plans | Implementation plan (next step) |
| superpowers:verification-before-completion | Before final commit |
| context7 MCP | Pull latest API docs for Anthropic SDK, Typer, Rich, Pydantic |
| Excalidraw MCP | Architecture diagrams for HTML report |

---

## 9. Dependencies (pyproject.toml)

```toml
[project]
name = "spectra-cli"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "anthropic>=0.40",
    "typer>=0.12",
    "rich>=13",
    "pydantic>=2.5",
    "gitpython>=3.1",
    "tiktoken>=0.7",
    "jinja2>=3.1",
    "httpx>=0.27",
]

[project.scripts]
spectra = "spectra.infrastructure.main:cli"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "ANN", "S", "B", "A", "C4", "RET", "SIM", "TCH"]

[tool.mypy]
strict = true
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
timeout = 30
```

---

*Next step: Invoke writing-plans skill to create detailed implementation plan.*
