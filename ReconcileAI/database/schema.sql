-- ReconcileAI – SQLite Schema
-- Run this file once to initialise the database.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ── Customers ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
    customer_id   TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    name_variants TEXT,              -- JSON array of known aliases
    gstin         TEXT,
    pan           TEXT,
    email         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Invoices ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id        TEXT PRIMARY KEY,
    customer_id       TEXT REFERENCES customers(customer_id),
    supplier_name     TEXT,
    customer_name     TEXT,
    customer_gstin    TEXT,
    invoice_date      TEXT,
    due_date          TEXT,
    taxable_amount    REAL NOT NULL DEFAULT 0,
    gst_amount        REAL NOT NULL DEFAULT 0,
    total_amount      REAL NOT NULL,
    outstanding_amount REAL NOT NULL,
    currency          TEXT NOT NULL DEFAULT 'INR',
    status            TEXT NOT NULL DEFAULT 'open',
    -- open | partially_paid | settled | overpaid
    source_document_id TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    invoice_number    TEXT,                       -- as printed; may repeat across customers / years
    opening_paid      REAL NOT NULL DEFAULT 0,    -- paid before the invoice was imported
    rounding_writeoff REAL NOT NULL DEFAULT 0,    -- residue within tolerance, recalculated
    verified          INTEGER NOT NULL DEFAULT 1  -- 0 = model-read, not yet confirmed by a person
);

-- ── Bank Transactions ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bank_transactions (
    transaction_id   TEXT PRIMARY KEY,
    utr              TEXT,            -- not UNIQUE: a repeated UTR must be stored so it can be flagged
    narration        TEXT,
    credit_amount    REAL NOT NULL DEFAULT 0,
    debit_amount     REAL NOT NULL DEFAULT 0,
    transaction_date TEXT,
    bank_name        TEXT,
    account_number   TEXT,
    currency         TEXT NOT NULL DEFAULT 'INR',
    status           TEXT NOT NULL DEFAULT 'unmatched',
    -- unmatched | matched | review | duplicate | excluded (debit / non-receivable)
    batch_id         TEXT,
    source_document_id TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Uploaded Documents ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    document_id    TEXT PRIMARY KEY,
    filename       TEXT NOT NULL,
    document_type  TEXT,
    -- bank_statement | invoice | remittance | tds_certificate | unknown
    file_hash      TEXT NOT NULL,
    file_path      TEXT,
    upload_time    TEXT NOT NULL DEFAULT (datetime('now')),
    batch_id       TEXT,
    UNIQUE(file_hash)
);

