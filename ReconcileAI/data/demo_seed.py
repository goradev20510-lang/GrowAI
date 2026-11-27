"""
Fill an empty database with the synthetic dataset so the demo login has something to show.

The ledger is left part-way through a month: the engine has run, and a few decisions with
clear evidence are already made (recorded in the audit log as sample decisions). The
ambiguous cases stay open, so a demo can show a person resolving them.
"""
from __future__ import annotations

from database.repositories import get_all_invoices, get_open_review_cases

WHO = "Demo setup"
NOTE = "Sample decision made when the demo data was loaded."
# Evidence strong enough to link a bank debit to a vendor bill without asking anyone.
_STRONG = ("bill number is in the narration", "vendor name is in the narration")


def _settle_clear_cases() -> None:
    from decision import review_manager as rm
    done: set[str] = set()
    for case in get_open_review_cases():
        kind = case["exception_type"]
        if kind in done:
            continue
        if kind in ("possible_tds_deduction", "bulk_payment"):
            rm.approve_match(case["case_id"], reviewer=WHO, notes=NOTE)
        elif kind == "possible_duplicate":
            rm.confirm_duplicate(case["case_id"], reviewer=WHO, notes=NOTE)
        else:
            continue
        done.add(kind)


def _link_vendor_payments() -> None:
    from decision import vendor_payments as vp
    for line in vp.statement():
        if line["direction"] != "out":
            continue
        tid, narration = line["transaction_id"], (line.get("narration") or "").upper()
        if "BANK CHARGES" in narration:
            vp.mark_not_vendor(tid, reviewer=WHO, notes="Bank charges, not a vendor payment.")
            continue
        best = next(iter(vp.debit_detail(tid)["suggestions"]), None)
        if best and any(r in _STRONG for r in best["reasons"]):
            vp.link_payment(tid, best["bill_id"], reviewer=WHO, notes=NOTE)


def seed_if_empty() -> bool:
    if get_all_invoices():
        return False
    from decision.decision_engine import run_batch_reconciliation
    from extraction.ingestion import load_synthetic_dataset
    from extraction.vendor_bills import load_sample
    load_synthetic_dataset()
    load_sample()
    run_batch_reconciliation(use_llm=False)
    _settle_clear_cases()
    _link_vendor_payments()
    return True
