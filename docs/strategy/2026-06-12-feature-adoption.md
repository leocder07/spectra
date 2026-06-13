# Cross-provider feature adoption — what to borrow from Claude / OpenAI / Gemini / Hermes / open-agent tools

**Date:** 2026-06-12
**Method:** five provider/ecosystem research agents (Anthropic, OpenAI, Gemini, Hermes/open-weights, open-source agentic coding tools) → principal synthesis → adversarial YAGNI/freeze critic. Transcripts in the `spectra-feature-adoption-research` workflow.
**Companion to:** [`2026-06-12-direction-decision.md`](2026-06-12-direction-decision.md) and [`2026-06-12-agentic-architecture.md`](2026-06-12-agentic-architecture.md). Same discipline: research is welcome, **building is demand-gated.**

## The one principle

> Borrow the *technique*, but make its output a **signed, replayable artifact** that inline reviewers (CodeRabbit / Greptile / Copilot) have no incentive to produce.

Every provider feature below is judged by that test. Spectra's moat is the evidence layer, so "adopt and do better" almost always means: take the capability, pin it into the composite cache key + the Ed25519 receipt, and degrade-visibly across backends.

## Fact-check first (the research disagreed with itself; here is the verified truth)

The critic caught the synthesis overstating its own rigor. Verified against the code on 2026-06-12:

- **ADR-026 (multi-cloud LLM gateway) exists** as a Proposed ADR with a `GatewayCapabilities` concept — but **no `GatewayCapabilities` attribute and no second LLM adapter exist in code.** Only `anthropic_adapter.py` + `anthropic_batch_adapter.py` are real. **Consequence:** every "do it on the Gemini/OpenAI path" idea silently presupposes building a second adapter first — that is gated work, not a free feature. The `s`/`m` effort tags on those items understate this.
- **Prompt caching is already shipped and tested** (`cache_control`/`cache_breakpoint` wired through `anthropic_adapter`, `meta_prompter`, `specialist_prompts`, `critique_agent`; `tests/integration/test_prompt_cache_savings_smoke.py` exists). So the "shared cached prefix" idea is **largely done** — only a composition-root regression assertion remains, if anything.
- **The adversarial catch-rate test exists** (`tests/integration/test_adversarial_catch_rate.py`) — but it is ~20 prompt-injection plants graded by a string match, **not** a CVE-labelled precision/recall/F1 corpus. The "signed F1 benchmark" keystone would require authoring and hand-labelling that corpus first — the most expensive, most subjective task in the plan, hidden in an `effort: l` line.

## ✅ Genuinely free / now — what actually survives the freeze

