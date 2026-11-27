"""One date parser for the whole app: Indian day-first, but ISO dates are never swapped."""
from __future__ import annotations
import re
from datetime import date

from dateutil import parser as dp

_ISO = re.compile(r"^\s*\d{4}[-/.]\d{1,2}[-/.]\d{1,2}")


def parse_date(value) -> date | None:
    text = str(value or "").strip()
    if not text or text.lower() in ("nan", "nat", "none"):
        return None
    try:
        iso = bool(_ISO.match(text))
        return dp.parse(text, yearfirst=iso, dayfirst=not iso).date()
    except (ValueError, OverflowError, TypeError):
        return None


def to_iso(value) -> str | None:
    d = parse_date(value)
    return d.isoformat() if d else None
