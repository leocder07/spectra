# Spectra Domain Model — Complete Entity Reference

## Entity Relationship Diagram

```
Codebase 1──* FileNode
    │
    │ analyzed by
    ▼
AnalysisConfig 1──1 TokenBudget
    │
    │ produces
    ▼
AnalysisPlan 1──* FocusArea
    │
    │ executed by
    ▼
AgentOutput *──1 AgentRole
    │
    │ contains
    ▼
Finding *──1 Severity
Finding *──1 Dimension
Finding *──1 FileLocation
    │
    │ validated into
    ▼
ScoreCard 1──6 DimensionScore
ScoreCard 1──* Finding (validated)
    │
    │ rendered as
    ▼
Report 1──* ReportSection
Report 1──* MermaidDiagram
```

## Complete Type Definitions

```typescript
// ═══════════════════════════════════════════════
// VALUE OBJECTS (Immutable, No Identity)
// ═══════════════════════════════════════════════

type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

type Dimension = 
  | 'architecture' 
  | 'security' 
  | 'quality' 
  | 'documentation' 
  | 'maintainability' 
  | 'overall';

type PipelineStage = 
  | 'ingest' 
  | 'plan' 
  | 'analyze' 
  | 'critique' 
  | 'score' 
  | 'report';

type AgentRole = 
  | 'meta-prompter' 
  | 'architecture' 
  | 'security' 
  | 'quality' 
  | 'documentation' 
  | 'critique';

type OutputFormat = 'html' | 'json' | 'markdown';

// ═══════════════════════════════════════════════
// CORE ENTITIES
// ═══════════════════════════════════════════════

interface FileNode {
  path: string;
  name: string;
  type: 'file' | 'directory';
  extension?: string;
  size: number;           // bytes
  tokenCount?: number;    // estimated
  children?: FileNode[];  // directories only
}

interface FileLocation {
  filePath: string;
  startLine: number;
  endLine: number;
}

interface Codebase {
  name: string;
  path: string;
  remoteUrl?: string;
  language: string;       // primary language
  languages: string[];    // all detected
  framework?: string;
  fileTree: FileNode[];
  totalFiles: number;
  totalLines: number;
  tokenCount: number;
  gitInfo?: GitInfo;
}

interface GitInfo {
  branch: string;
  lastCommit: string;
  commitCount: number;
  contributors: string[];
}

interface Finding {
  id: string;                    // UUID v4
  severity: Severity;
  dimension: Dimension;
  title: string;                 // ≤100 chars
  description: string;           // ≤500 chars
  location: FileLocation;
  recommendation: string;        // actionable fix
  confidence: number;            // 0.0-1.0
  agent: AgentRole;
  validated: boolean;            // CritiqueAgent sets this
  tags: string[];
  codeSnippet?: string;          // relevant code extract
  references?: string[];         // external resources
}

interface DimensionScore {
  dimension: Dimension;
  score: number;                 // 0-100
  weight: number;                // 0.0-1.0
  grade: string;                 // A+ through F
  findings: Finding[];
  rationale: string;             // why this score
  improvements: string[];        // top 3 improvements
}

interface ScoreCard {
  dimensions: Record<Dimension, DimensionScore>;
  overall: number;               // 0-100 weighted
  grade: string;                 // A+ through F
  findings: Finding[];           // all validated findings
  summary: string;               // executive summary
  metadata: AnalysisMetadata;
}

// ═══════════════════════════════════════════════
// PIPELINE ENTITIES
// ═══════════════════════════════════════════════

interface AnalysisConfig {
  maxTokenBudget: number;        // default 800_000
  agentTimeout: number;          // ms, default 120_000
  parallelAgents: number;        // default 4
  model: string;                 // 'claude-opus-4-6'
  outputFormat: OutputFormat;
  verbose: boolean;
  skipAgents?: AgentRole[];
}

interface TokenBudget {
  total: number;
  allocated: Record<string, number>;
  used: Record<string, number>;
  remaining: number;
}

interface FocusArea {
  path: string;
  reason: string;
  priority: number;             // 1-5
  suggestedAgents: AgentRole[];
  tokenAllocation: number;
}

interface AnalysisPlan {
  focusAreas: FocusArea[];
  skipPaths: string[];
  tokenAllocation: Record<AgentRole, number>;
  estimatedDuration: number;    // seconds
  complexity: 'small' | 'medium' | 'large' | 'massive';
}

interface AgentContext {
  codebase: Codebase;
  plan: AnalysisPlan;
  config: AnalysisConfig;
  tokenBudget: number;
  previousFindings?: Finding[];  // for CritiqueAgent
}

interface AgentOutput {
  agent: AgentRole;
  findings: Finding[];
  tokensUsed: number;
  duration: number;             // ms
  status: 'success' | 'partial' | 'failed';
  error?: string;
}

interface AnalysisMetadata {
  startedAt: string;            // ISO 8601
  completedAt: string;
  duration: number;             // ms
  tokensUsed: number;
  model: string;
  version: string;              // Spectra version
  repoName: string;
  repoUrl?: string;
}

// ═══════════════════════════════════════════════
// REPORT ENTITIES
// ═══════════════════════════════════════════════

interface ReportConfig {
  title: string;
  format: OutputFormat;
  includeCodeSnippets: boolean;
  includeMermaid: boolean;
  theme: 'light' | 'dark';
}

interface ReportSection {
  dimension: Dimension;
  score: DimensionScore;
  findings: Finding[];
  mermaidDiagram?: string;
}
```

## Scoring Weights

| Dimension | Weight | Rationale |
|-----------|--------|-----------|
| Architecture | 0.25 | Foundation — everything else depends on this |
| Security | 0.25 | Non-negotiable — vulnerabilities are existential |
| Quality | 0.20 | Code health determines velocity |
| Documentation | 0.15 | Enables team scale |
| Maintainability | 0.15 | Long-term sustainability |
| **Total** | **1.00** | |

## Grade Mapping

| Score Range | Grade | Color |
|-------------|-------|-------|
| 95-100 | A+ | #22C55E |
| 90-94 | A | #22C55E |
| 85-89 | A- | #4ADE80 |
| 80-84 | B+ | #86EFAC |
| 75-79 | B | #FDE047 |
| 70-74 | B- | #FACC15 |
| 65-69 | C+ | #FB923C |
| 60-64 | C | #F97316 |
| 55-59 | C- | #EA580C |
| 50-54 | D | #EF4444 |
| 0-49 | F | #DC2626 |
