-- calcfinc reference schema (SQLite). Idempotent.
-- Every number is stored as TEXT holding an exact decimal string. TEXT affinity matters:
-- a REAL or NUMERIC column would turn '100.10' into a binary float. NULL means "not reported".

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entities (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    name                  TEXT    NOT NULL,
    kind                  TEXT    NOT NULL DEFAULT 'company',
    currency              TEXT,
    fiscal_year_end_month INTEGER NOT NULL DEFAULT 12
);

CREATE TABLE IF NOT EXISTS entity_identifiers (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    scheme    TEXT    NOT NULL,                  -- 'ticker' | 'isin' | 'cik' | 'lei' | 'mic' | ...
    value     TEXT    NOT NULL,
    PRIMARY KEY (entity_id, scheme),
    UNIQUE (scheme, value COLLATE NOCASE)
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias     TEXT    NOT NULL,
    PRIMARY KEY (entity_id, alias)
);

CREATE TABLE IF NOT EXISTS sources (
    source_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL,
    entity_id      INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    document_title TEXT,
    uri            TEXT,
    content_hash   TEXT UNIQUE,                  -- sha256 of raw bytes; de-dup key
    retrieved_at   TEXT,                         -- ISO datetime
    period_label   TEXT
);

CREATE TABLE IF NOT EXISTS facts (
    fact_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id          INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    metric             TEXT    NOT NULL,
    value              TEXT,                     -- exact decimal string; NULL = not reported
    currency           TEXT,                     -- ISO 4217; NULL for dimensionless metrics
    period_start       TEXT,                     -- ISO date; NULL for point-in-time
    period_end         TEXT,
    financial_year     INTEGER,
    quarter            INTEGER,
    statement_type     TEXT    NOT NULL,
    basis              TEXT    NOT NULL,         -- 'consolidated' | 'standalone'
    is_annual          INTEGER NOT NULL DEFAULT 0,
    is_point_in_time   INTEGER NOT NULL DEFAULT 0,
    reported_at        TEXT,                     -- ISO date the figure was published
    source_id          INTEGER REFERENCES sources(source_id) ON DELETE SET NULL,
    mapping_confidence TEXT    NOT NULL DEFAULT 'exact',
    mapping_reason     TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_facts_grain ON facts (
    entity_id, metric, basis, statement_type,
    COALESCE(period_end, ''), COALESCE(period_start, ''), COALESCE(reported_at, '')
);

CREATE TABLE IF NOT EXISTS segments (
    segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    slug       TEXT NOT NULL,
    UNIQUE (entity_id, slug)
);

CREATE TABLE IF NOT EXISTS segment_facts (
    segment_fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id      INTEGER NOT NULL REFERENCES segments(segment_id) ON DELETE CASCADE,
    entity_id       INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    metric          TEXT NOT NULL,
    value           TEXT,
    currency        TEXT,
    period_start    TEXT,
    period_end      TEXT,
    financial_year  INTEGER,
    quarter         INTEGER,
    is_annual       INTEGER NOT NULL DEFAULT 0,
    basis           TEXT NOT NULL,
    source_id       INTEGER REFERENCES sources(source_id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_segment_facts_grain ON segment_facts (
    segment_id, metric, basis, COALESCE(period_end, ''), COALESCE(period_start, '')
);

CREATE TABLE IF NOT EXISTS share_prices (
    price_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    price_date TEXT NOT NULL,
    close      TEXT,                             -- exact decimal string; NULL = not traded
    currency   TEXT NOT NULL,
    source_id  INTEGER REFERENCES sources(source_id) ON DELETE SET NULL,
    UNIQUE (entity_id, price_date)
);

CREATE INDEX IF NOT EXISTS ix_facts_lookup ON facts (entity_id, metric, basis);
