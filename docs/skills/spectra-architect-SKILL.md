---
name: spectra-architect
description: |
  Full Spectra system architecture knowledge — 6-agent pipeline, Clean Architecture, meta-prompting patterns, domain model, and engineering standards. STRICT enforcement.

  **Triggers (ALWAYS activate for):**
  - Building: "build spectra", "implement pipeline", "create agent", "add stage", "wire dependency"
  - Architecture: "fix architecture", "refactor pipeline", "dependency rule", "layer violation"
  - Domain: "implement Finding", "implement Codebase", "implement ScoreCard", "implement AgentOutput"
  - Ports: "create LLMGateway", "create GitPort", "create TokenPort", "create ReportPort"
  - Testing: "test pipeline", "mock agent", "golden file", "eval harness"
  - Any code task within the Spectra project directory

  **Covers:** Clean Architecture (4 layers), 6-Agent Pipeline, Domain Model, 10 Design Patterns, Port/Adapter Interfaces, Error Taxonomy, Token Budget Management
---

# Spectra Architect — Your Founding Technical Architect

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   "I designed Spectra from first principles. 25 years of building      │
│    distributed systems, AI pipelines, and developer tools.              │
│                                                                         │
│    Every line of code in this system exists for a reason.              │
│    Dependencies point inward. Agents are stateless. The pipeline       │
│    is a state machine. No exceptions."                                 │
│                                                                         │
│                                — Spectra Architect, Sprint 0            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Mode: STRICT** | **Role: Founding Architect** | **Stack: TypeScript + Anthropic SDK + Clean Architecture**

---

## System Overview

Spectra deploys **6 AI agents** to analyze an entire repository — architecture, security, quality, documentation, maintainability — in **90 seconds**, not 90 hours.

**Tagline:** "The full spectrum of your codebase."

**Tech Stack:**
- Language: TypeScript (strict mode, Biome linting)
- CLI: Commander.js + chalk + ora
- AI: Anthropic SDK (Claude Opus 4.6, 1M context window)
- Git: simple-git
- Tokens: tiktoken (cl100k_base)
- Report: Handlebars HTML template + Mermaid diagrams
- Testing: Vitest + golden files

---

## Architecture: Clean Architecture (4 Concentric Layers)

```
┌───────────────────────────────────────────────────────────────┐
│  LAYER 4: Infrastructure (Adapters)                           │
│  AnthropicLLMAdapter, SimpleGitAdapter, TiktokenAdapter,      │
│  HandlebarsReportAdapter, CLIPresenter                        │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  LAYER 3: Interface Adapters (Controllers/Presenters) │    │
│  │  CLIController, AnalysisPresenter, ProgressReporter   │    │
│  │                                                       │    │
│  │  ┌───────────────────────────────────────────────┐    │    │
│  │  │  LAYER 2: Use Cases (Application Business)    │    │    │
│  │  │  AnalyzeRepositoryUseCase                     │    │    │
│  │  │  OrchestrateAgentsUseCase                     │    │    │
│  │  │  GenerateReportUseCase                        │    │    │
│  │  │  ManageTokenBudgetUseCase                     │    │    │
│  │  │                                               │    │    │
│  │  │  ┌───────────────────────────────────────┐    │    │    │
│  │  │  │  LAYER 1: Entities (Enterprise Core)  │    │    │    │
│  │  │  │  Codebase, Finding, ScoreCard,        │    │    │    │
│  │  │  │  AgentOutput, AnalysisConfig,         │    │    │    │
│  │  │  │  TokenBudget, Severity, Dimension     │    │    │    │
│  │  │  └───────────────────────────────────────┘    │    │    │
│  │  └───────────────────────────────────────────────┘    │    │
│  └───────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────┘
```

### THE DEPENDENCY RULE (ABSOLUTE)
**All dependencies point INWARD.** Layer 1 knows nothing about Layer 2, 3, or 4. Layer 2 defines Port interfaces that Layer 4 implements. NEVER import from an outer layer into an inner layer. Violations are architectural debt that compounds.

---

## 6-Agent Pipeline

### Agent Roster

| # | Agent | Role | Input | Output | Thinking |
|---|-------|------|-------|--------|----------|
| 1 | **MetaPrompter** | Analyzes file tree, creates analysis plan | File tree ONLY (≤5K tokens) | AnalysisPlan (focus areas, priorities, token allocation) | Standard |
| 2 | **ArchitectureAgent** | Evaluates structure, patterns, coupling | Code + MetaPrompter plan | Finding[] (architecture) | Standard |
| 3 | **SecurityAgent** | Finds vulnerabilities, auth issues | Code + MetaPrompter plan | Finding[] (security) | Standard |
| 4 | **QualityAgent** | Assesses code quality, complexity, smells | Code + MetaPrompter plan | Finding[] (quality) | Standard |
| 5 | **DocumentationAgent** | Evaluates docs, comments, API coverage | Code + MetaPrompter plan | Finding[] (documentation) | Standard |
| 6 | **CritiqueAgent** | Validates, deduplicates, scores all findings | All Finding[] + Code | ScoreCard + validated Finding[] | **Extended Thinking** |

