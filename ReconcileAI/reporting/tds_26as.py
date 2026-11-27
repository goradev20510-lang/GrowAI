"""
Match TDS claimed on approved payments against a Form 26AS register (CSV/Excel).

Expected columns (any order, case-insensitive): deductor name, section, tds amount,
transaction date (optional). This is a flat table prepared from the 26AS download,
not the portal's raw text file.
"""
from __future__ import annotations
import io
from decimal import Decimal

import pandas as pd

from database.db import transaction
from database.repositories import get_tds_components
from decision.review_manager import verify_tds
from matching.fuzzy_match import name_similarity
from extraction.rule_extractor import parse_amount
from utils.dates import to_iso

_ALIASES = {
    "deductor": ("deductor name", "name of deductor", "deductor", "party name", "name"),
    "section":  ("section", "tds section"),
    "amount":   ("tds amount", "tax deducted", "amount of tds", "total tax deducted", "tds"),
    "date":     ("transaction date", "date", "date of transaction", "date of booking"),
}
AMOUNT_SLACK = Decimal("1")          # 26AS amounts are often rounded to the rupee


def read_26as(filename: str, data: bytes) -> list[dict]:
    reader = pd.read_csv if filename.lower().endswith(".csv") else pd.read_excel
    df = reader(io.BytesIO(data), dtype=str).fillna("")
    cols = {" ".join(str(c).lower().replace("_", " ").split()): c for c in df.columns}
    pick = {k: next((cols[a] for a in names if a in cols), None) for k, names in _ALIASES.items()}
    if not (pick["deductor"] and pick["amount"]):
        raise ValueError("The file needs a deductor name column and a TDS amount column")
    rows = []
    for _, r in df.iterrows():
        amount = parse_amount(r[pick["amount"]])
        if not amount or amount <= 0:
            continue
        rows.append({"deductor": str(r[pick["deductor"]]).strip(), "amount": amount,
                     "section": str(r[pick["section"]]).strip().upper() if pick["section"] else "",
                     "date": to_iso(r[pick["date"]]) if pick["date"] else None})
    return rows


def match_26as(rows: list[dict]) -> dict:
    """Preview only. A pair is proposed when name, amount and (if both given) section agree."""
    claims = [c for c in get_tds_components() if c.get("tds_status") not in ("verified", "rejected")]
    used: set[int] = set()
    matched, ambiguous, unmatched = [], [], []
    for claim in claims:
        hits = [k for k, row in enumerate(rows) if k not in used
                and abs(Decimal(str(row["amount"])) - Decimal(str(claim["amount"]))) <= AMOUNT_SLACK
                and name_similarity(row["deductor"], claim.get("customer_name") or "") >= 85
                and (not row["section"] or not claim.get("tds_section")
                     or row["section"].replace(" ", "") == claim["tds_section"])]
        entry = {"component_id": claim["component_id"], "invoice_id": claim["invoice_id"],
                 "customer_name": claim.get("customer_name"), "amount": claim["amount"]}
        if not hits:
            unmatched.append(entry)
        elif len(hits) > 1 and len({(rows[k]["amount"], rows[k]["date"]) for k in hits}) > 1:
            ambiguous.append({**entry, "candidates": [rows[k] for k in hits]})
        else:
            used.add(hits[0])
            matched.append({**entry, "entry": rows[hits[0]]})
    return {"matched": matched, "ambiguous": ambiguous, "unmatched_claims": unmatched,
            "unused_26as_rows": [r for k, r in enumerate(rows) if k not in used]}


def apply_26as(rows: list[dict], reviewer: str) -> dict:
    """Mark the unambiguous matches verified, in one transaction."""
    with transaction():
        result = match_26as(rows)
        for m in result["matched"]:
            e = m["entry"]
            verify_tds(m["component_id"], reviewer=reviewer,
                       notes=f"26AS: {e['deductor']}, ₹{e['amount']:,.2f}, {e['date'] or 'date not stated'}")
    return result
