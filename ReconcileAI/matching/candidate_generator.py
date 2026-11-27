"""
ReconcileAI – Candidate Generator
Combines multiple matching signals to produce a ranked list of candidate invoices
for each bank transaction. All ranking is deterministic Python.
"""
from __future__ import annotations
import re
from decimal import Decimal

from database.repositories import get_all_invoices, get_all_customers, get_remittance_by_utr
from matching.exact_match import find_exact_invoice_match
from matching.fuzzy_match import match_customer_identity
from matching.references import find_references
from config.thresholds import amount_tolerance


# ── Narration regex parser (no LLM needed) ───────────────────────────────────

# Tokens that are payment-rail / bank boilerplate, never a payer name
_MODE_TOKENS = {
    "NEFT", "RTGS", "IMPS", "UPI", "BY TRANSFER", "BY", "TRANSFER", "TRF", "CLG", "CHQ", "CHEQUE",
    "INB", "MOB", "ACH", "NACH", "ECS", "FT", "IFT", "INF", "BIL", "ONL", "NET", "CR", "CREDIT",
}
_GENERIC_WORDS = {
    "PAYMENT", "PAYMENTS", "PYMT", "PMT", "PAY", "SETTLEMENT", "BULK", "AGAINST", "BILL", "BILLS",
    "INVOICE", "INVOICES", "PART", "PART1", "PART2", "PART3", "MISC", "REF", "ADVANCE", "TOWARDS",
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "SEPT", "OCT", "NOV", "DEC",
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
    "NOVEMBER", "DECEMBER", "FILLER",
}