### Pipeline Flow (6 Stages)

```
[Ingest] → [Plan] → [Analyze] → [Critique] → [Score] → [Report]
   │          │          │            │           │          │
   ▼          ▼          ▼            ▼           ▼          ▼
  Git     MetaPro    4 Agents     Critique    ScoreCard   HTML
  clone   mpter      PARALLEL     (extended   (6 dims)    report
  +tree   (5K tok)   execution    thinking)               +Mermaid
```

### HARD RULES
1. MetaPrompter NEVER gets full code — only file tree (≤5K tokens)
2. Extended thinking: CritiqueAgent ONLY
3. Agents 2-5 ALWAYS run in parallel (Promise.all)
4. Agent outputs MUST be validated against JSON schema before merge
5. Golden files refresh monthly
6. Total token budget: 800K per analysis (of 1M context)

---

## Domain Model

### Core Entities (Layer 1)

```typescript
// === Value Objects ===
type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';
type Dimension = 'architecture' | 'security' | 'quality' | 'documentation' | 'maintainability' | 'overall';
type PipelineStage = 'ingest' | 'plan' | 'analyze' | 'critique' | 'score' | 'report';
type AgentRole = 'meta-prompter' | 'architecture' | 'security' | 'quality' | 'documentation' | 'critique';

// === Core Entities ===
interface Finding {
  id: string;                    // UUID
  severity: Severity;
  dimension: Dimension;
  title: string;                 // ≤100 chars
  description: string;           // ≤500 chars
  location: FileLocation;        // file path + line range
  recommendation: string;        // actionable fix
  confidence: number;            // 0.0-1.0
  agent: AgentRole;              // which agent found it
  validated: boolean;            // set by CritiqueAgent
  tags: string[];
}

interface ScoreCard {
  dimensions: Record<Dimension, DimensionScore>;
  overall: number;               // 0-100 weighted
  findings: Finding[];
  metadata: AnalysisMetadata;
}

interface DimensionScore {
  score: number;                 // 0-100
  weight: number;                // 0.0-1.0, all weights sum to 1.0
  findings: Finding[];
  rationale: string;
}

interface Codebase {
  name: string;
  path: string;
  language: string;
  framework: string;
  fileTree: FileNode[];
  totalFiles: number;
  totalLines: number;
  tokenCount: number;
}

interface AnalysisConfig {
  maxTokenBudget: number;        // default 800_000
  agentTimeout: number;          // ms, default 120_000
  parallelAgents: number;        // default 4
  model: string;                 // 'claude-opus-4-6'
  outputFormat: 'html' | 'json' | 'markdown';
}
```

### Port Interfaces (Layer 2)

```typescript
// All ports are interfaces — Layer 4 provides implementations
interface LLMGateway {
  complete(prompt: string, config: LLMConfig): Promise<LLMResponse>;
  completeWithThinking(prompt: string, config: LLMConfig): Promise<LLMThinkingResponse>;
  countTokens(text: string): number;
}

interface GitPort {
  clone(url: string, target: string): Promise<void>;
  getFileTree(repoPath: string): Promise<FileNode[]>;
  getFileContent(filePath: string): Promise<string>;
  getRecentCommits(repoPath: string, count: number): Promise<Commit[]>;
}

interface TokenPort {
  count(text: string): number;
  truncate(text: string, maxTokens: number): string;
  allocate(budget: number, agents: AgentRole[]): TokenAllocation;
}

interface ReportPort {
  generate(scoreCard: ScoreCard, config: ReportConfig): Promise<Buffer>;
  renderMermaid(diagram: string): Promise<string>;
}

interface CachePort {
  get<T>(key: string): Promise<T | null>;
  set<T>(key: string, value: T, ttl?: number): Promise<void>;
  invalidate(pattern: string): Promise<void>;
}
```

---

## 10 Design Patterns

| # | Pattern | Where Used | Why |
|---|---------|-----------|-----|
| 1 | **Strategy** | Agent implementations | Swap agent algorithms without changing pipeline |
| 2 | **Factory** | AgentFactory | Create agents by role without exposing construction |
| 3 | **Decorator** | LoggingDecorator, RetryDecorator, MetricsDecorator | Cross-cutting concerns on LLMGateway |
| 4 | **Observer** | ProgressReporter | CLI progress updates without coupling to pipeline |
| 5 | **State Machine** | PipelineStateMachine | Enforce valid stage transitions |
| 6 | **Template Method** | BaseAgent | Common agent lifecycle (validate→execute→format) |
| 7 | **Adapter** | AnthropicLLMAdapter, SimpleGitAdapter | Bridge port interfaces to external libs |
| 8 | **Composition Root** | main.ts | Single place to wire all dependencies |
| 9 | **Repository** | FindingRepository | Aggregate and query findings |
| 10 | **Value Object** | Severity, Dimension, FileLocation | Immutable, self-validating domain primitives |

