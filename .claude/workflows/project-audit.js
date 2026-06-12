export const meta = {
  name: 'project-audit',
  description: 'Full project audit — engineering status + consulting-grade business lenses + SOTA agentic-architecture research, each finding adversarially red-teamed and demand-gated',
  whenToUse: 'When you want a complete, evidence-backed picture of where a software project actually stands — what shipped vs planned, code/git/release health, product/PMF/GTM/market/moat reality, and a sequenced agentic-architecture roadmap. Pass args to scope it.',
  phases: [
    { title: 'Engineering', detail: 'roadmap, code health, git hygiene, issues, docs' },
    { title: 'Business', detail: 'product, PMF, GTM, market, moat (web research)' },
    { title: 'Architecture', detail: 'memory, context, security, controls, agent expansion (web research)' },
    { title: 'RedTeam', detail: 'adversarial verification of every load-bearing claim' },
    { title: 'Synthesize', detail: 'one prioritized, demand-gated action list' },
  ],
}

// ---------------------------------------------------------------------------
// Reusable project-audit workflow.
//
// Invoke:
//   Workflow({ name: 'project-audit' })                       // full audit of cwd
//   Workflow({ name: 'project-audit', args: { mode: 'status' } })   // engineering only
//   Workflow({ name: 'project-audit', args: { mode: 'strategy' } }) // business only
//   Workflow({ name: 'project-audit', args: {
//     repo: '/abs/path', mode: 'full',
//     context: 'One paragraph the agents must treat as ground truth: what the
//               product is, current version, known traction, any hard constraint
//               (e.g. a freeze verdict). Cite-everything discipline applies.',
//   }})
//
// mode ∈ 'full' (default) | 'status' | 'strategy' | 'architecture'
// Every external claim must carry a URL/date; every repo claim a path/line.
// The demand gate below is the spine: recommendations are sequenced by the
// signal that unlocks them, never dumped as an undifferentiated backlog.
// ---------------------------------------------------------------------------

const REPO = (args && args.repo) || '.'
const MODE = (args && args.mode) || 'full'
const EXTRA = (args && args.context) || ''

const GROUND = `TARGET PROJECT: ${REPO} (READ-ONLY — change nothing; run read-only git/gh/test commands only).
${EXTRA ? `\nGROUND TRUTH (treat as given): ${EXTRA}\n` : ''}
DISCIPLINE: Cite every external/market claim with a URL + date. Cite every repo claim with a file path/line or command output. Distinguish verified fact from estimate. Prefer 2024-2026 sources. Return raw structured data per the schema — not prose for a human. Where a recommendation implies building, tag it with the demand signal that should gate it (e.g. "now / hygiene", "post-demand-test", "N paying users"); never recommend speculative engineering ahead of evidence.`

// ---- shared schemas -------------------------------------------------------

const AREA_SCHEMA = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    facts: { type: 'array', items: { type: 'string' } },
    risks: { type: 'array', items: { type: 'string' } },
    next_actions: { type: 'array', items: { type: 'string' } },
  },
  required: ['summary', 'facts', 'risks', 'next_actions'],
}

const LENS_SCHEMA = {
  type: 'object',
  properties: {
    frameworks_applied: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
    findings: { type: 'array', items: { type: 'object', properties: {
      title: { type: 'string' }, detail: { type: 'string' }, evidence: { type: 'string' },
      severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'positive'] },
    }, required: ['title', 'detail', 'evidence', 'severity'] } },
    score_0_10: { type: 'number' },
    recommendations: { type: 'array', items: { type: 'string' } },
  },
  required: ['frameworks_applied', 'summary', 'findings', 'score_0_10', 'recommendations'],
}

// ---- phase builders -------------------------------------------------------

async function engineering() {
  phase('Engineering')
  const AREAS = [
    { key: 'roadmap', p: `Audit roadmap progress for ${REPO}. Read any docs/strategy/*plan*, the top of CHANGELOG.md, and the ADR index. Determine which planned capabilities are SHIPPED (cite version/PR/commit + the code file that proves it), IN PROGRESS (cite the partial), and NOT STARTED (cite the absence — grep that returns nothing). State where the project sits vs its own planned sequencing and cadence.` },
    { key: 'code-health', p: `Audit code health for ${REPO} (do not modify). Run the project's own lint, type-check, and test commands (read CONTRIBUTING/CLAUDE.md/pyproject/package.json for them). Report exact pass/fail/error/skip counts, wall time, and the tool versions. Quote the first few real failures verbatim. If the suite can't run, say why and fall back to collect-only.` },
    { key: 'git-hygiene', p: `Audit git/branch/release hygiene for ${REPO} (read-only; never checkout/delete). Latest tag vs published package version; open PR state; recently merged PRs; working-tree cleanliness; stale local+remote branches (cross-ref merged-PR head refs, since squash-merges defeat ancestry). Flag dead long-lived branches.` },
    { key: 'issues-backlog', p: `Audit the issue/PR backlog for ${REPO} via gh. Open/closed issue counts, who files them (author vs strangers — a key traction signal), labels/milestones, repo vitals (stars/forks/pushed_at). Summarize backlog shape and anything urgent.` },
    { key: 'docs-release', p: `Audit docs & release-facing state for ${REPO}. Does the README claim the current version/feature set, or carry stale numbers (test counts, costs, timing, competitor tables)? Are ADR statuses consistent with shipped reality? Do error-code/glossary references cover the real range? TODO/FIXME density in src/. List every internal contradiction with file:line.` },
  ]
  return (await parallel(AREAS.map(a => () =>
    agent(`${GROUND}\n\nROLE: senior engineer doing a ${a.key} audit.\n${a.p}`, { label: `eng:${a.key}`, phase: 'Engineering', schema: AREA_SCHEMA })
      .then(r => ({ area: a.key, ...r })))) ).filter(Boolean)
}