-- ── Extraction Results ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS extractions (
    extraction_id   TEXT PRIMARY KEY,
    document_id     TEXT REFERENCES documents(document_id),
    extractor       TEXT,           -- llm | csv_parser | pdf_parser
    raw_output      TEXT,           -- JSON from LLM / parser
    validated_output TEXT,          -- JSON after Pydantic validation
    extraction_status TEXT,         -- complete | partial | failed
    missing_fields  TEXT,           -- JSON array
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Remittance Records ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS remittance_records (
    remittance_id      TEXT PRIMARY KEY,
    document_id        TEXT REFERENCES documents(document_id),
    customer_name      TEXT,
    invoice_references TEXT,        -- JSON array
    payment_amount     REAL,
    tds_amount         REAL DEFAULT 0,
    tds_section        TEXT,           -- 194C | 194J | 194H | 194I | 194A
    customer_gstin     TEXT,
    utr                TEXT,
    payment_date       TEXT,
    currency           TEXT DEFAULT 'INR',
    evidence_text      TEXT,        -- JSON array of verbatim excerpts
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Payment Allocations ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payment_allocations (
    allocation_id      TEXT PRIMARY KEY,
    transaction_id     TEXT NOT NULL REFERENCES bank_transactions(transaction_id),
    invoice_id         TEXT NOT NULL REFERENCES invoices(invoice_id),
    allocated_amount   REAL NOT NULL,
    allocation_status  TEXT NOT NULL DEFAULT 'proposed',
    -- proposed | approved | rejected | reversed
    confidence_score   REAL,
    decision_reason    TEXT,
    approved_by        TEXT,        -- 'system' or user name
    approved_at        TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    remittance_id      TEXT,
    from_credit_id     TEXT          -- set when the money comes from a held customer credit
);

-- ── Settlement Components ─────────────────────────────────────────────────────
-- Breaks an allocation into its constituent parts (cash + TDS + adjustments)
CREATE TABLE IF NOT EXISTS settlement_components (
    component_id     TEXT PRIMARY KEY,
    allocation_id    TEXT NOT NULL REFERENCES payment_allocations(allocation_id),
    component_type   TEXT NOT NULL,   -- bank_credit | tds | adjustment
    amount           REAL NOT NULL,
    tds_section      TEXT,
    tds_status       TEXT,            -- claimed | evidence_pending | verified | rejected
    supporting_doc   TEXT,
    notes            TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Human Review Queue ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS review_cases (
    case_id           TEXT PRIMARY KEY,
    transaction_id    TEXT REFERENCES bank_transactions(transaction_id),
    invoice_id        TEXT,           -- best candidate (may be null)
    exception_type    TEXT NOT NULL,
    exception_summary TEXT,
    suggested_action  TEXT,
    status            TEXT NOT NULL DEFAULT 'open',
    -- open | approved | rejected | corrected | escalated
    reviewer          TEXT,
    reviewed_at       TEXT,
    resolution_notes  TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Audit Logs ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id        TEXT PRIMARY KEY,
    entity_type   TEXT NOT NULL,   -- transaction | invoice | allocation | review_case
    entity_id     TEXT NOT NULL,
    action        TEXT NOT NULL,
    actor         TEXT NOT NULL DEFAULT 'system',
    details       TEXT,            -- JSON
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    prev_hash     TEXT,
    entry_hash    TEXT             -- hash chain: editing any earlier entry breaks verification
);

-- ── Reconciliation Batches ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reconciliation_batches (
    batch_id          TEXT PRIMARY KEY,
    started_at        TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at      TEXT,
    total_transactions INTEGER DEFAULT 0,
    matched           INTEGER DEFAULT 0,
    needs_review      INTEGER DEFAULT 0,
    unmatched         INTEGER DEFAULT 0,
    status            TEXT DEFAULT 'running'
);

-- ── Customer credits (advances and overpayments held for a customer) ──────────
CREATE TABLE IF NOT EXISTS customer_credits (
    credit_id      TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES bank_transactions(transaction_id),
    customer_id    TEXT REFERENCES customers(customer_id),
    amount         REAL NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open',   -- open | void
    created_by     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Invoice adjustments (credit notes, write-offs, bank charges) ──────────────
CREATE TABLE IF NOT EXISTS invoice_adjustments (
    adjustment_id TEXT PRIMARY KEY,
    invoice_id    TEXT NOT NULL REFERENCES invoices(invoice_id),
    kind          TEXT NOT NULL,                   -- credit_note | write_off | bank_charge
    amount        REAL NOT NULL,
    reference     TEXT,
    notes         TEXT,
    status        TEXT NOT NULL DEFAULT 'active',  -- active | reversed
    created_by    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Vendor bills (money to be paid out) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS vendor_bills (
    bill_id            TEXT PRIMARY KEY,
    vendor_name        TEXT NOT NULL,
    bill_number        TEXT NOT NULL,
    bill_date          TEXT,
    due_date           TEXT,
    amount             REAL NOT NULL,
    bill_on_file       INTEGER NOT NULL DEFAULT 0,   -- the paper needed for audit has been checked
    source_document_id TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Vendor payments: which bank debit paid which bill ─────────────────────────
CREATE TABLE IF NOT EXISTS vendor_payments (
    payment_id     TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES bank_transactions(transaction_id),
    bill_id        TEXT REFERENCES vendor_bills(bill_id),   -- NULL = not a vendor payment
    amount         REAL NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',          -- active | reversed
    linked_by      TEXT NOT NULL,
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Users (login) ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'viewer',  -- viewer | reviewer | admin
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Website sign-in sessions. Only a hash of each token is kept.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    username   TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);

CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit log entries cannot be changed'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit log entries cannot be deleted'); END;

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_invoices_customer    ON invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status      ON invoices(status);
CREATE INDEX IF NOT EXISTS idx_txn_status           ON bank_transactions(status);
CREATE INDEX IF NOT EXISTS idx_txn_utr              ON bank_transactions(utr);
CREATE INDEX IF NOT EXISTS idx_alloc_txn            ON payment_allocations(transaction_id);
CREATE INDEX IF NOT EXISTS idx_alloc_invoice        ON payment_allocations(invoice_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity         ON audit_logs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_review_status        ON review_cases(status);
CREATE INDEX IF NOT EXISTS idx_review_txn           ON review_cases(transaction_id);
CREATE INDEX IF NOT EXISTS idx_remit_utr            ON remittance_records(utr);
CREATE INDEX IF NOT EXISTS idx_credit_txn           ON customer_credits(transaction_id);
CREATE INDEX IF NOT EXISTS idx_adj_invoice          ON invoice_adjustments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_txn_amount           ON bank_transactions(credit_amount);
CREATE INDEX IF NOT EXISTS idx_vpay_txn             ON vendor_payments(transaction_id);
CREATE INDEX IF NOT EXISTS idx_vpay_bill            ON vendor_payments(bill_id);
CREATE INDEX IF NOT EXISTS idx_setl_alloc           ON settlement_components(allocation_id);
