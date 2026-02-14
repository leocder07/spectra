# Architecture Patterns — Spectra Implementation Guide

## Pattern 1: Strategy (Agent Implementations)

```typescript
// Port (Layer 2)
interface AnalysisAgent {
  readonly role: AgentRole;
  analyze(context: AgentContext): Promise<AgentOutput>;
}

// Concrete strategies (Layer 4)
class ArchitectureAgent implements AnalysisAgent {
  readonly role = 'architecture' as const;
  async analyze(ctx: AgentContext): Promise<AgentOutput> { /* ... */ }
}
class SecurityAgent implements AnalysisAgent {
  readonly role = 'security' as const;
  async analyze(ctx: AgentContext): Promise<AgentOutput> { /* ... */ }
}
```

## Pattern 2: Factory (AgentFactory)

```typescript
class AgentFactory {
  private readonly registry: Map<AgentRole, () => AnalysisAgent>;

  constructor(llm: LLMGateway, tokens: TokenPort) {
    this.registry = new Map([
      ['architecture', () => new ArchitectureAgent(llm, tokens)],
      ['security', () => new SecurityAgent(llm, tokens)],
      ['quality', () => new QualityAgent(llm, tokens)],
      ['documentation', () => new DocumentationAgent(llm, tokens)],
    ]);
  }

  create(role: AgentRole): AnalysisAgent {
    const factory = this.registry.get(role);
    if (!factory) throw new Error(`Unknown agent role: ${role}`);
    return factory();
  }

  createParallelTeam(): AnalysisAgent[] {
    return ['architecture', 'security', 'quality', 'documentation']
      .map(role => this.create(role as AgentRole));
  }
}
```

## Pattern 3: Decorator (LLMGateway Chain)

```typescript
// Base: AnthropicLLMAdapter
// Decorators wrap in order: Logging → Retry → Metrics

class RetryDecorator implements LLMGateway {
  constructor(
    private readonly inner: LLMGateway,
    private readonly maxRetries: number = 3,
    private readonly baseDelay: number = 1000,
  ) {}

  async complete(prompt: string, config: LLMConfig): Promise<LLMResponse> {
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        return await this.inner.complete(prompt, config);
      } catch (error) {
        if (attempt === this.maxRetries) throw error;
        const delay = this.baseDelay * Math.pow(2, attempt) + Math.random() * 500;
        await new Promise(r => setTimeout(r, delay));
      }
    }
    throw new Error('Unreachable');
  }
}

class LoggingDecorator implements LLMGateway {
  constructor(private readonly inner: LLMGateway, private readonly logger: Logger) {}

  async complete(prompt: string, config: LLMConfig): Promise<LLMResponse> {
    this.logger.info(`LLM call: ${config.model}, tokens: ${prompt.length}`);
    const start = Date.now();
    const result = await this.inner.complete(prompt, config);
    this.logger.info(`LLM response: ${Date.now() - start}ms`);
    return result;
  }
}

// Composition Root wiring:
const baseLLM = new AnthropicLLMAdapter(apiKey);
const withRetry = new RetryDecorator(baseLLM, 3);
const withLogging = new LoggingDecorator(withRetry, logger);
const withMetrics = new MetricsDecorator(withLogging, metrics);
// Use withMetrics everywhere — outermost decorator
```

## Pattern 4: Observer (ProgressReporter)

```typescript
interface PipelineObserver {
  onStageStart(stage: PipelineStage): void;
  onStageComplete(stage: PipelineStage, duration: number): void;
  onAgentStart(agent: AgentRole): void;
  onAgentComplete(agent: AgentRole, findings: number): void;
  onError(stage: PipelineStage, error: Error): void;
}

class CLIProgressReporter implements PipelineObserver {
  private spinner = ora();
  onStageStart(stage: PipelineStage) { this.spinner.start(`${stage}...`); }
  onStageComplete(stage: PipelineStage, ms: number) { this.spinner.succeed(`${stage} (${ms}ms)`); }
  onAgentStart(agent: AgentRole) { this.spinner.text = `Agent: ${agent}`; }
  onAgentComplete(agent: AgentRole, n: number) { this.spinner.info(`${agent}: ${n} findings`); }
  onError(stage: PipelineStage, err: Error) { this.spinner.fail(`${stage}: ${err.message}`); }
}
```

## Pattern 5: State Machine (Pipeline)

```typescript
const VALID_TRANSITIONS: Record<PipelineStage, PipelineStage[]> = {
  ingest:   ['plan'],
  plan:     ['analyze'],
  analyze:  ['critique'],
  critique: ['score'],
  score:    ['report'],
  report:   [],  // terminal
};

class PipelineStateMachine {
  private current: PipelineStage = 'ingest';

  transition(next: PipelineStage): void {
    const allowed = VALID_TRANSITIONS[this.current];
    if (!allowed.includes(next)) {
      throw new Error(`Invalid transition: ${this.current} → ${next}`);
    }
    this.current = next;
  }

  get stage(): PipelineStage { return this.current; }
  get isComplete(): boolean { return this.current === 'report'; }
}
```