def _looks_like_reference(token: str) -> bool:
    """UTRs, IFSC codes, account numbers: mostly digits or BANK+digits."""
    t = token.replace(" ", "")
    digits = sum(c.isdigit() for c in t)
    if digits >= max(4, len(t) / 2):
        return True
    return bool(re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", t.upper()))           # IFSC


def _extract_from_narration(narration: str,
                            invoices: list[dict] | None = None) -> tuple[list[str], str | None]:
    """
    Deterministically extract invoice references and a payer-name hint
    from a raw bank narration such as:
      'NEFT/XYZTECHNOLOGIES/INV-001/97200'
      'NEFT-HDFC0001234-APEX SOLUTIONS LTD-INV 0012'
      'RTGS/HDFCR52024101500123/GLOBAL TRADE/PAYMENT'
      'BY TRANSFER-IMPS-ORBIT LOG-INV/0045'
    Returns (invoice_refs, payer_hint)
    """
    if not narration:
        return [], None

    # 1. Invoice references (then blank them out so they can't be taken as a payer)
    refs: list[str] = []
    rest = narration
    for start, end, ref in reversed(find_references(narration, invoices)):
        if ref not in refs:
            refs.insert(0, ref)
        rest = rest[:start] + " | " + rest[end:]

    # 2. Payer: first segment that is not rail boilerplate, a reference or generic text
    payer_hint: str | None = None
    for raw in re.split(r"[/|:\-]", rest):
        tok = " ".join(raw.split()).strip(" .,")
        up = tok.upper()
        if not tok or up in _MODE_TOKENS or _looks_like_reference(tok):
            continue
        words = [w for w in re.split(r"\s+", up) if w and w not in _GENERIC_WORDS and not w.isdigit()]
        if not words:
            continue
        if sum(c.isalpha() for c in "".join(words)) < 3:
            continue
        payer_hint = tok
        break

    return refs, payer_hint


def generate_candidate_invoices(transaction: dict,
                                 narration_hints: dict | None = None,
                                 remittance: dict | None = None,
                                 exclude_invoice_ids: set[str] | None = None) -> list[dict]:
    """
    Build a list of candidate invoices for a bank transaction.

    Parameters
    ----------
    transaction    : bank_transactions row
    narration_hints: output from llm_extractor.interpret_bank_narration
    remittance     : remittance_records row (if found by UTR / amount)
    exclude_invoice_ids: invoices a reviewer already rejected for this transaction

    Returns
    -------
    list of dicts, each containing the invoice + signals dict
    """
    all_invoices  = get_all_invoices()
    all_customers = get_all_customers()

    # ── Step 1: Collect all reference signals ────────────────────────────────
    invoice_refs: list[str] = []
    ref_sources: dict[str, str] = {}
    payer_name: str | None  = None
    payer_gstin: str | None = None
    tds_amount: float       = 0.0
    tds_section: str | None = None

    if remittance:
        refs = remittance.get("invoice_references")
        if isinstance(refs, str):
            import json as _json
            try:
                refs = _json.loads(refs)
            except Exception:
                refs = [refs]
        for r in refs or []:
            if r and r not in invoice_refs:
                invoice_refs.append(r)
                ref_sources[r] = "remittance"
        payer_name = remittance.get("customer_name")
        payer_gstin = remittance.get("customer_gstin")
        tds_amount = float(remittance.get("tds_amount") or 0)
        tds_section = remittance.get("tds_section")

    # LLM narration hints (keys: invoice_references, likely_payer, tds_amount)
    if narration_hints:
        llm_refs = narration_hints.get("invoice_references") or []
        if isinstance(llm_refs, str):
            llm_refs = [llm_refs]
        for r in llm_refs:
            if r and r not in invoice_refs:
                invoice_refs.append(r)
                ref_sources[r] = "llm_narration"
        if not payer_name:
            payer_name = narration_hints.get("likely_payer")
        if not tds_amount:
            tds_amount = float(narration_hints.get("tds_amount") or 0)

    # Always parse the raw narration with regex (fast, no LLM, high precision)
    narration_str = transaction.get("narration", "")
    narr_refs, narr_payer = _extract_from_narration(narration_str, all_invoices)
    narration_keys: set[str] = set()          # invoices cited by the bank line itself
    for r in narr_refs:
        narration_keys |= {i["invoice_id"] for i in find_exact_invoice_match(r, all_invoices)}
    for r in narr_refs:
        if r not in invoice_refs:
            invoice_refs.append(r)
            ref_sources[r] = "narration"
    if not payer_name and narr_payer:
        payer_name = narr_payer
    exclude = exclude_invoice_ids or set()

    # ── Step 2: Exact invoice-reference candidates ────────────────────────────
    exact_candidates: set[str] = set()
    matched_ref_source: dict[str, str] = {}
    for ref in invoice_refs:
        numeric_ok = ref_sources.get(ref) in ("llm_narration", "remittance")
        for inv in find_exact_invoice_match(ref, all_invoices, allow_numeric=numeric_ok):
            exact_candidates.add(inv["invoice_id"])
            matched_ref_source.setdefault(inv["invoice_id"], ref_sources.get(ref, "narration"))

    # ── Step 3: Customer-based candidates ─────────────────────────────────────
    customer_candidates: dict[str, dict] = {}   # invoice_id → invoice
    customer_fuzzy_scores: dict[str, int] = {}  # invoice_id → fuzzy score
    customer_match_methods: dict[str, str] = {} # invoice_id → match method
    if payer_name or payer_gstin:
        matched_customers = match_customer_identity(payer_name, payer_gstin, all_customers)
        for mc in matched_customers:
            cid = mc["customer_id"]
            for inv in all_invoices:
                if inv.get("customer_id") == cid:
                    # A settled invoice is only of interest when the payment quotes it.
                    if inv["status"] not in ("settled", "overpaid") or inv["invoice_id"] in exact_candidates:
                        customer_candidates[inv["invoice_id"]] = inv
                        customer_fuzzy_scores[inv["invoice_id"]] = mc.get("fuzzy_score", 0)
                        customer_match_methods[inv["invoice_id"]] = mc.get("match_method", "name_fuzzy")

    # ── Step 4: Amount-based candidates ──────────────────────────────────────
    credit   = Decimal(str(transaction.get("credit_amount", 0)))
    tds_dec  = Decimal(str(tds_amount))
    effective_payment = credit + tds_dec      # what the invoice should total

    amount_matches: set[str] = set()
    for inv in all_invoices:
        if inv["status"] in ("settled", "overpaid"):
            continue
        outstanding = Decimal(str(inv["outstanding_amount"]))
        if abs(effective_payment - outstanding) <= amount_tolerance(inv["total_amount"]):
            amount_matches.add(inv["invoice_id"])

    # ── Step 5: Merge all candidates ─────────────────────────────────────────
    all_candidate_ids = exact_candidates | set(customer_candidates.keys()) | amount_matches
    inv_map = {inv["invoice_id"]: inv for inv in all_invoices}

    candidates = []
    for inv_id in sorted(all_candidate_ids):
        inv = inv_map.get(inv_id)
        if not inv or inv_id in exclude:
            continue
        if (inv.get("currency") or "INR").upper() != (transaction.get("currency") or "INR").upper():
            continue
        signals = {
            "invoice_ref_exact":  inv_id in exact_candidates,
            "ref_in_narration":   inv_id in narration_keys,
            "customer_match":     inv_id in customer_candidates,
            "amount_match":       inv_id in amount_matches,
            "tds_amount":         tds_amount,
            "credit_amount":      float(credit),
            "effective_payment":  float(effective_payment),
            "fuzzy_score":        customer_fuzzy_scores.get(inv_id, 0),
            "match_method":       customer_match_methods.get(inv_id, "none"),
            "ref_source":         matched_ref_source.get(inv_id),
            "invoice_refs":       list(invoice_refs),
            "payer_hint":         payer_name,
            "tds_section":        tds_section,
        }
        candidates.append({"invoice": inv, "signals": signals})

    return candidates


