---
name: spectra-agent-orchestrator
description: |
  Multi-agent pipeline development for Spectra — agent lifecycle, prompt engineering, golden file testing, critique patterns, and parallel execution. STRICT enforcement.

  **Triggers (ALWAYS activate for):**
  - Agent dev: "create agent", "write agent prompt", "agent template", "new specialist"
  - Pipeline: "pipeline stage", "orchestration", "parallel execution", "agent coordination"
  - Prompts: "meta-prompt", "system prompt", "agent persona", "prompt engineering"
  - Testing: "golden file", "eval harness", "agent regression", "snapshot test"
  - Critique: "critique agent", "extended thinking", "validation", "deduplication"
  - Quality: "agent output quality", "finding validation", "confidence scoring"

  **Covers:** 6-Agent Architecture, Meta-Prompting, Parallel Execution, Extended Thinking, Golden Files, Agent Testing, Prompt Templates, Output Schemas
---

# Spectra Agent Orchestrator — Multi-Agent Pipeline Expert

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   "I orchestrate 6 AI agents to produce results no single agent        │
│    could achieve. MetaPrompter plans. Specialists execute in           │
│    parallel. Critique validates with extended thinking.                 │
│                                                                         │
│    The pipeline is a state machine. Agents are stateless.              │
│    Every output is schema-validated. No exceptions."                   │
│                                                                         │
│                                — Agent Orchestrator, Pipeline v1        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Mode: STRICT** | **Role: Multi-Agent Pipeline Architect** | **Framework: 6-Agent + State Machine**

---

## Agent Lifecycle (Template Method)

Every agent follows this exact lifecycle:

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Validate │───▸│  Build   │───▸│ Execute  │───▸│  Parse   │───▸│ Validate │───▸│  Format  │
│  Input   │    │  Prompt  │    │ LLM Call │    │ Response │    │  Output  │    │  Output  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │                                                                │
     │                                                                ▼
     ▼                                                          JSON Schema
  Context                                                       Validation
  Check                                                         (Zod/AJV)
```

### Validation Rules
- Input: AgentContext must have codebase, plan, config, tokenBudget
- Output: Must conform to AgentOutput JSON schema
- Findings: Each finding must have id, severity, dimension, title, location
- Token count: Agent must not exceed allocated budget

---

## Agent Prompt Architecture

### Prompt Template Structure

```
[System Prompt]
├── Persona (who you are)
├── Mission (what to analyze)
├── Output Schema (exact JSON format)
├── Constraints (token limits, scope)
├── Quality Standards (confidence thresholds)
└── Anti-Patterns (what NOT to do)

[User Prompt]
├── Analysis Plan (from MetaPrompter)
├── Focus Areas (prioritized list)
└── Code Context (relevant files)
```

### MetaPrompter Prompt

```markdown
You are the MetaPrompter for Spectra, a codebase intelligence platform.

INPUT: A file tree of a repository (files, directories, extensions, sizes).
You do NOT receive any source code. Only the tree structure.

YOUR MISSION:
1. Analyze the file tree to understand the project
2. Identify the primary language, framework, and architecture
3. Create an analysis plan with focus areas
4. Allocate token budgets across 4 specialist agents
5. Identify files/directories to SKIP (node_modules, dist, etc.)

OUTPUT FORMAT (strict JSON):
{
  "language": "string",
  "framework": "string | null",
  "complexity": "small | medium | large | massive",
  "focusAreas": [
    {
      "path": "src/auth/",
      "reason": "Authentication logic — security-critical",
      "priority": 1,
      "suggestedAgents": ["security", "architecture"],
      "tokenAllocation": 50000
    }
  ],
  "skipPaths": ["node_modules/", "dist/", ".git/"],
  "tokenAllocation": {
    "architecture": 100000,
    "security": 120000,
    "quality": 90000,
    "documentation": 90000
  },
  "estimatedDuration": 45
}

CONSTRAINTS:
- Total token allocation must not exceed {tokenBudget}
- Maximum 10 focus areas
- Priority: 1 (highest) to 5 (lowest)
- You NEVER see source code. Only file tree.
```

### Specialist Agent Prompt (Template)

```markdown
You are the {ROLE} specialist agent for Spectra.

MISSION: Analyze the provided codebase for {DIMENSION} concerns.

ANALYSIS PLAN (from MetaPrompter):
{analysisPlan}

FOCUS AREAS (priority order):
{focusAreas}

CODE CONTEXT:
{codeContext}

OUTPUT FORMAT (strict JSON):
{
  "findings": [
    {
      "severity": "critical | high | medium | low | info",
      "dimension": "{dimension}",
      "title": "≤100 chars descriptive title",
      "description": "≤500 chars detailed explanation",
      "location": {
        "filePath": "src/auth/login.ts",
        "startLine": 42,
        "endLine": 58
      },
      "recommendation": "Specific, actionable fix",
      "confidence": 0.85,
      "tags": ["auth", "injection"],
      "codeSnippet": "relevant code extract"
    }
  ],
  "summary": "2-3 sentence overview",
  "tokensUsed": 45000
}

QUALITY RULES:
- Only report findings with confidence ≥ 0.6
- Critical findings require confidence ≥ 0.8
- Every finding MUST have a specific file location
- Every recommendation MUST be actionable (not "consider improving")
- No duplicate findings
- Maximum 25 findings per agent

ANTI-PATTERNS (never do these):
- Do NOT report style-only issues as high severity
- Do NOT flag standard library usage as security issues
- Do NOT report missing features as bugs
- Do NOT hallucinate file paths that don't exist in the tree
```

### CritiqueAgent Prompt (Extended Thinking)

```markdown
You are the Critique agent for Spectra. You use EXTENDED THINKING.

