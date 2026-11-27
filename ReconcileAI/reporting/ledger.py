"""
Books-balance check:  receipts = applied to invoices + held as customer credit
                                 + undecided + duplicates + excluded
and every invoice balance = total − paid before import − payments − adjustments − rounding.
"""
from __future__ import annotations
from decimal import Decimal

from database.repositories import (
    get_all_transactions, get_all_invoices, get_all_allocations, get_all_settlement_components,
    get_credits, get_adjustments,
)


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def check_ledger() -> dict:
    allocs = [a for a in get_all_allocations("approved")]
    cash: dict[str, Decimal] = {}
    for c in get_all_settlement_components():
        if c["component_type"] == "bank_credit":
            cash[c["allocation_id"]] = cash.get(c["allocation_id"], Decimal(0)) + _d(c["amount"])
    direct: dict[str, Decimal] = {}
    for a in allocs:
        if not a.get("from_credit_id"):
            direct[a["transaction_id"]] = direct.get(a["transaction_id"], Decimal(0)) + cash.get(a["allocation_id"], 0)
    credits = {c["transaction_id"]: c for c in get_credits()}

    buckets = {k: Decimal(0) for k in
               ("applied_to_invoices", "held_as_credit", "undecided", "duplicates", "excluded")}
    problems: list[str] = []
    receipts = Decimal(0)
    for t in get_all_transactions():
        amount = _d(t["credit_amount"])
        if amount <= 0:
            continue
        receipts += amount
        tid, held = t["transaction_id"], credits.get(t["transaction_id"])
        if t["status"] == "matched":
            used_from_credit = _d(held["amount"]) - _d(held["remaining"]) if held else Decimal(0)
            remaining = _d(held["remaining"]) if held else Decimal(0)
            buckets["applied_to_invoices"] += direct.get(tid, Decimal(0)) + used_from_credit
            buckets["held_as_credit"] += remaining
            gap = amount - direct.get(tid, Decimal(0)) - (_d(held["amount"]) if held else 0)
            if abs(gap) >= Decimal("0.01"):
                problems.append(f"{tid}: ₹{gap:,.2f} of a matched credit is not accounted for")
            if remaining < 0:
                problems.append(f"{tid}: more has been applied from its credit than was held")
        else:
            key = {"duplicate": "duplicates", "excluded": "excluded"}.get(t["status"], "undecided")
            buckets[key] += amount
            if direct.get(tid) or held:
                problems.append(f"{tid}: status is {t['status']} but money from it is applied or held")

    paid: dict[str, Decimal] = {}
    for a in allocs:
        paid[a["invoice_id"]] = paid.get(a["invoice_id"], Decimal(0)) + _d(a["allocated_amount"])
    adjusted: dict[str, Decimal] = {}
    for a in get_adjustments():
        adjusted[a["invoice_id"]] = adjusted.get(a["invoice_id"], Decimal(0)) + _d(a["amount"])
    for i in get_all_invoices():
        iid = i["invoice_id"]
        expected = (_d(i["total_amount"]) - _d(i.get("opening_paid")) - paid.get(iid, 0) - adjusted.get(iid, 0)
                    - _d(i.get("rounding_writeoff")))
        if i["status"] == "overpaid":
            problems.append(f"{iid}: overpaid by ₹{-expected:,.2f} — reverse and re-apply to hold the excess")
        elif abs(expected - _d(i["outstanding_amount"])) >= Decimal("0.01"):
            problems.append(f"{iid}: outstanding ₹{i['outstanding_amount']:,.2f}, entries imply ₹{expected:,.2f}")

    total = sum(buckets.values(), Decimal(0))
    return {"balanced": abs(receipts - total) < Decimal("0.01") and not problems,
            "receipts": float(receipts), **{k: float(v) for k, v in buckets.items()},
            "problems": problems}
