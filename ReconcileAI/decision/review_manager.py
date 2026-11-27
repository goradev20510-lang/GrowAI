"""
ReconcileAI – Human Review Manager
Approve, reject, correct, reverse and dismiss reconciliation decisions, and
manage TDS evidence. Every action checks the current state, runs in one database
transaction and is recorded in the audit log. Invoice balances are always
recomputed from approved allocations (never edited by hand).
"""
from __future__ import annotations
from decimal import Decimal
from functools import wraps

from database.db import transaction
from database.repositories import (
    get_review_case, update_review_case, update_allocation_status,
    get_allocations_for_transaction, get_allocation, insert_allocation,
    insert_settlement_component, update_transaction_status, create_audit_log,
    get_invoice, get_transaction, get_settlement_component, update_settlement_component,
    update_allocation_amount, get_open_cases_for_transaction, get_open_credit_for_transaction,
    update_credit, mark_invoice_verified,
)
from decision.credits import sync_customer_credit
from validation.settlement import finalise_settlement

PAISA = Decimal("0.01")


class ReviewError(ValueError):
    """A review action that cannot be applied (bad state or input)."""


def _atomic(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with transaction():
            return fn(*args, **kwargs)
    return wrapper


def _open_case(case_id: str) -> dict:
    case = get_review_case(case_id)
    if not case:
        raise ReviewError(f"Review case {case_id} not found")
    if case["status"] != "open":
        raise ReviewError(f"Case {case_id} is already {case['status']}")
    return case


def _unresolved_txn(transaction_id: str) -> dict:
    """The bank credit, provided no money from it has been applied yet."""
    txn = get_transaction(transaction_id)
    if not txn:
        raise ReviewError("Transaction not found")
    if txn["status"] in ("matched", "excluded") or any(
            a["allocation_status"] == "approved" for a in get_allocations_for_transaction(transaction_id)):
        raise ReviewError(f"{transaction_id} is already {txn['status']} — reverse it before deciding again")
    return txn


def _proposed(transaction_id: str) -> list[dict]:
    return [a for a in get_allocations_for_transaction(transaction_id) if a["allocation_status"] == "proposed"]


def _close_other_cases(transaction_id: str, keep: str, reviewer: str) -> None:
    for c in get_open_cases_for_transaction(transaction_id):
        if c["case_id"] != keep:
            update_review_case(c["case_id"], "superseded", reviewer, "Resolved via another case")


# ── Approve / Reject ──────────────────────────────────────────────────────────

@_atomic
def approve_match(case_id: str, allocation_id: str | None = None, reviewer: str = "human",
                  notes: str = "") -> dict:
    """
    Approve the proposed allocation(s) of a review case. A bulk payment has one
    proposed allocation per invoice; all of them are approved together.
    """
    case = _open_case(case_id)
    if case["exception_type"] == "possible_duplicate":
        raise ReviewError("Confirm or release the duplicate instead")
    tid = case["transaction_id"]
    _unresolved_txn(tid)
    proposed = _proposed(tid)
    if allocation_id:
        proposed = [a for a in proposed if a["allocation_id"] == allocation_id]
    if not proposed:
        raise ReviewError("Nothing to approve — this case has no proposed allocation. Use Correct instead.")

    invoices = []
    for alloc in proposed:
        inv = get_invoice(alloc["invoice_id"])
        # Balances can move between proposal and approval.
        if Decimal(str(alloc["allocated_amount"])) > Decimal(str(inv["outstanding_amount"])) + PAISA:
            raise ReviewError(f"{inv['invoice_id']} now has only ₹{inv['outstanding_amount']:,.2f} outstanding — "
                              "reconcile the credit again or use Correct")
        update_allocation_status(alloc["allocation_id"], "approved", reviewer, notes)
        mark_invoice_verified(alloc["invoice_id"])          # the reviewer has looked at it
        invoices.append(alloc["invoice_id"])
    for alloc in _proposed(tid):                            # anything not chosen is dropped
        update_allocation_status(alloc["allocation_id"], "rejected", reviewer, notes)
    settlements = {iid: finalise_settlement(iid, actor=reviewer) for iid in dict.fromkeys(invoices)}
    update_transaction_status(tid, "matched")
    credit = sync_customer_credit(tid, reviewer)
    update_review_case(case_id, "approved", reviewer, notes)
    _close_other_cases(tid, case_id, reviewer)
    create_audit_log("transaction", tid, "human_approved", actor=reviewer,
                     details={"case_id": case_id, "allocations": [a["allocation_id"] for a in proposed],
                              "invoices": invoices, "notes": notes, "customer_credit": credit})
    return {"status": "approved", "allocation_ids": [a["allocation_id"] for a in proposed],
            "invoices": {k: v.get("status") for k, v in settlements.items()}, "customer_credit": credit}


@_atomic
def reject_match(case_id: str, allocation_id: str | None = None, reviewer: str = "human",
                 notes: str = "") -> dict:
    """
    Reject the proposed allocation(s). The transaction goes back to 'unmatched' and
    the rejected invoices are excluded the next time it is reconciled.
    """
    case = _open_case(case_id)
    tid = case["transaction_id"]
    _unresolved_txn(tid)
    proposed = _proposed(tid)
    for alloc in proposed:
        update_allocation_status(alloc["allocation_id"], "rejected", reviewer, notes)
    update_review_case(case_id, "rejected", reviewer, notes)
    _close_other_cases(tid, case_id, reviewer)
    update_transaction_status(tid, "unmatched")
    create_audit_log("transaction", tid, "human_rejected", actor=reviewer,
                     details={"case_id": case_id, "rejected_invoices": [a["invoice_id"] for a in proposed],
                              "notes": notes})
    return {"status": "rejected", "allocation_ids": [a["allocation_id"] for a in proposed]}


# ── Correct ───────────────────────────────────────────────────────────────────

@_atomic
def correct_match(case_id: str | None, transaction_id: str, new_invoice_id: str | list[str],
                  reviewer: str = "human", notes: str = "", tds_amount: float = 0.0,
                  tds_section: str | None = None) -> dict:
    """
    Allocate the transaction to the invoice(s) the reviewer chose, in the order given,
    never beyond what each still owes. Money left over is held as customer credit.
    """
    ids = [new_invoice_id] if isinstance(new_invoice_id, str) else list(new_invoice_id)
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        raise ReviewError("Choose at least one invoice")
    if case_id:
        case = _open_case(case_id)
        if case["transaction_id"] != transaction_id:
            raise ReviewError("That case belongs to a different bank credit")
        if case["exception_type"] == "possible_duplicate":
            raise ReviewError("Confirm or release the duplicate instead")
    txn = _unresolved_txn(transaction_id)
    if txn["status"] == "duplicate":
        raise ReviewError("Release the duplicate flag before applying this credit")
    invoices = [get_invoice(i) for i in ids]
    missing = [i for i, inv in zip(ids, invoices) if not inv]
    if missing:
        raise ReviewError(f"Invoice not found: {', '.join(missing)}")
    settled = [i["invoice_id"] for i in invoices if float(i["outstanding_amount"]) <= 0]
    if settled:
        raise ReviewError(f"Nothing is outstanding on {', '.join(settled)}")
    tds = Decimal(str(tds_amount or 0))
    if not tds.is_finite() or tds < 0:
        raise ReviewError("TDS cannot be negative")

    credit = Decimal(str(txn["credit_amount"]))
    owed = sum((Decimal(str(i["outstanding_amount"])) for i in invoices), Decimal("0"))
    applied = min(credit + tds, owed)
    if tds > applied:
        raise ReviewError("TDS is more than the chosen invoices still owe")

    for alloc in _proposed(transaction_id):
        update_allocation_status(alloc["allocation_id"], "rejected", reviewer, notes)

    remaining, tds_left, created = applied, tds, []
    for inv in invoices:
        portion = min(remaining, Decimal(str(inv["outstanding_amount"])))
        if portion <= 0:
            break
        remaining -= portion
        tds_part = tds_left if remaining <= 0 else (tds * portion / applied).quantize(PAISA)
        tds_part = min(tds_part, tds_left, portion)
        tds_left -= tds_part
        aid = insert_allocation({
            "transaction_id": transaction_id, "invoice_id": inv["invoice_id"],
            "allocated_amount": float(portion), "allocation_status": "approved",
            "confidence_score": 1.0,
            "decision_reason": f"Manually allocated by {reviewer}" + (f": {notes}" if notes else ""),
            "approved_by": reviewer,
        })
        insert_settlement_component({"allocation_id": aid, "component_type": "bank_credit",
                                     "amount": float(portion - tds_part)})
        if tds_part > 0:
            insert_settlement_component({"allocation_id": aid, "component_type": "tds", "amount": float(tds_part),
                                         "tds_status": "claimed", "tds_section": tds_section})
        created.append(aid)
        mark_invoice_verified(inv["invoice_id"])
        finalise_settlement(inv["invoice_id"], actor=reviewer)

    update_transaction_status(transaction_id, "matched")
    held = sync_customer_credit(transaction_id, reviewer)
    if case_id:
        update_review_case(case_id, "corrected", reviewer, notes)
        _close_other_cases(transaction_id, case_id, reviewer)
    create_audit_log("transaction", transaction_id, "human_corrected", actor=reviewer,
                     details={"new_invoice_ids": ids, "allocations": created, "tds_amount": float(tds),
                              "notes": notes, "customer_credit": held})
    return {"status": "corrected", "new_allocation_ids": created, "new_allocation_id": created[0] if created else None,
            "new_invoice_id": ids[0], "new_invoice_ids": ids, "customer_credit": held}


# ── Reverse / Dismiss ─────────────────────────────────────────────────────────

def _reverse_one(alloc: dict, reviewer: str, notes: str) -> dict:
    update_allocation_status(alloc["allocation_id"], "reversed", reviewer, notes)
    settlement = finalise_settlement(alloc["invoice_id"], actor=reviewer)
    create_audit_log("allocation", alloc["allocation_id"], "reversed", actor=reviewer,
                     details={"transaction_id": alloc["transaction_id"], "invoice_id": alloc["invoice_id"],
                              "notes": notes})
    return settlement


def _release_credit(transaction_id: str) -> None:
    held = get_open_credit_for_transaction(transaction_id)
    if held:
        update_credit(held["credit_id"], status="void")


@_atomic
def reverse_allocation(allocation_id: str, reviewer: str = "human", notes: str = "") -> dict:
    """Reverse one approved allocation and reinstate the invoice balance."""
    alloc = get_allocation(allocation_id)
    if not alloc:
        return {"status": "error", "reason": "Allocation not found"}
    if alloc["allocation_status"] != "approved":
        return {"status": "error", "reason": f"Allocation is {alloc['allocation_status']}, not approved"}

    settlement = _reverse_one(alloc, reviewer, notes)
    tid = alloc["transaction_id"]
    if any(a["allocation_status"] == "approved" for a in get_allocations_for_transaction(tid)):
        if get_open_credit_for_transaction(tid) or not alloc.get("from_credit_id"):
            sync_customer_credit(tid, reviewer)
    elif not alloc.get("from_credit_id"):
        _release_credit(tid)
        update_transaction_status(tid, "unmatched")
    return {"status": "reversed", "allocation_id": allocation_id, "invoice_id": alloc["invoice_id"],
            "new_outstanding": settlement.get("outstanding")}


@_atomic
def reverse_transaction(transaction_id: str, reviewer: str = "human", notes: str = "") -> dict:
    """Undo a match: every approved allocation and any credit held from this bank line."""
    approved = [a for a in get_allocations_for_transaction(transaction_id) if a["allocation_status"] == "approved"]
    if not approved and not get_open_credit_for_transaction(transaction_id):
        raise ReviewError("This transaction has no approved allocation to reverse")
    for alloc in approved:
        _reverse_one(alloc, reviewer, notes)
    _release_credit(transaction_id)
    update_transaction_status(transaction_id, "unmatched")
    create_audit_log("transaction", transaction_id, "match_reversed", actor=reviewer, details={"notes": notes})
    return {"status": "reversed", "allocations": [a["allocation_id"] for a in approved],
            "invoices": [a["invoice_id"] for a in approved]}


@_atomic
def dismiss_transaction(case_id: str, reviewer: str = "human", notes: str = "") -> dict:
    """Mark a credit as not a customer receipt (interest, refund, internal transfer…)."""
    case = _open_case(case_id)
    tid = case["transaction_id"]
    _unresolved_txn(tid)
    for alloc in _proposed(tid):
        update_allocation_status(alloc["allocation_id"], "rejected", reviewer, notes)
    update_transaction_status(tid, "excluded")
    update_review_case(case_id, "dismissed", reviewer, notes)
    _close_other_cases(tid, case_id, reviewer)
    create_audit_log("transaction", tid, "dismissed_non_receivable", actor=reviewer, details={"notes": notes})
    return {"status": "dismissed", "transaction_id": tid}


# ── Duplicates ────────────────────────────────────────────────────────────────

def _duplicate_case(case_id: str) -> dict:
    case = _open_case(case_id)
    if case["exception_type"] != "possible_duplicate":
        raise ReviewError("This case is not about a possible duplicate")
    _unresolved_txn(case["transaction_id"])
    return case


@_atomic
def confirm_duplicate(case_id: str, reviewer: str = "human", notes: str = "") -> dict:
    case = _duplicate_case(case_id)
    update_review_case(case_id, "approved", reviewer, notes or "Confirmed duplicate")
    _close_other_cases(case["transaction_id"], case_id, reviewer)
    create_audit_log("transaction", case["transaction_id"], "duplicate_confirmed", actor=reviewer,
                     details={"case_id": case_id, "notes": notes})
    return {"status": "confirmed", "transaction_id": case["transaction_id"]}


def release_duplicate(case_id: str, reviewer: str = "human", notes: str = "",
                      reconcile_now: bool = True) -> dict:
    """The flagged credit is genuine — clear the flag and (optionally) reconcile it immediately."""
    with transaction():
        case = _duplicate_case(case_id)
        tid = case["transaction_id"]
        update_review_case(case_id, "rejected", reviewer, notes or "Not a duplicate")
        _close_other_cases(tid, case_id, reviewer)
        create_audit_log("transaction", tid, "duplicate_released", actor=reviewer,
                         details={"case_id": case_id, "notes": notes})
        update_transaction_status(tid, "unmatched")
    result = None
    if reconcile_now:                      # outside the lock: this may call the model
        from decision.decision_engine import reconcile_transaction
        result = reconcile_transaction(tid)
    return {"status": "released", "transaction_id": tid, "reconcile_result": result}


# ── Invoice confirmation ──────────────────────────────────────────────────────

@_atomic
def confirm_invoice(invoice_id: str, reviewer: str = "human", notes: str = "") -> dict:
    """A person has checked a model-read invoice against the document."""
    if not get_invoice(invoice_id):
        raise ReviewError(f"Invoice {invoice_id} not found")
    mark_invoice_verified(invoice_id)
    create_audit_log("invoice", invoice_id, "invoice_confirmed", actor=reviewer, details={"notes": notes})
    return {"status": "confirmed", "invoice_id": invoice_id}


# ── TDS evidence ──────────────────────────────────────────────────────────────

def _live_tds(component_id: str) -> tuple[dict, dict]:
    comp = get_settlement_component(component_id)
    if not comp or comp["component_type"] != "tds":
        raise ReviewError("TDS component not found")
    if comp.get("tds_status") == "rejected":
        raise ReviewError("This TDS claim was rejected; apply the payment again if evidence has arrived")
    alloc = get_allocation(comp["allocation_id"])
    if alloc["allocation_status"] != "approved":
        raise ReviewError(f"The payment carrying this TDS is {alloc['allocation_status']}, not approved")
    return comp, alloc


@_atomic
def verify_tds(component_id: str, reviewer: str = "human", certificate_document_id: str | None = None,
               notes: str = "") -> dict:
    """Mark a TDS component verified. Needs a certificate or a note naming the evidence checked."""
    comp, _ = _live_tds(component_id)
    if not (certificate_document_id or comp.get("supporting_doc") or (notes or "").strip()):
        raise ReviewError("Attach the certificate or note the evidence checked (e.g. the 26AS entry)")
    update_settlement_component(component_id, tds_status="verified",
                                supporting_doc=certificate_document_id or comp.get("supporting_doc"),
                                notes=notes or comp.get("notes"))
    create_audit_log("settlement_component", component_id, "tds_verified", actor=reviewer,
                     details={"allocation_id": comp["allocation_id"], "amount": comp["amount"],
                              "certificate": certificate_document_id, "notes": notes})
    return {"status": "verified", "component_id": component_id}


@_atomic
def reject_tds(component_id: str, reviewer: str = "human", notes: str = "") -> dict:
    """
    The customer's TDS claim is not supported: the deducted amount is still owed.
    The allocation is reduced by the TDS amount and the invoice re-opened for it.
    """
    comp, alloc = _live_tds(component_id)
    update_settlement_component(component_id, tds_status="rejected", notes=notes)
    update_allocation_amount(alloc["allocation_id"], float(alloc["allocated_amount"]) - float(comp["amount"]))
    settlement = finalise_settlement(alloc["invoice_id"], actor=reviewer)
    create_audit_log("settlement_component", component_id, "tds_rejected", actor=reviewer,
                     details={"allocation_id": alloc["allocation_id"], "invoice_id": alloc["invoice_id"],
                              "amount": comp["amount"], "notes": notes})
    return {"status": "rejected", "invoice_id": alloc["invoice_id"], "new_outstanding": settlement.get("outstanding")}
