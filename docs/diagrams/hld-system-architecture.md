# High-Level System Architecture

## Clean Architecture Layers

```mermaid
graph TB
    subgraph "Layer 4 — Infrastructure"
        MAIN["main.py<br/><i>Composition Root</i>"]
        ANTHRO["AnthropicAdapter<br/><i>LLMGateway impl</i>"]
        RETRY["RetryDecorator<br/><i>Backoff 1s/2s/4s</i>"]
        LOGDEC["LoggingDecorator<br/><i>Call metrics</i>"]
        GIT["GitAdapter<br/><i>GitPython</i>"]
        TIKTOKEN["TiktokenAdapter<br/><i>Token counting</i>"]
        REPORT["ReportAdapter<br/><i>Jinja2 HTML</i>"]
        FACTORY["AgentFactory"]
        META["MetaPrompter<br/><i>Sonnet 4.5</i>"]
        SPEC_AGENTS["6 SpecialistAgents<br/><i>Opus 4.6</i>"]
        CRITIQUE["CritiqueAgent<br/><i>Opus 4.6 + Thinking</i>"]
    end

    subgraph "Layer 3 — Adapters"
        CLI["cli_controller.py<br/><i>Typer CLI</i>"]
        PROGRESS["RichProgressReporter<br/><i>Rich Console</i>"]
        PRESENTER["AnalysisPresenter<br/><i>ScoreCard display</i>"]
    end

    subgraph "Layer 2 — Use Cases"
        ANALYZE["analyze_repository<br/><i>6-stage pipeline</i>"]
        ORCH["orchestrate_agents<br/><i>asyncio.gather</i>"]
        BUDGET["manage_token_budget"]
        IFACES["interfaces.py<br/><i>Ports / Protocols</i>"]
    end

    subgraph "Layer 1 — Entities"
        MODELS["models.py<br/><i>Frozen Pydantic</i>"]
        ENUMS["enums.py<br/><i>Literal types</i>"]
        ERRORS["errors.py<br/><i>SPEC-001 to SPEC-009</i>"]
    end

    %% DI wiring (composition root)
    MAIN -->|wires| CLI
    MAIN -->|creates| FACTORY
    MAIN -->|chains| LOGDEC
    MAIN -->|creates| GIT
    MAIN -->|creates| REPORT

    %% Decorator chain
    LOGDEC -->|wraps| RETRY
    RETRY -->|wraps| ANTHRO

    %% Factory creates agents
    FACTORY -->|creates| META
    FACTORY -->|creates| SPEC_AGENTS
    FACTORY -->|creates| CRITIQUE

    %% CLI triggers pipeline
    CLI -->|invokes| ANALYZE

    %% Pipeline uses agents
    ANALYZE -->|Stage 2| META
    ANALYZE -->|Stage 3| ORCH
    ANALYZE -->|Stage 5| CRITIQUE
    ORCH -->|parallel| SPEC_AGENTS

    %% Progress reporting
    ANALYZE -.->|notifies| PROGRESS

    %% Layer 2 depends on Layer 1 only
    ANALYZE --> MODELS
    ORCH --> ENUMS
    BUDGET --> MODELS

    %% Agents use gateway through decorator chain
    META -->|LLMGateway| LOGDEC
    SPEC_AGENTS -->|LLMGateway| LOGDEC
    CRITIQUE -->|analyze_with_thinking| LOGDEC

    %% Infrastructure adapters implement ports
    GIT -.->|implements| IFACES
    ANTHRO -.->|implements| IFACES
    TIKTOKEN -.->|implements| IFACES
    REPORT -.->|implements| IFACES
    PROGRESS -.->|implements| IFACES

    style MAIN fill:#7C3AED,color:#fff
    style CLI fill:#F59E0B,color:#000
    style ANALYZE fill:#22C55E,color:#000
    style MODELS fill:#3B82F6,color:#fff
    style META fill:#F59E0B,color:#000
    style SPEC_AGENTS fill:#EF4444,color:#fff
    style CRITIQUE fill:#EF4444,color:#fff
    style LOGDEC fill:#A78BFA,color:#000
    style RETRY fill:#A78BFA,color:#000
    style ANTHRO fill:#A78BFA,color:#000
```

