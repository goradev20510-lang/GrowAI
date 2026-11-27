"""
ReconcileAI – Fuzzy Customer Matching
Uses RapidFuzz to find likely customer candidates when names don't match exactly.
Identity is confirmed only if corroborated by GSTIN or additional evidence.
"""
from __future__ import annotations
import json
import re
from rapidfuzz import fuzz

import config.thresholds as _thresholds


# Common Indian company suffixes to normalise before fuzzy matching
_SUFFIX_MAP = {
    r"\bpvt\.?\b":      "private",
    r"\bltd\.?\b":      "limited",
    r"\bllp\.?\b":      "llp",
    r"\bco\.?\b":       "company",
    r"\bcorp\.?\b":     "corporation",
    r"\btech\.?\b":     "technologies",
    r"\btechnologies\b": "technologies",
}


def normalize_customer_name(name: str) -> str:
    """Lowercase, strip punctuation, and expand abbreviations."""
    n = name.lower().strip()
    n = re.sub(r"[^\w\s]", " ", n)
    for pattern, replacement in _SUFFIX_MAP.items():
        n = re.sub(pattern, replacement, n, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", n).strip()


# Words that describe a kind of business, not a particular one.
_LEGAL = {"private", "limited", "llp", "company", "corporation", "pvt", "ltd", "co", "corp", "inc", "the", "m", "s"}
_GENERIC = {"solutions", "solution", "systems", "system", "technologies", "technology", "tech", "enterprises",
            "enterprise", "industries", "industry", "traders", "trading", "trade", "infotech", "logistics",
            "consultants", "consultancy", "services", "software", "retail", "healthcare", "analytics",
            "infrastructure", "partners", "group", "india", "international", "agencies", "sons", "associates"}


def _core(name: str) -> list[str]:
    return [w for w in normalize_customer_name(name).split() if w not in _LEGAL]


def name_similarity(payer: str, customer: str) -> float:
    """
    0–100. Legal suffixes are ignored, and shared business words are never enough:
    something distinctive in the customer's name must show up in the payer's.
    """
    p, c = _core(payer), _core(customer)
    if not p or not c:
        return 0.0
    p_joined, c_joined = "".join(p), "".join(c)
    if p_joined == c_joined:
        return 100.0
    distinctive = [w for w in c if w not in _GENERIC and len(w) > 1]
    if distinctive:
        evidence = any(
            (len(w) >= 3 and w in p_joined)
            or any(fuzz.ratio(w, t) >= 80 or (len(t) >= 4 and w.startswith(t)) for t in p if t not in _GENERIC)
            for w in distinctive)
        if not evidence:
            return 0.0
    elif fuzz.ratio(p_joined, c_joined) < 90:
        return 0.0
    score = max(fuzz.token_set_ratio(" ".join(p), " ".join(c)), fuzz.ratio(p_joined, c_joined))
    if len(p_joined) >= 8 and c_joined.startswith(p_joined):       # banks truncate long names
        score = max(score, 90.0)
    return float(score)


def fuzzy_match_customer(candidate_name: str, all_customers: list[dict],
                          threshold: int | None = None) -> list[dict]:
    """
    Return up to 5 customers whose name (or a recorded alias) scores at least `threshold`.
    Each result includes the original customer dict plus a 'fuzzy_score' key.
    """
    if not candidate_name or not all_customers:
        return []
    if threshold is None:
        threshold = _thresholds.CUSTOMER_NAME_FUZZY_MIN

    matched = []
    for customer in all_customers:
        aliases = customer.get("name_variants") or []
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except ValueError:
                aliases = []
        score = max(name_similarity(candidate_name, n) for n in [customer["name"], *aliases])
        if score >= threshold:
            matched.append({**customer, "fuzzy_score": score})

    matched.sort(key=lambda x: x["fuzzy_score"], reverse=True)
    return matched[:5]


def match_customer_identity(payer_name: str | None, payer_gstin: str | None,
                             all_customers: list[dict]) -> list[dict]:
    """
    Attempt to identify the customer behind a bank transaction.
    Prioritises GSTIN match, then falls back to fuzzy name matching.
    Returns candidate customer dicts with a 'match_method' key.
    """
    if not payer_name and not payer_gstin:
        return []

    # GSTIN exact match – highest confidence
    if payer_gstin:
        gstin_matches = [c for c in all_customers
                         if c.get("gstin") and c["gstin"].upper() == payer_gstin.upper()]
        if gstin_matches:
            return [{**c, "match_method": "gstin_exact", "fuzzy_score": 100} for c in gstin_matches]

    # Fuzzy name match
    if payer_name:
        fuzzy = fuzzy_match_customer(payer_name, all_customers)
        return [{**c, "match_method": "name_fuzzy"} for c in fuzzy]

    return []
