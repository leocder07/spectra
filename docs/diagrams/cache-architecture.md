# Cache Subsystem — Schema, Keys, and Telemetry

Deep-dive on `CachePort` + `SqliteCacheAdapter`. Covers the four SQLite tables, the composite-key invalidation strategy, and the hit-log telemetry flow.

> The Excalidraw companion is at [`excalidraw/cache-schema.excalidraw`](excalidraw/cache-schema.excalidraw) — same content, hand-laid table boxes for editorial polish.

## SQLite schema (4 tables)

```mermaid
erDiagram
    findings_cache {
        TEXT file_hash PK "blake2b(file bytes, 16B → 32 hex)"
        TEXT dimension PK "Dimension literal"
        TEXT model_version PK "claude-opus-4-7"
        TEXT prompt_version PK "per-dimension"
        TEXT schema_version PK "v1 (Finding shape)"
        TEXT file_path "first finding's path"
        TEXT findings_json "list of Finding"
        TEXT spectra_version "spectra.__version__"
        TEXT repo_signature "blake2b of file_tree"
        TIMESTAMP computed_at "UTC"
    }
    full_report_cache {
        TEXT repo_signature PK "blake2b(file_tree)"
        TEXT spectra_version PK
        TEXT model_versions PK "canonical sort across all 8 agents"
        TEXT prompt_versions PK "blake2b(shared+spec+critique)"
        TEXT schema_version PK
        TEXT report_json "AnalysisReport.model_dump_json"
        TIMESTAMP computed_at
    }
    findings_batches {
        TEXT batch_id PK "blake2b(sorted file_hashes)"
        TEXT dimension PK
        TEXT model_version PK
        TEXT prompt_version PK
        TEXT schema_version PK
        TEXT spectra_version PK
        TEXT findings_json "Finding[]"
        TIMESTAMP computed_at
    }
    hit_log {
        TIMESTAMP ts "append-only"
        INTEGER hit "1 = hit, 0 = miss"
    }

    findings_cache ||--o{ findings_batches : "Phase 1 vs Phase 3 granularity"
    full_report_cache ||--o{ findings_batches : "shortcuts when repo unchanged"
    hit_log }o--|| findings_batches : "telemetry source"
```

| Table | Phase | Purpose |
|-------|-------|---------|
| `findings_cache` | 1 | Per-`(file_hash, dimension)` rows. Foundation; survives intact even when `findings_batches` is the active read path. |
| `full_report_cache` | 2 | One row per `(file_tree, model+prompt+schema+spectra versions)`. Killer for the trivial "nothing changed" case — short-circuits Stages 3–5. |
| `findings_batches` | 3 | One row per `(focus_area, dimension)` batch. The killer feature: edit one file, invalidate one batch, all other batches keep returning instantly. |
| `hit_log` | 3 | Append-only telemetry. `_hit_rate_last_100` = rolling cache hit rate over the last 100 lookups, surfaced via `CacheStats.hit_rate_last_100`. Phase 4 will add `dimension`/`batch_id` columns. |

WAL mode (`PRAGMA journal_mode=WAL`) is set on every connect so concurrent reads don't block writes.

## Cache key composition

```mermaid
flowchart LR
    classDef src fill:#fef3c7,stroke:#92400e,color:#1e293b
    classDef key fill:#ede9fe,stroke:#7C3AED,color:#1e293b,stroke-width:2px

    subgraph Phase1[Phase 1 — per-file finding row]
        F1[file bytes]:::src
        D1[Dimension literal]:::src
        M1[model id]:::src
        P1[prompt version<br/>per dimension]:::src
        S1[SchemaVersion]:::src
        F1 --> H1[blake2b 16B]
        H1 --> K1[(findings_cache PK<br/>file_hash + dim + model<br/>+ prompt + schema)]:::key
        D1 --> K1
        M1 --> K1
        P1 --> K1
        S1 --> K1
    end

    subgraph Phase2[Phase 2 — full-report row]
        T2[file_tree tuple]:::src
        SV2[spectra.__version__]:::src
        MV2[model_versions<br/>canonical-sorted]:::src
        PV2[prompt_versions<br/>blake2b shared+spec+critique]:::src
        SC2[SchemaVersion]:::src
        T2 --> H2[blake2b 16B<br/>repo_signature]
        H2 --> K2[(full_report_cache PK<br/>repo_sig + spectra + models<br/>+ prompts + schema)]:::key
        SV2 --> K2
        MV2 --> K2
        PV2 --> K2
        SC2 --> K2
    end

    subgraph Phase3[Phase 3 — per-batch row]
        FH3[sorted file_hashes<br/>in this focus_area]:::src
        D3[Dimension]:::src
        MV3[model_version]:::src
        PV3[prompt_version]:::src
        SC3[SchemaVersion]:::src
        SV3[spectra.__version__]:::src
        FH3 --> H3[blake2b 16B<br/>batch_id]
        H3 --> K3[(findings_batches PK<br/>batch_id + dim + model<br/>+ prompt + schema + spectra)]:::key
        D3 --> K3
        MV3 --> K3
        PV3 --> K3
        SC3 --> K3
        SV3 --> K3
    end
```

