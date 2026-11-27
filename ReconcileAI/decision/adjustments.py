"""
Entries that change what a customer owes without a new bank line: credit notes,
write-offs, bank charges, holding a receipt as an advance, and applying held credit.
Every action needs a named person and a note, and is atomic.
"""
from __future__ import annotations
from decimal import Decimal

from database.db import transaction
from database.repositories import (
    get_invoice, get_adjustment, insert_adjustment, set_adjustment_status, create_audit_log,
    get_credit, insert_allocation, insert_settlement_component, get_review_case, get_transaction,
    update_review_case, update_transaction_status, get_allocations_for_transaction,
    update_allocation_status, get_customer_by_id,
)
from decision.credits import sync_customer_credit
from decision.review_manager import ReviewError
from validation.settlement import finalise_settlement

KINDS = ("credit_note", "write_off", "bank_charge")


def _require(value: str, what: str) -> str:
    if not (value or "").strip():
        raise ReviewError(f"{what} is required")
    return value.strip()


def _money(value) -> Decimal:
    amount = Decimal(str(value))
    if amount.is_finite():
        amount = amount.quantize(Decimal("0.01"))
    if not amount.is_finite() or amount <= 0:
        raise ReviewError("Amount must be greater than zero")
    return amount


def add_adjustment(invoice_id: str, kind: str, amount: float, reviewer: str, notes: str,
                   reference: str | None = None) -> dict:
    _require(reviewer, "Reviewer")
    _require(notes, "A note")
    if kind not in KINDS:
        raise ReviewError(f"Unknown adjustment type '{kind}' (use {', '.join(KINDS)})")
    value = _money(amount)
    with transaction():
        inv = get_invoice(invoice_id)
        if not inv:
            raise ReviewError(f"Invoice {invoice_id} not found")
        if value > Decimal(str(inv["outstanding_amount"])):
            raise ReviewError(f"Amount exceeds the ₹{inv['outstanding_amount']:,.2f} outstanding")
        aid = insert_adjustment(invoice_id, kind, float(value), reference, notes, reviewer)
        settlement = finalise_settlement(invoice_id, actor=reviewer)
        create_audit_log("invoice", invoice_id, f"{kind}_added", actor=reviewer,
                         details={"adjustment_id": aid, "amount": float(value), "reference": reference,
                                  "notes": notes})
    return {"adjustment_id": aid, "invoice_id": invoice_id, "new_outstanding": settlement["outstanding"]}


def reverse_adjustment(adjustment_id: str, reviewer: str, notes: str) -> dict:
    _require(reviewer, "Reviewer")
    _require(notes, "A note")
    with transaction():
        adj = get_adjustment(adjustment_id)
        if not adj or adj["status"] != "active":
            raise ReviewError("No active adjustment with that id")
        set_adjustment_status(adjustment_id, "reversed")
        settlement = finalise_settlement(adj["invoice_id"], actor=reviewer)
        create_audit_log("invoice", adj["invoice_id"], "adjustment_reversed", actor=reviewer,
                         details={"adjustment_id": adjustment_id, "notes": notes})
    return {"invoice_id": adj["invoice_id"], "new_outstanding": settlement["outstanding"]}


def hold_as_credit(case_id: str, customer_id: str, reviewer: str, notes: str) -> dict:
    """The receipt is an advance: keep all of it as the customer's credit."""
    _require(reviewer, "Reviewer")
    _require(notes, "A note")
    with transaction():
        case = get_review_case(case_id)
        if not case or case["status"] != "open":
            raise ReviewError("This case is not open")
        if case["exception_type"] == "possible_duplicate":
            raise ReviewError("Resolve the duplicate question first")
        if not get_customer_by_id(customer_id):
            raise ReviewError("Choose a known customer")
        tid = case["transaction_id"]
        if get_transaction(tid)["status"] not in ("review", "unmatched"):
            raise ReviewError("This credit has already been resolved")
        for a in get_allocations_for_transaction(tid):
            if a["allocation_status"] == "approved":
                raise ReviewError("This credit is already applied to an invoice")
            if a["allocation_status"] == "proposed":
                update_allocation_status(a["allocation_id"], "rejected", reviewer, notes)
        update_transaction_status(tid, "matched")
        credit = sync_customer_credit(tid, reviewer, customer_id=customer_id)
        update_review_case(case_id, "corrected", reviewer, notes)
        create_audit_log("transaction", tid, "held_as_advance", actor=reviewer,
                         details={"case_id": case_id, "customer_id": customer_id, "notes": notes})
    return {"status": "held", **credit}


def apply_credit(credit_id: str, invoice_id: str, reviewer: str, notes: str,
                 amount: float | None = None) -> dict:
    """Pay (part of) an invoice from a customer's held credit."""
    _require(reviewer, "Reviewer")
    _require(notes, "A note")
    with transaction():
        credit = get_credit(credit_id)
        if not credit or credit["status"] != "open":
            raise ReviewError("No open credit with that id")
        inv = get_invoice(invoice_id)
        if not inv:
            raise ReviewError(f"Invoice {invoice_id} not found")
        if credit.get("customer_id") and inv.get("customer_id") != credit["customer_id"]:
            raise ReviewError("That invoice belongs to a different customer")
        remaining, owed = Decimal(str(credit["remaining"])), Decimal(str(inv["outstanding_amount"]))
        value = _money(amount) if amount is not None else min(remaining, owed)
        if value <= 0 or value > remaining or value > owed:
            raise ReviewError(f"Amount must be within the credit (₹{remaining:,.2f}) and the balance (₹{owed:,.2f})")
        aid = insert_allocation({
            "transaction_id": credit["transaction_id"], "invoice_id": invoice_id, "allocated_amount": float(value),
            "allocation_status": "approved", "confidence_score": 1.0, "approved_by": reviewer,
            "decision_reason": f"Applied from customer credit {credit_id}: {notes}", "from_credit_id": credit_id})
        insert_settlement_component({"allocation_id": aid, "component_type": "bank_credit", "amount": float(value)})
        settlement = finalise_settlement(invoice_id, actor=reviewer)
        create_audit_log("allocation", aid, "credit_applied", actor=reviewer,
                         details={"credit_id": credit_id, "invoice_id": invoice_id, "amount": float(value)})
    return {"allocation_id": aid, "new_outstanding": settlement["outstanding"],
            "credit_remaining": float(remaining - value)}
