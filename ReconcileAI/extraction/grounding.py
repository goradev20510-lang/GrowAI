"""
A model's answer is only used where the source document supports it: every amount
and reference it returns must actually appear in the text it was given.
"""
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation


def _amounts_in(text: str) -> set[Decimal]:
    out = set()
    for raw in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        try:
            out.add(Decimal(raw.replace(",", "")))
        except InvalidOperation:
            pass
    return out


def _squash(value) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def ground(result: dict, source: str, amount_fields: tuple[str, ...],
           text_fields: tuple[str, ...] = ()) -> tuple[dict, list[str]]:
    """Return (result with unsupported values removed, names of the removed fields)."""
    out, dropped = dict(result), []
    amounts, flat = _amounts_in(source), _squash(source)
    for field in amount_fields:
        value = out.get(field)
        if value not in (None, "", 0, 0.0) and Decimal(str(value)) not in amounts:
            out[field] = None
            dropped.append(field)
    for field in text_fields:
        value = out.get(field)
        if value and _squash(value) not in flat:
            out[field] = None
            dropped.append(field)
    refs = out.get("invoice_references")
    if refs:
        def _supported(ref) -> bool:
            digits = re.findall(r"\d+", str(ref))
            return _squash(ref) in flat or bool(digits) and re.sub(r"\D", "", str(ref)) in flat
        out["invoice_references"] = [r for r in refs if _supported(r)]
        if len(out["invoice_references"]) != len(refs):
            dropped.append("invoice_references")
    return out, dropped