async function business() {
  phase('Business')
  const LENSES = [
    { key: 'product', who: 'Chief Product Officer (devtools)', fw: 'Jobs-to-be-Done, Kano, April Dunford positioning, feature-parity scan vs current competitors (web-verify their June-2026 feature sets)', q: 'Is this a product or a portfolio artifact? What is the smallest change that makes it obviously a product? Is the ICP clear and is the wedge real?' },
    { key: 'pmf', who: 'Seed VC + Superhuman-school PMF operator', fw: 'Sean Ellis behavioral proxies, Superhuman PMF engine, traction forensics (decompose stars/downloads by provenance), built-it vs want-it bucketing', q: 'Pre-PMF, PMF-curious, or PMF? Pull hard numbers (gh api stars/forks/issues-by-strangers, pypistats/npm downloads, HN/X/Reddit footprint). What single 2-week experiment most cheaply tests demand?' },
    { key: 'gtm', who: 'PLG growth lead (ex-Vercel/Datadog)', fw: 'PLG + bowtie funnel, channel-fit mapping, time-to-wow, LTV:CAC sanity, competitor GTM contrast', q: 'Audit distribution surfaces (marketplace listing? website? working install path? telemetry to measure a funnel?). What are the 3 highest-leverage GTM moves on a solo time budget?' },
    { key: 'market', who: 'McKinsey/BCG engagement manager', fw: 'TAM/SAM/SOM (triangulate analyst numbers AND rebuild bottom-up), Porter Five Forces, 3 Horizons, competitive map with funding/pricing/traction (web research heavy)', q: 'Is this a distinct category or a feature of an adjacent one? Where is the white space? Size the actual wedge bottom-up, not just top-down.' },
    { key: 'moat', who: 'Strategy partner (Playing-to-Win / Helmer 7 Powers)', fw: 'Helmer 7 Powers (benefit AND barrier per power), Lafley/Martin Where-to-Play/How-to-Win, WWHTBT per strategic option, OSS-commercialization patterns, unit-economics validation at current model pricing', q: 'Which of the 7 Powers does it hold or could build? Where to play, how to win, what to STOP doing? Is the unit-economics story current?' },
  ]
  return (await parallel(LENSES.map(l => () =>
    agent(`${GROUND}\n\nPERSONA: ${l.who}.\nApply: ${l.fw}.\nAnswer: ${l.q}\nUse WebSearch/WebFetch for any market/competitor/traction claim and cite URLs.`, { label: `biz:${l.key}`, phase: 'Business', schema: LENS_SCHEMA })
      .then(r => ({ lens: l.key, ...r })))) ).filter(Boolean)
}

