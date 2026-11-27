"""
ReconcileAI – Exact Match Engine
Fast lookup for transactions that carry explicit invoice references.
"""
from __future__ import annotations
import re
from database.repositories import get_all_invoices
from matching.references import invoice_key, invoice_number


def find_exact_invoice_match(invoice_ref_candidate: str | None,
                              all_invoices: list[dict] | None = None,
                              allow_numeric: bool = False) -> list[dict]:
    """
    Search for invoices whose invoice_id matches the extracted reference.
    Returns a list of matching invoice dicts (usually 0 or 1 items).

    allow_numeric: also match a bare number ("0045", from an LLM-read narration or a
    remittance saying "bill 45") against the numeric part of invoice ids, but only
    when exactly one invoice has that number and it has at least 3 digits.
    """
    if not invoice_ref_candidate:
        return []

    key        = invoice_key(invoice_ref_candidate)
    invoices   = all_invoices if all_invoices is not None else get_all_invoices()
    matches    = [inv for inv in invoices if invoice_key(invoice_number(inv)) == key
                  or invoice_key(inv.get("invoice_id", "")) == key]

    raw = re.sub(r"\D", "", invoice_ref_candidate)
    if not matches and allow_numeric and invoice_ref_candidate.strip().isdigit() and len(raw) >= 3:
        num = raw.lstrip("0") or "0"
        hits = [inv for inv in invoices
                if (re.sub(r"\D", "", invoice_number(inv)).lstrip("0") or "0") == num]
        if len(hits) == 1:
            matches = hits
    return matches
