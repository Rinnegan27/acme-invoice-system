PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;

-- Main work queue
CREATE TABLE IF NOT EXISTS work_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stage           TEXT    NOT NULL,
    payload         TEXT    NOT NULL,
    idempotency_key TEXT    NOT NULL,
    correlation_id  TEXT    NOT NULL,
    receive_count   INTEGER NOT NULL DEFAULT 0,
    visible_at      REAL    NOT NULL DEFAULT (strftime('%s','now')),
    created_at      REAL    NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_work_queue_idempotency
    ON work_queue (stage, idempotency_key);

-- Dead-letter queue
CREATE TABLE IF NOT EXISTS dlq (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id     INTEGER,
    stage           TEXT    NOT NULL,
    payload         TEXT    NOT NULL,
    idempotency_key TEXT    NOT NULL,
    invoice_id      TEXT    NOT NULL,
    correlation_id  TEXT    NOT NULL,
    receive_count   INTEGER NOT NULL,
    reason          TEXT    NOT NULL,
    moved_at        REAL    NOT NULL DEFAULT (strftime('%s','now')),
    operator_id     TEXT
);

-- Processed keys (for atomic idempotency)
CREATE TABLE IF NOT EXISTS processed_keys (
    stage           TEXT    NOT NULL,
    idempotency_key TEXT    NOT NULL,
    correlation_id  TEXT    NOT NULL,
    processed_at    REAL    NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (stage, idempotency_key)
);

-- PaymentIntent + outbox (saga)
CREATE TABLE IF NOT EXISTS payment_intent (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id                  TEXT    NOT NULL UNIQUE,
    vendor                      TEXT    NOT NULL,
    amount                      TEXT    NOT NULL,
    status                      TEXT    NOT NULL,
    idempotency_key             TEXT    NOT NULL UNIQUE,
    correlation_id              TEXT    NOT NULL,
    needs_manual_reconciliation INTEGER NOT NULL DEFAULT 0,
    created_at                  REAL    NOT NULL DEFAULT (strftime('%s','now')),
    updated_at                  REAL    NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    aggregate_id    TEXT    NOT NULL,
    event_type      TEXT    NOT NULL,
    payload         TEXT    NOT NULL,
    correlation_id  TEXT    NOT NULL,
    created_at      REAL    NOT NULL DEFAULT (strftime('%s','now')),
    published       INTEGER NOT NULL DEFAULT 0
);

-- Simple alert log
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    severity    TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    correlation_id TEXT,
    created_at  REAL    NOT NULL DEFAULT (strftime('%s','now'))
);
