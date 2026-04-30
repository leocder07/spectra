-- ADR-022 §3 — initial history-store schema.
--
-- Three tables, three indexes. No JSONB column for findings (kept in
-- object storage); no foreign keys outside the three-table group.
--
-- Compatible with both Postgres and SQLite — we use TEXT in place of
-- VARCHAR(N) (SQLite ignores the length anyway, Postgres treats them
-- as TEXT internally), REAL for floats, and TIMESTAMP for timestamps
-- (Postgres widens to TIMESTAMPTZ on its own, SQLite stores as text
-- via the connector's adapter). Both backends accept this DDL verbatim.

CREATE TABLE IF NOT EXISTS reports (
    scan_id              TEXT     PRIMARY KEY,
    repo_signature       TEXT     NOT NULL,
    repo_url             TEXT     NOT NULL,
    repo_name            TEXT     NOT NULL,
    org_id               TEXT     NOT NULL DEFAULT 'default',
    ts                   TIMESTAMP NOT NULL,
    overall_score        REAL     NOT NULL,
    overall_grade        TEXT     NOT NULL,
    pipeline_state       TEXT     NOT NULL DEFAULT 'complete',
    validation_status    TEXT     NOT NULL,
    spectra_version      TEXT     NOT NULL,
    model_versions       TEXT     NOT NULL,
    prompt_versions      TEXT     NOT NULL,
    cost_usd             REAL     NOT NULL,
    duration_seconds     REAL     NOT NULL,
    summary_json         TEXT     NOT NULL,
    created_at           TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS report_dimension_scores (
    scan_id              TEXT     NOT NULL,
    dimension            TEXT     NOT NULL,
    score                REAL     NOT NULL,
    grade                TEXT     NOT NULL,
    finding_count        INTEGER  NOT NULL,
    PRIMARY KEY (scan_id, dimension)
);

CREATE TABLE IF NOT EXISTS report_severity_counts (
    scan_id              TEXT     NOT NULL,
    severity             TEXT     NOT NULL,
    count                INTEGER  NOT NULL,
    PRIMARY KEY (scan_id, severity)
);

CREATE INDEX IF NOT EXISTS reports_repo_ts        ON reports (repo_signature, ts DESC);
CREATE INDEX IF NOT EXISTS reports_org_ts         ON reports (org_id, ts DESC);
CREATE INDEX IF NOT EXISTS reports_org_grade      ON reports (org_id, overall_grade);
