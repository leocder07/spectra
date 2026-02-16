# LLD: Component Interaction Diagram

How `main.py` wires the dependency injection chain and how agents are created.

```mermaid
graph TB
    subgraph "Composition Root (main.py)"
        direction TB
        API_KEY["os.environ[ANTHROPIC_API_KEY]"]
        AA["AnthropicAdapter<br/><i>api_key, httpx pool (10 conns)</i>"]
        RD["RetryDecorator<br/><i>max_retries=3, backoff=1s/2s/4s</i>"]
        LD["LoggingDecorator<br/><i>observer=RichProgressReporter</i>"]
        AF["AgentFactory<br/><i>gateway=LoggingDecorator</i>"]

        API_KEY -->|"api_key"| AA
        AA -->|"inner"| RD
        RD -->|"inner"| LD
        LD -->|"gateway"| AF
    end

    subgraph "LLMGateway Protocol"
        direction LR
        AN["analyze(system_prompt, user_prompt, model, max_tokens) -> str"]
        AT["analyze_with_thinking(...) -> str"]
    end

    AA -.->|"implements"| AN
    RD -.->|"implements"| AN
    LD -.->|"implements"| AN
    AA -.->|"implements"| AT
    RD -.->|"implements"| AT
    LD -.->|"implements"| AT

    subgraph "Agent Factory Output"
        direction TB
        MP["MetaPrompter<br/><i>Sonnet 4.5, 5K tokens</i>"]
        S1["SpecialistAgent<br/><i>architecture, Opus 4.6</i>"]
        S2["SpecialistAgent<br/><i>security, Opus 4.6</i>"]
        S3["SpecialistAgent<br/><i>quality, Opus 4.6</i>"]
        S4["SpecialistAgent<br/><i>documentation, Opus 4.6</i>"]
        S5["SpecialistAgent<br/><i>dependency, Opus 4.6</i>"]
        S6["SpecialistAgent<br/><i>performance, Opus 4.6</i>"]
        CA["CritiqueAgent<br/><i>Opus 4.6, adaptive thinking</i>"]
    end

    AF -->|"create('meta_prompter')"| MP
    AF -->|"create_specialists()"| S1
    AF -->|"create_specialists()"| S2
    AF -->|"create_specialists()"| S3
    AF -->|"create_specialists()"| S4
    AF -->|"create_specialists()"| S5
    AF -->|"create_specialists()"| S6
    AF -->|"create('critique')"| CA

    subgraph "Infrastructure Adapters"
        GA["GitAdapter<br/><i>implements GitPort</i>"]
        RA["ReportAdapter<br/><i>implements ReportPort, Jinja2</i>"]
        TA["TiktokenAdapter<br/><i>implements TokenPort</i>"]
        RP["RichProgressReporter<br/><i>implements ProgressObserver</i>"]
    end

    subgraph "Decorator Chain Call Flow"
        direction LR
        CALL["Agent.execute_llm()"] --> LD2["LoggingDecorator<br/>logs model + duration"]
        LD2 --> RD2["RetryDecorator<br/>retries on SPEC-002/003"]
        RD2 --> AA2["AnthropicAdapter<br/>streaming HTTP call"]
        AA2 --> ANTHROPIC["Anthropic API"]
    end

    style AA fill:#7C3AED,color:#fff
    style RD fill:#7C3AED,color:#fff
    style LD fill:#7C3AED,color:#fff
    style MP fill:#F59E0B,color:#000
    style CA fill:#EF4444,color:#fff
    style S1 fill:#22C55E,color:#000
    style S2 fill:#22C55E,color:#000
    style S3 fill:#22C55E,color:#000
    style S4 fill:#22C55E,color:#000
    style S5 fill:#22C55E,color:#000
    style S6 fill:#22C55E,color:#000
```

## Decorator Chain Detail

The chain wraps innermost-to-outermost. Each layer satisfies the `LLMGateway` Protocol via structural subtyping:

| Layer | Class | Responsibility |
|-------|-------|----------------|
| Innermost | `AnthropicAdapter` | Raw HTTP streaming, connection pooling (10 conns), error mapping |
| Middle | `RetryDecorator` | Exponential backoff (1s/2s/4s + jitter), max 3 retries for SPEC-002/003 |
| Outermost | `LoggingDecorator` | Logs model, duration, token count to `ProgressObserver` |

## Agent Factory Dispatch

```mermaid
graph LR
    ROLE["AgentRole"] --> |"meta_prompter"| MP["MetaPrompter(gateway)"]
    ROLE --> |"critique"| CA["CritiqueAgent(gateway)"]
    ROLE --> |"architecture/security/..."| SC["SPECIALIST_CONFIGS[role]"]
    SC --> SA["SpecialistAgent(role, gateway, dimension, id_prefix, system_prompt, model)"]
```

The factory holds a single reference to the decorated `LLMGateway`. All 8 agents share this gateway instance.
