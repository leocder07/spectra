# State Diagram — Agent Lifecycle

## BaseAgent Template Method Lifecycle

States traced from `infrastructure/agents/base_agent.py` `run()` method.

```mermaid
stateDiagram-v2
    [*] --> created : AgentFactory.create(role)

    created --> validating_input : run(user_prompt) called

    validating_input --> building_prompt : input valid
    validating_input --> failed : ValueError (empty input)

    building_prompt --> executing_llm : prompt assembled

    executing_llm --> parsing_output : LLM response received
    executing_llm --> timed_out : asyncio.wait_for > 120s (SPEC-006)
    executing_llm --> retrying : SpectraRetryError (retryable)

    retrying --> executing_llm : attempt < max_retries
    retrying --> failed : retries exhausted (SPEC-002/003)

    parsing_output --> validating_output : JSON parsed OK
    parsing_output --> extracting_json : primary parse failed
    extracting_json --> validating_output : fallback extraction OK
    extracting_json --> failed : all extraction failed (SPEC-005)

    validating_output --> formatting_result : Pydantic validation passed
    validating_output --> failed : missing required keys (SPEC-005)

    formatting_result --> complete : AgentOutput returned

    complete --> [*]
    failed --> [*]
    timed_out --> [*]

    note right of executing_llm
        Standard agents: gateway.analyze()
        CritiqueAgent: gateway.analyze_with_thinking()
    end note

    note right of retrying
        RetryDecorator: exponential backoff
        Delays: 1s, 2s, 4s + jitter
        Max retries: 3
    end note

    note right of formatting_result
        Builds AgentOutput with:
        - findings tuple
        - tokens_used
        - duration_seconds
        - raw_response
        - dimension_score
    end note
```

## Specialist Agent — Parallel Execution Context

```mermaid
stateDiagram-v2
    [*] --> queued : created by AgentFactory

    state "Orchestrator (asyncio.gather)" as orch {
        queued --> waiting_semaphore : coroutine started
        waiting_semaphore --> executing : semaphore acquired

        state "Per-Agent Timeout (120s)" as timeout {
            executing --> validate_input
            validate_input --> build_prompt
            build_prompt --> call_llm
            call_llm --> parse_json
            parse_json --> validate_pydantic
            validate_pydantic --> format_output
        }

        executing --> timed_out : wait_for timeout
    }

    format_output --> success : AgentOutput
    timed_out --> failure : TimeoutError

    success --> [*]
    failure --> [*]

    note right of waiting_semaphore
        Semaphore(4) limits
        concurrent API calls
        to avoid 429 rate limits
    end note

    note right of timed_out
        Individual agent timeout
        does not cancel siblings
        (return_exceptions=True)
    end note
```

## CritiqueAgent — Adaptive Thinking Lifecycle

```mermaid
stateDiagram-v2
    [*] --> created : factory.create("critique")

    created --> checking_eligibility : pipeline reaches Stage 5

    checking_eligibility --> skipped : --quick flag
    checking_eligibility --> skipped : pipeline degraded (2+ failures)
    checking_eligibility --> skipped : no budget remaining
    checking_eligibility --> executing : eligible to run

    executing --> validating_input : run(findings_json)
    validating_input --> building_prompt : input valid
    building_prompt --> calling_llm : prompt with XML tags

    calling_llm --> thinking : analyze_with_thinking()
    note right of thinking
        Adaptive thinking
        thinking={type: "adaptive", display: "summarized"}
        Opus 4.7 decides reasoning depth
        effort=high · task_budget=80K · max_tokens=64K
        beta header: task-budgets-2026-03-13
        Only agent using this feature
    end note

    thinking --> parsing : response received
    parsing --> validating : JSON extracted

    validating --> applying : validated_findings + rejected_findings present
    validating --> critique_failed : SPEC-008

    applying --> filtering : reject false positive findings
    filtering --> adjusting : apply severity_adjustments
    adjusting --> insights : extract cross_cutting_insights
    insights --> complete : StageOutput returned

    critique_failed --> fallback : return unmodified findings
    fallback --> complete

    skipped --> complete : return raw findings, no insights

    complete --> [*]
```

---

*Last updated: 2026-04-29 — terminology change ("extended" → "adaptive" thinking) and Opus 4.7 settings.*
