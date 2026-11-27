"""
ReconcileAI – Repository Layer
All database read/write operations. No SQL lives outside this file.
"""
from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from database.db import get_connection, commit, transaction


# ── Helpers ───────────────────────────────────────────────────────────────────

def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12].upper()}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def _rows(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ── Customer Repository ───────────────────────────────────────────────────────

def upsert_customer(name: str, gstin: str | None = None, pan: str | None = None,
                    email: str | None = None, variants: list[str] | None = None) -> str:
    conn = get_connection()
    name = (name or "Unknown").strip()
    # Try match by GSTIN first, then by name
    if gstin:
        row = conn.execute("SELECT customer_id FROM customers WHERE gstin = ?", (gstin,)).fetchone()
        if row:
            return row["customer_id"]
    row = conn.execute("SELECT customer_id, gstin, name_variants FROM customers WHERE name = ?",
                       (name,)).fetchone()
    if row:
        updates, params = [], []
        if gstin and not row["gstin"]:
            updates.append("gstin=?"); params.append(gstin)
        if variants:
            known = set(json.loads(row["name_variants"] or "[]"))
            if not set(variants) <= known:
                updates.append("name_variants=?"); params.append(json.dumps(sorted(known | set(variants))))
        if updates:
            conn.execute(f"UPDATE customers SET {', '.join(updates)} WHERE customer_id=?",
                         (*params, row["customer_id"]))
            commit()
        return row["customer_id"]
    cid = _new_id("CUST")
    conn.execute(
        "INSERT INTO customers(customer_id,name,name_variants,gstin,pan,email,created_at) VALUES(?,?,?,?,?,?,?)",
        (cid, name, json.dumps(variants or []), gstin, pan, email, _now())
    )
    commit()
    return cid


def get_all_customers() -> list[dict]:
    conn = get_connection()
    return _rows(conn.execute("SELECT * FROM customers ORDER BY name").fetchall())


def get_customer_by_id(customer_id: str) -> dict:
    conn = get_connection()
    return _row_to_dict(conn.execute("SELECT * FROM customers WHERE customer_id=?", (customer_id,)).fetchone())


# ── Invoice Repository ────────────────────────────────────────────────────────

def invoice_exists(invoice_id: str) -> bool:
    conn = get_connection()
    return conn.execute("SELECT 1 FROM invoices WHERE invoice_id=?", (invoice_id,)).fetchone() is not None


def insert_invoice(data: dict) -> str:
    """
    Insert an invoice. If the invoice id already exists the existing row is kept
    unchanged — re-importing a file must never reset outstanding balances or
    status for invoices that have already received payments.
    """
    conn = get_connection()
    iid = data.get("invoice_id") or _new_id("INV")
    total = data.get("total_amount", 0) or 0
    given = data.get("outstanding_amount")
    opening = round(max(0.0, float(total) - float(given)), 2) if given is not None else 0.0
    conn.execute(
        """INSERT INTO invoices
           (invoice_id,customer_id,supplier_name,customer_name,customer_gstin,
            invoice_date,due_date,taxable_amount,gst_amount,total_amount,
            outstanding_amount,currency,status,source_document_id,created_at,
            invoice_number,opening_paid,verified)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(invoice_id) DO NOTHING""",
        (iid, data.get("customer_id"), data.get("supplier_name"), data.get("customer_name"),
         data.get("customer_gstin"), data.get("invoice_date"), data.get("due_date"),
         data.get("taxable_amount", 0) or 0, data.get("gst_amount", 0) or 0, total,
         data.get("outstanding_amount", total) if data.get("outstanding_amount") is not None else total,
         data.get("currency", "INR") or "INR", data.get("status", "open") or "open",
         data.get("source_document_id"), _now(),
         data.get("invoice_number") or iid, opening, 1 if data.get("verified", True) else 0)
    )
    commit()
    return iid


def find_invoices_by_number(number: str) -> list[dict]:
    conn = get_connection()
    return _rows(conn.execute("SELECT * FROM invoices WHERE UPPER(COALESCE(invoice_number, invoice_id))=UPPER(?)",
                              (number,)).fetchall())


def mark_invoice_verified(invoice_id: str) -> None:
    get_connection().execute("UPDATE invoices SET verified=1 WHERE invoice_id=?", (invoice_id,))
    commit()


def get_invoice(invoice_id: str) -> dict:
    conn = get_connection()
    return _row_to_dict(conn.execute("SELECT * FROM invoices WHERE invoice_id=?", (invoice_id,)).fetchone())


def get_all_invoices(status: str | None = None) -> list[dict]:
    conn = get_connection()
    if status:
        rows = conn.execute("SELECT * FROM invoices WHERE status=? ORDER BY rowid", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM invoices ORDER BY rowid").fetchall()
    return _rows(rows)


def get_open_invoices() -> list[dict]:
    """Invoices that can still receive money (open or partially paid)."""
    conn = get_connection()
    return _rows(conn.execute(
        "SELECT * FROM invoices WHERE status IN ('open','partially_paid') ORDER BY rowid").fetchall())


def get_partially_paid_invoices(customer_id: str | None = None) -> list[dict]:
    conn = get_connection()
    if customer_id:
        rows = conn.execute(
            "SELECT * FROM invoices WHERE status='partially_paid' AND customer_id=?", (customer_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM invoices WHERE status='partially_paid'").fetchall()
    return _rows(rows)


def update_invoice_outstanding(invoice_id: str, new_outstanding: float, new_status: str,
                               rounding_writeoff: float = 0.0) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE invoices SET outstanding_amount=?, status=?, rounding_writeoff=? WHERE invoice_id=?",
        (round(float(new_outstanding), 2), new_status, round(float(rounding_writeoff), 2), invoice_id)
    )
    commit()


# ── Bank Transaction Repository ───────────────────────────────────────────────

def transaction_exists(transaction_id: str) -> bool:
    conn = get_connection()
    return conn.execute("SELECT 1 FROM bank_transactions WHERE transaction_id=?",
                        (transaction_id,)).fetchone() is not None


def insert_transaction(data: dict) -> str:
    """Insert a bank line. Re-importing the identical line (same id) is a no-op."""
    conn = get_connection()
    tid = data.get("transaction_id") or _new_id("TXN")
    credit = float(data.get("credit_amount", 0) or 0)
    status = data.get("status", "unmatched")
    if credit <= 0 and status == "unmatched":
        status = "excluded"          # debits / zero lines are not receivables
    conn.execute(
        """INSERT OR IGNORE INTO bank_transactions
           (transaction_id,utr,narration,credit_amount,debit_amount,
            transaction_date,bank_name,account_number,currency,status,batch_id,
            source_document_id,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tid, data.get("utr"), data.get("narration"), credit,
         data.get("debit_amount", 0) or 0, data.get("transaction_date"),
         data.get("bank_name"), data.get("account_number"),
         data.get("currency", "INR"), status,
         data.get("batch_id"), data.get("source_document_id"), _now())
    )
    commit()
    return tid


def get_transaction(transaction_id: str) -> dict:
    conn = get_connection()
    return _row_to_dict(conn.execute(
        "SELECT * FROM bank_transactions WHERE transaction_id=?", (transaction_id,)
    ).fetchone())


def get_all_transactions(status: str | None = None) -> list[dict]:
    conn = get_connection()
    if status:
        rows = conn.execute("SELECT * FROM bank_transactions WHERE status=? ORDER BY rowid",
                            (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM bank_transactions ORDER BY rowid").fetchall()
    return _rows(rows)


def get_possible_duplicates(transaction_id: str, utr: str | None, amount: float) -> list[dict]:
    """Earlier credits sharing the UTR or the amount — the only rows duplicate rules can match."""
    conn = get_connection()
    row = conn.execute("SELECT rowid FROM bank_transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
    if not row:
        return get_all_transactions()
    return _rows(conn.execute(
        """SELECT * FROM bank_transactions
           WHERE rowid < ? AND status != 'excluded'
             AND ((? != '' AND UPPER(TRIM(COALESCE(utr,''))) = ?) OR ABS(credit_amount - ?) < 0.005)
           ORDER BY rowid""",
        (row[0], (utr or "").strip().upper(), (utr or "").strip().upper(), float(amount or 0))).fetchall())


def update_transaction_status(transaction_id: str, status: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE bank_transactions SET status=? WHERE transaction_id=?", (status, transaction_id)
    )
    commit()


# ── Document Repository ───────────────────────────────────────────────────────

def get_document_by_hash(file_hash: str) -> dict:
    conn = get_connection()
    return _row_to_dict(conn.execute("SELECT * FROM documents WHERE file_hash=?", (file_hash,)).fetchone())


def insert_document(data: dict) -> str:
    conn = get_connection()
    existing = get_document_by_hash(data["file_hash"])
    if existing:
        return existing["document_id"]
    did = data.get("document_id") or _new_id("DOC")
    conn.execute(
        """INSERT INTO documents(document_id,filename,document_type,file_hash,file_path,upload_time,batch_id)
           VALUES(?,?,?,?,?,?,?)""",
        (did, data["filename"], data.get("document_type"), data["file_hash"],
         data.get("file_path"), _now(), data.get("batch_id"))
    )
    commit()
    return did


def delete_document(document_id: str) -> None:
    """Forget a file that produced nothing, so a corrected retry is not refused as already uploaded."""
    with transaction() as conn:
        conn.execute("DELETE FROM extractions WHERE document_id=?", (document_id,))
        conn.execute("DELETE FROM documents WHERE document_id=?", (document_id,))


def get_all_documents() -> list[dict]:
    conn = get_connection()
    return _rows(conn.execute("SELECT * FROM documents ORDER BY upload_time DESC, rowid DESC").fetchall())


# ── Extraction Repository ─────────────────────────────────────────────────────

def insert_extraction(data: dict) -> str:
    conn = get_connection()
    eid = _new_id("EXT")
    conn.execute(
        """INSERT INTO extractions(extraction_id,document_id,extractor,raw_output,validated_output,
           extraction_status,missing_fields,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (eid, data.get("document_id"), data.get("extractor"), data.get("raw_output"),
         data.get("validated_output"), data.get("extraction_status", "complete"),
         json.dumps(data.get("missing_fields", [])), _now())
    )
    commit()
    return eid


def get_extractions_for_document(document_id: str) -> list[dict]:
    conn = get_connection()
    return _rows(conn.execute("SELECT * FROM extractions WHERE document_id=? ORDER BY created_at",
                              (document_id,)).fetchall())


# ── Remittance Repository ─────────────────────────────────────────────────────

def insert_remittance(data: dict) -> str:
    conn = get_connection()
    rid = _new_id("REM")
    conn.execute(
        """INSERT INTO remittance_records
           (remittance_id,document_id,customer_name,customer_gstin,invoice_references,payment_amount,
            tds_amount,tds_section,utr,payment_date,currency,evidence_text,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rid, data.get("document_id"), data.get("customer_name"), data.get("customer_gstin"),
         json.dumps(data.get("invoice_references") or []),
         data.get("payment_amount"), data.get("tds_amount") or 0, data.get("tds_section"),
         data.get("utr"), data.get("payment_date"), data.get("currency") or "INR",
         json.dumps(data.get("evidence") or []), _now())
    )
    commit()
    return rid


def get_remittance_by_utr(utr: str) -> dict | None:
    if not utr:
        return None
    conn = get_connection()
    row = conn.execute("SELECT * FROM remittance_records WHERE UPPER(utr)=UPPER(?) ORDER BY rowid DESC LIMIT 1",
                       (utr.strip(),)).fetchone()
    return _row_to_dict(row) if row else None


def find_remittances_by_amount(amount: float, around_date: str | None = None,
                               window_days: int = 10, for_transaction: str | None = None) -> list[dict]:
    """
    Remittances *without* a UTR whose stated payment amount equals `amount`.
    Used to link remittance emails that never quoted the bank reference.
    """
    conn = get_connection()
    rows = _rows(conn.execute(
        """SELECT * FROM remittance_records
           WHERE (utr IS NULL OR utr = '') AND ABS(COALESCE(payment_amount,0) - ?) < 0.01
             AND remittance_id NOT IN (
                 SELECT remittance_id FROM payment_allocations
                 WHERE remittance_id IS NOT NULL AND allocation_status IN ('proposed','approved')
                   AND transaction_id != ?)""",
        (float(amount), for_transaction or "")).fetchall())
    if not around_date:
        return rows
    try:
        from dateutil import parser as dp
        d = dp.parse(around_date).date()
    except Exception:
        return rows
    out = []
    for r in rows:
        if not r.get("payment_date"):
            out.append(r)
            continue
        try:
            if abs((dp.parse(r["payment_date"]).date() - d).days) <= window_days:
                out.append(r)
        except Exception:
            out.append(r)
    return out


def get_all_remittances() -> list[dict]:
    conn = get_connection()
    return _rows(conn.execute("SELECT * FROM remittance_records ORDER BY rowid").fetchall())


# ── Allocation Repository ─────────────────────────────────────────────────────

def insert_allocation(data: dict) -> str:
    conn = get_connection()
    aid = _new_id("ALLOC")
    conn.execute(
        """INSERT INTO payment_allocations
           (allocation_id,transaction_id,invoice_id,allocated_amount,allocation_status,
            confidence_score,decision_reason,approved_by,approved_at,created_at,remittance_id,from_credit_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (aid, data["transaction_id"], data["invoice_id"], round(float(data["allocated_amount"]), 2),
         data.get("allocation_status", "proposed"), data.get("confidence_score"),
         data.get("decision_reason"), data.get("approved_by"),
         _now() if data.get("allocation_status") == "approved" else None, _now(),
         data.get("remittance_id"), data.get("from_credit_id"))
    )
    commit()
    return aid


def get_allocation(allocation_id: str) -> dict:
    conn = get_connection()
    return _row_to_dict(conn.execute("SELECT * FROM payment_allocations WHERE allocation_id=?",
                                     (allocation_id,)).fetchone())


def get_all_allocations(status: str | None = None) -> list[dict]:
    conn = get_connection()
    if status:
        return _rows(conn.execute("SELECT * FROM payment_allocations WHERE allocation_status=? ORDER BY rowid",
                                  (status,)).fetchall())
    return _rows(conn.execute("SELECT * FROM payment_allocations ORDER BY rowid").fetchall())


def get_allocations_for_transaction(transaction_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM payment_allocations WHERE transaction_id=? ORDER BY rowid", (transaction_id,)
    ).fetchall()
    return _rows(rows)


def get_allocations_for_invoice(invoice_id: str) -> list[dict]:
    """Approved allocations only — these are the ones that reduce the balance."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM payment_allocations WHERE invoice_id=? AND allocation_status='approved' ORDER BY rowid",
        (invoice_id,)
    ).fetchall()
    return _rows(rows)


def get_rejected_invoice_ids(transaction_id: str) -> set[str]:
    """Invoices a reviewer already rejected (or reversed) for this transaction."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT DISTINCT invoice_id FROM payment_allocations
           WHERE transaction_id=? AND allocation_status IN ('rejected','reversed')""",
        (transaction_id,)).fetchall()
    return {r["invoice_id"] for r in rows}


def update_decision_reason(allocation_id: str, reason: str) -> None:
    get_connection().execute("UPDATE payment_allocations SET decision_reason=? WHERE allocation_id=?",
                             (reason, allocation_id))
    commit()


def update_allocation_status(allocation_id: str, status: str, reviewer: str = "system",
                             notes: str | None = None) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE payment_allocations
           SET allocation_status=?, approved_by=?, approved_at=?
           WHERE allocation_id=?""",
        (status, reviewer, _now(), allocation_id)
    )
    commit()


# ── Settlement Components ─────────────────────────────────────────────────────

def insert_settlement_component(data: dict) -> str:
    conn = get_connection()
    cid = _new_id("SETL")
    conn.execute(
        """INSERT INTO settlement_components
           (component_id,allocation_id,component_type,amount,tds_section,
            tds_status,supporting_doc,notes,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (cid, data["allocation_id"], data["component_type"], round(float(data["amount"]), 2),
         data.get("tds_section"), data.get("tds_status"), data.get("supporting_doc"),
         data.get("notes"), _now())
    )
    commit()
    return cid


def get_settlement_components(allocation_id: str) -> list[dict]:
    conn = get_connection()
    return _rows(conn.execute("SELECT * FROM settlement_components WHERE allocation_id=? ORDER BY rowid",
                              (allocation_id,)).fetchall())


def get_tds_components(status: str | None = None) -> list[dict]:
    """TDS components on approved allocations, joined with invoice + transaction context."""
    conn = get_connection()
    sql = """SELECT sc.*, pa.invoice_id, pa.transaction_id, pa.allocation_status,
                    i.customer_name, i.total_amount AS invoice_total
             FROM settlement_components sc
             JOIN payment_allocations pa ON sc.allocation_id = pa.allocation_id
             LEFT JOIN invoices i ON i.invoice_id = pa.invoice_id
             WHERE sc.component_type='tds' AND pa.allocation_status='approved'"""
    params: tuple = ()
    if status:
        sql += " AND sc.tds_status=?"
        params = (status,)
    return _rows(conn.execute(sql + " ORDER BY sc.rowid", params).fetchall())


def update_settlement_component(component_id: str, **fields: Any) -> None:
    allowed = {"tds_status", "supporting_doc", "notes", "tds_section"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    conn = get_connection()
    conn.execute(f"UPDATE settlement_components SET {', '.join(f'{k}=?' for k in sets)} WHERE component_id=?",
                 (*sets.values(), component_id))
    commit()


def get_all_settlement_components() -> list[dict]:
    conn = get_connection()
    return _rows(conn.execute("SELECT * FROM settlement_components ORDER BY rowid").fetchall())


# ── Review Cases ──────────────────────────────────────────────────────────────

def insert_review_case(data: dict) -> str:
    conn = get_connection()
    cid = _new_id("CASE")
    conn.execute(
        """INSERT INTO review_cases
           (case_id,transaction_id,invoice_id,exception_type,exception_summary,
            suggested_action,status,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (cid, data.get("transaction_id"), data.get("invoice_id"),
         data["exception_type"], data.get("exception_summary"),
         data.get("suggested_action"), "open", _now())
    )
    commit()
    return cid


def get_review_case(case_id: str) -> dict:
    conn = get_connection()
    return _row_to_dict(conn.execute("SELECT * FROM review_cases WHERE case_id=?", (case_id,)).fetchone())


def get_open_review_cases() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM review_cases WHERE status='open' ORDER BY created_at, rowid"
    ).fetchall()
    return _rows(rows)


def get_open_cases_for_transaction(transaction_id: str) -> list[dict]:
    conn = get_connection()
    return _rows(conn.execute(
        "SELECT * FROM review_cases WHERE transaction_id=? AND status='open' ORDER BY rowid",
        (transaction_id,)).fetchall())


def get_all_review_cases() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM review_cases ORDER BY created_at DESC, rowid DESC").fetchall()
    return _rows(rows)


def update_review_case(case_id: str, status: str, reviewer: str, notes: str) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE review_cases
           SET status=?, reviewer=?, reviewed_at=?, resolution_notes=?
           WHERE case_id=?""",
        (status, reviewer, _now(), notes, case_id)
    )
    commit()


# ── Audit Logs ────────────────────────────────────────────────────────────────

def _audit_hash(prev: str, *fields: str) -> str:
    return hashlib.sha256(json.dumps([prev, *fields]).encode("utf-8")).hexdigest()


def create_audit_log(entity_type: str, entity_id: str, action: str,
                     actor: str = "system", details: dict | None = None) -> str:
    lid = _new_id("LOG")
    payload, now = json.dumps(details or {}, default=str), _now()
    with transaction() as conn:
        last = conn.execute("SELECT entry_hash FROM audit_logs ORDER BY rowid DESC LIMIT 1").fetchone()
        prev = (last["entry_hash"] if last else None) or ""
        digest = _audit_hash(prev, lid, entity_type, entity_id, action, actor, payload, now)
        conn.execute(
            """INSERT INTO audit_logs(log_id,entity_type,entity_id,action,actor,details,created_at,prev_hash,entry_hash)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (lid, entity_type, entity_id, action, actor, payload, now, prev, digest))
    return lid


def verify_audit_chain() -> dict:
    """
    Re-compute the hash chain. Entries written before the chain existed are counted as
    unprotected. Removal of the newest entries cannot be detected from the table alone:
    record `head` somewhere else to cover that.
    """
    rows = _rows(get_connection().execute("SELECT * FROM audit_logs ORDER BY rowid").fetchall())
    prev, started, unprotected = "", False, 0
    for r in rows:
        if not r.get("entry_hash"):
            if started:
                return {"ok": False, "broken_at": r["log_id"], "reason": "entry without a hash inside the chain"}
            unprotected += 1
            continue
        expected = _audit_hash(prev, r["log_id"], r["entity_type"], r["entity_id"], r["action"], r["actor"],
                               r["details"], r["created_at"])
        if r["prev_hash"] != prev or r["entry_hash"] != expected:
            return {"ok": False, "broken_at": r["log_id"], "reason": "entry changed, inserted or removed"}
        prev, started = r["entry_hash"], True
    return {"ok": True, "entries": len(rows), "unprotected": unprotected, "head": prev}


def get_audit_logs(entity_id: str | None = None, limit: int = 200,
                   entity_type: str | None = None, action: str | None = None,
                   search: str | None = None) -> list[dict]:
    conn = get_connection()
    where, params = [], []
    if entity_id:
        where.append("entity_id=?"); params.append(entity_id)
    if entity_type:
        where.append("entity_type=?"); params.append(entity_type)
    if action:
        where.append("action=?"); params.append(action)
    if search:
        where.append("(entity_id LIKE ? OR details LIKE ? OR action LIKE ?)")
        params += [f"%{search}%"] * 3
    sql = "SELECT * FROM audit_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    return _rows(conn.execute(sql, (*params, limit)).fetchall())


def get_audit_actions() -> list[str]:
    conn = get_connection()
    return [r[0] for r in conn.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action").fetchall()]


# ── Reconciliation Batch ──────────────────────────────────────────────────────

def get_batch(batch_id: str) -> dict:
    return _row_to_dict(get_connection().execute(
        "SELECT * FROM reconciliation_batches WHERE batch_id=?", (batch_id,)).fetchone())


def set_batch_status(batch_id: str, status: str) -> None:
    get_connection().execute("UPDATE reconciliation_batches SET status=?, completed_at=? WHERE batch_id=?",
                             (status, _now(), batch_id))
    commit()


def create_batch() -> str:
    conn = get_connection()
    bid = _new_id("BATCH")
    conn.execute(
        "INSERT INTO reconciliation_batches(batch_id,started_at,status) VALUES(?,?,?)",
        (bid, _now(), "running")
    )
    commit()
    return bid


def update_batch(batch_id: str, stats: dict) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE reconciliation_batches
           SET completed_at=?,total_transactions=?,matched=?,needs_review=?,unmatched=?,status=?
           WHERE batch_id=?""",
        (_now(), stats.get("total", 0), stats.get("matched", 0),
         stats.get("needs_review", 0), stats.get("unmatched", 0),
         "completed", batch_id)
    )
    commit()


def get_all_batches() -> list[dict]:
    conn = get_connection()
    return _rows(conn.execute("SELECT * FROM reconciliation_batches ORDER BY started_at DESC, rowid DESC").fetchall())


def get_reconciliation_summary() -> dict:
    conn = get_connection()
    q = lambda sql: conn.execute(sql).fetchone()[0]
    return {
        "total_transactions": q("SELECT COUNT(*) FROM bank_transactions WHERE status != 'excluded'"),
        "matched":            q("SELECT COUNT(*) FROM bank_transactions WHERE status='matched'"),
        "needs_review":       q("SELECT COUNT(*) FROM bank_transactions WHERE status='review'"),
        "unmatched":          q("SELECT COUNT(*) FROM bank_transactions WHERE status='unmatched'"),
        "duplicates":         q("SELECT COUNT(*) FROM bank_transactions WHERE status='duplicate'"),
        "excluded":           q("SELECT COUNT(*) FROM bank_transactions WHERE status='excluded'"),
        "invoices_total":     q("SELECT COUNT(*) FROM invoices"),
        "invoices_open":      q("SELECT COUNT(*) FROM invoices WHERE status='open'"),
        "invoices_partial":   q("SELECT COUNT(*) FROM invoices WHERE status='partially_paid'"),
        "invoices_settled":   q("SELECT COUNT(*) FROM invoices WHERE status='settled'"),
        "invoices_overpaid":  q("SELECT COUNT(*) FROM invoices WHERE status='overpaid'"),
        "open_review_cases":  q("SELECT COUNT(*) FROM review_cases WHERE status='open'"),
        "amount_received":    round(q("SELECT COALESCE(SUM(credit_amount),0) FROM bank_transactions WHERE status != 'excluded'"), 2),
        "amount_matched":     round(q("SELECT COALESCE(SUM(credit_amount),0) FROM bank_transactions WHERE status='matched'"), 2),
        "amount_in_review":   round(q("SELECT COALESCE(SUM(credit_amount),0) FROM bank_transactions WHERE status='review'"), 2),
        "amount_unmatched":   round(q("SELECT COALESCE(SUM(credit_amount),0) FROM bank_transactions WHERE status='unmatched'"), 2),
        "invoice_value":      round(q("SELECT COALESCE(SUM(total_amount),0) FROM invoices"), 2),
        "outstanding_value":  round(q("SELECT COALESCE(SUM(outstanding_amount),0) FROM invoices WHERE status IN ('open','partially_paid')"), 2),
        "tds_pending":        round(q("""SELECT COALESCE(SUM(sc.amount),0) FROM settlement_components sc
                                         JOIN payment_allocations pa ON pa.allocation_id = sc.allocation_id
                                         WHERE sc.component_type='tds' AND pa.allocation_status='approved'
                                           AND COALESCE(sc.tds_status,'') NOT IN ('verified','rejected')"""), 2),
        "unapplied_credit":   round(q("""SELECT COALESCE(SUM(c.amount),0) - COALESCE((
                                             SELECT SUM(pa.allocated_amount) FROM payment_allocations pa
                                             WHERE pa.from_credit_id IS NOT NULL AND pa.allocation_status='approved'),0)
                                         FROM customer_credits c WHERE c.status='open'"""), 2),
    }


def update_allocation_amount(allocation_id: str, new_amount: float) -> None:
    conn = get_connection()
    conn.execute("UPDATE payment_allocations SET allocated_amount=? WHERE allocation_id=?",
                 (round(float(new_amount), 2), allocation_id))
    commit()


def get_settlement_component(component_id: str) -> dict:
    conn = get_connection()
    return _row_to_dict(conn.execute("SELECT * FROM settlement_components WHERE component_id=?",
                                     (component_id,)).fetchone())


# ── Customer credits ──────────────────────────────────────────────────────────

_CREDIT_SQL = """
    SELECT c.*, cu.name AS customer_name,
           ROUND(c.amount - COALESCE((SELECT SUM(pa.allocated_amount) FROM payment_allocations pa
                 WHERE pa.from_credit_id = c.credit_id AND pa.allocation_status='approved'), 0), 2) AS remaining
    FROM customer_credits c LEFT JOIN customers cu ON cu.customer_id = c.customer_id
"""


def get_credits(open_only: bool = True) -> list[dict]:
    sql = _CREDIT_SQL + (" WHERE c.status='open'" if open_only else "") + " ORDER BY c.rowid"
    return _rows(get_connection().execute(sql).fetchall())


def get_credit(credit_id: str) -> dict:
    return _row_to_dict(get_connection().execute(_CREDIT_SQL + " WHERE c.credit_id=?", (credit_id,)).fetchone())


def get_open_credit_for_transaction(transaction_id: str) -> dict:
    return _row_to_dict(get_connection().execute(
        _CREDIT_SQL + " WHERE c.transaction_id=? AND c.status='open'", (transaction_id,)).fetchone())


def insert_credit(transaction_id: str, customer_id: str | None, amount: float, created_by: str) -> str:
    cid = _new_id("CRED")
    get_connection().execute(
        """INSERT INTO customer_credits(credit_id,transaction_id,customer_id,amount,status,created_by,created_at)
           VALUES(?,?,?,?,'open',?,?)""", (cid, transaction_id, customer_id, round(float(amount), 2), created_by, _now()))
    commit()
    return cid


def update_credit(credit_id: str, amount: float | None = None, status: str | None = None) -> None:
    conn = get_connection()
    if amount is not None:
        conn.execute("UPDATE customer_credits SET amount=? WHERE credit_id=?", (round(float(amount), 2), credit_id))
    if status is not None:
        conn.execute("UPDATE customer_credits SET status=? WHERE credit_id=?", (status, credit_id))
    commit()


# ── Invoice adjustments ───────────────────────────────────────────────────────

def get_adjustments(invoice_id: str | None = None, active_only: bool = True) -> list[dict]:
    where, params = [], []
    if invoice_id:
        where.append("invoice_id=?"); params.append(invoice_id)
    if active_only:
        where.append("status='active'")
    sql = "SELECT * FROM invoice_adjustments" + (" WHERE " + " AND ".join(where) if where else "")
    return _rows(get_connection().execute(sql + " ORDER BY rowid", params).fetchall())


def get_adjustment(adjustment_id: str) -> dict:
    return _row_to_dict(get_connection().execute(
        "SELECT * FROM invoice_adjustments WHERE adjustment_id=?", (adjustment_id,)).fetchone())


def insert_adjustment(invoice_id: str, kind: str, amount: float, reference: str | None,
                      notes: str, created_by: str) -> str:
    aid = _new_id("ADJ")
    get_connection().execute(
        """INSERT INTO invoice_adjustments(adjustment_id,invoice_id,kind,amount,reference,notes,status,created_by,created_at)
           VALUES(?,?,?,?,?,?,'active',?,?)""",
        (aid, invoice_id, kind, round(float(amount), 2), reference, notes, created_by, _now()))
    commit()
    return aid


def set_adjustment_status(adjustment_id: str, status: str) -> None:
    get_connection().execute("UPDATE invoice_adjustments SET status=? WHERE adjustment_id=?",
                             (status, adjustment_id))
    commit()
