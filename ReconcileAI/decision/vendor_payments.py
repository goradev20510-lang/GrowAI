"""
ReconcileAI – Outgoing payments
Links bank debits to vendor bills. All amounts are computed here, in code. A link is only
ever made by a named person; the engine suggests and explains, it does not post.
"""
from __future__ import annotations
import re
from collections import Counter

from database.db import get_connection, transaction
from database.repositories import _new_id, _now, _rows, create_audit_log, get_transaction
from decision.review_manager import ReviewError

_GENERIC = {"pvt", "ltd", "private", "limited", "llp", "and", "the", "services", "solutions", "company",
            "enterprises", "india", "traders"}


def _money(value) -> float:
    return round(float(value or 0), 2)


def _active_links() -> list[dict]:
    return _rows(get_connection().execute(
        """SELECT p.*, b.vendor_name, b.bill_number, t.transaction_date, t.utr
             FROM vendor_payments p
             JOIN bank_transactions t ON t.transaction_id = p.transaction_id
             LEFT JOIN vendor_bills b ON b.bill_id = p.bill_id
            WHERE p.status = 'active' ORDER BY p.rowid""").fetchall())


def list_bills() -> list[dict]:
    bills = _rows(get_connection().execute(
        "SELECT * FROM vendor_bills ORDER BY COALESCE(due_date, bill_date, created_at), vendor_name").fetchall())
    links = _active_links()
    for b in bills:
        mine = [p for p in links if p["bill_id"] == b["bill_id"]]
        paid = _money(sum(p["amount"] for p in mine))
        b.update(paid=paid, pending=_money(b["amount"] - paid), payments=mine, bill_on_file=bool(b["bill_on_file"]),
                 status="paid" if paid >= _money(b["amount"]) else "part_paid" if paid else "unpaid")
    return bills


def list_debits() -> list[dict]:
    """Every outgoing bank line with what has been accounted for."""
    debits = _rows(get_connection().execute(
        """SELECT * FROM bank_transactions WHERE debit_amount > 0
            ORDER BY transaction_date DESC, transaction_id""").fetchall())
    links = _active_links()
    for d in debits:
        mine = [p for p in links if p["transaction_id"] == d["transaction_id"]]
        linked = _money(sum(p["amount"] for p in mine))
        unlinked = _money(d["debit_amount"] - linked)
        d.update(links=mine, linked=linked, unlinked=unlinked)
        if unlinked > 0:
            d["link_status"] = "part_linked" if linked else "not_linked"
        else:
            d["link_status"] = "not_vendor" if all(p["bill_id"] is None for p in mine) else "linked"
    return debits


def payables_summary() -> dict:
    bills, debits = list_bills(), list_debits()
    return {
        "vendor_bills": len(bills),
        "vendor_billed": _money(sum(b["amount"] for b in bills)),
        "vendor_paid": _money(sum(b["paid"] for b in bills)),
        "vendor_unpaid": _money(sum(b["pending"] for b in bills)),
        "vendor_bills_missing": sum(not b["bill_on_file"] for b in bills),
        "debit_total": _money(sum(d["debit_amount"] for d in debits)),
        "debit_unlinked": _money(sum(d["unlinked"] for d in debits)),
        "debit_unlinked_count": sum(d["unlinked"] > 0 for d in debits),
    }


