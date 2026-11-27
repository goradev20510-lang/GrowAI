"""
Customer credits: money received from a customer that is not (yet) applied to an
invoice — overpayments and advances. The credit always equals
  bank credit − cash applied directly from that bank line,
and invoices paid *from* the credit reduce what remains of it.
"""
from __future__ import annotations
from decimal import Decimal

from database.repositories import (
    get_transaction, get_allocations_for_transaction, get_settlement_components,
    get_open_credit_for_transaction, insert_credit, update_credit, get_invoice, create_audit_log,
)


def direct_cash_applied(transaction_id: str) -> Decimal:
    total = Decimal("0")
    for a in get_allocations_for_transaction(transaction_id):
        if a["allocation_status"] == "approved" and not a.get("from_credit_id"):
            total += sum((Decimal(str(c["amount"])) for c in get_settlement_components(a["allocation_id"])
                          if c["component_type"] == "bank_credit"), Decimal("0"))
    return total


def sync_customer_credit(transaction_id: str, actor: str, customer_id: str | None = None) -> dict:
    """Create, resize or void the credit of a *matched* bank line. Call inside a transaction."""
    txn = get_transaction(transaction_id)
    unapplied = Decimal(str(txn["credit_amount"])) - direct_cash_applied(transaction_id)
    existing = get_open_credit_for_transaction(transaction_id)
    if unapplied < Decimal("0.01"):
        if existing:
            update_credit(existing["credit_id"], status="void")
        return {}
    if existing:
        update_credit(existing["credit_id"], amount=float(unapplied))
        return {"credit_id": existing["credit_id"], "amount": float(unapplied)}
    if customer_id is None:
        for a in get_allocations_for_transaction(transaction_id):
            if a["allocation_status"] == "approved":
                customer_id = get_invoice(a["invoice_id"]).get("customer_id")
                break
    cid = insert_credit(transaction_id, customer_id, float(unapplied), actor)
    create_audit_log("transaction", transaction_id, "customer_credit_held", actor=actor,
                     details={"credit_id": cid, "amount": float(unapplied), "customer_id": customer_id})
    return {"credit_id": cid, "amount": float(unapplied)}