async function architecture() {
  phase('Architecture')
  // SOTA agentic-system research dimensions — added 2026-06 after the
  // memory/context/security/controls/agent-expansion deep dive.
  const DIMS = [
    { key: 'agentic-memory', who: 'agentic-memory researcher', fw: 'episodic/semantic/procedural/working memory taxonomy; MemGPT/Letta, Anthropic Memory Tool, Mem0, Zep/Graphiti, LangMem; FTS vs vector vs hybrid vs KG retrieval; consolidation/decay/conflict-resolution', q: 'How should the system store, score, and surface cross-run memory without blowing context? Is memory a flat paragraph or a retrieval TOOL? Where is the loop unclosed?' },
    { key: 'context-engineering', who: 'context-engineering researcher', fw: 'Anthropic effective-context-engineering + compaction; context-rot / lost-in-the-middle; just-in-time retrieval; sub-agent context isolation; prompt-caching economics (5-min TTL, read vs write); code-graph vs RAG for large repos', q: 'Does the system exploit prompt caching across its fan-out? What is the large-repo context strategy? Cite Anthropic pricing URLs.' },
    { key: 'agentic-security', who: 'adversarial agentic-security researcher (input is hostile by definition)', fw: 'OWASP LLM Top 10 (2025), OWASP Agentic threats, MITRE ATLAS, MAESTRO; spotlighting/data-marking, dual-LLM/quarantined pattern; sandboxing, SSRF, path-traversal, resource exhaustion, secret exfiltration; own-dependency supply chain', q: 'Map every attacker-controlled surface fed to an LLM. Does the data/instruction boundary actually hold? Can analyzed input set its own gate? List must-fix-before-launch items.' },
    { key: 'controls-governance', who: 'AI governance / platform-reliability lead', fw: 'NeMo/Guardrails-AI/constitutional guardrails, policy-as-code; LLM-judge calibration, self-consistency, seeded-bug benchmarks, determinism controls; OTel GenAI semconv, Langfuse/Phoenix/Braintrust; deterministic compliance mapping', q: 'For any grading/judge system: design the accuracy benchmark and determinism controls. What observability and control-plane gaps exist?' },
    { key: 'agent-expansion', who: 'multi-agent systems architect', fw: 'Anthropic Building-Effective-Agents patterns (orchestrator-workers, evaluator-optimizer, routing, chaining, parallelization), reflection, ReAct/tool-use, agentic-RAG, LLM-judge ensembles', q: 'Map the current pipeline onto these patterns; find what is missing. Propose NEW agents with: pattern, pipeline slot, port, model tier + effort, value-per-effort, and demand gate. Rank them. Name the ONE worth building pre-launch (if any) because it directly creates a demand signal.' },
  ]
  return (await parallel(DIMS.map(d => () =>
    agent(`${GROUND}\n\nROLE: ${d.who}. RESEARCH (web + read the relevant source).\nApply: ${d.fw}.\nAnswer: ${d.q}\nProduce gaps (with repo evidence) and recommendations (each with an effort estimate and a demand gate).`, { label: `arch:${d.key}`, phase: 'Architecture', schema: LENS_SCHEMA })
      .then(r => ({ dimension: d.key, ...r })))) ).filter(Boolean)
}

// ---- run selected phases --------------------------------------------------

const out = {}
if (MODE === 'full' || MODE === 'status') out.engineering = await engineering()
if (MODE === 'full' || MODE === 'strategy') out.business = await business()
if (MODE === 'full' || MODE === 'architecture') out.architecture = await architecture()

// ---- red-team (barrier: needs ALL findings to cross-check) -----------------

phase('RedTeam')
const RED_SCHEMA = {
  type: 'object',
  properties: {
    upheld: { type: 'array', items: { type: 'string' } },
    challenged: { type: 'array', items: { type: 'object', properties: {
      original: { type: 'string' }, challenge: { type: 'string' },
    }, required: ['original', 'challenge'] } },
    contradictions: { type: 'array', items: { type: 'string' } },
    missed: { type: 'array', items: { type: 'string' } },
    partner_verdict: { type: 'string' },
  },
  required: ['upheld', 'challenged', 'contradictions', 'missed', 'partner_verdict'],
}
const redteam = await agent(
  `${GROUND}\n\nROLE: senior partner running adversarial QC before this audit reaches the client. The team's findings (JSON):\n${JSON.stringify(out, null, 2)}\n\nFor each load-bearing claim: is the cited evidence real and sufficient? Spot-check the heaviest claims yourself (read the repo, use WebSearch). Find contradictions between lenses. Be hard on confidence-without-evidence — especially market-size numbers, PMF claims, and "ship this agent" proposals that violate the demand gate. Identify what the whole team missed. Apply Minto/SCQA: what is THE answer? Return raw structured data.`,
  { label: 'red-team', phase: 'RedTeam', schema: RED_SCHEMA }
)

// ---- synthesize one prioritized, demand-gated action list ------------------

phase('Synthesize')
const SYNTH_SCHEMA = {
  type: 'object',
  properties: {
    headline: { type: 'string', description: 'The one-paragraph SCQA verdict' },
    act_today: { type: 'array', items: { type: 'string' }, description: 'Live exposures / hygiene that must happen regardless of strategy' },
    demand_test: { type: 'array', items: { type: 'string' }, description: 'The cheapest experiment(s) that create a real demand signal, with pre-committed kill gates' },
    sequenced: { type: 'array', items: { type: 'object', properties: {
      gate: { type: 'string' }, items: { type: 'array', items: { type: 'string' } },
    }, required: ['gate', 'items'] } },
    freeze: { type: 'array', items: { type: 'string' }, description: 'What to explicitly NOT build until a signal arrives' },
  },
  required: ['headline', 'act_today', 'demand_test', 'sequenced', 'freeze'],
}
const synthesis = await agent(
  `${GROUND}\n\nROLE: principal synthesizing the audit + red-team into ONE prioritized, demand-gated action list a founder can execute. Findings:\n${JSON.stringify(out)}\n\nRed-team:\n${JSON.stringify(redteam)}\n\nKeep only red-team-surviving claims. Separate (a) act-today hygiene/exposures from (b) the cheapest demand test with pre-committed kill gates from (c) everything else, sequenced by the signal that unlocks it. Apply YAGNI + Last-Responsible-Moment. Return raw structured data.`,
  { label: 'synthesis', phase: 'Synthesize', schema: SYNTH_SCHEMA }
)

return { mode: MODE, ...out, redteam, synthesis }
