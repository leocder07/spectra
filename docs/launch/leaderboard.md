# Spectra Leaderboard — Real OSS Scans (Full Mode)

Live scans of well-known open-source projects, run with `spectra-ai==0.3.2`
on Claude Opus 4.7. **Full pipeline** (all 8 agents including the CritiqueAgent
stage that filters false positives via adaptive thinking + task budget). All
findings link to the actual file:line on GitHub. No cherry-picking — each
scan is one shot.

## 📄 Open the styled reports in your browser

- [`anthropic-sdk-python.html`](reports/anthropic-sdk-python.html) — **B+** (85.6)
- [`gstack.html`](reports/gstack.html) — **C** (72.7)
- [`gbrain.html`](reports/gbrain.html) — **C+** (73.0)
- [`gbrain-evals.html`](reports/gbrain-evals.html) — **C+** (76.1)
- [`alphaclaw.html`](reports/alphaclaw.html) — **C+** (74.6)

Each HTML report includes the animated scorecard, per-dimension breakdown,
full findings list with severity, file:line, fix recommendation, estimated
hours, agent attribution, and confidence — exactly what `spectra analyze`
writes to `spectra-report.html` by default.

## Summary

| # | Repo | Stars | Grade | Score | Findings | Critical | High | Wall | Cost | HTML | JSON |
|---:|---|---:|:---:|---:|---:|---:|---:|---:|---:|:---:|:---:|
| 1 | [`anthropic-sdk-python`](https://github.com/anthropics/anthropic-sdk-python) | Anthropic | **B+** | 85.6 | 50 | 0 | 0 | 248s | $7.41 | [📄](reports/anthropic-sdk-python.html) | [📦](../leaderboard-data/anthropic-sdk-python.json) |
| 2 | [`gstack`](https://github.com/garrytan/gstack) | 86k | **C** | 72.7 | 49 | 1 | 7 | 190s | $9.16 | [📄](reports/gstack.html) | [📦](../leaderboard-data/gstack.json) |
| 3 | [`gbrain`](https://github.com/garrytan/gbrain) | 12k | **C+** | 73.0 | 61 | 0 | 7 | 264s | $5.25 | [📄](reports/gbrain.html) | [📦](../leaderboard-data/gbrain.json) |
| 4 | [`gbrain-evals`](https://github.com/garrytan/gbrain-evals) | 65 | **C+** | 76.1 | 55 | 1 | 6 | 276s | $6.32 | [📄](reports/gbrain-evals.html) | [📦](../leaderboard-data/gbrain-evals.json) |
| 5 | [`alphaclaw`](https://github.com/garrytan/alphaclaw) | ~64 | **C+** | 74.6 | 50 | 0 | 7 | 234s | $5.30 | [📄](reports/alphaclaw.html) | [📦](../leaderboard-data/alphaclaw.json) |

**Totals: 265 findings · 2 critical · 27 high · $33.44 real Anthropic spend across all 5 scans.**

Verified against the Anthropic console: cost numbers reflect honest Opus 4.7 pricing ($5/M input + $25/M output) at the typical 70/30 input/output split. The earlier 3× cost-overstatement bug (PR #28) is fixed in v0.3.2.

---

## `anthropic-sdk-python` — Grade B+ (85.6)

📄 **[Full HTML report](reports/anthropic-sdk-python.html)** · 📦 **[Raw JSON](../leaderboard-data/anthropic-sdk-python.json)** · 🔗 **[Repo on GitHub](https://github.com/anthropics/anthropic-sdk-python)**

**Findings:** 50 total — 🟡 16 medium · 🟢 20 low · ⚪ 14 info
**Wall-clock:** 248s · **Cost:** $7.41 · **Tokens:** 673,411

### Per-dimension scores

| Dimension | Grade | Score | Weight | Findings |
|---|:---:|---:|---:|---:|
| Performance | A | 92.3 | 10% | 1 |
| Security | A | 90.9 | 25% | 10 |
| Maintainability | B+ | 85.9 | 10% | 10 |
| Quality | B+ | 85.8 | 20% | 5 |
| Architecture | B | 81.2 | 25% | 10 |
| Documentation | C+ | 76.1 | 10% | 14 |

### Top findings (clickable entry points → GitHub)

- 🟡 **MEDIUM** · [`src/anthropic/_streaming.py:96`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_streaming.py#L96)
  - **SSE event-name dispatch is a hand-maintained string ladder duplicated sync/async**
  - Stream.__stream__ and AsyncStream.__stream__ both contain an enormous `or`-chain enumerating ~25 SSE event names (`message_start`, `agent.tool_use`, `session.deleted`, etc.). The list is duplicated verbatim in two places. Adding a new server-side event requires editing two locations; forgetting one …
  - *Fix:* Define a module-level `_KNOWN_EVENT_TYPES: frozenset[str]` (or a small dispatch table) shared by both Stream and AsyncStream. The dispatch loop becomes `if sse.event in _KNOWN_EVENT_TYPES:` and the tw…
  - *agent: `architecture` · confidence: 0.95 · est: 1.5h*

- 🟡 **MEDIUM** · [`src/anthropic/_streaming.py`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_streaming.py)
  - **Long stream event matching uses repetitive or-chain instead of set/lookup**
  - Both Stream.__stream__ and AsyncStream.__stream__ in _streaming.py contain a large if-statement chaining 30+ string equality checks via `or` operators. This is duplicated between sync and async implementations and is hard to maintain — adding a new event type requires editing two places. Cyclomatic …
  - *Fix:* Define a module-level frozenset of known event names (e.g., `_KNOWN_EVENTS = frozenset({...})`) and replace the chained or-comparisons with `if sse.event in _KNOWN_EVENTS:`. This reduces complexity, d…
  - *agent: `quality` · confidence: 0.95 · est: 1.0h*

- 🟡 **MEDIUM** · [`src/anthropic/_legacy_response.py:188`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_legacy_response.py#L188)
  - **Massive duplication between APIResponse and LegacyAPIResponse**
  - _response.py and _legacy_response.py contain near-identical parsing logic in BaseAPIResponse._parse and LegacyAPIResponse._parse (handling of TypeAlias unwrap, Annotated unwrap, JSONLDecoder, stream_cls, NoneType, str/int/float/bool, httpx.Response, BaseModel coercion, content-type parsing). Both co…
  - *Fix:* Extract a shared `_parse_to_python(response, cast_to, *, is_stream, stream_cls, client, options)` free function and call it from both LegacyAPIResponse._parse and BaseAPIResponse._parse. Keep the publ…
  - *agent: `architecture` · confidence: 0.90 · est: 6.0h*

- 🟡 **MEDIUM** · [`src/anthropic/_base_client.py:877`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_base_client.py#L877)
  - **Sync/async request loop duplicated nearly verbatim in BaseClient subclasses**
  - SyncAPIClient.request and AsyncAPIClient.request implement the same retry/backoff/timeout/HTTP-status-error pipeline (lines ~877-1004 vs ~1182-1320 in _base_client.py) with only `await`/`anyio.sleep` vs `time.sleep` differing. This is hundreds of lines of duplicated control flow — any change to retr…
  - *Fix:* Factor the retry/error-handling pipeline into a generic helper that takes `send`/`sleep`/`close_response` callables (one sync set, one async set). Alternatively, push the loop body into pure functions…
  - *agent: `architecture` · confidence: 0.90 · est: 12.0h*

- 🟡 **MEDIUM** · [`src/anthropic/_base_client.py`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_base_client.py)
  - **Significant code duplication between sync/async client implementations**
  - The Anthropic and AsyncAnthropic classes in _client.py duplicate ~150 lines of nearly identical code (constructor, copy(), _make_status_error, _validate_headers, _api_key_auth, _bearer_auth, default_headers). Similar duplication exists between SyncAPIClient and AsyncAPIClient in _base_client.py for …
  - *Fix:* Extract shared socket option / transport setup into a helper function. Acknowledge that some duplication is required between sync/async due to await semantics, but the transport/socket configuration b…
  - *agent: `quality` · confidence: 0.90 · est: 4.0h*

- 🟡 **MEDIUM** · [`src/anthropic/_client.py:168`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_client.py#L168)
  - **`copy`/`with_options` parameters undocumented**
  - `Anthropic.copy` and `AsyncAnthropic.copy` (aliased as `with_options`) accept a number of subtle parameters — `default_headers` vs `set_default_headers`, `default_query` vs `set_default_query`, and `_extra_kwargs` — whose mutual-exclusion semantics and merge behavior are non-obvious. The docstring i…
  - *Fix:* Document each parameter in the `copy` docstring, explicitly explaining: (a) `default_headers` merges with existing headers while `set_default_headers` replaces them, (b) the same for query params, (c)…
  - *agent: `documentation` · confidence: 0.90 · est: 1.5h*

- 🟡 **MEDIUM** · [`src/anthropic/_exceptions.py:79`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_exceptions.py#L79)
  - **Exception class hierarchy lacks docstrings on most concrete error types**
  - In `_exceptions.py`, only `APIStatusError`, `APIError.body`, and `APITimeoutError` (via its message) carry any documentation. The eight concrete status-code subclasses (`BadRequestError`, `AuthenticationError`, `PermissionDeniedError`, `NotFoundError`, `ConflictError`, `RequestTooLargeError`, `Unpro…
  - *Fix:* Add a one-paragraph docstring to each concrete exception class describing the API condition that produces it and reminding users of the available attributes. Also add a module-level docstring summariz…
  - *agent: `documentation` · confidence: 0.90 · est: 1.5h*

- 🟡 **MEDIUM** · [`src/anthropic/_constants.py:21`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_constants.py#L21)
  - **`MODEL_NONSTREAMING_TOKENS` constant is undocumented**
  - `_constants.py` defines `MODEL_NONSTREAMING_TOKENS`, a model->token threshold map used by `_calculate_nonstreaming_timeout` to decide when streaming is required. There is no docstring explaining what the dictionary represents, when entries should be added, or how end users should interpret it. Becau…
  - *Fix:* Add a comment/docstring above `MODEL_NONSTREAMING_TOKENS` explaining: the keys are model identifiers (including Bedrock/Vertex variants), the values are the maximum `max_tokens` allowed for non-stream…
  - *agent: `documentation` · confidence: 0.90 · est: 0.5h*

---

## `gstack` — Grade C (72.7)

📄 **[Full HTML report](reports/gstack.html)** · 📦 **[Raw JSON](../leaderboard-data/gstack.json)** · 🔗 **[Repo on GitHub](https://github.com/garrytan/gstack)**

**Findings:** 49 total — 🔴 1 critical · 🟠 7 high · 🟡 15 medium · 🟢 15 low · ⚪ 11 info
**Wall-clock:** 190s · **Cost:** $9.16 · **Tokens:** 832,859

### Per-dimension scores

| Dimension | Grade | Score | Weight | Findings |
|---|:---:|---:|---:|---:|
| Documentation | A- | 89.6 | 10% | 12 |
| Performance | B | 80.8 | 10% | 5 |
| Maintainability | B- | 79.0 | 10% | 10 |
| Security | C | 71.4 | 25% | 7 |
| Architecture | C- | 67.2 | 25% | 10 |
| Quality | D+ | 65.4 | 20% | 5 |

### Top findings (clickable entry points → GitHub)

- 🔴 **CRITICAL** · [`browse/src/cli.ts`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/cli.ts)
  - **Syntax error in cli.ts disconnect handler — invalid JSON.stringify body**
  - In handlePairAgent's disconnect path, the body of fetch contains a stray `domains,` line inside JSON.stringify that references an undeclared variable in this scope, breaking compilation. This indicates either dead code from a bad merge or a broken disconnect flow that never actually runs/compiles. C…
  - *Fix:* Remove the orphaned `domains,` line from the JSON.stringify({ command: 'disconnect', args: [] }) call. Add a build/typecheck step (tsc --noEmit) to the test script to catch syntax errors before commit…
  - *agent: `quality` · confidence: 0.95 · est: 0.5h*

- 🟠 **HIGH** · [`browse/src/server.ts`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/server.ts)
  - **server.ts is a 1500+ line monolith mixing routing, business logic, and lifecycle**
  - browse/src/server.ts is a single file containing: HTTP routing for ~20 endpoints, dual-listener tunnel management, ngrok integration, SSE streaming for activity + inspector, command dispatch with security pipeline (scope/domain/tab/rate/audit/wrapping), idle/parent-process watchdogs, signal handlers…
  - *Fix:* Introduce a minimal route table (Map<{method, path}, handler>) and split handlers into route modules: routes/auth.ts (/connect, /pair, /token, /agents, /sse-session, /pty-session), routes/command.ts (…
  - *agent: `architecture` · confidence: 0.95 · est: 20.0h*

- 🟠 **HIGH** · [`browse/src/server.ts`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/server.ts)
  - **server.ts is a 1500+ line god module with mixed concerns**
  - browse/src/server.ts handles HTTP routing, auth, tunnel management, SSE streaming, inspector state, PTY handshake, audit logging, idle/parent watchdogs, signal handling, port discovery, command dispatch, and lifecycle — all in one file. The makeFetchHandler closure alone spans hundreds of lines with…
  - *Fix:* Extract route groups into modules: routes/auth.ts (/connect, /token, /pair), routes/inspector.ts, routes/sse.ts, routes/batch.ts, routes/tunnel.ts. Keep server.ts as the wiring layer (<300 lines). Thi…
  - *agent: `quality` · confidence: 0.95 · est: 16.0h*

- 🟠 **HIGH** · [`browse/src/browser-manager.ts`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/browser-manager.ts)
  - **Unbounded response body buffering for network capture**
  - In browser-manager.ts wirePageEvents(), every requestfinished event calls `await res.body()` which loads the full response body into memory just to compute its byte length. For pages that download large assets (videos, PDFs, large JSON), this allocates the full payload (potentially hundreds of MB) p…
  - *Fix:* Use the Content-Length response header when present, or fall back to a size cap (e.g., skip body() for responses where headers indicate >1MB; or read response.headers()['content-length']). Never downl…
  - *agent: `performance` · confidence: 0.95 · est: 1.5h*

- 🟠 **HIGH** · [`browse/src/browser-manager.ts`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/browser-manager.ts)
  - **God object: BrowserManager has 40+ public methods spanning 8 unrelated concerns**
  - BrowserManager in browser-manager.ts is a classic god object. It owns: lifecycle (launch/close/handoff), tab management, ownership/multi-agent isolation, dialog handling, cookie tracking, viewport/UA, watch mode, ref maps, snapshot diffing, frame context, two-tier CDP mutex, headed mode patches, ant…
  - *Fix:* Extract focused collaborators: (1) TabRegistry (pages/sessions/ownership), (2) CdpMutex (two-tier locking), (3) HeadedBrandingService (plist/icon patching), (4) StateSerializer (saveState/restoreState…
  - *agent: `architecture` · confidence: 0.92 · est: 24.0h*

- 🟠 **HIGH** · [`browse/src/server.ts`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/server.ts)
  - **Auth token leaked via /health endpoint without origin restriction**
  - The /health endpoint returns the daemon's root AUTH_TOKEN unconditionally when in headed mode, and to any caller whose Origin header starts with 'chrome-extension://'. The Origin header is client-controlled in non-browser contexts (curl, fetch from any process on the host), and any local process on …
  - *Fix:* Remove the token from /health entirely. Use a separate authenticated bootstrap endpoint that requires either a one-time exchange code (similar to setup_key flow) or a filesystem-protected handoff (rea…
  - *agent: `security` · confidence: 0.92 · est: 4.0h*

- 🟠 **HIGH** · [`browse/src/browser-manager.ts`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/browser-manager.ts)
  - **BrowserManager class spans 800+ lines with too many responsibilities**
  - BrowserManager owns browser lifecycle, tab management, dialog handling, ownership tracking, viewport/UA state, watch mode, headed/handoff state, CDP locks (two-tier mutex), state save/restore, ref maps, frame context, cookie tracking, Chromium binary patching for branding, and stealth init scripts. …
  - *Fix:* Split responsibilities: extract HeadedLauncher (plist+icon+UA), AntiDetectionScripts (stealth init), TabOwnership, CdpLockManager, StateSnapshotter. Keep BrowserManager focused on Browser/Context/Page…
  - *agent: `quality` · confidence: 0.90 · est: 24.0h*

- 🟠 **HIGH** · [`browse/src/cli.ts:478`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/cli.ts#L478)
  - **Module boundary violation: browse CLI imports host config via dynamic absolute path**
  - browse/src/cli.ts dynamically imports hosts/index.ts using path.resolve(__dirname, '..', '..', 'hosts', 'index.ts'). This creates a hidden cross-module dependency from the browse subsystem (which compiles to a standalone binary) into the hosts/ registry. It bypasses the module system, breaks in comp…
  - *Fix:* Either (a) extract host globalRoot resolution into a small data file (e.g., hosts/globals.json) that browse can read, (b) accept the globalRoot as a CLI argument from the calling skill, or (c) move th…
  - *agent: `architecture` · confidence: 0.88 · est: 4.0h*

---

## `gbrain` — Grade C+ (73.0)

📄 **[Full HTML report](reports/gbrain.html)** · 📦 **[Raw JSON](../leaderboard-data/gbrain.json)** · 🔗 **[Repo on GitHub](https://github.com/garrytan/gbrain)**

**Findings:** 61 total — 🟠 7 high · 🟡 26 medium · 🟢 22 low · ⚪ 6 info
**Wall-clock:** 264s · **Cost:** $5.25 · **Tokens:** 477,328

### Per-dimension scores

| Dimension | Grade | Score | Weight | Findings |
|---|:---:|---:|---:|---:|
| Security | B+ | 86.5 | 25% | 7 |
| Performance | B | 80.9 | 10% | 7 |
| Documentation | C+ | 76.4 | 10% | 14 |
| Maintainability | C+ | 73.9 | 10% | 8 |
| Architecture | C- | 67.2 | 25% | 11 |
| Quality | D- | 57.5 | 20% | 14 |

### Top findings (clickable entry points → GitHub)

- 🟠 **HIGH** · [`package.json:41`](https://github.com/garrytan/gbrain/blob/HEAD/package.json#L41)
  - **@types/bun: latest — non-deterministic builds**
  - `"@types/bun": "latest"` in devDependencies resolves to whatever is current at install time. While the lockfile pins the actual resolved version, this is an anti-pattern that defeats reproducibility for any contributor running `bun install` after lockfile drift, and signals to tools that any version…
  - *Fix:* Replace `"latest"` with the currently-resolved version from bun.lock (e.g., `"^1.x.y"` matching the Bun runtime version). Pin both @types/bun and the implied Bun runtime in package.json's `engines` fi…
  - *agent: `dependency` · confidence: 0.98 · est: 0.2h*

- 🟠 **HIGH** · [`src/commands/call.ts:2`](https://github.com/garrytan/gbrain/blob/HEAD/src/commands/call.ts#L2)
  - **Command layer reaches into MCP transport (cross-layer dependency)**
  - src/commands/call.ts imports handleToolCall from '../mcp/server.ts'. This inverts the expected layering: commands should depend on core (operations, engine), not on a transport adapter. The MCP server should depend on operations, and `gbrain call` should also dispatch through operations directly — n…
  - *Fix:* Refactor `gbrain call` to import dispatchToolCall from src/mcp/dispatch.ts (or better: a renamed src/core/dispatch.ts since dispatch is transport-agnostic). Move dispatch.ts under src/core/ since it's…
  - *agent: `architecture` · confidence: 0.95 · est: 2.0h*

- 🟠 **HIGH** · [`src/cli.ts:153`](https://github.com/garrytan/gbrain/blob/HEAD/src/cli.ts#L153)
  - **Pervasive use of 'any' type undermines TypeScript strictness**
  - Despite TypeScript usage, the codebase contains numerous `as any` casts and `: any` type annotations in critical paths (cli.ts formatResult, mcp/server.ts request handlers, autopilot.ts engine probes, auth.ts error handling). This defeats the value of TypeScript's type system, particularly in the CL…
  - *Fix:* Define explicit result types for each operation (GetPageResult, ListPagesResult, etc.) and replace `as any` casts with proper type narrowing. For MCP SDK width issues, create a local typed interface r…
  - *agent: `quality` · confidence: 0.95 · est: 8.0h*

- 🟠 **HIGH** · [`src/cli.ts:246`](https://github.com/garrytan/gbrain/blob/HEAD/src/cli.ts#L246)
  - **Massive command dispatcher in cli.ts violates single responsibility**
  - The handleCliOnly function in cli.ts is approximately 230 lines containing 30+ if/switch branches for command dispatch, each duplicating the dynamic-import pattern. This is a textbook God Function: high cyclomatic complexity (~30+), difficult to test, and adding/removing commands requires touching t…
  - *Fix:* Extract to a command registry pattern: `commandRegistry.register({ name, needsEngine, lazyImport })`. Drive both CLI_ONLY membership and dispatch from one source of truth. Cuts ~200 lines and eliminat…
  - *agent: `quality` · confidence: 0.95 · est: 6.0h*

- 🟠 **HIGH** · [`src/commands/autopilot.ts:116`](https://github.com/garrytan/gbrain/blob/HEAD/src/commands/autopilot.ts#L116)
  - **Long function with high complexity: runAutopilot**
  - src/commands/autopilot.ts:runAutopilot is ~250 lines with worker spawn, lock file handling, signal handlers, dispatch loop, peer-liveness probe, health check, adaptive interval, and shutdown logic all interleaved. Cyclomatic complexity is high (>15 branches), and the function is impossible to unit-t…
  - *Fix:* Extract: `acquireLock()`, `spawnManagedWorker(cliPath)`, `dispatchOneCycle(engine, mode)`, `runPeerLivenessProbe(engine)`, `runAdaptiveSleep(score, base)`. Each extraction unblocks unit testing. Aim f…
  - *agent: `quality` · confidence: 0.95 · est: 8.0h*

- 🟠 **HIGH** · [`src/cli.ts:22`](https://github.com/garrytan/gbrain/blob/HEAD/src/cli.ts#L22)
  - **CLI dispatcher is a god-function with hardcoded command registry**
  - src/cli.ts contains a 60+ entry CLI_ONLY Set and a giant switch/if-else chain in handleCliOnly that hardcodes every command name and its dynamic import path. Adding a command requires touching 3+ places (CLI_ONLY set, handleCliOnly switch, help text). This violates open-closed principle and is the s…
  - *Fix:* Introduce a command registry pattern: each command module exports a CommandSpec { name, needsEngine, handler, help } and a barrel file aggregates them. Replace the switch with a Map lookup, mirroring …
  - *agent: `architecture` · confidence: 0.93 · est: 8.0h*

- 🟠 **HIGH** · [`src/commands/auth.ts:17`](https://github.com/garrytan/gbrain/blob/HEAD/src/commands/auth.ts#L17)
  - **Auth command bypasses engine abstraction with raw postgres driver**
  - src/commands/auth.ts imports `postgres` directly and uses raw SQL via the postgres tagged template, completely bypassing BrainEngine. This means: (a) the command will not work with PGLite brains despite the rest of the system supporting both engines, (b) it duplicates connection/config logic (DATABA…
  - *Fix:* Refactor auth.ts to receive a BrainEngine and use engine.executeRaw() for the access_tokens CRUD. Either route through cli.ts's connectEngine() or expose a thin AuthRepository in core/ that both engin…
  - *agent: `architecture` · confidence: 0.92 · est: 3.0h*

- 🟡 **MEDIUM** · [`src/commands/agent.ts:167`](https://github.com/garrytan/gbrain/blob/HEAD/src/commands/agent.ts#L167)
  - **Duplicated subagent data construction in agent.ts fanout path**
  - In runFanout (src/commands/agent.ts), the SubagentHandlerData object construction is duplicated verbatim between the single-entry short-circuit and the N-entry loop (~12 lines each). This violates DRY and any future field added to subagent submission must be edited in both places.
  - *Fix:* Extract `buildSubagentData(entry, flags, promptTemplate): SubagentHandlerData` and call it from both branches. Same for the `submitOpts` construction.
  - *agent: `quality` · confidence: 0.95 · est: 1.0h*

---

## `gbrain-evals` — Grade C+ (76.1)

📄 **[Full HTML report](reports/gbrain-evals.html)** · 📦 **[Raw JSON](../leaderboard-data/gbrain-evals.json)** · 🔗 **[Repo on GitHub](https://github.com/garrytan/gbrain-evals)**

**Findings:** 55 total — 🔴 1 critical · 🟠 6 high · 🟡 27 medium · 🟢 19 low · ⚪ 2 info
**Wall-clock:** 276s · **Cost:** $6.32 · **Tokens:** 574,385

### Per-dimension scores

| Dimension | Grade | Score | Weight | Findings |
|---|:---:|---:|---:|---:|
| Security | B+ | 85.4 | 25% | 8 |
| Quality | B | 81.5 | 20% | 7 |
| Documentation | C | 72.2 | 10% | 9 |
| Architecture | C | 71.3 | 25% | 13 |
| Performance | C | 70.4 | 10% | 10 |
| Maintainability | D+ | 63.3 | 10% | 8 |

### Top findings (clickable entry points → GitHub)

- 🔴 **CRITICAL** · [`package.json:32`](https://github.com/garrytan/gbrain-evals/blob/HEAD/package.json#L32)
  - **Git dependency pinned to mutable branch (master) instead of commit SHA**
  - `gbrain` is sourced from `github:garrytan/gbrain#master` — pinning to a branch ref. Any push to master in the upstream repo silently changes what users install with no version bump, breaking reproducibility of every benchmark run and creating a supply-chain risk (a compromised or rewritten master wo…
  - *Fix:* Pin gbrain to an immutable commit SHA: `"gbrain": "github:garrytan/gbrain#<40-char-sha>"`. Better, publish gbrain to npm (or a private registry) with semver and consume `"gbrain": "^X.Y.Z"`. Pair with…
  - *agent: `dependency` · confidence: 0.98 · est: 1.0h*

- 🟠 **HIGH** · [`eval/generators/amara-life-gen.ts:75`](https://github.com/garrytan/gbrain-evals/blob/HEAD/eval/generators/amara-life-gen.ts#L75)
  - **Generator scripts assume undocumented .env.testing file with cross-worktree discovery**
  - Both eval/generators/gen.ts and eval/generators/amara-life-gen.ts require a .env.testing file at the repo root and throw with a cryptic message instructing users to 'Copy it from a sibling worktree'. There is no documented onboarding path for a fresh contributor who has no sibling worktree. The .env…
  - *Fix:* Provide an .env.testing.example template at the repo root listing required keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, GROQ_API_KEY) with placeholder values and a comment block. Document in eval/RUNBOOK.…
  - *agent: `documentation` · confidence: 0.95 · est: 1.5h*

- 🟠 **HIGH** · [`eval/runner/all.ts:90`](https://github.com/garrytan/gbrain-evals/blob/HEAD/eval/runner/all.ts#L90)
  - **Cat 5/8/9 'programmatic-only' runners lack external harness documentation**
  - eval/runner/all.ts explicitly skips Cat 5 (provenance), Cat 8 (skill compliance), and Cat 9 (workflows) because they require runtime inputs (claims, probes, scenarios, pre-seeded state). The code says 'Run via runCatN({...}) from a harness' but no harness, example, or test fixture is referenced. A c…
  - *Fix:* Add an example harness file (e.g., eval/runner/harness/programmatic-cats.ts) demonstrating how to invoke runCat5/runCat8/runCat9 with sample inputs, and document this in eval/RUNBOOK.md. At minimum, t…
  - *agent: `documentation` · confidence: 0.92 · est: 4.0h*

- 🟠 **HIGH** · [`eval/generators/amara-life-gen.ts`](https://github.com/garrytan/gbrain-evals/blob/HEAD/eval/generators/amara-life-gen.ts)
  - **Sequential per-item LLM generation in amara-life-gen wastes wall time**
  - All four item types (50 emails, 300 slack messages, 8 meetings, 40 notes — ~398 LLM calls total) are generated in serial `for...of await` loops. With Opus latency typically 5-15s per call, this means ~30-100 minutes of wall time even though Anthropic supports concurrent requests. The HARD_STOP_USD c…
  - *Fix:* Wrap each batch (emails, slack, meetings, notes) with a bounded concurrency pool (e.g., `p-limit(6)` or hand-rolled worker queue like the one in `gen.ts`). Read concurrency from env (`BRAINBENCH_LLM_C…
  - *agent: `performance` · confidence: 0.90 · est: 3.0h*

- 🟠 **HIGH** · [`eval/runner/adapters/claude-sonnet-with-tools.ts:145`](https://github.com/garrytan/gbrain-evals/blob/HEAD/eval/runner/adapters/claude-sonnet-with-tools.ts#L145)
  - **Adapter interface contract violated by agent adapter**
  - ClaudeSonnetWithToolsAdapter implements the Adapter interface but its query() method throws unconditionally. This is a Liskov Substitution violation — any code iterating over adapters generically (e.g., multi-adapter dispatch) must special-case this adapter. The interface should be split into Retrie…
  - *Fix:* Introduce two interfaces: RetrievalAdapter (with query) and AgentAdapter (with runAgentLoop). Have ClaudeSonnetWithToolsAdapter implement only AgentAdapter. Update types.ts to export both, and let run…
  - *agent: `architecture` · confidence: 0.88 · est: 4.0h*

- 🟠 **HIGH** · [`package.json:30`](https://github.com/garrytan/gbrain-evals/blob/HEAD/package.json#L30)
  - **Missing lockfile in repository**
  - The provided file listing shows package.json but no bun.lockb, package-lock.json, or yarn.lock. Without a committed lockfile, dependency resolution is non-deterministic across developers, CI, and time — which directly undermines the BrainBench benchmark's reproducibility claims (the report includes …
  - *Fix:* Run `bun install` and commit the resulting `bun.lockb` to the repo. Update .gitignore to ensure the lockfile is NOT ignored. Add a CI check that fails if the lockfile is out of sync (`bun install --fr…
  - *agent: `dependency` · confidence: 0.85 · est: 0.5h*

- 🟠 **HIGH** · [`eval/runner/adapters/claude-sonnet-with-tools.ts:270`](https://github.com/garrytan/gbrain-evals/blob/HEAD/eval/runner/adapters/claude-sonnet-with-tools.ts#L270)
  - **Agent loop appends full message history every turn — token cost grows quadratically**
  - Each turn appends the full assistant response (including tool_use blocks) and tool_result blocks back into `messages`, then re-sends the entire history on the next call. Tool results can be large (search returning 10+ chunks of compiled_truth), so input tokens grow O(turns²). With turnCap=10 and lar…
  - *Fix:* Apply `cache_control: { type: 'ephemeral' }` to the last static prefix of `messages` each turn (Anthropic's prompt-cache supports up to 4 cache breakpoints; one on system + one on the last assistant t…
  - *agent: `performance` · confidence: 0.85 · est: 4.0h*

- 🟡 **MEDIUM** · [`eval/generators/amara-life-gen.ts`](https://github.com/garrytan/gbrain-evals/blob/HEAD/eval/generators/amara-life-gen.ts)
  - **Bug in writeDocs path construction — dead/confusing code**
  - In amara-life-gen.ts writeDocs(), the line `const path = join(CORPUS_ROOT, slugPath + '.md'.replace(/\.md$/, '') === slugPath ? slugPath : slugPath);` is computed but never used (fullPath is built independently and used). The expression is also semantically nonsensical: `'.md'.replace(/\.md$/, '')` …
  - *Fix:* Remove the unused `const path = ...` line entirely. Keep only `const fullPath = join(CORPUS_ROOT, slugPath);` and the writeFileSync call. Add a unit test that writeDocs writes to the expected paths.
  - *agent: `quality` · confidence: 0.98 · est: 0.5h*

---

## `alphaclaw` — Grade C+ (74.6)

📄 **[Full HTML report](reports/alphaclaw.html)** · 📦 **[Raw JSON](../leaderboard-data/alphaclaw.json)** · 🔗 **[Repo on GitHub](https://github.com/garrytan/alphaclaw)**

**Findings:** 50 total — 🟠 7 high · 🟡 22 medium · 🟢 15 low · ⚪ 6 info
**Wall-clock:** 234s · **Cost:** $5.30 · **Tokens:** 482,023

### Per-dimension scores

| Dimension | Grade | Score | Weight | Findings |
|---|:---:|---:|---:|---:|
| Security | B+ | 86.5 | 25% | 2 |
| Maintainability | B+ | 83.8 | 10% | 5 |
| Performance | B | 80.8 | 10% | 8 |
| Architecture | C | 70.5 | 25% | 9 |
| Documentation | C- | 67.8 | 10% | 13 |
| Quality | D | 60.6 | 20% | 13 |

### Top findings (clickable entry points → GitHub)

- 🟠 **HIGH** · [`lib/public/js/app.js:217`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/app.js#L217)
  - **Inconsistent routing strategy: hand-rolled conditionals bypass Switch/Route**
  - Some routes (/general, /doctor, /telegram, /usage, /webhooks, /watchdog) are declared inside <Switch> with proper <Route> elements, while /agents, /chat, /cron, /envars, /models, /nodes are mounted via plain conditional rendering using location.startsWith(). This dual routing model means route prece…
  - *Fix:* Pick one routing strategy (recommend wouter <Switch>/<Route>) and migrate all panes into it. The barrel in components/routes/index.js already exports route components — use them uniformly inside the S…
  - *agent: `architecture` · confidence: 0.92 · est: 8.0h*

- 🟠 **HIGH** · [`lib/public/js/app.js:64`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/app.js#L64)
  - **Monolithic App component with excessive route-specific knowledge**
  - lib/public/js/app.js acts as a god component: it owns location parsing for /agents, /chat, /cron, /envars, /models, /nodes, manually checks isXRoute booleans, extracts selectedAgentId/selectedCronJobId via regex, and mounts route components conditionally outside the Switch. This bypasses wouter-prea…
  - *Fix:* Move all route mounting into the <Switch> with <Route> declarations and use route params (via wouter useParams) instead of regex parsing of location. Extract sidebar wiring into a separate AppShell co…
  - *agent: `architecture` · confidence: 0.90 · est: 12.0h*

- 🟠 **HIGH** · [`lib/public/js/app.js:47`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/app.js#L47)
  - **Massive App component with excessive responsibilities (~470 lines)**
  - The App component in lib/public/js/app.js spans roughly 470 lines and orchestrates onboarding, sidebar, routing for 15+ routes, browse navigation, agent selection, chat sessions, doctor warnings, and UI settings persistence. It composes 5 hooks, contains 3 useEffects with mixed concerns, 3 inline II…
  - *Fix:* Extract a RouteSwitcher component for the route ternaries, move route param derivation (selectedAgentId, agentDetailTab, selectedCronJobId) into a useRouteParams hook, and split the StatusBar/MobileTo…
  - *agent: `quality` · confidence: 0.90 · est: 8.0h*

- 🟠 **HIGH** · [`lib/public/js/components/doctor/index.js:38`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/components/doctor/index.js#L38)
  - **DoctorTab component exceeds 400 lines with deeply nested ternary rendering**
  - lib/public/js/components/doctor/index.js DoctorTab is over 450 lines with 4 useEffects containing complex dependency-driven state synchronization (selectedRunFilter reset logic, pendingRunSelectionId reconciliation), 14+ useMemo/derived values, and multi-level nested ternary template rendering (show…
  - *Fix:* Extract a useDoctorRunSelection hook to encapsulate run filter reconciliation. Move banner/empty-state/findings panels into separate sub-components. Replace nested ternaries with early returns or a sw…
  - *agent: `quality` · confidence: 0.90 · est: 12.0h*

- 🟠 **HIGH** · [`lib/public/js/app.js:215`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/app.js#L215)
  - **Hash-router routes have no central documentation**
  - lib/public/js/app.js declares the entire client-side route map (/general, /doctor, /telegram/:accountId, /providers, /watchdog, /usage, /usage/:sessionId, /webhooks, /webhooks/:hookName, /agents, /chat, /cron, /envars, /models, /nodes, /browse) inline in the App component. The plan explicitly flagge…
  - *Fix:* Add a 'Routes' section to README.md or create docs/routes.md enumerating every hash route, its params, the component that renders it, and required state (e.g., onboarded). Optionally add a JSDoc block…
  - *agent: `documentation` · confidence: 0.90 · est: 3.0h*

- 🟠 **HIGH** · [`lib/public/js/components/google/index.js:30`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/components/google/index.js#L30)
  - **Google component has 18+ state variables and 12+ handlers in one file**
  - lib/public/js/components/google/index.js has 18+ pieces of useState and useMemo state (expandedAccountId, scopesByAccountId, savedScopesByAccountId, apiStatusByAccountId, checkingByAccountId, addMenuOpen, credentialsModalState, addCompanyModalOpen, savingAddCompany, disconnectAccountId, gmailWizardS…
  - *Fix:* Extract a useGoogleAccountActions hook covering credential modal state and auth flows; extract a useApiStatusChecker hook for the apiStatus/checking maps. Move handleAddCompanyAccount/handleAddCompany…
  - *agent: `quality` · confidence: 0.88 · est: 6.0h*

- 🟠 **HIGH** · [`lib/plugin/usage-tracker/index.js:174`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/plugin/usage-tracker/index.js#L174)
  - **Synchronous SQLite writes in usage-tracker block event loop on every LLM/tool event**
  - writeUsageEvent() and writeToolEvent() use DatabaseSync (node:sqlite synchronous binding) on the hot path of every llm_output and tool_result_persist event. Each LLM completion triggers two sequential synchronous writes (insertUsageEventStmt.run + upsertUsageDailyStmt.run) which block the Node.js ev…
  - *Fix:* Either (a) wrap the two writes in a single transaction (BEGIN/COMMIT) to halve the fsync cost; (b) batch events in memory and flush every N ms / N events; or (c) move writes to a worker_thread. Given …
  - *agent: `performance` · confidence: 0.85 · est: 6.0h*

- 🟡 **MEDIUM** · [`lib/public/js/components/telegram-workspace/index.js:33`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/components/telegram-workspace/index.js#L33)
  - **Silent error swallowing in catch blocks**
  - Multiple catch blocks silently swallow errors with empty bodies, hiding failures that could indicate genuine bugs. In app.js: `try { window.localStorage.clear(); ... } catch {}`. In telegram-workspace/index.js: `} catch {}` appears in 6 places (loadTelegramWorkspaceState, save/remove variants, boots…
  - *Fix:* At minimum, log errors via console.warn or a logger. Distinguish between expected errors (e.g., JSON.parse on missing key) and unexpected ones. Avoid blanket `catch {}`.
  - *agent: `quality` · confidence: 0.95 · est: 2.0h*

---

## Methodology

- All scans use **full mode** (8 agents including CritiqueAgent — `--no-cache` for honest cold-run cost).
- Models: all 8 agents on Claude Opus 4.7 with per-role effort tuning (meta=medium, specialists=xhigh, critique=high+task_budget).
- Per-dimension weights: Architecture 25%, Security 25%, Quality 20%, Documentation 10%, Maintainability 10%, Performance 10%.
- Cost = sum of input + output tokens × Opus 4.7 pricing ($5/M input, $25/M output) at the typical 70/30 split.
- Scans done 2026-04-29 by Vivek Kumar.

## Reproduce

```bash
pip install spectra-ai==0.3.2
export ANTHROPIC_API_KEY=sk-ant-...
spectra analyze https://github.com/<owner>/<repo>
# default output is HTML; pass --format json -o report.json for CI integration
```

Raw JSON outputs and full HTML reports are checked into [`docs/leaderboard-data/`](../leaderboard-data/) and [`docs/launch/reports/`](reports/) respectively — the source of truth for every number above.
