import { useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar } from "recharts";

const C = {
  bg: "#0c0e14", surface: "#12151e", border: "#1c2030", highlight: "#222840",
  amber: "#f0a030", green: "#30d060", red: "#f04040", blue: "#3090f0",
  purple: "#9060f0", cyan: "#30c0d0", pink: "#e060a0",
  text: "#d8dce8", muted: "#5c6478", dim: "#2a3040",
};

const gapRegister = [
  { id: "G01", area: "Domain", gap: "Finding deduplication logic not specified", severity: "HIGH", status: "OPEN", sprint: 1 },
  { id: "G02", area: "Domain", gap: "Severity scoring weights undefined", severity: "MED", status: "OPEN", sprint: 1 },
  { id: "G03", area: "Ports", gap: "ProgressObserver callback frequency", severity: "LOW", status: "RESOLVED", sprint: 1 },
  { id: "G04", area: "Infra", gap: "Rate limit handling (429) retry ceiling", severity: "HIGH", status: "OPEN", sprint: 1 },
  { id: "G05", area: "Infra", gap: "Token counter accuracy vs tiktoken drift", severity: "MED", status: "OPEN", sprint: 2 },
  { id: "G06", area: "Pipeline", gap: "Parallel agent timeout coordination", severity: "HIGH", status: "OPEN", sprint: 2 },
  { id: "G07", area: "Pipeline", gap: "Meta-prompt token budget allocation", severity: "MED", status: "OPEN", sprint: 2 },
  { id: "G08", area: "Pipeline", gap: "Degraded state partial merge strategy", severity: "HIGH", status: "OPEN", sprint: 2 },
  { id: "G09", area: "Report", gap: "Health score dimension weights", severity: "MED", status: "OPEN", sprint: 3 },
  { id: "G10", area: "Report", gap: "File hotspot risk formula", severity: "MED", status: "OPEN", sprint: 3 },
  { id: "G11", area: "Testing", gap: "LLM response mock strategy", severity: "HIGH", status: "OPEN", sprint: 3 },
  { id: "G12", area: "Testing", gap: "Integration test golden files", severity: "MED", status: "OPEN", sprint: 3 },
  { id: "G13", area: "Deploy", gap: "PyPI packaging + CLI entry point", severity: "LOW", status: "OPEN", sprint: 3 },
  { id: "G14", area: "Deploy", gap: "Docker image size optimization", severity: "LOW", status: "DEFERRED", sprint: 0 },
];

const patterns = [
  { name: "Facade", where: "AnalyzeCodebase", why: "Single entry point orchestrating 6-stage pipeline", complexity: 9 },
  { name: "Strategy", where: "DeepAnalysis/Quick", why: "Swap Opus 4.6 (critique) vs Sonnet 4.5 (fast)", complexity: 6 },
  { name: "Decorator", where: "TimingGW/RetryGW", why: "Onion wrapping: Timing > Retry > Anthropic", complexity: 8 },
  { name: "Factory", where: "AgentFactory", why: "Create 4 agent configs from meta-prompt output", complexity: 5 },
  { name: "Observer", where: "ProgressObserver", why: "Rich UI progress bars + stage callbacks", complexity: 4 },
  { name: "Ports/Adapters", where: "6 Protocol interfaces", why: "Clean Architecture boundary enforcement", complexity: 7 },
  { name: "State Machine", where: "PipelineState (10)", why: "PENDING->COMPLETE with DEGRADED/FAILED paths", complexity: 8 },
  { name: "Value Object", where: "Finding (frozen)", why: "Immutable domain entities, hashable for dedup", complexity: 3 },
];