## Decorator Chain (LLMGateway)

```mermaid
graph LR
    AGENT["Agent.execute_llm()"] --> LOG["LoggingDecorator<br/><i>timing + metrics</i>"]
    LOG --> RET["RetryDecorator<br/><i>backoff 1s/2s/4s</i>"]
    RET --> API["AnthropicAdapter<br/><i>HTTP to Anthropic</i>"]
    API --> CLAUDE["Claude API"]

    style AGENT fill:#22C55E,color:#000
    style LOG fill:#A78BFA,color:#000
    style RET fill:#A78BFA,color:#000
    style API fill:#7C3AED,color:#fff
    style CLAUDE fill:#3B82F6,color:#fff
```

## 6-Stage Pipeline Overview

```mermaid
graph LR
    S1["1. INGEST<br/><i>Git clone + file tree</i>"]
    S2["2. PLAN<br/><i>MetaPrompter</i><br/><i>Sonnet 4.5</i>"]
    S3["3. ANALYZE<br/><i>6 Specialists</i><br/><i>asyncio.gather</i>"]
    S4["4. MERGE<br/><i>Deduplicate +</i><br/><i>validate paths</i>"]
    S5["5. CRITIQUE<br/><i>CritiqueAgent</i><br/><i>Opus 4.6 + Thinking</i>"]
    S6["6. REPORT<br/><i>Jinja2 HTML /</i><br/><i>JSON / SARIF</i>"]

    S1 --> S2 --> S3 --> S4 --> S5 --> S6

    style S1 fill:#3B82F6,color:#fff
    style S2 fill:#F59E0B,color:#000
    style S3 fill:#EF4444,color:#fff
    style S4 fill:#22C55E,color:#000
    style S5 fill:#7C3AED,color:#fff
    style S6 fill:#A78BFA,color:#000
```

## 8 Agents — Model Assignment

```mermaid
graph TB
    subgraph "Planning"
        MP["MetaPrompter<br/>claude-sonnet-4-5<br/><i>File tree only, 5K tokens</i>"]
    end

    subgraph "6 Parallel Specialists — asyncio.gather"
        ARCH["ArchitectureAgent<br/>claude-opus-4-6"]
        SEC["SecurityAgent<br/>claude-opus-4-6"]
        QUAL["QualityAgent<br/>claude-opus-4-6"]
        DOC["DocumentationAgent<br/>claude-opus-4-6"]
        DEP["DependencyAgent<br/>claude-opus-4-6"]
        PERF["PerformanceAgent<br/>claude-opus-4-6"]
    end

    subgraph "Validation"
        CR["CritiqueAgent<br/>claude-opus-4-6<br/><i>Adaptive thinking</i>"]
    end

    MP --> ARCH
    MP --> SEC
    MP --> QUAL
    MP --> DOC
    MP --> DEP
    MP --> PERF

    ARCH --> CR
    SEC --> CR
    QUAL --> CR
    DOC --> CR
    DEP --> CR
    PERF --> CR

    style MP fill:#F59E0B,color:#000
    style ARCH fill:#EF4444,color:#fff
    style SEC fill:#EF4444,color:#fff
    style QUAL fill:#EF4444,color:#fff
    style DOC fill:#EF4444,color:#fff
    style DEP fill:#EF4444,color:#fff
    style PERF fill:#EF4444,color:#fff
    style CR fill:#7C3AED,color:#fff
```

## ScoreCard Weights

| Dimension | Weight | Agent | Model |
|-----------|--------|-------|-------|
| Architecture | 25% | ArchitectureAgent | Opus 4.6 |
| Security | 25% | SecurityAgent | Opus 4.6 |
| Quality | 20% | QualityAgent | Opus 4.6 |
| Documentation | 10% | DocumentationAgent | Opus 4.6 |
| Maintainability | 10% | DependencyAgent | Opus 4.6 |
| Performance | 10% | PerformanceAgent | Opus 4.6 |