## Pattern 6: Template Method (BaseAgent)

```typescript
abstract class BaseAgent implements AnalysisAgent {
  abstract readonly role: AgentRole;

  async analyze(context: AgentContext): Promise<AgentOutput> {
    this.validateInput(context);              // Step 1: Validate
    const prompt = this.buildPrompt(context); // Step 2: Build prompt
    const raw = await this.execute(prompt);   // Step 3: Call LLM
    const parsed = this.parseResponse(raw);   // Step 4: Parse
    this.validateOutput(parsed);              // Step 5: Validate output
    return this.formatOutput(parsed);         // Step 6: Format
  }

  protected abstract buildPrompt(ctx: AgentContext): string;
  protected abstract parseResponse(raw: string): unknown;
  protected abstract formatOutput(parsed: unknown): AgentOutput;

  // Common implementations
  protected validateInput(ctx: AgentContext): void { /* shared validation */ }
  protected validateOutput(parsed: unknown): void { /* JSON schema check */ }
  protected async execute(prompt: string): Promise<string> { /* LLM call */ }
}
```

## Pattern 7: Adapter (External Library Bridges)

```typescript
// Port (Layer 2)
interface GitPort {
  clone(url: string, target: string): Promise<void>;
  getFileTree(repoPath: string): Promise<FileNode[]>;
}

// Adapter (Layer 4) — wraps simple-git
class SimpleGitAdapter implements GitPort {
  async clone(url: string, target: string): Promise<void> {
    const git = simpleGit();
    await git.clone(url, target, ['--depth', '1']);
  }

  async getFileTree(repoPath: string): Promise<FileNode[]> {
    // Recursively walk directory, build FileNode tree
    // Exclude: node_modules, .git, dist, build, __pycache__
  }
}
```

## Pattern 8: Composition Root (main.ts)

```typescript
// ALL wiring happens HERE and ONLY here
function bootstrap(config: AnalysisConfig): AnalyzeRepositoryUseCase {
  // Layer 4: Infrastructure
  const llmBase = new AnthropicLLMAdapter(config.apiKey);
  const llm = new MetricsDecorator(new LoggingDecorator(new RetryDecorator(llmBase)));
  const git = new SimpleGitAdapter();
  const tokens = new TiktokenAdapter();
  const report = new HandlebarsReportAdapter();
  const cache = new InMemoryCacheAdapter();

  // Layer 4: Agents
  const agentFactory = new AgentFactory(llm, tokens);
  const metaPrompter = new MetaPrompterAgent(llm, tokens);
  const critiqueAgent = new CritiqueAgent(llm, tokens);

  // Layer 3: Presenters
  const progress = new CLIProgressReporter();

  // Layer 2: Use Cases
  const orchestrator = new OrchestrateAgentsUseCase(agentFactory, metaPrompter, critiqueAgent, progress);
  const reportGen = new GenerateReportUseCase(report);
  const analyzer = new AnalyzeRepositoryUseCase(git, tokens, orchestrator, reportGen, progress);

  return analyzer;
}
```

## Pattern 9: Repository (FindingRepository)

```typescript
class FindingRepository {
  private findings: Finding[] = [];

  add(finding: Finding): void { this.findings.push(finding); }
  addBatch(findings: Finding[]): void { this.findings.push(...findings); }

  bySeverity(severity: Severity): Finding[] {
    return this.findings.filter(f => f.severity === severity);
  }

  byDimension(dim: Dimension): Finding[] {
    return this.findings.filter(f => f.dimension === dim);
  }

  validated(): Finding[] {
    return this.findings.filter(f => f.validated);
  }

  critical(): Finding[] {
    return this.findings.filter(f => f.severity === 'critical' && f.validated);
  }

  count(): Record<Severity, number> {
    return this.findings.reduce((acc, f) => {
      acc[f.severity] = (acc[f.severity] || 0) + 1;
      return acc;
    }, {} as Record<Severity, number>);
  }
}
```

## Pattern 10: Value Object (Self-Validating)

```typescript
class FileLocation {
  private constructor(
    readonly filePath: string,
    readonly startLine: number,
    readonly endLine: number,
  ) {}

  static create(path: string, start: number, end: number): FileLocation {
    if (!path || path.includes('..')) throw new Error('Invalid file path');
    if (start < 1 || end < start) throw new Error('Invalid line range');
    return new FileLocation(path, start, end);
  }

  toString(): string { return `${this.filePath}:${this.startLine}-${this.endLine}`; }
  equals(other: FileLocation): boolean {
    return this.filePath === other.filePath && this.startLine === other.startLine && this.endLine === other.endLine;
  }
}
```