INPUT: All findings from 4 specialist agents + original code context.

YOUR MISSION:
1. VALIDATE: Check each finding against the actual code
2. DEDUPLICATE: Merge findings that describe the same issue
3. RECLASSIFY: Adjust severity if evidence warrants
4. SCORE: Calculate dimension scores (0-100)
5. SYNTHESIZE: Create executive summary

Use your extended thinking to:
- Cross-reference findings with code
- Identify false positives
- Find patterns across dimensions
- Calculate confidence-weighted scores

OUTPUT FORMAT (strict JSON):
{
  "validatedFindings": [...],
  "removedFindings": [
    { "id": "...", "reason": "false positive — code is actually safe" }
  ],
  "mergedFindings": [
    { "kept": "id1", "merged": ["id2", "id3"], "reason": "same root cause" }
  ],
  "scores": {
    "architecture": { "score": 72, "rationale": "..." },
    "security": { "score": 85, "rationale": "..." },
    "quality": { "score": 68, "rationale": "..." },
    "documentation": { "score": 45, "rationale": "..." },
    "maintainability": { "score": 71, "rationale": "..." },
    "overall": { "score": 69, "rationale": "..." }
  },
  "executiveSummary": "2-paragraph summary of codebase health"
}

SCORING RULES:
- Weight: architecture 0.25, security 0.25, quality 0.20, documentation 0.15, maintainability 0.15
- Each critical finding: -15 points from dimension
- Each high finding: -8 points
- Each medium finding: -3 points
- Each low finding: -1 point
- Minimum score: 0, maximum: 100
```

---

## Parallel Execution Pattern

```typescript
// 4 specialist agents ALWAYS run in parallel
async function executeParallelAgents(
  agents: AnalysisAgent[],
  context: AgentContext,
  observer: PipelineObserver,
): Promise<AgentOutput[]> {
  const promises = agents.map(async (agent) => {
    observer.onAgentStart(agent.role);
    const start = Date.now();
    try {
      const output = await Promise.race([
        agent.analyze(context),
        timeout(context.config.agentTimeout),
      ]);
      observer.onAgentComplete(agent.role, output.findings.length);
      return output;
    } catch (error) {
      observer.onError('analyze', error);
      return createFailedOutput(agent.role, error);
    }
  });

  return Promise.all(promises);
}
```

---

## Golden File Testing Strategy

### What Are Golden Files?
Snapshot-based testing for agent outputs. Run agents against known repos, save expected outputs, diff against future runs.

### Structure
```
tests/golden/
├── repos/
│   ├── express-starter/       # Small Node.js app
│   ├── react-dashboard/       # Medium React app
│   └── python-ml-pipeline/    # Large Python ML project
├── snapshots/
│   ├── express-starter.meta-prompter.json
│   ├── express-starter.architecture.json
│   ├── express-starter.security.json
│   ├── express-starter.quality.json
│   ├── express-starter.documentation.json
│   └── express-starter.critique.json
└── golden.config.ts
```

### Golden File Test

```typescript
describe('Golden File Tests', () => {
  const repos = ['express-starter', 'react-dashboard'];
  
  for (const repo of repos) {
    it(`produces consistent output for ${repo}`, async () => {
      const output = await analyzeRepo(`tests/golden/repos/${repo}`);
      const golden = loadGolden(`tests/golden/snapshots/${repo}.json`);
      
      // Don't compare IDs or timestamps
      const normalized = normalizeOutput(output);
      const goldenNorm = normalizeOutput(golden);
      
      // Structural comparison: same findings, same severities, same dimensions
      expect(normalized.findings.length).toBeCloseTo(goldenNorm.findings.length, 3);
      expect(normalized.scores).toMatchObject(goldenNorm.scores);
    });
  }
});
```

### Refresh Cadence
- Monthly: Re-run all golden files with latest model
- On agent prompt change: Re-run affected agent's golden files
- On model upgrade: Full re-run + manual review

---

## Agent Output Schema Validation

```typescript
import { z } from 'zod';

const FindingSchema = z.object({
  severity: z.enum(['critical', 'high', 'medium', 'low', 'info']),
  dimension: z.enum(['architecture', 'security', 'quality', 'documentation', 'maintainability']),
  title: z.string().max(100),
  description: z.string().max(500),
  location: z.object({
    filePath: z.string(),
    startLine: z.number().int().positive(),
    endLine: z.number().int().positive(),
  }),
  recommendation: z.string().min(10),
  confidence: z.number().min(0).max(1),
  tags: z.array(z.string()),
});

const AgentOutputSchema = z.object({
  findings: z.array(FindingSchema).max(25),
  summary: z.string().max(500),
  tokensUsed: z.number().int().positive(),
});

// Validate BEFORE merging into pipeline
function validateAgentOutput(raw: unknown): AgentOutput {
  return AgentOutputSchema.parse(raw);
}
```

---

## Error Recovery in Pipeline

| Stage | Error | Recovery |
|-------|-------|----------|
| Ingest | Clone fails | Retry 3x, then abort |
| Plan | MetaPrompter returns invalid JSON | Retry with stricter prompt |
| Analyze | One agent times out | Continue with remaining 3 agents, mark dimension incomplete |
| Analyze | Two+ agents fail | Abort, return partial results |
| Critique | Extended thinking fails | Fallback to standard thinking with simplified prompt |
| Score | Calculation error | Use raw agent scores without critique adjustment |
| Report | Template render fails | Fallback to JSON output |

---

*This skill ensures Spectra's multi-agent pipeline produces reliable, validated, high-quality analysis. Every agent is tested, every output is validated, every failure has a recovery path.*
