"""
ReconcileAI – Settlement Ledger
Recalculates and finalises invoice settlement state after allocations change.
"""
from __future__ import annotations
from decimal import Decimal

from config.thresholds import amount_tolerance
from database.repositories import (
    get_allocations_for_invoice, get_invoice, update_invoice_outstanding, create_audit_log, get_adjustments
)


def calculate_settlement_balance(invoice_id: str) -> dict:
    """
    Recalculate the full settlement state of an invoice.

    Returns
    -------
    {
        "invoice_id": str,
        "total_amount": float,
        "total_paid": float,
        "outstanding": float,
        "status": "open" | "partially_paid" | "settled" | "overpaid",
        "components": list of allocation summaries
    }
    """
    invoice = get_invoice(invoice_id)
    if not invoice:
        return {"error": f"Invoice {invoice_id} not found"}

    allocs = get_allocations_for_invoice(invoice_id)   # only 'approved'
    # Balance = total − paid before import − adjustments − approved payments.
    total       = Decimal(str(invoice["total_amount"]))
    opening     = Decimal(str(invoice.get("opening_paid") or 0))
    adjusted    = sum((Decimal(str(a["amount"])) for a in get_adjustments(invoice_id)), Decimal("0"))
    allocated   = sum((Decimal(str(a["allocated_amount"])) for a in allocs), Decimal("0"))
    total_paid  = opening + allocated
    outstanding = total - total_paid - adjusted

    tol = max(amount_tolerance(total), Decimal("0.01"))
    rounding = Decimal("0")
    if outstanding < -tol:
        status = "overpaid"
    elif outstanding <= tol:
        status = "settled"
        rounding = max(outstanding, Decimal("0"))      # recorded, never silently dropped
    elif total_paid + adjusted > 0:
        status = "partially_paid"
    else:
        status = "open"

    return {
        "invoice_id":   invoice_id,
        "total_amount": float(total),
        "total_paid":   float(total_paid),
        "opening_paid": float(opening),
        "adjustments":  float(adjusted),
        "rounding_writeoff": float(rounding),
        "outstanding":  float(max(outstanding, Decimal("0"))),
        "overpaid_by":  float(abs(min(outstanding, Decimal("0")))),
        "status":       status,
        "allocations":  len(allocs),
    }


def finalise_settlement(invoice_id: str, actor: str = "system", audit: bool = True) -> dict:
    """
    Recalculate and persist the settlement state for an invoice from its approved
    allocations. This is the single place invoice balances are written.
    """
    result = calculate_settlement_balance(invoice_id)
    if "error" in result:
        return result
    # A balance within the rounding tolerance counts as settled — clear the residue.
    outstanding = 0.0 if result["status"] in ("settled", "overpaid") else result["outstanding"]
    result["outstanding"] = outstanding
    update_invoice_outstanding(invoice_id, outstanding, result["status"], result["rounding_writeoff"])
    if audit:
        create_audit_log("invoice", invoice_id, "settlement_recalculated", actor=actor,
                         details={k: result[k] for k in ("status", "total_paid", "adjustments", "rounding_writeoff",
                                                       "outstanding", "overpaid_by")})
    return result
