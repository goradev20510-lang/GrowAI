"""
ReconcileAI – Database Connection Manager
Provides a thread-safe SQLite connection with WAL mode enabled, schema creation
and lightweight in-place migrations for databases created by older versions.
"""
from __future__ import annotations
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from config import settings


# One connection per thread
_local = threading.local()
_path_override: Path | None = None


def get_database_path() -> Path:
    return _path_override or settings.DATABASE_PATH


def set_database_path(path: str | Path | None) -> None:
    """Point the app at a different database file (used by tests and scripts)."""
    global _path_override
    close_connection()
    _path_override = Path(path) if path else None


def get_connection() -> sqlite3.Connection:
    """Return (or create) a thread-local SQLite connection."""
    path = get_database_path()
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) != path:
        conn.close()
        conn = None
    if conn is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        _local.conn = conn
        _local.path = path
        _local.depth = 0
    return conn


def commit() -> None:
    """Commit, unless an enclosing transaction() owns the commit."""
    if getattr(_local, "depth", 0) == 0:
        get_connection().commit()


@contextmanager
def transaction():
    """
    Make every write inside the block atomic. The outermost block takes SQLite's
    write lock immediately, so state checked inside it cannot change underneath us.
    Nested blocks become savepoints.
    """
    conn = get_connection()
    depth = getattr(_local, "depth", 0)
    name = f"sp{depth}"
    if depth == 0:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute(f"SAVEPOINT {name}")
    _local.depth = depth + 1
    try:
        yield conn
    except BaseException:
        _local.depth = depth
        if depth == 0:
            conn.rollback()
        else:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
        raise
    _local.depth = depth
    if depth == 0:
        conn.commit()
    else:
        conn.execute(f"RELEASE {name}")


def initialise_database() -> None:
    """Create all tables if they don't already exist, then apply migrations."""
    schema_path = Path(__file__).parent / "schema.sql"
    conn = get_connection()
    _migrate(conn)                       # must run before CREATE INDEX on new columns
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    conn.commit()


def reset_database() -> None:
    """Delete all business data (keeps the schema and user accounts). Used by tests and demos."""
    conn = get_connection()
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    for table in ("settlement_components", "payment_allocations", "customer_credits", "invoice_adjustments",
                  "review_cases", "remittance_records", "extractions", "audit_logs", "reconciliation_batches",
                  "bank_transactions", "invoices", "customers", "documents"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    initialise_database()                # restores the audit triggers


def close_connection() -> None:
    """Close the thread-local connection."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
    _local.conn = None
    _local.path = None
    _local.depth = 0


# ── Migrations ────────────────────────────────────────────────────────────────

def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)).fetchone() is not None


def _migrate(conn: sqlite3.Connection) -> None:
    # v1 → v2: bank_transactions.utr was UNIQUE, which silently dropped a second
    # credit carrying the same UTR instead of letting duplicate detection flag it.
    if _table_exists(conn, "bank_transactions"):
        unique_utr = False
        for idx in conn.execute("PRAGMA index_list(bank_transactions)").fetchall():
            if idx["unique"] and idx["origin"] == "u":
                cols = [c["name"] for c in conn.execute(f"PRAGMA index_info('{idx['name']}')")]
                unique_utr |= cols == ["utr"]
        if unique_utr:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.executescript("""
                BEGIN;
                CREATE TABLE bank_transactions_new (
                    transaction_id   TEXT PRIMARY KEY,
                    utr              TEXT,
                    narration        TEXT,
                    credit_amount    REAL NOT NULL DEFAULT 0,
                    debit_amount     REAL NOT NULL DEFAULT 0,
                    transaction_date TEXT,
                    bank_name        TEXT,
                    account_number   TEXT,
                    currency         TEXT NOT NULL DEFAULT 'INR',
                    status           TEXT NOT NULL DEFAULT 'unmatched',
                    batch_id         TEXT,
                    source_document_id TEXT,
                    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
                );
                INSERT INTO bank_transactions_new SELECT
                    transaction_id, utr, narration, credit_amount, debit_amount, transaction_date,
                    bank_name, account_number, currency, status, batch_id, source_document_id, created_at
                FROM bank_transactions;
                DROP TABLE bank_transactions;
                ALTER TABLE bank_transactions_new RENAME TO bank_transactions;
                COMMIT;
            """)
            conn.execute("PRAGMA foreign_keys = ON")

    # v2: remittances carry the TDS section so the right rate is validated
    if _table_exists(conn, "remittance_records") and "tds_section" not in _columns(conn, "remittance_records"):
        conn.execute("ALTER TABLE remittance_records ADD COLUMN tds_section TEXT")
    if _table_exists(conn, "remittance_records") and "customer_gstin" not in _columns(conn, "remittance_records"):
        conn.execute("ALTER TABLE remittance_records ADD COLUMN customer_gstin TEXT")

    # v3: ledger columns
    for table, column, ddl in (
            ("invoices", "invoice_number", "TEXT"),
            ("invoices", "rounding_writeoff", "REAL NOT NULL DEFAULT 0"),
            ("invoices", "verified", "INTEGER NOT NULL DEFAULT 1"),
            ("payment_allocations", "remittance_id", "TEXT"),
            ("payment_allocations", "from_credit_id", "TEXT"),
            ("audit_logs", "prev_hash", "TEXT"),
            ("audit_logs", "entry_hash", "TEXT")):
        if _table_exists(conn, table) and column not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # v3: what was already paid before import is kept, so recalculation never forgets it
    if _table_exists(conn, "invoices") and "opening_paid" not in _columns(conn, "invoices"):
        conn.execute("ALTER TABLE invoices ADD COLUMN opening_paid REAL NOT NULL DEFAULT 0")
        applied = ("COALESCE((SELECT SUM(allocated_amount) FROM payment_allocations pa "
                   "WHERE pa.invoice_id = invoices.invoice_id AND pa.allocation_status='approved'), 0)"
                   if _table_exists(conn, "payment_allocations") else "0")
        conn.execute(f"UPDATE invoices SET opening_paid = MAX(0, ROUND(total_amount - outstanding_amount - {applied}, 2))")

    # v2: older engines opened a new case on every re-run. Keep only the newest open
    # case per transaction; the rest are marked 'superseded' (idempotent).
    if _table_exists(conn, "review_cases"):
        conn.execute("""
            UPDATE review_cases SET status='superseded',
                   resolution_notes=COALESCE(resolution_notes, 'Superseded by a newer case (migration)')
            WHERE status='open' AND rowid NOT IN (
                SELECT MAX(rowid) FROM review_cases WHERE status='open' GROUP BY transaction_id)""")
        # A credit that is already matched (or excluded) has nothing left to decide.
        if _table_exists(conn, "bank_transactions"):
            conn.execute("""
                UPDATE review_cases SET status='superseded',
                       resolution_notes=COALESCE(resolution_notes, 'Credit already resolved (migration)')
                WHERE status='open' AND transaction_id IN (
                    SELECT transaction_id FROM bank_transactions WHERE status IN ('matched','excluded'))""")
    conn.commit()