const sprintPlan = [
  {
    sprint: 1, name: "Foundation", hours: 12, status: "current",
    tasks: [
      { task: "Domain models + value objects", hours: 2, status: "done" },
      { task: "6 Protocol interfaces", hours: 1, status: "done" },
      { task: "Error taxonomy + special cases", hours: 1, status: "done" },
      { task: "AnthropicGateway + retry decorator", hours: 2, status: "active" },
      { task: "GitPython driver", hours: 1, status: "todo" },
      { task: "Token counter + file packer", hours: 1, status: "todo" },
      { task: "MetaPrompter use case", hours: 2, status: "todo" },
      { task: "4x Agent prompt templates", hours: 2, status: "todo" },
    ]
  },
  {
    sprint: 2, name: "Pipeline + Orchestration", hours: 12, status: "upcoming",
    tasks: [
      { task: "MergeFindings dedup engine", hours: 1, status: "todo" },
      { task: "CritiqueAgent reviewer", hours: 1, status: "todo" },
      { task: "AnalyzeCodebase facade (CRITICAL)", hours: 3, status: "todo" },
      { task: "Pipeline state machine", hours: 1, status: "todo" },
      { task: "Composition root DI wiring", hours: 1, status: "todo" },
      { task: "Jinja2 HTML report template", hours: 3, status: "todo" },
      { task: "Typer CLI + Rich progress", hours: 1, status: "todo" },
      { task: "Quick mode (Sonnet 4.5)", hours: 1, status: "todo" },
    ]
  },
  {
    sprint: 3, name: "Test + Ship", hours: 10, status: "upcoming",
    tasks: [
      { task: "Integration test real repo (CRITICAL)", hours: 2, status: "todo" },
      { task: "Unit tests - domain layer", hours: 2, status: "todo" },
      { task: "LLM mock fixtures", hours: 1, status: "todo" },
      { task: "Demo recording + README", hours: 2, status: "todo" },
      { task: "Bug fixes + edge cases", hours: 2, status: "todo" },
      { task: "PyPI publish + CLI entry", hours: 1, status: "todo" },
    ]
  },
];

const resilienceMatrix = [
  { scenario: "API Rate Limited (429)", probability: "High", impact: "Medium", mitigation: "RetryGW 3x exponential backoff", recovery: "Auto" },
  { scenario: "API Timeout (30s)", probability: "Medium", impact: "Medium", mitigation: "Per-call timeout + retry", recovery: "Auto" },
  { scenario: "1-3 Agents Fail", probability: "Low", impact: "Low", mitigation: "DEGRADED state, partial merge", recovery: "Auto" },
  { scenario: "All 4 Agents Fail", probability: "Very Low", impact: "Critical", mitigation: "FAILED state with E020", recovery: "Manual" },
  { scenario: "Token Overflow (>1M)", probability: "Medium", impact: "High", mitigation: "Smart file filtering + truncation", recovery: "Auto" },
  { scenario: "Git Clone Failure", probability: "Low", impact: "Critical", mitigation: "E001 with auth token hint", recovery: "Manual" },
  { scenario: "Malformed JSON Response", probability: "Low", impact: "Medium", mitigation: "E012 + retry with stricter prompt", recovery: "Auto" },
];

const archLayers = [
  { layer: "Adapters", modules: ["CLIController", "RichPresenter", "PromptTemplates"], color: C.blue, desc: "I/O boundary" },
  { layer: "Use Cases", modules: ["AnalyzeCodebase", "MetaPrompter", "MergeFindings", "CritiqueAgent", "GenerateReport"], color: C.purple, desc: "Business logic" },
  { layer: "Domain", modules: ["Finding", "Severity", "Codebase", "Report", "AgentResult", "PipelineState"], color: C.green, desc: "Entities + rules" },
  { layer: "Ports", modules: ["LLMGateway", "GitPort", "FilePort", "TokenPort", "ReportPort", "ProgressObserver"], color: C.cyan, desc: "Protocol interfaces" },
  { layer: "Infrastructure", modules: ["AnthropicGW", "GitPythonDriver", "PathLibReader", "TiktokenCounter", "Jinja2Reporter"], color: C.red, desc: "External adapters" },
];

const patternRadar = patterns.map(p => ({ name: p.name, complexity: p.complexity }));

const StatusBadge = ({ status }) => {
  const colors = { done: C.green, active: C.amber, todo: C.muted, OPEN: C.red, RESOLVED: C.green, DEFERRED: C.muted };
  const col = colors[status] || C.muted;
  return (
    <span style={{
      fontSize: 10, fontFamily: "monospace", padding: "2px 8px", borderRadius: 3,
      background: `${col}18`, color: col, border: `1px solid ${col}40`, textTransform: "uppercase", letterSpacing: 1,
    }}>{status}</span>
  );
};