A code-grounded review (Greptile, PR #94) trimmed this list: of the items the synthesis called "free," only **one** is a true no-new-surface change. The rest are small but real work, reclassified below.

1. **Adopt a span-type taxonomy** (`generation` / `guardrail` / `function`, OpenAI-Agents-SDK style or OTel GenAI semconv) as the naming convention for Spectra's **existing** OTel spans across Stages 2–5. Spectra is already OTel-native (vendor-neutral, which the SDK is not), so this is a rename/convention pass on shipped tracing. Makes the signed provenance trail uniformly queryable. **The one genuinely-free pure win.**
2. **Verify (likely already done):** assert prefix-stable prompt layout in the existing `test_prompt_cache_savings_smoke.py`. Prompt caching is shipped + tested, so this is at most a one-line regression assertion.

### Cheap but NOT free — small, real changes (still freeze-defensible as integrity/provenance)

- **Pin `effort` into the composite cache key + receipt.** *Correction:* the cache key is `(repo, spectra, model, prompt, schema)` — **`effort` is not in it**, and the receipt signs the score-card hash + scan metadata, not effort. So an effort change can silently reuse a stale cached report, and the receipt can't prove which reasoning depth produced the grade. This is genuine provenance work (small), not a skip.
- **Per-agent cost/token breakdown in the report.** *Correction:* this is **not** pure presentation — `AnalysisReport` persists only totals + cache savings; the cost tracker's per-agent ledger is dropped before Stage 6. Rendering the breakdown needs the per-agent data carried into the report model first (small pipeline/model change), then the renderer.
4. **The honest, cheap trust number:** wire the existing `SignerPort` over the output of the existing `test_adversarial_catch_rate` (≥80%). This is the *cheap substitute* for the eval-harness keystone — no new corpus, no F1 fiction — and even this waits until a trust number is actually needed in a buyer conversation.

## ⭐ The two transformative ideas — real, but NOT free (build when demand names them)

Both converged across every provider lens. Both are net-new builds with no current buyer, so they **defer** — but they are the first things to reach for the moment a demand signal appears.

| Idea | Source (best-of-breed) | Spectra move | Why it's transformative | Honest gate |
|---|---|---|---|---|
| **Signed accuracy / catch-rate benchmark** | OpenAI Evals + open-agent **SWE-bench Verified / CVE-Bench** (graded on *findings*, not patches; OpenAI sunsets hosted Evals 2026-11-30, so the durable asset is a *self-hosted* harness) | `EvalHarnessPort` (L2) + local adapter replaying `golden_files/` through the real Stage-3/5 agents, emitting a **signed** precision/recall/F1 card pinned to `(model, prompt, schema, spectra)` | A buyer-verifiable accuracy claim is exactly the signal a DD buyer responds to — and no inline reviewer ships one | **When a buyer asks for an accuracy number.** Until then, sign the existing catch-rate (`test_adversarial_catch_rate`). The CVE-labelled corpus must be authored first — that is the real cost. |
| **Code-graph context for the MetaPrompter** | **Aider's tree-sitter + PageRank repo-map** | `CodeGraphPort` + ranked symbol map replacing the 4-tier stem-match in `prioritize_source_files`; sign the ranked map as a **coverage artifact**; cache per-file symbol tables under the existing composite key | Solves the named large-repo context weakness *within* the ≤5K-token file-tree invariant (a ranked symbol map is a better 5K-token summary than a stem-matched file list) | **When a real large repo from a real user starves the specialists** (observable). Interim cheap fix: raise the heuristic's file budget. |

## Per-provider — the single best idea from each

- **Anthropic (own provider, lowest friction):** **constrained structured output** for agent payloads. *Current state (verified):* the adapter sends only `output_config` (effort/task-budget) through `messages.stream`; there is **no** `tools` / `tool_choice` / `input_schema` wiring — agents prompt for JSON, parse free-form text, then validate with Pydantic. So adopting tool-use-with-`input_schema` (or a future native structured-output feature) to constrain the model at generation time and cut SPEC-005 retries is **real adapter/request-surface work** on the Anthropic path — *not* a prompt tweak, and *not* an OpenAI-style `messages.parse`/`json_schema` call (don't let an implementer drift to that API). The genuinely-cheap Anthropic win is the **`count_tokens` endpoint** (true tokenizer, retires the `tiktoken` under-count flagged in the architecture memo). Plus a **Haiku/Sonnet/Opus tier mix** — reserve Opus for high-signal dimensions — the cheap half of the future Cost-Governor.
- **OpenAI:** the **Evals → signed F1** path (above). Also **Agents-SDK Guardrails** as *signed* due-diligence evidence (formalize SPEC-011 / ADR-011 / the MetaPrompter ≤5K rule as replayable guard outcomes) — `post-demand-test`.
- **Gemini:** the **code-execution sandbox as a Stage-5.5 finding-reproduction verifier** (`VerifierPort` — turn an asserted finding into an executed, signed `finding+stdout+exit` artifact) — transformative, `post-demand-test`. Plus **Grounding with Google Search** for live CVE/EOL enrichment of the DependencyAgent only (`--grounded`, off by default, citations+timestamp signed).
- **Hermes / open-weights:** **open-weight model pinning recorded in the signed receipt + cache key** (`transformative/s`) — turns the receipt into a provenance chain that proves *which* model graded. And the **air-gapped / on-prem `OpenWeightAdapter`** (Hermes/Llama/Qwen on self-hosted vLLM) — the concrete unlock for **ZDR (#15) and EU-residency / no-egress regulated-DD audits**, the Direction-C ICP. Open weights are also the cheap tier for the Cost-Governor router.
- **Open-agent tools:** the **repo-map** and **eval harness** (the two keystones). Also **Spectra-as-MCP-server** (read-only `spectra.audit/verify/history`) — distribution into the ~13K-MCP-server channel as the one server that returns a *verifiable* result — `10-paying-users`.

## Sequenced backlog (by demand gate)

- **Now (free):** the span-taxonomy rename (item 1) + the cache-prefix assertion (item 2).
- **Now (cheap, integrity/provenance):** pin `effort` into the cache key + receipt; carry per-agent cost into the report model + render it.
- **Pre-launch, only if a trust number is needed in a conversation:** sign the existing catch-rate (`test_adversarial_catch_rate`, ≥80%). Do **not** author the F1 corpus speculatively.
- **Post-demand-test:** `EvalHarnessPort` (when asked) · `CodeGraphPort` repo-map (when a large repo starves the specialists) · `VerifierPort` + Gemini code-exec · read-only `NavigationPort` (grep-as-tool for specialists) · `GuardrailPort` · stage-boundary checkpointing (signed PARTIAL receipt) · open-weight pinning in the receipt.
- **10 paying users:** second LLM adapter (built **only** when a specific buyer constraint — ZDR region, existing Azure/GCP contract — names it) · Gemini batch on the existing `BatchSubmitterPort` · MCP server · `GroundingPort` (CVE enrichment) · `EmbeddingPort` (semantic dedup) · `--plan-gate` scope-of-work attestation · Cost-Governor router.
- **Scale:** self-hosted `SandboxPort` (Docker, no-egress) · explicit named context-cache handle.

## ❌ Explicitly skip (tempting, wrong for a signed read-only audit)

- **Gemini 1M-token whole-repo pass** as the primary context strategy — flirts with the MetaPrompter invariant, attention decays past ~400–500K tokens, and a signed PageRank symbol map wins on cost *and* verifiable coverage.
- **OpenAI Predicted Outputs / speculative decoding** — rejected tokens are still billed, and trading correctness for speed on a *signed verdict* is exactly the wrong tradeoff.
- **RFT / distillation of a cheaper grader** — a fine-tuned model must never touch a signed verdict; resume-driven, `xl`, gated to 10-users at best.
- **OpenAI hosted vector stores (`file_search`)** — a non-starter for no-egress DD buyers; keep retrieval local/self-hostable behind `MemoryPort`. Adopt the semantic-retrieval *pattern* (local embedding index), not the hosted store.
- **Jules / any autonomous-remediation writer in-pipeline** — adding an editing/world-acting surface contradicts the read-only signed-auditor positioning. At most a strictly-downstream `RemediationPort` that hands a signed finding ID to an external writer after Stage 6 — research-only, no build until a buyer asks.
- **Building a second LLM adapter speculatively** — `ADR-026` exists as a doc but the code does not; build it only when a named buyer constraint requires it (Last-Responsible-Moment), not to unlock features for their own sake.
- **OpenAI Agents-SDK tracing as a runtime dependency** — Spectra is already OTel-native; take the span-taxonomy *naming* (free), not the SDK infrastructure.

## Bottom line

The freeze holds — and a code-grounded review made the "free" list honest: the only true no-new-surface win is the OTel span-taxonomy rename. Two more (pin `effort` into the cache key/receipt; carry per-agent cost into the report) are cheap, real, and defensible as provenance/integrity work. Everything genuinely new — the eval harness and the repo-map, however transformative — waits for the demand signal that names it, then is built as the cheapest thing that answers that signal, re-evaluated against the then-current provider APIs. The durable insight is the adoption rule itself, now a lens in the reusable [`project-audit`](AUDIT-PROMPT.md) workflow: *borrow the technique, sign the artifact.*