## Invalidation matrix

The composite primary key on every table makes invalidation a *no-op*: a stale row simply never matches a current-context lookup. There is no "cache invalidation logic" to maintain.

| Trigger | Detection | Tables affected | Scope |
|---------|-----------|-----------------|-------|
| `--force` flag | CLI: `force_cache_bypass=True` on `PipelineContext` | All reads bypassed; writes still occur | Whole run |
| `--no-cache` flag | Composition root: `cache_port=None` | All reads + writes skipped | Whole run |
| `spectra.__version__` bump | New `spectra_version` value in key | `full_report_cache`, `findings_batches` | Whole repo |
| Model version change | New `model_version` value in key | All three findings tables | Per dimension (or whole repo for full-report) |
| Prompt version bump | New `prompt_version` value (per-dim or `blake2b(prompt_text)`) in key | All three findings tables | Per dimension |
| Schema version bump | New `SchemaVersion` literal (manual bump in `cache_adapter.SCHEMA_VERSION`) | All three findings tables | Whole repo |
| File content change | `blake2b(file bytes)` differs → different `file_hash` | `findings_cache`, `findings_batches` (via `batch_id`) | Per file (and its containing batch) |
| File deleted | Path absent from new `file_tree` → different `repo_signature` | `full_report_cache` | Whole repo |
| Row >N days old | `computed_at < now - N` | All findings tables | Per row (lazy GC via Phase 4 `spectra cache prune`) |

Physical deletion of stale rows is deferred to `spectra cache prune` (Phase 4 — shipped in PR #19). The cache grows only as fast as you analyze new content; pruning is a maintenance task, not a hot-path operation.

## Run-context binding

Phase 3 introduced `bind_run_context(model_versions, prompt_versions, schema_version, spectra_version)` to eliminate the intermediate-inconsistent-state failure mode of the original Phase 1 setters. Composition-root callers configure the cache exactly once at startup; subsequent `batch_key_for()` calls inherit the four versions atomically.

```mermaid
sequenceDiagram
    participant Main as main.py<br/>(composition root)
    participant Cache as SqliteCacheAdapter
    participant Pipeline as analyze_repository

    Main->>Cache: bind_run_context(<br/>"claude-opus-4-7,...", prompt_hash, "v1", "0.2.0")
    Note over Cache: stores _run_versions tuple atomically

    Pipeline->>Cache: batch_key_for(batch_id, "security")
    alt run-context bound
        Cache-->>Pipeline: BatchCacheKey(batch_id, dim, model, prompt, schema, spectra)
    else not bound
        Cache-->>Pipeline: None
        Note over Pipeline: short-circuits per-batch caching for this run
    end
```

## Hit-log telemetry flow

```mermaid
flowchart LR
    classDef phase fill:#dcfce7,stroke:#166534,color:#1e293b
    classDef table fill:#fef3c7,stroke:#92400e,color:#1e293b
    classDef api fill:#ede9fe,stroke:#7C3AED,color:#1e293b

    A[analyze_repository<br/>per-batch lookup]:::phase --> B{get_batch_findings<br/>HIT?}
    B -- "yes" --> C[record_hit dim batch_id true]:::api
    B -- "no" --> D[record_hit dim batch_id false]:::api
    C --> E[(hit_log table<br/>append-only)]:::table
    D --> E
    F[ProgressObserver]:::phase --> G[on_cache_lookup<br/>dim, hits, total]
    A --> F

    H[CacheStats] --> I[hit_rate_last_100<br/>= sum hits over last 100 / 100]
    E --> I
    H --> J[total_entries · total_repos<br/>db_size_bytes · oldest_entry_at]

    K[spectra cache stats CLI<br/>Phase 4 shipped] --> H
```

The terminal sees a per-dimension tally during ANALYZE (e.g. `security cache 7/8 hits`); the rolling rate is exposed via `spectra cache stats` once Phase 4 lands.

## Default cache location

```
$XDG_CACHE_HOME/spectra/cache.db          # if XDG_CACHE_HOME is set
~/.cache/spectra/cache.db                 # default fallback
~/.cache/spectra/cache.db-wal             # WAL sidecar
~/.cache/spectra/cache.db-shm             # shared-memory sidecar
```

Single-file SQLite; trivially backed up or wiped. The repos directory (`~/.cache/spectra/repos/<repo_signature>/last_report.json`) is reserved for `spectra cache stats` UX in Phase 4.

---

*Last updated: 2026-04-29 — schema for findings_cache, full_report_cache, findings_batches, hit_log; bind_run_context flow; SPEC-010 degradation reference.*
