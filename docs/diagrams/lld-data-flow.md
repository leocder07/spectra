# LLD: Data Flow Diagram

Data transformations at each pipeline stage, traced from source code.

```mermaid
flowchart TD
    subgraph "Stage 1: INGEST"
        REQ["AnalysisRequest<br/>{repo_url, quick, output_format}"]
        REQ --> CLONE["git.clone(repo_url, clone_dir)"]
        CLONE --> TREE["git.get_file_tree(clone_dir)<br/>-> list[str]"]
        TREE --> READ["_read_key_source_files()<br/>-> dict[str, str] (up to 20 files, 100K tokens)"]
        READ --> CB["Codebase<br/>{repo_url, repo_name, local_path, file_tree}"]
    end

    subgraph "Stage 2: PLAN"
        CB --> MP_IN["MetaPrompter.run(file_tree_text)<br/><i>Sonnet 4.5, file tree ONLY, &le;5K tokens</i>"]
        MP_IN --> MP_OUT["AgentOutput<br/>{agent_role='meta_prompter', findings=(), raw_response}"]
        MP_OUT --> PLAN["Parsed Plan JSON<br/>{repo_language, focus_areas[], token_allocation{}}"]
        PLAN --> ALLOC["allocate_specialist_budgets()<br/>-> dict[Dimension, int]"]
        PLAN --> FILES["_extract_agent_files()<br/>-> dict[AgentRole, set[str]]"]
    end

    subgraph "Stage 3: ANALYZE"
        FILES --> PROMPTS["_build_specialist_prompts()<br/>filtered_tree + plan_context + source_code"]
        PROMPTS --> PAR{{"asyncio.gather(*6 agents)<br/>Semaphore(4), timeout=120s"}}
        PAR --> R1["AgentOutput (architecture)"]
        PAR --> R2["AgentOutput (security)"]
        PAR --> R3["AgentOutput (quality)"]
        PAR --> R4["AgentOutput (documentation)"]
        PAR --> R5["AgentOutput (dependency)"]
        PAR --> R6["AgentOutput (performance)"]
    end

    subgraph "Stage 4: MERGE"
        R1 & R2 & R3 & R4 & R5 & R6 --> EVAL["evaluate_results()<br/>-> successes[], failed_roles[], PipelineState"]
        EVAL --> MERGE["_merge_findings(successes)<br/>dict.fromkeys dedup via Finding.__hash__"]
        MERGE --> VALIDATE["_validate_finding_paths(findings, file_tree)<br/>removes hallucinated paths"]
        VALIDATE --> FINDINGS["tuple[Finding, ...]<br/>deduplicated, path-validated"]
    end

    subgraph "Stage 5: CRITIQUE"
        FINDINGS --> CRIT_CHECK{"_should_run_critique?<br/>!quick && !degraded<br/>&& remaining_tokens > 0"}
        CRIT_CHECK -->|"yes"| CRIT_IN["CritiqueAgent.run(findings_json)<br/><i>Opus 4.6, adaptive thinking</i>"]
        CRIT_CHECK -->|"no"| SKIP["Pass findings through unchanged"]
        CRIT_IN --> CRIT_OUT["Critique JSON<br/>{validated[], rejected[], severity_adjustments[], cross_cutting_insights[]}"]
        CRIT_OUT --> APPLY["_apply_critique()<br/>_reject_findings() + _apply_severity_adjustments()"]
        APPLY --> FILTERED["tuple[Finding, ...] + tuple[str, ...] insights"]
    end

    subgraph "Stage 6: REPORT"
        FILTERED --> SCORE["_compute_scorecard()<br/>penalty + LLM blend (40/60)"]
        SCORE --> SC["ScoreCard<br/>{overall_score, overall_grade, dimensions[], total_findings}"]
        SC --> REPORT["AnalysisReport<br/>{repo_url, repo_name, score_card, findings,<br/>duration, tokens, cost, agents_used, ...}"]
        REPORT --> FMT{"output_format?"}
        FMT -->|"html"| HTML["ReportAdapter.render()<br/>Jinja2 -> report.html"]
        FMT -->|"json"| JSON["json.dumps(report.model_dump())"]
        FMT -->|"sarif"| SARIF["_build_sarif(report)<br/>SARIF v2.1.0"]
    end

    style REQ fill:#7C3AED,color:#fff
    style CB fill:#7C3AED,color:#fff
    style MP_OUT fill:#F59E0B,color:#000
    style FINDINGS fill:#22C55E,color:#000
    style SC fill:#22C55E,color:#000
    style REPORT fill:#22C55E,color:#000
    style PAR fill:#F59E0B,color:#000
    style CRIT_IN fill:#EF4444,color:#fff
```

## Data Type Transformation Summary

| Stage | Input | Output | Key Transform |
|-------|-------|--------|---------------|
| INGEST | `repo_url: str` | `Codebase` | Git clone + file tree extraction + heuristic source read |
| PLAN | `Codebase.file_tree` (text) | `AgentOutput` (plan JSON) | MetaPrompter identifies focus areas + token allocations |
| ANALYZE | Per-agent prompts (tree + plan + source) | `list[AgentOutput]` (6x) | 6 parallel LLM calls, each returns `tuple[Finding, ...]` |
| MERGE | `list[AgentOutput]` | `tuple[Finding, ...]` | Dedup via `Finding.__hash__` + path validation vs file_tree |
| CRITIQUE | `findings_json: str` | Filtered `tuple[Finding, ...]` | Reject false positives, adjust severities, extract insights |
| REPORT | `tuple[Finding, ...]` | `AnalysisReport` | Compute ScoreCard (penalty + LLM blend), render HTML/JSON/SARIF |

## Finding Deduplication

Two `Finding` objects are equal when they share `(file_path, line_start, dimension)`. This is enforced by `Finding.__hash__` and `Finding.__eq__`. Deduplication uses `dict.fromkeys()` for O(n) single-pass with insertion-order preservation.

## Score Computation

```
penalty_score = 100 - min(sum(PENALTY[severity] * confidence for each finding), 55)
blended_score = 0.4 * llm_score + 0.6 * penalty_score   (when LLM score available)
overall_score = sum(dimension_score * normalized_weight)
```
