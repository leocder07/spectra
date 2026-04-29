# Spectra Leaderboard — Real OSS Scans

Live scans of well-known open-source projects, run with `spectra-ai==0.3.2`
on Claude Opus 4.7 (`--quick --no-cache`). All findings link to the actual
file:line on GitHub. No cherry-picking — each scan is one shot.

## Summary

| Rank | Repo | Stars | Grade | Score | Findings | Critical | High | Cost | Wall |
|---:|---|---:|:---:|---:|---:|---:|---:|---:|---:|
| 1 | [`anthropic-sdk-python`](https://github.com/anthropics/anthropic-sdk-python) | Anthropic | **B** | 82.5 | 55 | 0 | 3 | $6.82 | 168s |
| 2 | [`gstack`](https://github.com/garrytan/gstack) | 86k | **C** | 72.0 | 54 | 2 | 8 | $9.19 | 187s |
| 3 | [`gbrain`](https://github.com/garrytan/gbrain) | 12k | **C-** | 68.5 | 72 | 0 | 10 | $4.90 | 188s |
| 4 | [`gbrain-evals`](https://github.com/garrytan/gbrain-evals) | 65 | **C+** | 75.2 | 62 | 1 | 9 | $17.29 | 188s |
| 5 | [`alphaclaw`](https://github.com/garrytan/alphaclaw) | ~64 | **C+** | 73.2 | 63 | 0 | 9 | $4.86 | 162s |

> **Note on cost:** v0.3.1 had a 3× cost-overstatement bug (Opus 4.7 prices were copied from the older Opus 4.0/4.1 rate card). The two scans done before that fix (anthropic-sdk-python, alphaclaw) are reported with the corrected cost (`raw ÷ 3`); scans done with v0.3.2+ are direct. Fix shipped in [PR #28](https://github.com/leocder07/spectra/pull/28).

---

## `anthropic-sdk-python` — Grade B (82.5)

**Repo:** https://github.com/anthropics/anthropic-sdk-python
**Findings:** 55 total · 🟠 3 high · 🟡 19 medium · 🟢 23 low · ⚪ 10 info
**Wall-clock:** 168s · **Cost:** $6.82

### Per-dimension

| Dimension | Grade | Score | Weight |
|---|:---:|---:|---:|
| Security | A | 90.0 | 25% |
| Maintainability | A- | 87.2 | 10% |
| Quality | B | 82.8 | 20% |
| Performance | B | 81.6 | 10% |
| Architecture | B- | 77.4 | 25% |
| Documentation | C | 72.4 | 10% |

### Top findings (entry points → GitHub)

- 🟠 **HIGH** · [`src/anthropic/_response.py`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_response.py)
  - **JSONL decoder uses 64-byte chunk size for HTTP iteration**
  - In `_response.py` and `_legacy_response.py`, when constructing JSONLDecoder/AsyncJSONLDecoder the underlying `iter_bytes`/`aiter_bytes` is invoked with `chunk_size=64`. Reading streaming HTTP bodies in 64-byte chunks dramatically increases the number of iterator wakeups, syscalls, and Python-level l…
  - *Fix:* Increase the chunk_size for JSONL streaming to a more reasonable value (e.g. 8192 or omit to use httpx default). 64 bytes is far too small for network streams. Apply the same change in `_legacy_respon…
  - *agent: `performance` · confidence: 0.90 · est: 0.5h*

- 🟠 **HIGH** · [`helpers.md`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/helpers.md)
  - **Streaming/agents SSE event list likely not reflected in helpers.md**
  - Stream.__stream__ and AsyncStream.__stream__ in _streaming.py handle a large set of SSE event types including new agent/session/span events: user.message, user.interrupt, user.tool_confirmation, user.custom_tool_result, agent.message, agent.thinking, agent.tool_use, agent.tool_result, agent.mcp_tool…
  - *Fix:* Audit helpers.md against the event list in src/anthropic/_streaming.py and add a dedicated section documenting agent.*, user.*, session.*, and span.* events, including which payload models each maps t…
  - *agent: `documentation` · confidence: 0.80 · est: 6.0h*

- 🟠 **HIGH** · [`examples/agents.py`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/examples/agents.py)
  - **Examples directory likely missing coverage for agents, sessions, skills, and vaults**
  - The PLAN file lists only examples/agents.py, examples/messages_stream.py, and examples/tools_runner.py for documentation review and explicitly flags 'examples coverage of new agents/sessions/skills/vaults' as a concern. The streaming code clearly supports session.* and span.* events, and pyproject.t…
  - *Fix:* Add example scripts under examples/ for each new product surface: examples/sessions_basic.py, examples/sessions_streaming.py, examples/skills_create_and_run.py, and examples/vaults_secret_usage.py. En…
  - *agent: `documentation` · confidence: 0.70 · est: 12.0h*

- 🟡 **MEDIUM** · [`src/anthropic/_streaming.py`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_streaming.py)
  - **Long, repeated SSE event-name string check in Stream and AsyncStream**
  - Both Stream.__stream__ and AsyncStream.__stream__ contain a 30-line `if sse.event == "..." or sse.event == "..."` chain listing ~28 event names. This is duplicated verbatim between sync and async implementations and is brittle: adding a new event requires editing two places.
  - *Fix:* Extract a module-level constant `_HANDLED_SSE_EVENTS: frozenset[str] = frozenset({...})` and use `if sse.event in _HANDLED_SSE_EVENTS:` in both implementations. Reduces 30 lines to 1 lookup and remove…
  - *agent: `quality` · confidence: 0.98 · est: 0.5h*

- 🟡 **MEDIUM** · [`src/anthropic/_base_client.py:640`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_base_client.py#L640)
  - **Massive duplication between SyncAPIClient and AsyncAPIClient**
  - The `SyncAPIClient` (lines ~640-1000) and `AsyncAPIClient` (lines ~1100-1500) in `_base_client.py` contain near-identical implementations of `request()`, `_process_response()`, `_sleep_for_retry()`, all HTTP verb methods (get/post/put/patch/delete), and request-options preparation. The only meaningf…
  - *Fix:* Since this is generator-emitted code, the duplication is acceptable but should be guarded by (a) automated parity tests asserting that public method signatures and behavior match between Sync/Async va…
  - *agent: `architecture` · confidence: 0.95 · est: 8.0h*

- 🟡 **MEDIUM** · [`src/anthropic/_base_client.py`](https://github.com/anthropics/anthropic-sdk-python/blob/HEAD/src/anthropic/_base_client.py)
  - **Duplicated _DefaultHttpxClient and _DefaultAsyncHttpxClient initialization logic**
  - The synchronous _DefaultHttpxClient.__init__ and asynchronous _DefaultAsyncHttpxClient.__init__ contain ~30 lines of nearly identical socket option configuration, proxy mapping, and transport setup. Only the transport class differs (HTTPTransport vs AsyncHTTPTransport). This duplication makes mainte…
  - *Fix:* Extract a shared helper function `_build_socket_options()` and `_build_proxy_mounts(transport_cls, kwargs)` that both classes call. Target ~15 lines of class-specific code.
  - *agent: `quality` · confidence: 0.95 · est: 2.0h*


---

## `gstack` — Grade C (72.0)

**Repo:** https://github.com/garrytan/gstack
**Findings:** 54 total · 🔴 2 critical · 🟠 8 high · 🟡 22 medium · 🟢 16 low · ⚪ 6 info
**Wall-clock:** 187s · **Cost:** $9.19

### Per-dimension

| Dimension | Grade | Score | Weight |
|---|:---:|---:|---:|
| Security | B+ | 85.0 | 25% |
| Documentation | B- | 77.7 | 10% |
| Performance | B- | 77.1 | 10% |
| Maintainability | C+ | 73.4 | 10% |
| Architecture | D+ | 66.5 | 25% |
| Quality | F | 56.4 | 20% |

### Top findings (entry points → GitHub)

- 🔴 **CRITICAL** · [`browse/src/cli.ts`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/cli.ts)
  - **Syntax error: stray code in disconnect handler**
  - In browse/src/cli.ts within the 'disconnect' command handler, the JSON.stringify body call contains an orphaned `domains,` token left over from what appears to be a bad merge. This is invalid JavaScript/TypeScript and will fail to compile. The disconnect path is entirely broken until fixed.
  - *Fix:* Remove the stray `domains,` line. The body should simply be `JSON.stringify({ command: 'disconnect', args: [] })`. Add a unit test that exercises the disconnect path so future merges don't reintroduce…
  - *agent: `architecture` · confidence: 0.98 · est: 0.5h*

- 🔴 **CRITICAL** · [`browse/src/cli.ts:700`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/cli.ts#L700)
  - **Syntax error in cli.ts disconnect handler — invalid JSON.stringify body**
  - The disconnect command handler contains a malformed JSON.stringify call with a stray `domains,` token from a partial copy-paste. The body object has unbalanced braces and references an undefined `domains` variable. This is a parse-time syntax error that would prevent the file from loading.
  - *Fix:* Remove the stray `domains,` line. The body should be: `JSON.stringify({ command: 'disconnect', args: [] })`. Add a regression test that imports the module to catch syntax errors at CI time.
  - *agent: `quality` · confidence: 0.98 · est: 0.5h*

- 🟠 **HIGH** · [`browse/src/server.ts`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/server.ts)
  - **server.ts is a 1500+ line god module mixing every cross-cutting concern**
  - browse/src/server.ts owns: HTTP routing (~20 endpoints inline in one fetch handler), auth (root + scoped + SSE cookie + PTY cookie), tunnel lifecycle, ngrok integration, idle-timer + parent-watchdog, signal handling, buffer flushing, inspector SSE, batch dispatch, file serving, welcome page, command…
  - *Fix:* Extract route handlers into a routes/ directory: routes/auth.ts (/connect, /token, /pair, /sse-session, /pty-session), routes/tunnel.ts (/tunnel/start, closeTunnel), routes/inspector.ts, routes/activi…
  - *agent: `architecture` · confidence: 0.95 · est: 16.0h*

- 🟠 **HIGH** · [`browse/src/server.ts:308`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/server.ts#L308)
  - **handleCommandInternal exceeds 280 lines with very high cyclomatic complexity**
  - handleCommandInternal in server.ts is ~280 lines long with deeply nested conditionals covering scope checks, domain checks, rate limits, tab pinning, ownership, watch-mode gating, read/write/meta dispatch, content filtering, audit logging, and error/restoration paths. Cyclomatic complexity is well a…
  - *Fix:* Extract pure helpers: validateScopeAndDomain(tokenInfo, command, args), enforceRateLimit(tokenInfo, opts), pinTab(tabId), runReadWithHiddenStripping(...), wrapResultIfPageContent(...). Aim for a top-l…
  - *agent: `quality` · confidence: 0.95 · est: 8.0h*

- 🟠 **HIGH** · [`browse/src/server.ts`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/server.ts)
  - **AUTH_TOKEN exposed via /health endpoint enables token theft from any local browser**
  - The /health endpoint returns the root AUTH_TOKEN unconditionally when in headed mode, or when the request Origin is a chrome-extension:// URL. The Origin header is set by browsers but can be spoofed by any non-browser local HTTP client (curl, malware), and any process on localhost can hit /health an…
  - *Fix:* Replace the /health token leak with the existing /pty-session or a dedicated /bootstrap endpoint requiring proof of extension identity (e.g., a one-time bootstrap nonce written to a file with 0600 per…
  - *agent: `security` · confidence: 0.92 · est: 6.0h*

- 🟠 **HIGH** · [`browse/src/browser-manager.ts`](https://github.com/garrytan/gstack/blob/HEAD/browse/src/browser-manager.ts)
  - **BrowserManager is a god class — 600+ lines, 30+ responsibilities**
  - BrowserManager owns: launch/close, tab CRUD, ownership, viewport, headers, user agent, dialog handling, cookie origin tracking, watch mode, handoff (headless→headed), state save/restore, page event wiring, two-tier CDP mutex, ref maps, snapshot diffing, anti-bot stealth scripts, custom Chromium bina…
  - *Fix:* Split into: BrowserLifecycle (launch/close/health), TabManager (tabs + ownership), SessionState (saveState/restoreState), HandoffController, CdpMutex (per-tab + global locks), AppRebrand (plist + icon…
  - *agent: `architecture` · confidence: 0.90 · est: 24.0h*


---

## `gbrain` — Grade C- (68.5)

**Repo:** https://github.com/garrytan/gbrain
**Findings:** 72 total · 🟠 10 high · 🟡 31 medium · 🟢 27 low · ⚪ 4 info
**Wall-clock:** 188s · **Cost:** $4.90

### Per-dimension

| Dimension | Grade | Score | Weight |
|---|:---:|---:|---:|
| Performance | B+ | 83.4 | 10% |
| Security | C+ | 73.1 | 25% |
| Maintainability | C | 72.5 | 10% |
| Architecture | C- | 69.7 | 25% |
| Documentation | D+ | 65.2 | 10% |
| Quality | F | 53.5 | 20% |

### Top findings (entry points → GitHub)

- 🟠 **HIGH** · [`src/commands/autopilot.ts:362`](https://github.com/garrytan/gbrain/blob/HEAD/src/commands/autopilot.ts#L362)
  - **Engine abstraction leaks via unsafe casts (engine as any)**
  - The BrainEngine interface is the architectural seam between PostgresEngine and PGLiteEngine, but call sites bypass it with `(engine as any).executeRaw?.(...)` and `(engine as any).connect?.()` (autopilot.ts:362, 393). This indicates either the interface is incomplete or callers are reaching into eng…
  - *Fix:* Add `executeRaw<T>` and a `reconnect()` method to the BrainEngine interface (both engines already implement executeRaw based on usage). Remove the `as any` casts. If reconnect semantics differ, docume…
  - *agent: `architecture` · confidence: 0.95 · est: 3.0h*

- 🟠 **HIGH** · [`src/cli.ts:174`](https://github.com/garrytan/gbrain/blob/HEAD/src/cli.ts#L174)
  - **Pervasive use of `as any` casts undermines TypeScript's type safety**
  - Multiple files cast values through `any` to bypass type checking, defeating the purpose of TypeScript's strict mode. In cli.ts formatResult uses `result as any` repeatedly for every command branch, losing type guarantees on operation results. autopilot.ts uses `(engine as any).executeRaw?.(...)` and…
  - *Fix:* Define discriminated union return types per operation and replace `as any` with proper type narrowing. Add `executeRaw`, `connect`, and `getHealth` to the BrainEngine interface so autopilot.ts doesn't…
  - *agent: `quality` · confidence: 0.95 · est: 8.0h*

- 🟠 **HIGH** · [`src/cli.ts:245`](https://github.com/garrytan/gbrain/blob/HEAD/src/cli.ts#L245)
  - **handleCliOnly is a 250+ line dispatcher with high cyclomatic complexity**
  - The handleCliOnly function in cli.ts uses a long sequence of if-statements followed by a switch, dispatching ~40 commands. Each command has its own dynamic import and small variations (some need engine, some don't, some don't disconnect). This monolithic function has cyclomatic complexity well over …
  - *Fix:* Extract a command registry: `Map<string, { needsDb: boolean; disconnect: boolean; load: () => Promise<Handler> }>`. Replace the if-chain and switch with a single dispatch loop driven by the registry. …
  - *agent: `quality` · confidence: 0.95 · est: 6.0h*

- 🟠 **HIGH** · [`src/commands/autopilot.ts:96`](https://github.com/garrytan/gbrain/blob/HEAD/src/commands/autopilot.ts#L96)
  - **runAutopilot is ~280 lines combining 5 distinct responsibilities**
  - runAutopilot in autopilot.ts handles: lock-file management, worker child-process supervision (spawn + restart + crash counting), Minions dispatch loop, inline cycle fallback, no-worker liveness probe, health-based interval adaptation, and shutdown signal handling. This is a god function with cycloma…
  - *Fix:* Extract: WorkerSupervisor class (spawn/restart/crash logic), DispatchLoop (the while loop body), LockManager (acquire/refresh/release), and ShutdownCoordinator. runAutopilot should orchestrate them in…
  - *agent: `quality` · confidence: 0.95 · est: 12.0h*

- 🟠 **HIGH** · [`src/cli.ts:380`](https://github.com/garrytan/gbrain/blob/HEAD/src/cli.ts#L380)
  - **CLI help text omits documented commands (auth, agent, skillpack, skillify, etc.)**
  - The printHelp() function in src/cli.ts is the canonical user-facing help, but it omits many commands present in CLI_ONLY and dispatched in handleCliOnly: 'auth', 'agent', 'skillpack', 'skillify', 'check-resolvable', 'routing-eval', 'apply-migrations', 'skillpack-check', 'resolvers', 'integrity', 're…
  - *Fix:* Add a SUBAGENTS section (agent run/logs), an AUTH section (auth create/list/revoke/test), expand SETUP to include `apply-migrations` and `skillpack-check`, and add the missing utility commands (skilli…
  - *agent: `documentation` · confidence: 0.95 · est: 3.0h*

- 🟠 **HIGH** · [`src/cli.ts:26`](https://github.com/garrytan/gbrain/blob/HEAD/src/cli.ts#L26)
  - **`reconcile-links` command not registered in CLI_ONLY but handled in switch**
  - src/cli.ts handles `case 'reconcile-links':` in the handleCliOnly switch (with a v0.20.0 comment), but 'reconcile-links' is missing from the CLI_ONLY Set. This means the dispatcher never routes the command into handleCliOnly — it falls through to the shared-operations path and prints 'Unknown comman…
  - *Fix:* Add 'reconcile-links' to the CLI_ONLY Set, or document that the command is unreleased. Also add it to printHelp() under the CODE INDEXING section. Add a smoke test asserting every case label in handle…
  - *agent: `documentation` · confidence: 0.95 · est: 0.5h*


---

## `gbrain-evals` — Grade C+ (75.2)

**Repo:** https://github.com/garrytan/gbrain-evals
**Findings:** 62 total · 🔴 1 critical · 🟠 9 high · 🟡 23 medium · 🟢 19 low · ⚪ 10 info
**Wall-clock:** 188s · **Cost:** $17.29

### Per-dimension

| Dimension | Grade | Score | Weight |
|---|:---:|---:|---:|
| Security | A- | 89.5 | 25% |
| Architecture | C+ | 76.1 | 25% |
| Documentation | C+ | 75.3 | 10% |
| Performance | C+ | 75.2 | 10% |
| Maintainability | D+ | 63.0 | 10% |
| Quality | D | 62.4 | 20% |

### Top findings (entry points → GitHub)

- 🔴 **CRITICAL** · [`package.json:24`](https://github.com/garrytan/gbrain-evals/blob/HEAD/package.json#L24)
  - **Critical core dependency pinned to a moving git branch (master)**
  - `gbrain` is the central library this benchmark consumes, but it is referenced as `github:garrytan/gbrain#master` — a branch ref, not a tag or commit SHA. Every fresh install can pull a different gbrain HEAD, silently changing benchmark results. This is the single largest reproducibility risk in the …
  - *Fix:* Pin to a commit SHA or a versioned tag, e.g. `github:garrytan/gbrain#v0.3.1` or `github:garrytan/gbrain#<40-char-sha>`. For published benchmark runs, record the resolved SHA in the report metadata. Lo…
  - *agent: `dependency` · confidence: 0.98 · est: 1.0h*

- 🟠 **HIGH** · [`eval/generators/amara-life-gen.ts:413`](https://github.com/garrytan/gbrain-evals/blob/HEAD/eval/generators/amara-life-gen.ts#L413)
  - **Bug in writeDocs: redundant/dead path-rewriting logic**
  - writeDocs() in amara-life-gen.ts contains visibly broken path logic: `const path = join(CORPUS_ROOT, slugPath + '.md'.replace(/\.md$/, '') === slugPath ? slugPath : slugPath);` — the ternary always evaluates to `slugPath` (both branches), and `path` is then unused (`fullPath` is what's actually writ…
  - *Fix:* Delete the dead `path` line entirely and rely on `fullPath`. Also note the docs slugs already end with .md (e.g. 'doc/novamind-investor-update.md'), so review whether the stored doc paths should match…
  - *agent: `architecture` · confidence: 0.95 · est: 1.0h*

- 🟠 **HIGH** · [`eval/generators/amara-life-gen.ts:405`](https://github.com/garrytan/gbrain-evals/blob/HEAD/eval/generators/amara-life-gen.ts#L405)
  - **Broken docs path-mangling logic in writeDocs() is dead-code-equivalent**
  - The expression `slugPath + '.md'.replace(/\.md$/, '') === slugPath ? slugPath : slugPath` always evaluates to `slugPath` regardless of the comparison (both branches are identical). This is buggy/confused code that does nothing useful. The variable `path` is then computed but never used — only `fullP…
  - *Fix:* Remove the dead `path` variable and the no-op ternary. Just use `const fullPath = join(CORPUS_ROOT, slugPath); ensureDir(dirname(fullPath)); writeFileSync(fullPath, body);`
  - *agent: `quality` · confidence: 0.95 · est: 0.5h*

- 🟠 **HIGH** · [`eval/generators/amara-life-gen.ts`](https://github.com/garrytan/gbrain-evals/blob/HEAD/eval/generators/amara-life-gen.ts)
  - **Sequential per-item LLM calls in amara-life generator (no concurrency)**
  - The main generation loop in amara-life-gen.ts processes 50 emails + 300 slack + 8 meetings + 40 notes (398 LLM calls) strictly sequentially via `for...of` with `await callOpus()` inside. At ~5-10s per Opus call, this means 30-60 minutes of wall time for a full uncached run, dominated by network roun…
  - *Fix:* Refactor the four sequential loops (emails, slack, meetings, notes) into a worker-pool pattern matching gen.ts (lines using `Promise.all(Array.from({length: concurrency}, () => worker()))`). Default c…
  - *agent: `performance` · confidence: 0.92 · est: 3.0h*

- 🟠 **HIGH** · [`package.json:1`](https://github.com/garrytan/gbrain-evals/blob/HEAD/package.json#L1)
  - **No lockfile present (bun.lockb / package-lock.json not committed)**
  - The provided files include package.json but no lockfile is visible. Without a committed lockfile (bun.lockb for Bun, or package-lock.json), dependency resolution is non-deterministic across contributors and CI. Combined with caret ranges (^0.30.0, ^2.4.5) and a git-ref dependency, two installs can p…
  - *Fix:* Commit bun.lockb (or package-lock.json if mixing tooling) and add a CI step (e.g., `bun install --frozen-lockfile`) to enforce lockfile integrity. Document the lockfile in CONTRIBUTING.md.
  - *agent: `dependency` · confidence: 0.90 · est: 1.0h*

- 🟠 **HIGH** · [`eval/runner/adapters/vector.test.ts:4`](https://github.com/garrytan/gbrain-evals/blob/HEAD/eval/runner/adapters/vector.test.ts#L4)
  - **Vector adapter integration tests gated/missing — no end-to-end coverage**
  - vector.test.ts only unit-tests the pure cosine helper. The comment explicitly states 'VectorOnlyAdapter.init/query require a live embedding API key. Those end-to-end tests live in a smoke-test class and gate on OPENAI_API_KEY.' No such smoke-test file is provided/visible in this slice, so init() and…
  - *Fix:* Add a fake/stub embedder injection point so init/query can be tested deterministically without API calls. Mock embedBatch/embed via DI or a test-mode config. Provides regression coverage without budge…
  - *agent: `quality` · confidence: 0.85 · est: 4.0h*


---

## `alphaclaw` — Grade C+ (73.2)

**Repo:** https://github.com/garrytan/alphaclaw
**Findings:** 63 total · 🟠 9 high · 🟡 23 medium · 🟢 24 low · ⚪ 7 info
**Wall-clock:** 162s · **Cost:** $4.86

### Per-dimension

| Dimension | Grade | Score | Weight |
|---|:---:|---:|---:|
| Security | B | 81.4 | 25% |
| Maintainability | C+ | 75.6 | 10% |
| Architecture | C+ | 73.1 | 25% |
| Documentation | C- | 69.6 | 10% |
| Performance | C- | 69.0 | 10% |
| Quality | D+ | 65.6 | 20% |

### Top findings (entry points → GitHub)

- 🟠 **HIGH** · [`package.json`](https://github.com/garrytan/alphaclaw/blob/HEAD/package.json)
  - **Dependency manifest files referenced in PLAN but not provided for analysis**
  - The PLAN explicitly lists package.json, package-lock.json, .npmrc, patches/openclaw+2026.4.1.patch, scripts/apply-openclaw-patches.js, and .github/workflows/ci.yml as the focus files for dependency analysis. However, none of these files were included in the source code provided — only application so…
  - *Fix:* Re-run the dependency analysis with the actual manifest files attached: package.json, package-lock.json, .npmrc, patches/openclaw+2026.4.1.patch, scripts/apply-openclaw-patches.js, and .github/workflo…
  - *agent: `dependency` · confidence: 0.98 · est: 0.5h*

- 🟠 **HIGH** · [`lib/public/js/app.js:96`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/app.js#L96)
  - **App component is a god component composing all routes inline**
  - lib/public/js/app.js is ~370 lines and directly composes every route (Agents, Browse, Chat, Cron, Envars, Models, Nodes, General, Doctor, Telegram, Usage, Watchdog, Webhooks), threads dozens of props per route, runs route-specific regex parsing inline (selectedAgentId, agentDetailTab, selectedCronJo…
  - *Fix:* Extract a RouteShell/RouteSwitch component that owns route matching and pane selection. Move per-route prop wiring (e.g. AgentsPane, CronPane, ChatPane wrappers) into the routes/ folder so app.js only…
  - *agent: `architecture` · confidence: 0.90 · est: 8.0h*

- 🟠 **HIGH** · [`lib/public/js/components/google/index.js:215`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/components/google/index.js#L215)
  - **postMessage handler accepts any origin for OAuth completion**
  - The window message handler processes event.data.google === 'success' or 'error' without validating event.origin. Any page the user visits (or any iframe/popup) can postMessage to this window and trigger toast notifications, refresh of accounts, and force handleCheckApis with an attacker-supplied acc…
  - *Fix:* Validate event.origin against window.location.origin (or an explicit allowlist) before processing message data. Example: if (event.origin !== window.location.origin) return;
  - *agent: `security` · confidence: 0.90 · est: 0.5h*

- 🟠 **HIGH** · [`lib/public/js/app.js:47`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/app.js#L47)
  - **App component exceeds 350 lines with deeply nested JSX and inline handlers**
  - The App component in app.js spans roughly 300+ lines with deeply nested template literals, multiple inline IIFEs for route parsing, inline event handlers creating closures on every render, and conditional rendering for 7+ routes. Cyclomatic complexity is elevated by cascading isXxxRoute checks and t…
  - *Fix:* Extract route parsing IIFEs into helper functions (e.g., parseSelectedAgentId(location)). Move the long Switch/Route block into a dedicated <AppRoutes> component. Lift inline onclick handlers (e.g., t…
  - *agent: `quality` · confidence: 0.90 · est: 6.0h*

- 🟠 **HIGH** · [`lib/public/js/components/doctor/index.js:36`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/components/doctor/index.js#L36)
  - **DoctorTab component is a god-component with excessive state and effects**
  - DoctorTab in lib/public/js/components/doctor/index.js is ~400 lines, manages 5 useState hooks, 4 useEffect hooks with complex interdependent dependency arrays, 3 polling subscriptions, multiple useMemo computations, and inline JSX rendering for run pills, banners, summaries, and findings. The interp…
  - *Fix:* Extract a useDoctorRunSelection hook encapsulating run filter state and the three sync effects. Split rendering into <DoctorRunTabs>, <DoctorBanners>, and <DoctorEmptyState> sub-components. Move pure …
  - *agent: `quality` · confidence: 0.90 · est: 8.0h*

- 🟠 **HIGH** · [`lib/public/js/components/google/index.js:39`](https://github.com/garrytan/alphaclaw/blob/HEAD/lib/public/js/components/google/index.js#L39)
  - **Google component has 15+ useState hooks indicating over-broad responsibility**
  - Google component declares roughly 8 useState hooks plus delegates more state to two custom hooks (useGoogleAccounts, useGmailWatch). It mixes concerns: account expansion UI, scope editing per-account, API status checking, credentials modal state, add-account modal state, disconnect dialog, Gmail wiz…
  - *Fix:* Extract per-account scope/API-status state into a useAccountScopes(accountId) hook. Split modal management into a useGoogleModals hook returning {credentials, addCompany, gmailWizard, disconnect}. Thi…
  - *agent: `quality` · confidence: 0.85 · est: 8.0h*


---

## Methodology

- All scans use `--quick` (skips Stage 5 CritiqueAgent — ~3× faster, slightly less false-positive filtering).
- All scans use `--no-cache` (cold-run, honest cost).
- Models: all 8 agents on Claude Opus 4.7 with the per-role effort tuning from CLAUDE.md (meta=medium, specialists=xhigh, critique=high+task_budget).
- Per-dimension weights: Architecture 25%, Security 25%, Quality 20%, Documentation 10%, Maintainability 10%, Performance 10%.
- Cost = sum of input + output tokens × Claude Opus 4.7 pricing ($5/M input, $25/M output) at the typical 70/30 input/output ratio.
- Scans done 2026-04-29.

## Reproduce

```bash
pip install spectra-ai==0.3.2
export ANTHROPIC_API_KEY=sk-ant-...
spectra analyze https://github.com/<owner>/<repo> --quick --format json -o report.json
```

Raw JSON outputs for every scan are in [`docs/leaderboard-data/`](../leaderboard-data/) — the source of truth for the table.
