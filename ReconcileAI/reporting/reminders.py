"""Draft payment reminders for overdue invoices. Drafts only: nothing is ever sent."""
from __future__ import annotations
from datetime import date

from database.repositories import get_all_customers, get_credits
from reporting.report_generator import aging_report


def draft_reminders(as_of: date | None = None, min_days_overdue: int = 1) -> list[dict]:
    as_of = as_of or date.today()
    detail = aging_report(as_of)
    if detail.empty:
        return []
    overdue = detail[detail["days_past_due"] >= min_days_overdue]
    emails = {c["name"]: c.get("email") for c in get_all_customers()}
    credit: dict[str, float] = {}
    for c in get_credits():
        credit[c.get("customer_name")] = credit.get(c.get("customer_name"), 0.0) + float(c["remaining"])

    drafts = []
    for name, group in overdue.groupby("customer_name", sort=True):
        total = float(group["outstanding_amount"].sum())
        lines = [f"- {r.invoice_id}: ₹{r.outstanding_amount:,.2f}, due {r.due_date} ({r.days_past_due} days ago)"
                 for r in group.itertuples()]
        held = round(credit.get(name, 0.0), 2)
        body = (f"Dear {name},\n\nOur records show the following overdue balance as of {as_of.isoformat()}:\n\n"
                + "\n".join(lines) + f"\n\nTotal overdue: ₹{total:,.2f}\n\n"
                "If you have already paid, please reply with the UTR and any TDS deducted.\n\nRegards,\n"
                "Accounts Receivable")
        drafts.append({
            "customer_name": name, "email": emails.get(name), "invoices": group["invoice_id"].tolist(),
            "total_overdue": round(total, 2), "unapplied_credit": held,
            "warning": (f"We hold ₹{held:,.2f} of unapplied credit from this customer — apply it before sending."
                        if held > 0 else None),
            "subject": f"Payment reminder: ₹{total:,.2f} overdue", "body": body})
    return sorted(drafts, key=lambda d: -d["total_overdue"])
