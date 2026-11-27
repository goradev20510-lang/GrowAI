"""Mask personal and account identifiers before text is sent to a model provider."""
from __future__ import annotations
import re

from config import settings

_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),                    # e-mail
    re.compile(r"(?<![A-Z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Z0-9])"),     # PAN (not the one inside a GSTIN)
    re.compile(r"(?<![\w.])(?:\+91[\s-]?)?[6-9]\d{9}(?![\w.])"),    # Indian mobile
    re.compile(r"(?<![\w.,])\d{9,18}(?![\w]|[.,]\d)"),              # account numbers
]


def mask_sensitive(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    if not settings.LLM_MASK_SENSITIVE:
        return text, mapping
    seen: dict[str, str] = {}

    def _swap(m: re.Match) -> str:
        value = m.group(0)
        if value not in seen:
            token = f"[[M{len(seen) + 1}]]"
            seen[value] = token
            mapping[token] = value
        return seen[value]

    for pattern in _PATTERNS:
        text = pattern.sub(_swap, text)
    return text, mapping


def unmask(text: str, mapping: dict[str, str]) -> str:
    for token, value in mapping.items():
        text = text.replace(token, value)
    return text