const SevBadge = ({ sev }) => {
  const col = sev === "HIGH" ? C.red : sev === "MED" ? C.amber : C.cyan;
  return (
    <span style={{
      fontSize: 10, fontFamily: "monospace", padding: "2px 6px", borderRadius: 3,
      background: `${col}18`, color: col, letterSpacing: 1,
    }}>{sev}</span>
  );
};

const Section = ({ title, children, color = C.amber }) => (
  <div style={{ marginBottom: 28 }}>
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
      <div style={{ width: 10, height: 10, background: color, borderRadius: 2, transform: "rotate(45deg)" }} />
      <h2 style={{ fontSize: 18, color: C.text, margin: 0, fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600, letterSpacing: -0.5 }}>{title}</h2>
      <div style={{ flex: 1, height: 1, background: C.border }} />
    </div>
    {children}
  </div>
);

const tabs = ["Architecture", "Patterns", "Gap Register", "Sprint Plan", "Resilience"];

export default function TechDashboard() {
  const [tab, setTab] = useState("Architecture");

  const openGaps = gapRegister.filter(g => g.status === "OPEN");
  const highGaps = openGaps.filter(g => g.severity === "HIGH");

  return (
    <div style={{ background: C.bg, minHeight: "100vh", color: C.text, fontFamily: "'IBM Plex Sans', sans-serif" }}>
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet" />

      {/* Header */}
      <div style={{ padding: "24px 32px 0", borderBottom: `1px solid ${C.border}`, background: C.surface }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: C.amber, letterSpacing: 3, textTransform: "uppercase" }}>
              SYS://REPOINTEL/ARCH
            </div>
            <h1 style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 28, margin: "4px 0 4px", fontWeight: 600, color: C.text, letterSpacing: -1 }}>
              Technical Command Center
            </h1>
            <div style={{ fontSize: 13, color: C.muted }}>
              Clean Architecture + 8 Design Patterns + 14 Gap Register + 48hr Build
            </div>
          </div>
          <div style={{ display: "flex", gap: 12 }}>
            {[
              { label: "OPEN GAPS", value: openGaps.length, color: C.red },
              { label: "HIGH SEV", value: highGaps.length, color: C.amber },
              { label: "PATTERNS", value: patterns.length, color: C.purple },
              { label: "SPRINTS", value: 3, color: C.green },
            ].map((m, i) => (
              <div key={i} style={{
                background: C.bg, border: `1px solid ${C.border}`, borderRadius: 6, padding: "8px 16px", textAlign: "center", minWidth: 70,
              }}>
                <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: m.color, letterSpacing: 1 }}>{m.label}</div>
                <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 24, color: m.color, fontWeight: 600 }}>{m.value}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", gap: 0, marginTop: 20 }}>
          {tabs.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              background: "none", border: "none", cursor: "pointer", padding: "10px 20px",
              fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 500, letterSpacing: 0.5,
              color: tab === t ? C.amber : C.muted,
              borderBottom: tab === t ? `2px solid ${C.amber}` : "2px solid transparent",
              transition: "all 0.15s",
            }}>
              {t.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: "28px 32px" }}>

        {/* ARCHITECTURE */}
        {tab === "Architecture" && (
          <div>
            <Section title="Clean Architecture Layers" color={C.green}>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {archLayers.map((layer, i) => (
                  <div key={i} style={{
                    display: "flex", alignItems: "stretch", background: C.surface,
                    border: `1px solid ${C.border}`, borderRadius: 8, overflow: "hidden",
                  }}>
                    <div style={{
                      width: 140, padding: "14px 16px", borderRight: `1px solid ${C.border}`,
                      background: `${layer.color}08`, display: "flex", flexDirection: "column", justifyContent: "center",
                    }}>
                      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: layer.color, fontWeight: 600 }}>{layer.layer}</div>
                      <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>{layer.desc}</div>
                    </div>
                    <div style={{ flex: 1, padding: "12px 16px", display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                      {layer.modules.map((mod, j) => (
                        <span key={j} style={{
                          fontSize: 12, fontFamily: "'IBM Plex Mono', monospace", padding: "4px 10px",
                          background: `${layer.color}12`, border: `1px solid ${layer.color}30`, borderRadius: 4, color: layer.color,
                        }}>
                          {mod}
                        </span>
                      ))}
                    </div>
                    <div style={{
                      width: 60, display: "flex", alignItems: "center", justifyContent: "center",
                      fontFamily: "'IBM Plex Mono', monospace", fontSize: 18, color: C.dim,
                    }}>
                      {i < archLayers.length - 1 ? "^" : ""}
                    </div>
                  </div>
                ))}
              </div>
              <div style={{
                marginTop: 12, padding: "10px 16px", background: `${C.green}08`,
                border: `1px solid ${C.green}20`, borderRadius: 6, fontSize: 12, color: C.green,
                fontFamily: "'IBM Plex Mono', monospace",
              }}>
                DEPENDENCY RULE: Infrastructure implements Ports. Use Cases depend on Domain. Adapters depend on Use Cases. Nothing depends outward.
              </div>
            </Section>

            <Section title="Pipeline Architecture — 6 Stages" color={C.amber}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
                {[
                  { stage: "1. INGEST", time: "5-10s", desc: "git clone, file filter, tiktoken pack to ~900K tokens", color: C.blue },
                  { stage: "2. META-PROMPT", time: "10-15s", desc: "Opus 4.6 generates custom prompts based on repo patterns", color: C.purple },
                  { stage: "3. ANALYZE", time: "30-60s", desc: "4 parallel Opus calls: Arch, Security, Quality, Docs", color: C.amber },
                  { stage: "4. MERGE", time: "5-10s", desc: "Deduplicate findings by file path, cross-reference, score", color: C.cyan },
                  { stage: "5. CRITIQUE", time: "15-30s", desc: "Opus reviews merged findings, catches missing insights", color: C.red },
                  { stage: "6. REPORT", time: "5-10s", desc: "Jinja2 template renders single-file HTML with charts", color: C.green },
                ].map((s, i) => (
                  <div key={i} style={{
                    background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8,
                    padding: 16, borderTop: `3px solid ${s.color}`,
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                      <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: s.color, fontWeight: 600 }}>{s.stage}</span>
                      <span style={{
                        fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, padding: "2px 6px",
                        background: `${s.color}15`, color: s.color, borderRadius: 3,
                      }}>{s.time}</span>
                    </div>
                    <div style={{ fontSize: 12, color: C.muted, lineHeight: 1.5 }}>{s.desc}</div>
                  </div>
                ))}
              </div>
              <div style={{
                marginTop: 12, display: "flex", gap: 16, padding: "12px 16px",
                background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6,
              }}>
                {[
                  { label: "API CALLS", value: "6", color: C.amber },
                  { label: "TOTAL TIME", value: "~90s", color: C.green },
                  { label: "COST/RUN", value: "$3-7", color: C.cyan },
                  { label: "MODEL", value: "Opus 4.6", color: C.purple },
                  { label: "CONTEXT", value: "~1M tok", color: C.red },
                ].map((m, i) => (
                  <div key={i} style={{ textAlign: "center", flex: 1 }}>
                    <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: C.muted, letterSpacing: 1 }}>{m.label}</div>
                    <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 16, color: m.color, fontWeight: 600 }}>{m.value}</div>
                  </div>
                ))}
              </div>
            </Section>
          </div>
        )}

        {/* PATTERNS */}
        {tab === "Patterns" && (
          <div>
            <Section title="Design Pattern Map — 8 Patterns" color={C.purple}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
                <div>
                  <ResponsiveContainer width="100%" height={300}>
                    <RadarChart data={patternRadar}>
                      <PolarGrid stroke={C.dim} />
                      <PolarAngleAxis dataKey="name" stroke={C.muted} fontSize={10} />
                      <PolarRadiusAxis domain={[0, 10]} stroke={C.dim} fontSize={9} />
                      <Radar dataKey="complexity" stroke={C.purple} fill={C.purple} fillOpacity={0.25} strokeWidth={2} />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
                <div>
                  {patterns.map((p, i) => (
                    <div key={i} style={{
                      display: "flex", alignItems: "center", gap: 10, marginBottom: 10,
                      padding: "10px 12px", background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6,
                    }}>
                      <div style={{ width: 90 }}>
                        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: C.purple, fontWeight: 600 }}>{p.name}</div>
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12, color: C.text }}>{p.where}</div>
                        <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>{p.why}</div>
                      </div>
                      <div style={{ width: 50, textAlign: "right" }}>
                        <div style={{ background: C.dim, borderRadius: 3, height: 6, width: 40 }}>
                          <div style={{
                            width: `${p.complexity * 10}%`, height: "100%", borderRadius: 3,
                            background: p.complexity >= 8 ? C.red : p.complexity >= 5 ? C.amber : C.green,
                          }} />
                        </div>
                        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: C.muted, marginTop: 2 }}>{p.complexity}/10</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </Section>

            <Section title="Decorator Chain Detail" color={C.amber}>
              <div style={{ display: "flex", gap: 0, alignItems: "stretch" }}>
                {[
                  { name: "AnalyzeCodebase", desc: "Calls gateway.analyze()", role: "Consumer", color: C.blue },
                  { name: "TimingGateway", desc: "Logs duration per call", role: "Decorator", color: C.purple },
                  { name: "RetryGateway", desc: "3x exponential backoff", role: "Decorator", color: C.amber },
                  { name: "AnthropicGateway", desc: "AsyncAnthropic -> API", role: "Implementation", color: C.red },
                ].map((item, i) => (
                  <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column" }}>
                    <div style={{
                      background: `${item.color}12`, border: `1px solid ${item.color}30`,
                      borderRadius: i === 0 ? "8px 0 0 8px" : i === 3 ? "0 8px 8px 0" : 0,
                      padding: "14px 12px", textAlign: "center", flex: 1,
                    }}>
                      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: item.color, fontWeight: 600 }}>{item.name}</div>
                      <div style={{ fontSize: 11, color: C.muted, marginTop: 4 }}>{item.desc}</div>
                      <div style={{
                        fontSize: 9, fontFamily: "'IBM Plex Mono', monospace", marginTop: 6,
                        padding: "2px 6px", background: `${item.color}15`, borderRadius: 3, color: item.color, display: "inline-block",
                      }}>{item.role}</div>
                    </div>
                    {i < 3 && <div style={{ textAlign: "center", fontSize: 16, color: C.muted, padding: "2px 0" }}>-&gt;</div>}
                  </div>
                ))}
              </div>
            </Section>
          </div>
        )}

        {/* GAP REGISTER */}
        {tab === "Gap Register" && (
          <div>
            <Section title={`Gap Register — ${openGaps.length} Open / ${gapRegister.length} Total`} color={C.red}>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: `2px solid ${C.border}` }}>
                      {["ID", "Area", "Gap Description", "Severity", "Status", "Sprint"].map(h => (
                        <th key={h} style={{
                          textAlign: "left", padding: "10px 12px", fontFamily: "'IBM Plex Mono', monospace",
                          fontSize: 10, color: C.muted, letterSpacing: 1, textTransform: "uppercase",
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {gapRegister.map((g, i) => (
                      <tr key={i} style={{
                        borderBottom: `1px solid ${C.border}`,
                        background: g.severity === "HIGH" && g.status === "OPEN" ? `${C.red}06` : "transparent",
                      }}>
                        <td style={{ padding: "10px 12px", fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: C.amber }}>{g.id}</td>
                        <td style={{ padding: "10px 12px", fontSize: 12, color: C.text }}>{g.area}</td>
                        <td style={{ padding: "10px 12px", fontSize: 12, color: C.text }}>{g.gap}</td>
                        <td style={{ padding: "10px 12px" }}><SevBadge sev={g.severity} /></td>
                        <td style={{ padding: "10px 12px" }}><StatusBadge status={g.status} /></td>
                        <td style={{ padding: "10px 12px", fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: g.sprint === 0 ? C.muted : C.text }}>
                          {g.sprint === 0 ? "—" : `S${g.sprint}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginTop: 16 }}>
                {[
                  { label: "Sprint 1 Gaps", count: gapRegister.filter(g => g.sprint === 1).length, color: C.amber },
                  { label: "Sprint 2 Gaps", count: gapRegister.filter(g => g.sprint === 2).length, color: C.purple },
                  { label: "Sprint 3 Gaps", count: gapRegister.filter(g => g.sprint === 3).length, color: C.cyan },
                ].map((s, i) => (
                  <div key={i} style={{
                    background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6,
                    padding: "12px 16px", display: "flex", justifyContent: "space-between", alignItems: "center",
                  }}>
                    <span style={{ fontSize: 13, color: C.text }}>{s.label}</span>
                    <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 20, color: s.color, fontWeight: 600 }}>{s.count}</span>
                  </div>
                ))}
              </div>
            </Section>
          </div>
        )}

        {/* SPRINT PLAN */}
        {tab === "Sprint Plan" && (
          <div>
            <Section title="48-Hour Hackathon Build — 3 Sprints" color={C.green}>
              {sprintPlan.map((sprint, si) => (
                <div key={si} style={{
                  background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8,
                  marginBottom: 16, overflow: "hidden",
                }}>
                  <div style={{
                    padding: "14px 20px", borderBottom: `1px solid ${C.border}`,
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    background: sprint.status === "current" ? `${C.green}08` : "transparent",
                  }}>
                    <div>
                      <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, color: sprint.status === "current" ? C.green : C.text, fontWeight: 600 }}>
                        Sprint {sprint.sprint}: {sprint.name}
                      </span>
                      {sprint.status === "current" && (
                        <span style={{
                          marginLeft: 10, fontSize: 10, fontFamily: "'IBM Plex Mono', monospace",
                          padding: "2px 8px", background: `${C.green}20`, color: C.green, borderRadius: 3,
                        }}>ACTIVE</span>
                      )}
                    </div>
                    <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: C.amber }}>{sprint.hours}h total</span>
                  </div>
                  <div style={{ padding: "12px 20px" }}>
                    {sprint.tasks.map((task, ti) => {
                      const doneCount = sprint.tasks.filter(t => t.status === "done").length;
                      return (
                        <div key={ti} style={{
                          display: "flex", alignItems: "center", gap: 12, padding: "8px 0",
                          borderBottom: ti < sprint.tasks.length - 1 ? `1px solid ${C.border}50` : "none",
                          opacity: task.status === "done" ? 0.6 : 1,
                        }}>
                          <div style={{
                            width: 16, height: 16, borderRadius: 3, flexShrink: 0,
                            border: `2px solid ${task.status === "done" ? C.green : task.status === "active" ? C.amber : C.dim}`,
                            background: task.status === "done" ? `${C.green}30` : "transparent",
                            display: "flex", alignItems: "center", justifyContent: "center",
                            fontSize: 10, color: C.green,
                          }}>
                            {task.status === "done" ? "x" : ""}
                          </div>
                          <span style={{
                            flex: 1, fontSize: 13, color: C.text,
                            textDecoration: task.status === "done" ? "line-through" : "none",
                          }}>
                            {task.task}
                          </span>
                          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: C.muted }}>{task.hours}h</span>
                          <StatusBadge status={task.status} />
                        </div>
                      );
                    })}
                  </div>
                  <div style={{ padding: "8px 20px 12px", borderTop: `1px solid ${C.border}` }}>
                    <div style={{ background: C.dim, borderRadius: 3, height: 6 }}>
                      <div style={{
                        width: `${(sprint.tasks.filter(t => t.status === "done").length / sprint.tasks.length) * 100}%`,
                        height: "100%", borderRadius: 3, background: C.green, transition: "width 0.3s",
                      }} />
                    </div>
                    <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: C.muted, marginTop: 4 }}>
                      {sprint.tasks.filter(t => t.status === "done").length}/{sprint.tasks.length} tasks complete
                    </div>
                  </div>
                </div>
              ))}

              <div style={{
                padding: "14px 20px", background: `${C.amber}08`, border: `1px solid ${C.amber}25`,
                borderRadius: 8, fontSize: 12, fontFamily: "'IBM Plex Mono', monospace",
              }}>
                <span style={{ color: C.amber }}>CRITICAL PATH:</span>
                <span style={{ color: C.text, marginLeft: 8 }}>AnalyzeCodebase Facade (S2, 3h) + Integration Test on Real Repo (S3, 2h)</span>
              </div>
            </Section>
          </div>
        )}

        {/* RESILIENCE */}
        {tab === "Resilience" && (
          <div>
            <Section title="Resilience Matrix — 7 Failure Scenarios" color={C.red}>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: `2px solid ${C.border}` }}>
                      {["Scenario", "Probability", "Impact", "Mitigation", "Recovery"].map(h => (
                        <th key={h} style={{
                          textAlign: "left", padding: "10px 12px", fontFamily: "'IBM Plex Mono', monospace",
                          fontSize: 10, color: C.muted, letterSpacing: 1, textTransform: "uppercase",
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {resilienceMatrix.map((r, i) => (
                      <tr key={i} style={{ borderBottom: `1px solid ${C.border}` }}>
                        <td style={{ padding: "10px 12px", fontSize: 12, color: C.text, fontWeight: 500 }}>{r.scenario}</td>
                        <td style={{ padding: "10px 12px" }}>
                          <span style={{
                            fontSize: 11, color: r.probability === "High" ? C.red : r.probability === "Medium" ? C.amber : C.green,
                          }}>{r.probability}</span>
                        </td>
                        <td style={{ padding: "10px 12px" }}>
                          <span style={{
                            fontSize: 11, color: r.impact === "Critical" ? C.red : r.impact === "High" ? C.amber : r.impact === "Medium" ? C.amber : C.green,
                          }}>{r.impact}</span>
                        </td>
                        <td style={{ padding: "10px 12px", fontSize: 12, color: C.muted }}>{r.mitigation}</td>
                        <td style={{ padding: "10px 12px" }}>
                          <span style={{
                            fontSize: 10, fontFamily: "'IBM Plex Mono', monospace", padding: "2px 8px", borderRadius: 3,
                            background: r.recovery === "Auto" ? `${C.green}15` : `${C.amber}15`,
                            color: r.recovery === "Auto" ? C.green : C.amber,
                          }}>{r.recovery}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>

            <Section title="State Machine — 10 Pipeline States" color={C.cyan}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {[
                  { state: "PENDING", color: C.muted, next: "INGESTING" },
                  { state: "INGESTING", color: C.blue, next: "META_PROMPTING" },
                  { state: "META_PROMPTING", color: C.purple, next: "ANALYZING" },
                  { state: "ANALYZING", color: C.amber, next: "MERGING" },
                  { state: "MERGING", color: C.cyan, next: "CRITIQUING" },
                  { state: "CRITIQUING", color: C.red, next: "REPORTING" },
                  { state: "REPORTING", color: C.green, next: "COMPLETE" },
                  { state: "COMPLETE", color: C.green, next: null },
                  { state: "DEGRADED", color: C.amber, next: null },
                  { state: "FAILED", color: C.red, next: null },
                ].map((s, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <div style={{
                      padding: "8px 14px", background: `${s.color}12`, border: `1px solid ${s.color}40`,
                      borderRadius: 6, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: s.color, fontWeight: 600,
                    }}>
                      {s.state}
                    </div>
                    {s.next && <span style={{ color: C.dim, fontSize: 14 }}>-&gt;</span>}
                  </div>
                ))}
              </div>
              <div style={{
                marginTop: 16, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12,
              }}>
                <div style={{ padding: "12px 16px", background: `${C.amber}08`, border: `1px solid ${C.amber}20`, borderRadius: 6 }}>
                  <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: C.amber }}>DEGRADED PATH</div>
                  <div style={{ fontSize: 12, color: C.muted, marginTop: 4 }}>
                    1-3 agents fail during ANALYZING. Pipeline continues to MERGING with partial results. Report includes coverage warnings.
                  </div>
                </div>
                <div style={{ padding: "12px 16px", background: `${C.red}08`, border: `1px solid ${C.red}20`, borderRadius: 6 }}>
                  <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: C.red }}>FAILED PATH</div>
                  <div style={{ fontSize: 12, color: C.muted, marginTop: 4 }}>
                    Git clone fails (E001), all 4 agents fail (E020), or file write fails (E030). Pipeline halts, error logged with full context.
                  </div>
                </div>
              </div>
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}
