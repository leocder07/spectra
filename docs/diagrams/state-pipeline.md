# State Diagram — Pipeline Lifecycle

## Pipeline State Machine

States sourced from `entities/enums.py` `PipelineState` literal type.

```mermaid
stateDiagram-v2
    [*] --> pending : CLI invoked

    pending --> ingesting : clone starts

    ingesting --> meta_prompting : file tree ready
    ingesting --> failed : SPEC-001 Git clone failed

    meta_prompting --> analyzing : plan ready + budgets allocated
    meta_prompting --> failed : SPEC-005 plan validation failed

    analyzing --> merging : 0-1 agent failures
    analyzing --> degraded : 2+ agent failures (SPEC-007)

    merging --> critiquing : budget remaining + not --quick
    merging --> reporting : --quick or no budget left

    degraded --> reporting : skip critique, partial report

    critiquing --> reporting : critique complete
    critiquing --> reporting : SPEC-008 critique failed (use raw findings)

    reporting --> complete : report rendered
    reporting --> failed : SPEC-009 render failed

    complete --> [*]
    failed --> [*]
    degraded --> [*]

    state ingesting {
        [*] --> cloning
        cloning --> validating_size
        validating_size --> extracting_tree
        extracting_tree --> reading_sources
        reading_sources --> [*]
    }

    state analyzing {
        [*] --> building_prompts
        building_prompts --> parallel_execution
        parallel_execution --> evaluating_results
        evaluating_results --> [*]
        note right of parallel_execution
            asyncio.gather with
            Semaphore(4) + wait_for(120s)
            6 specialists in parallel
        end note
    }

    state merging {
        [*] --> collecting_findings
        collecting_findings --> deduplicating
        deduplicating --> validating_paths
        validating_paths --> [*]
        note right of validating_paths
            Removes hallucinated
            file paths not in tree
        end note
    }

    state critiquing {
        [*] --> checking_budget
        checking_budget --> executing_critique
        executing_critique --> applying_rejections
        applying_rejections --> adjusting_severity
        adjusting_severity --> extracting_insights
        extracting_insights --> [*]
    }
```

## Error Code to State Mapping

| Error Code | Trigger State | Transition | Retryable |
|------------|---------------|------------|-----------|
| SPEC-001 | ingesting | failed | Yes (2x) |
| SPEC-002 | analyzing | (retry in decorator) | Yes (3x) |
| SPEC-003 | analyzing | (retry in decorator) | Yes (3x) |
| SPEC-004 | merging | skip critique | No |
| SPEC-005 | meta_prompting / analyzing | failed / count failure | Yes (1x) |
| SPEC-006 | analyzing | count failure | No |
| SPEC-007 | analyzing | degraded | No |
| SPEC-008 | critiquing | reporting (fallback) | No |
| SPEC-009 | reporting | failed | No |
