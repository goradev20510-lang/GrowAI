"""
ReconcileAI – Bank Statement Parser
Reads CSV or Excel bank statements and returns a list of normalised transaction dicts.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from utils.dates import to_iso

# Possible column name aliases (compared case-insensitively, ignoring dots and "(INR)")
_COL_MAP = {
    "utr":         ["utr", "utr no", "ref no", "reference", "transaction ref", "txn ref", "chq/ref no",
                    "chq / ref no", "chq/ref number", "reference number", "transaction id", "utr/ref",
                    "ref no/cheque no"],
    "narration":   ["narration", "description", "particulars", "remarks", "transaction details",
                    "transaction narration", "details", "transaction remarks", "txn remarks"],
    "credit":      ["credit", "credit amount", "cr amount", "deposit", "deposits", "inward",
                    "cr", "received", "deposit amt", "deposit amount", "credit amt"],
    "debit":       ["debit", "debit amount", "dr amount", "withdrawal", "withdrawals",
                    "outward", "dr", "withdrawal amt", "withdrawal amount", "debit amt"],
    "amount":      ["amount", "transaction amount", "txn amount"],
    "drcr":        ["dr/cr", "cr/dr", "dr / cr", "cr / dr", "type", "transaction type", "debit/credit"],
    "date":        ["date", "transaction date", "value date", "txn date", "posting date", "tran date", "value dt"],
    "balance":     ["balance", "closing balance", "running balance", "available balance"],
    "currency":    ["currency", "ccy"],
}

# Extra aliases for a particular bank: {"narration": ["txn particulars"], ...}
_EXTRA = Path(__file__).resolve().parent.parent / "config" / "bank_columns.json"
if _EXTRA.exists():
    for _key, _names in json.loads(_EXTRA.read_text(encoding="utf-8")).items():
        _COL_MAP.setdefault(_key, []).extend(str(n).lower() for n in _names)


def _header(name) -> str:
    text = str(name).lower().replace(".", " ").replace("(inr)", " ").replace("(₹)", " ")
    return " ".join(text.split())


def _resolve_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """Return a mapping from canonical name to actual column in df."""
    lower_cols = {_header(c): c for c in df.columns}
    return {canonical: next((lower_cols[_header(a)] for a in aliases if _header(a) in lower_cols), None)
            for canonical, aliases in _COL_MAP.items()}


def _clean_amount(val) -> float | None:
    """
    Cell → signed float. Handles ₹ / Rs. / INR, commas, "Cr"/"Dr" suffixes and
    (bracketed) negatives. Empty → 0.0; text that is not an amount → None.
    """
    if val is None or (not isinstance(val, str) and pd.isna(val)):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    text = re.sub(r"₹|\bINR\b|\bRs\b\.?|,|\s", "", str(val).strip(), flags=re.IGNORECASE)
    if text.lower() in ("", "-", "--", "nan", "na", "nil"):
        return 0.0
    sign = 1.0
    suffix = re.search(r"\(?(cr|dr)\.?\)?$", text, re.IGNORECASE)
    if suffix:
        sign = -1.0 if suffix.group(1).lower() == "dr" else 1.0
        text = text[:suffix.start()]
    if text.startswith("(") and text.endswith(")"):
        sign, text = -1.0, text[1:-1]
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", text):
        return None
    return sign * float(text)


def read_bank_csv(filepath: str | Path, bank_name: str = "Unknown",
                  account_number: str | None = None, rejected: list | None = None) -> list[dict]:
    """Parse a bank statement CSV file into transaction dicts. Unreadable rows go to `rejected`."""
    # Everything is read as text so long reference numbers are never turned into floats.
    df = pd.read_csv(str(filepath), skiprows=_detect_header_row(filepath, ".csv"), dtype=str,
                     encoding="utf-8-sig", encoding_errors="replace", index_col=False)
    return _parse_bank_df(df, bank_name, account_number, rejected)


def read_bank_excel(filepath: str | Path, bank_name: str = "Unknown",
                    account_number: str | None = None, rejected: list | None = None) -> list[dict]:
    """Parse a bank statement Excel file into transaction dicts."""
    # Try each sheet until we find one with financial headers
    xf = pd.ExcelFile(str(filepath))
    for sheet in xf.sheet_names:
        raw = xf.parse(sheet, header=None, dtype=object)
        # find the header row (statements often start with account metadata)
        for i in range(min(len(raw), 30)):
            cand = raw.iloc[i + 1:].copy()
            cand.columns = [str(c).strip() for c in raw.iloc[i].tolist()]
            col_map = _resolve_columns(cand)
            if col_map["date"] and (col_map["credit"] or col_map["amount"] or col_map["narration"]):
                return _parse_bank_df(cand.reset_index(drop=True), bank_name, account_number, rejected)
    return []


def _detect_header_row(filepath: str | Path, ext: str) -> int:
    """Skip rows that are bank metadata/headers, return row index of actual header."""
    with open(str(filepath), "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f):
            lower = line.lower()
            # a header row names at least two columns (metadata lines like "Statement date: …" don't)
            hits = sum(kw in lower for kw in ["date", "narration", "description", "particulars",
                                              "amount", "credit", "debit", "balance", "utr"])
            if hits >= 2 and "," in line or hits >= 3:
                return i
            if i > 50:
                break
    return 0


def _cell(row, column) -> str:
    if not column:
        return ""
    value = row.get(column)
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return "" if text.lower() in ("nan", "nat", "none") else text


def _amounts(row, col) -> tuple[float, float] | None:
    """(credit, debit) for a row, or None when a value cannot be read."""
    if col["credit"] or col["debit"]:
        credit = _clean_amount(row.get(col["credit"])) if col["credit"] else 0.0
        debit = _clean_amount(row.get(col["debit"])) if col["debit"] else 0.0
        if credit is None or debit is None:
            return None
        if credit < 0:                      # "500 Dr" or "(500)" in a credit column
            credit, debit = 0.0, debit + abs(credit)
        return credit, abs(debit)
    amount = _clean_amount(row.get(col["amount"])) if col["amount"] else None
    if amount is None:
        return None
    kind = _cell(row, col["drcr"]).lower()
    if kind.startswith(("d", "w")) or amount < 0:
        return 0.0, abs(amount)
    if col["drcr"] and not kind.startswith("c"):
        return None                          # direction unknown: never guess
    return amount, 0.0


def _parse_bank_df(df: pd.DataFrame, bank_name: str, account_number: str | None,
                   rejected: list | None = None) -> list[dict]:
    df = df.dropna(how="all")
    col = _resolve_columns(df)
    if not (col["credit"] or col["debit"] or col["amount"]):
        return []
    transactions = []
    seen: dict[str, int] = {}

    def _reject(index, reason, row):
        if rejected is not None:
            rejected.append({"row": int(index) + 1, "reason": reason,
                             "text": " | ".join(str(v) for v in row.tolist() if str(v) != "nan")[:200]})

    for index, row in df.iterrows():
        amounts = _amounts(row, col)
        if amounts is None:
            _reject(index, "amount could not be read", row)
            continue
        credit, debit = amounts
        if credit == 0 and debit == 0:
            if _cell(row, col["date"]):
                _reject(index, "no amount", row)
            continue
        narration = _cell(row, col["narration"])
        date_raw  = _cell(row, col["date"])
        iso_date  = _normalise_date_str(date_raw)
        if not iso_date:                    # totals, footers, or a date we must not guess
            _reject(index, f"date '{date_raw}' could not be read", row)
            continue
        utr_column = _cell(row, col["utr"])
        utr = utr_column or _extract_utr_from_narration(narration)

        # Stable id: the same line in an overlapping statement gets the same id, while two
        # genuine payments (different reference, balance, account, or a repeat) stay apart.
        parts = [date_raw, narration, str(credit), str(debit)]
        parts += [p for p in (utr_column, account_number or "") if p]
        signature = "|".join(parts)
        seen[signature] = seen.get(signature, 0) + 1
        if seen[signature] > 1:
            signature += f"|#{seen[signature]}"
        txn_hash = hashlib.sha256(signature.encode()).hexdigest()[:16].upper()

        transactions.append({
            "transaction_id": f"TXN{txn_hash}",
            "utr": utr or None,
            "narration": narration,
            "credit_amount": credit,
            "debit_amount": debit,
            "transaction_date": iso_date,
            "bank_name": bank_name,
            "account_number": account_number,
            "currency": (_cell(row, col["currency"]) or "INR").upper(),
            "status": "unmatched",
        })
    return transactions


def _extract_utr_from_narration(narration: str) -> str | None:
    """
    Only formats that are recognisably a transfer reference: NEFT/RTGS UTRs (bank code
    followed by digits) and the 12-digit RRN of IMPS/UPI. A bare long number elsewhere
    is usually an account number, which repeats across genuine payments.
    """
    text = (narration or "").upper()
    m = re.search(r"\b([A-Z]{4}[A-Z0-9]?\d{9,18})\b", text)
    if m:
        return m.group(1)
    if re.search(r"\b(IMPS|UPI)\b", text):
        m = re.search(r"(?<!\d)(\d{12})(?!\d)", text)
        if m:
            return m.group(1)
    return None


def _normalise_date_str(date_str: str) -> str | None:
    """ISO YYYY-MM-DD, reading dd/mm as day-first and never swapping ISO dates."""
    return to_iso(date_str)
