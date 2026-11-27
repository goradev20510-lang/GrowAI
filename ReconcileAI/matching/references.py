"""
Invoice-number handling. An invoice number is compared segment by segment:
letters and digit groups, ignoring separators and leading zeros *of each group*.
So INV-0101 == INV101, while INV-101, INV-11 and INV-1010 are all different.
"""
from __future__ import annotations
import re
from functools import lru_cache

_SEGMENT = re.compile(r"[A-Z]+|\d+")
_SEP = r"[\s\-_/#.:]"
# A reference we can recognise even when no such invoice exists (e.g. a wrong number).
GENERIC_REF = re.compile(r"(?<![A-Za-z0-9])INV(?:OICE)?[\s\-_/#]{0,2}\d{1,8}(?:-\d{1,8})*(?![A-Za-z0-9])",
                         re.IGNORECASE)


def invoice_key(ref: str) -> str:
    parts = _SEGMENT.findall(str(ref or "").upper())
    return "|".join(str(int(p)) if p.isdigit() else p for p in parts)


def invoice_number(inv: dict) -> str:
    return str(inv.get("invoice_number") or inv.get("invoice_id") or "")


@lru_cache(maxsize=50_000)
def _pattern(number: str) -> re.Pattern | None:
    parts = _SEGMENT.findall(number.upper())
    digits = [p for p in parts if p.isdigit()]
    # A bare number ("4521") cannot be told apart from account or reference numbers.
    if not digits or (len(parts) == 1):
        return None
    out = []
    for i, p in enumerate(parts):
        if i:
            both_digits = p.isdigit() and parts[i - 1].isdigit()
            out.append(f"{_SEP}{{1,3}}" if both_digits else f"{_SEP}{{0,3}}")
        out.append(f"0*{int(p)}" if p.isdigit() else p)
    # Must not continue into a longer number: "INV-2024" is not found inside "INV-2024-001".
    tail = r"(?![A-Z0-9])" + (r"(?![\-_]\d)" if parts[-1].isdigit() else "")
    return re.compile(r"(?<![A-Z0-9])" + "".join(out) + tail, re.IGNORECASE)


def find_references(text: str, invoices: list[dict] | None = None) -> list[tuple[int, int, str]]:
    """
    (start, end, reference) for every invoice reference in `text`: known invoice numbers
    in any format first (longest wins), then generic INV references not covered by one.
    """
    if not text:
        return []
    upper = text.upper()
    numbers_in_text = {int(n) for n in re.findall(r"\d+", upper)}
    found: list[tuple[int, int, str]] = []
    for number in {invoice_number(i) for i in invoices or []}:
        digit_parts = [int(p) for p in re.findall(r"\d+", number)]
        if not digit_parts or digit_parts[-1] not in numbers_in_text:      # cheap pre-filter
            continue
        pat = _pattern(number)
        if pat:
            found += [(m.start(), m.end(), number.upper()) for m in pat.finditer(text)]
    found.sort(key=lambda f: (-(f[1] - f[0]), f[0]))
    kept: list[tuple[int, int, str]] = []
    for f in found:
        if not any(f[0] < k[1] and k[0] < f[1] for k in kept):
            kept.append(f)
    for m in GENERIC_REF.finditer(text):
        if not any(m.start() < k[1] and k[0] < m.end() for k in kept):
            kept.append((m.start(), m.end(), re.sub(r"[\s_/#\-]+", "-", m.group(0).upper())))
    return sorted(kept)
