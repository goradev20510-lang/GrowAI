"""
ReconcileAI – Vendor bill register
Reads a CSV or Excel register of bills to be paid. No model is involved.
"""
from __future__ import annotations
import io
from pathlib import Path

import pandas as pd

from database.db import get_connection, transaction
from database.repositories import _new_id, _now, create_audit_log, insert_document
from extraction.bank_parser import _clean_amount
from extraction.ingestion import _precheck, calculate_document_hash, ingest_bank_statement
from utils.dates import to_iso

_COLS = {
    "vendor_name": ["vendor", "vendor name", "supplier", "supplier name", "payee"],
    "bill_number": ["bill number", "bill no", "invoice number", "invoice no", "bill"],
    "bill_date":   ["bill date", "invoice date", "date"],
    "due_date":    ["due date", "due"],
    "amount":      ["amount", "bill amount", "total", "total amount"],
    "bill_on_file": ["bill on file", "on file"],
}


def _text(value) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def ingest_vendor_bills(filename: str, file_bytes: bytes) -> dict:
    err = _precheck(filename, file_bytes, "bank_statement", False)     # same file types: CSV / Excel
    if err:
        return err
    try:
        reader = pd.read_csv if Path(filename).suffix.lower() == ".csv" else pd.read_excel
        df = reader(io.BytesIO(file_bytes), dtype=str)
    except Exception as e:
        return {"success": False, "reason": f"Could not read the bill register: {e}"}
    headers = {" ".join(str(c).lower().replace(".", " ").replace("_", " ").split()): c for c in df.columns}
    col = {k: next((headers[a] for a in names if a in headers), None) for k, names in _COLS.items()}
    if not (col["vendor_name"] and col["bill_number"] and col["amount"]):
        return {"success": False, "reason": "The file needs Vendor, Bill number and Amount columns."}

    bills, rejected = [], []
    for index, row in df.dropna(how="all").iterrows():
        get = lambda k: _text(row.get(col[k])) if col[k] else ""
        amount = _clean_amount(get("amount"))
        if not get("vendor_name") or not get("bill_number") or amount is None or amount <= 0:
            rejected.append({"row": int(index) + 1, "reason": "vendor, bill number or amount missing or unreadable"})
            continue
        bills.append({"vendor_name": get("vendor_name"), "bill_number": get("bill_number"),
                      "bill_date": to_iso(get("bill_date")), "due_date": to_iso(get("due_date")),
                      "amount": round(amount, 2),
                      "bill_on_file": int(get("bill_on_file").lower() in ("1", "yes", "y", "true"))})
    if not bills:
        return {"success": False, "reason": "No readable bills in this file.", "rejected_rows": rejected}

    with transaction() as conn:
        doc_id = insert_document({"filename": filename, "document_type": "vendor_bills",
                                  "file_hash": calculate_document_hash(file_bytes)})
        imported = already = 0
        for b in bills:
            if conn.execute("""SELECT 1 FROM vendor_bills
                                WHERE lower(vendor_name)=lower(?) AND lower(bill_number)=lower(?)""",
                            (b["vendor_name"], b["bill_number"])).fetchone():
                already += 1
                continue
            bill_id = _new_id("BILL")
            conn.execute(
                """INSERT INTO vendor_bills(bill_id,vendor_name,bill_number,bill_date,due_date,amount,
                                            bill_on_file,source_document_id,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (bill_id, b["vendor_name"], b["bill_number"], b["bill_date"], b["due_date"], b["amount"],
                 b["bill_on_file"], doc_id, _now()))
            create_audit_log("vendor_bill", bill_id, "imported", details={"source": filename})
            imported += 1
    return {"success": True, "document_id": doc_id, "bills_imported": imported, "already_present": already,
            "rejected_rows": rejected}


# Made-up vendors and payments for the demo.
_SAMPLE_BILLS = b"""Vendor,Bill Number,Bill Date,Due Date,Amount,Bill On File
Apex Office Supplies,APX-1042,2026-10-28,2026-11-12,48500,yes
BlueLine Logistics,BLL-337,2026-11-01,2026-11-16,126000,yes
Nimbus Cloud Services,NCS-2291,2026-11-03,2026-11-18,84000,yes
Kaveri Print Works,KPW-88,2026-11-05,2026-11-20,32500,no
Orion Facility Care,OFC-510,2026-11-08,2026-11-23,67000,yes
"""
_SAMPLE_DEBITS = b"""Date,Narration,Ref No,Debit,Credit
2026-11-10,NEFT DR APEX OFFICE SUPPLIES APX-1042,DEMOD0000000001,48500,
2026-11-14,NEFT DR BLUELINE LOGISTICS PART PAYMENT BLL-337,DEMOD0000000002,60000,
2026-11-17,IMPS DR NIMBUS CLOUD,DEMOD0000000003,84000,
2026-11-19,UPI DR VENDOR PAYMENT,DEMOD0000000004,32500,
2026-11-21,BANK CHARGES NEFT NOV,DEMOD0000000005,590,
"""


def load_sample() -> dict:
    """Idempotent: a file already imported is skipped by its hash."""
    bills = ingest_vendor_bills("demo_vendor_bills_synthetic.csv", _SAMPLE_BILLS)
    debits = ingest_bank_statement("demo_outgoing_payments_synthetic.csv", _SAMPLE_DEBITS, bank_name="AXIS Bank")
    return {"bills": bills.get("bills_imported", 0), "payments_out": debits.get("debits_excluded", 0)}