def _plain(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _debit(transaction_id: str) -> dict:
    debit = next((d for d in list_debits() if d["transaction_id"] == transaction_id), None)
    if not debit:
        raise ReviewError(f"{transaction_id} is not an outgoing payment.")
    return debit


def suggest_bills(transaction_id: str) -> list[dict]:
    """Unpaid bills that share evidence with this debit, strongest first, with the reasons."""
    debit = _debit(transaction_id)
    if debit["unlinked"] <= 0:
        return []
    narration = _plain(debit["narration"])
    out = []
    for bill in list_bills():
        if bill["pending"] <= 0:
            continue
        reasons, score = [], 0
        number = _plain(bill["bill_number"])
        if len(number) >= 4 and number in narration:
            reasons.append("bill number is in the narration")
            score += 4
        words = [w for w in re.findall(r"[a-z0-9]+", bill["vendor_name"].lower()) if len(w) >= 4 and w not in _GENERIC]
        if any(w in narration for w in words):
            reasons.append("vendor name is in the narration")
            score += 2
        if bill["pending"] == debit["unlinked"]:
            reasons.append("amount equals the pending balance")
            score += 1
        if score:
            out.append({**bill, "score": score, "reasons": reasons,
                        "would_link": _money(min(bill["pending"], debit["unlinked"]))})
    return sorted(out, key=lambda b: -b["score"])


def _check_not_repeated(debit: dict) -> None:
    """The same bank reference must not pay twice."""
    if not debit["utr"]:
        return
    other = next((p for p in _active_links()
                  if p["utr"] == debit["utr"] and p["transaction_id"] != debit["transaction_id"]), None)
    if other:
        raise ReviewError(f"Reference {debit['utr']} is already accounted for on {other['transaction_id']}. "
                          "Check the statement for a duplicate line.")


def _insert(transaction_id: str, bill_id: str | None, amount: float, who: str, notes: str) -> str:
    payment_id = _new_id("VPAY")
    get_connection().execute(
        """INSERT INTO vendor_payments(payment_id,transaction_id,bill_id,amount,status,linked_by,notes,created_at)
           VALUES(?,?,?,?,'active',?,?,?)""",
        (payment_id, transaction_id, bill_id, amount, who, notes, _now()))
    return payment_id


def link_payment(transaction_id: str, bill_id: str, reviewer: str, notes: str = "") -> dict:
    """Apply as much of the debit as the bill still needs."""
    with transaction():
        debit = _debit(transaction_id)
        bill = next((b for b in list_bills() if b["bill_id"] == bill_id), None)
        if not bill:
            raise ReviewError("That vendor bill does not exist.")
        if debit["unlinked"] <= 0:
            raise ReviewError("This payment is already fully accounted for.")
        if bill["pending"] <= 0:
            raise ReviewError(f"Bill {bill['bill_number']} is already paid.")
        _check_not_repeated(debit)
        amount = _money(min(bill["pending"], debit["unlinked"]))
        payment_id = _insert(transaction_id, bill_id, amount, reviewer, notes)
        create_audit_log("vendor_bill", bill_id, "vendor_payment_linked", actor=reviewer,
                         details={"transaction_id": transaction_id, "amount": amount, "notes": notes,
                                  "bill_number": bill["bill_number"], "vendor": bill["vendor_name"]})
    return {"payment_id": payment_id, "amount": amount, "bill_id": bill_id}


def mark_not_vendor(transaction_id: str, reviewer: str, notes: str) -> dict:
    """Bank charges, salaries, transfers: account for the rest of a debit without a bill."""
    with transaction():
        debit = _debit(transaction_id)
        if debit["unlinked"] <= 0:
            raise ReviewError("This payment is already fully accounted for.")
        _check_not_repeated(debit)
        payment_id = _insert(transaction_id, None, debit["unlinked"], reviewer, notes)
        create_audit_log("transaction", transaction_id, "debit_marked_not_vendor", actor=reviewer,
                         details={"amount": debit["unlinked"], "notes": notes})
    return {"payment_id": payment_id, "amount": debit["unlinked"]}


def unlink_payment(payment_id: str, reviewer: str, notes: str) -> dict:
    with transaction() as conn:
        row = conn.execute("SELECT * FROM vendor_payments WHERE payment_id=? AND status='active'",
                           (payment_id,)).fetchone()
        if not row:
            raise ReviewError("That link no longer exists.")
        conn.execute("UPDATE vendor_payments SET status='reversed' WHERE payment_id=?", (payment_id,))
        create_audit_log("transaction", row["transaction_id"], "vendor_payment_unlinked", actor=reviewer,
                         details={"payment_id": payment_id, "bill_id": row["bill_id"], "amount": row["amount"],
                                  "notes": notes})
    return {"payment_id": payment_id, "transaction_id": row["transaction_id"]}


def set_bill_on_file(bill_id: str, on_file: bool, reviewer: str) -> dict:
    with transaction() as conn:
        if not conn.execute("UPDATE vendor_bills SET bill_on_file=? WHERE bill_id=?",
                            (int(on_file), bill_id)).rowcount:
            raise ReviewError("That vendor bill does not exist.")
        create_audit_log("vendor_bill", bill_id, "bill_on_file_changed", actor=reviewer,
                         details={"bill_on_file": on_file})
    return {"bill_id": bill_id, "bill_on_file": on_file}


def statement() -> list[dict]:
    """Every bank line, money in and out, with what each one is linked to."""
    conn = get_connection()
    invoices: dict[str, list[str]] = {}
    for r in conn.execute("""SELECT transaction_id, invoice_id FROM payment_allocations
                              WHERE allocation_status='approved' ORDER BY rowid""").fetchall():
        invoices.setdefault(r["transaction_id"], []).append(r["invoice_id"])
    debits = {d["transaction_id"]: d for d in list_debits()}
    rows = _rows(conn.execute(
        "SELECT * FROM bank_transactions ORDER BY transaction_date DESC, transaction_id DESC").fetchall())
    for t in rows:
        d = debits.get(t["transaction_id"])
        if d:
            t.update(direction="out", status=d["link_status"], unlinked=d["unlinked"],
                     linked_to=[f"{p['vendor_name']} · {p['bill_number']}" for p in d["links"] if p["bill_id"]])
        else:
            # A repeated posting is shown as "×2", never silently merged.
            counts = Counter(invoices.get(t["transaction_id"], []))
            t.update(direction="in", unlinked=0,
                     linked_to=[i if n == 1 else f"{i} ×{n}" for i, n in counts.items()])
    return rows


def debit_detail(transaction_id: str) -> dict:
    if not get_transaction(transaction_id):
        raise ReviewError(f"No bank line {transaction_id}")
    return {"debit": _debit(transaction_id), "suggestions": suggest_bills(transaction_id)}