---

## Project Structure

```
spectra/
├── CLAUDE.md
├── ARCHITECTURE.md
├── package.json
├── tsconfig.json
├── biome.json
├── src/
│   ├── entities/              # LAYER 1 — Zero dependencies
│   │   └── index.ts           # All types, value objects, enums
│   ├── use-cases/             # LAYER 2 — Depends ONLY on entities
│   │   ├── interfaces.ts      # Port interfaces
│   │   ├── analyze-repository.ts
│   │   ├── orchestrate-agents.ts
│   │   ├── generate-report.ts
│   │   └── manage-token-budget.ts
│   ├── adapters/              # LAYER 3 — Controllers, presenters
│   │   ├── cli-controller.ts
│   │   ├── analysis-presenter.ts
│   │   └── progress-reporter.ts
│   ├── infrastructure/        # LAYER 4 — External implementations
│   │   ├── anthropic-llm-adapter.ts
│   │   ├── simple-git-adapter.ts
│   │   ├── tiktoken-adapter.ts
│   │   ├── handlebars-report-adapter.ts
│   │   └── agents/
│   │       ├── base-agent.ts
│   │       ├── meta-prompter.ts
│   │       ├── architecture-agent.ts
│   │       ├── security-agent.ts
│   │       ├── quality-agent.ts
│   │       ├── documentation-agent.ts
│   │       ├── critique-agent.ts
│   │       └── agent-factory.ts
│   ├── main.ts                # Composition Root
│   └── cli.ts                 # Entry point
├── templates/
│   └── report.hbs             # Handlebars HTML report
├── tests/
│   ├── golden/                # Golden file snapshots
│   ├── unit/                  # Per-module tests
│   └── integration/           # Pipeline tests
└── docs/
    ├── HLD.md
    └── LLD.md
```

---

## Engineering Standards (Hard Limits)

| Rule | Limit | Enforcement |
|------|-------|-------------|
| Function length | ≤20 lines | Biome rule |
| Function parameters | ≤3 | Code review |
| Cyclomatic complexity | ≤10 | Biome rule |
| File length | ≤200 lines | Biome rule |
| No `any` type | Zero tolerance | tsconfig strict |
| No `console.log` in src/ | Zero tolerance | Biome rule |
| Test coverage | ≥80% | Vitest |
| Import restriction | Layer N only imports Layer N-1 or lower | Architecture test |
| Naming | camelCase functions, PascalCase types, UPPER_SNAKE constants | Biome |
| Error handling | Result<T, E> pattern, never throw | Code review |

---

## Error Taxonomy

| Code | Category | Retry? | Recovery |
|------|----------|--------|----------|
| SPEC-001 | Git clone failed | Yes (3x) | Check URL, auth, network |
| SPEC-002 | Token budget exceeded | No | Reduce scope, skip large files |
| SPEC-003 | LLM rate limited | Yes (exp backoff) | Wait, retry with jitter |
| SPEC-004 | LLM response invalid JSON | Yes (2x) | Re-prompt with stricter schema |
| SPEC-005 | Agent timeout | Yes (1x, 2x timeout) | Skip agent, mark dimension as "incomplete" |
| SPEC-006 | Schema validation failed | No | Log, return partial result |
| SPEC-007 | File read permission denied | No | Skip file, note in report |
| SPEC-008 | Template render failed | No | Fallback to JSON output |

---

## Token Budget Strategy

```
Total Budget: 800,000 tokens (of 1M context)

Allocation:
├── MetaPrompter:     5,000 tokens (input: file tree only)
├── System prompts:   20,000 tokens (4 agents × 5K each)
├── Code context:     400,000 tokens (split across 4 parallel agents)
├── Agent outputs:    100,000 tokens (4 × 25K max output)
├── CritiqueAgent:    200,000 tokens (all findings + code sample)
├── Report gen:       50,000 tokens (template + Mermaid)
└── Buffer:           25,000 tokens (retries, overhead)
```

---

## CLAUDE.md Integration

When this skill is active in a Claude Code project, add to CLAUDE.md:

```markdown
## Architecture Rules (from spectra-architect skill)
- ALL dependencies point inward (Layer 1 ← 2 ← 3 ← 4)
- NEVER import from infrastructure/ in entities/ or use-cases/
- EVERY agent implements BaseAgent template method
- EVERY port interface lives in use-cases/interfaces.ts
- EVERY external library is wrapped in an adapter
- Result<T, E> pattern — never throw exceptions
- Functions ≤20 lines, ≤3 params, complexity ≤10
```

---

## Quality Gates

Before any PR merge:
1. `biome check --apply` passes with zero warnings
2. `vitest run` — all tests pass, coverage ≥80%
3. Architecture test: no cross-layer imports detected
4. Golden file diff: no unexpected regressions
5. Token budget: no agent exceeds its allocation by >10%

---

*This skill embodies 25 years of systems architecture experience applied to AI-native developer tools. Every pattern is battle-tested. Every limit exists because we hit the problem it prevents.*
