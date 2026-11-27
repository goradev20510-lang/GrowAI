"""
ReconcileAI – Decision Engine
Decides the reconciliation outcome for each transaction using scored candidates
and validation results. The LLM only reads narrations / phrases explanations;
this module decides.

  auto_block_reason()     – why a high score still needs a person (None = may auto-approve)
  evaluate_transaction()  – pure: reads the DB, writes nothing (used by the
                            Workspace "why?" panel and by reconcile_transaction)
  reconcile_transaction() – evaluate + persist allocations, review cases, audit
  run_batch_reconciliation() – every unmatched credit, in import order

The auto-match gates here are mirrored by training/train_matcher.py (decide());
keep the two in sync when changing them.
"""
from __future__ import annotations
from decimal import Decimal
from itertools import combinations
from typing import Callable

import config.thresholds as T
from config.settings import LLM_NARRATION_HINTS, LLM_MATCH_EXPLANATIONS
from database.repositories import (
    get_all_invoices, get_transaction, get_remittance_by_utr, find_remittances_by_amount,
    insert_allocation, insert_settlement_component, update_transaction_status,
    create_audit_log, insert_review_case, update_review_case, get_open_cases_for_transaction,
    get_rejected_invoice_ids, get_all_transactions, update_batch, create_batch,
    get_allocations_for_transaction, update_allocation_status, set_batch_status,
    get_audit_logs, get_invoice, update_decision_reason,
)
from database.db import transaction
from decision.credits import sync_customer_credit
from matching.candidate_generator import generate_candidate_invoices, _extract_from_narration
from matching.scoring import score_candidates
from validation.financial_rules import validate_allocation, infer_tds_deduction
from validation.duplicate_detection import detect_duplicate_transaction
from validation.settlement import finalise_settlement

MAX_BULK_INVOICES = 4
MAX_BULK_POOL = 14

SUGGESTED_ACTIONS = {
    "multiple_candidate_invoices": "Several invoices fit equally well — pick the right one (Correct) or approve the suggestion.",
    "possible_tds_deduction":      "Confirm the TDS amount and section with the customer and collect Form 16A, then approve.",
    "partial_payment":             "Confirm this is a part-payment; the balance stays open on the invoice.",
    "overpayment":                 "Customer paid more than the invoice — approve to hold the excess as credit, or correct.",
    "invoice_already_settled":     "The referenced invoice is already settled — check for a duplicate payment or a wrong reference.",
    "bulk_payment":                "One credit appears to cover several invoices — approve to apply it across all of them.",
    "low_confidence_match":        "Evidence is weak — verify payer and invoice before approving.",
    "missing_invoice_reference":   "No invoice could be identified. Obtain the remittance advice from the payer, then Correct.",
    "unknown_customer":            "Payer does not match any customer. Identify the payer, or dismiss if this is not a receivable.",
    "possible_duplicate":          "Same transfer appears more than once. Confirm it is a duplicate, or release it if genuine.",
    "payer_mismatch":              "The payer could not be tied to the invoice's customer — confirm who paid.",
    "unverified_evidence":         "The match rests on evidence that needs a person to check it before posting.",
    "processing_error":            "The engine failed on this line. Check the audit trail, then apply it manually.",
}


# ═════════════════════════════════════════════════════════════════════════════
# Evaluation (no writes)
# ═════════════════════════════════════════════════════════════════════════════

def remittance_fits(txn: dict, remittance: dict | None) -> bool:
    """The advice's stated amount (if any) agrees with what the bank actually received."""
    paid = (remittance or {}).get("payment_amount")
    if paid in (None, "", 0):
        return True
    credit = float(txn.get("credit_amount") or 0)
    return abs(Decimal(str(paid)) - Decimal(str(credit))) <= T.amount_tolerance(credit)


def auto_block_reason(txn: dict, cand: dict, remittance: dict | None, link: str | None) -> tuple[str, str] | None:
    """(exception type, reason) if this candidate must be reviewed whatever its score."""
    sig, inv = cand["signals"], cand["invoice"]
    if remittance and not remittance_fits(txn, remittance):
        return ("unverified_evidence",
                f"The remittance advice states ₹{float(remittance['payment_amount']):,.2f}, not the amount received.")
    if not sig.get("invoice_ref_exact"):
        return ("low_confidence_match", "No invoice reference identifies this invoice.")
    from_advice = bool(remittance) and link == "utr" and sig.get("ref_source") == "remittance"
    if not (sig.get("ref_in_narration") or from_advice):
        return ("unverified_evidence", "The invoice reference was not read from the bank line or from a "
                                       "remittance advice carrying this UTR.")
    if not sig.get("customer_match"):
        return ("payer_mismatch", f"Payer '{sig.get('payer_hint') or 'not stated'}' does not match "
                                  f"{inv.get('customer_name')}.")
    if not inv.get("verified", 1):
        return ("unverified_evidence", f"{inv['invoice_id']} was read by the model and has not been confirmed.")
    return None


def _find_remittance(transaction: dict) -> tuple[dict | None, str | None]:
    rem = get_remittance_by_utr(transaction.get("utr"))
    if rem:
        return rem, "utr"
    matches = find_remittances_by_amount(transaction.get("credit_amount", 0), transaction.get("transaction_date"),
                                         for_transaction=transaction.get("transaction_id"))
    if len(matches) == 1:
        return matches[0], "amount_and_date"
    return None, None


def _released_duplicate(transaction_id: str) -> bool:
    return any(l["action"] == "duplicate_released" for l in get_audit_logs(entity_id=transaction_id, limit=50))


def _find_bulk_combo(transaction: dict, ranked: list[dict], tds_amount: float) -> list[dict] | None:
    """
    Find 2–4 open invoices whose outstanding balances add up to the payment.
    The pool is restricted to invoices the evidence points at: invoice refs found in
    the narration/remittance, or invoices of the identified customer.
    """
    pool = [c for c in ranked if c["signals"].get("invoice_ref_exact") or c["signals"].get("customer_match")]
    pool = [c for c in pool if c["invoice"]["status"] in ("open", "partially_paid")][:MAX_BULK_POOL]
    if len(pool) < 2:
        return None
    effective = Decimal(str(transaction.get("credit_amount", 0))) + Decimal(str(tds_amount))
    tol = max(T.amount_tolerance(effective), Decimal("1"))
    refs = {c["invoice"]["invoice_id"] for c in pool if c["signals"].get("invoice_ref_exact")}
    best = None
    for n in range(2, min(MAX_BULK_INVOICES, len(pool)) + 1):
        for combo in combinations(pool, n):
            total = sum(Decimal(str(c["invoice"]["outstanding_amount"])) for c in combo)
            if abs(total - effective) > tol:
                continue
            ids = {c["invoice"]["invoice_id"] for c in combo}
            customers = {c["invoice"]["customer_id"] for c in combo}
            if len(customers) > 1 and not ids <= refs:
                continue               # never mix customers unless every invoice was referenced
            key = (len(ids & refs), -n)  # prefer combos that use the cited references, then fewer invoices
            if best is None or key > best[0]:
                best = (key, [c["invoice"] for c in combo])
    return best[1] if best else None


def narration_hints(txn: dict) -> dict | None:
    """Ask the model to read a narration that has no reference of its own (never inside a DB lock)."""
    if not (LLM_NARRATION_HINTS and txn and float(txn.get("credit_amount") or 0) > 0):
        return None
    from extraction.llm_extractor import llm_available, interpret_bank_narration
    refs, _ = _extract_from_narration(txn.get("narration") or "", get_all_invoices())
    if refs or _find_remittance(txn)[0] or not llm_available():
        return None
    try:
        return interpret_bank_narration(txn.get("narration") or "", float(txn["credit_amount"]),
                                        txn.get("transaction_date"))
    except Exception:
        return None


def evaluate_transaction(transaction: dict | str, *, use_llm: bool = True, hints: dict | None = None) -> dict:
    """
    Work out what should happen to one bank credit. Reads the database, writes nothing.

    Returns a dict with:
      outcome        matched | review | unmatched | duplicate | excluded
      exception_type review/unmatched reason (see SUGGESTED_ACTIONS)
      ranked         scored candidates (best first)
      best, score, validation, tds_amount, tds_section, implied_tds, bulk_invoices
      remittance, remittance_link, narration_hints, explanation
    """
    txn = get_transaction(transaction) if isinstance(transaction, str) else transaction
    if not txn:
        return {"outcome": "error", "reason": "Transaction not found"}
    tid = txn["transaction_id"]
    credit = float(txn.get("credit_amount") or 0)
    base = {"transaction": txn, "ranked": [], "best": None, "score": 0.0, "validation": None,
            "tds_amount": 0.0, "tds_section": None, "implied_tds": None, "bulk_invoices": None,
            "remittance": None, "remittance_link": None, "narration_hints": None, "exception_type": None}

    if credit <= 0:
        return {**base, "outcome": "excluded", "reason": "Debit / zero-value line — not a receivable."}

    # 1. Duplicate check
    if not _released_duplicate(tid):
        dup = detect_duplicate_transaction(txn)
        if dup["is_duplicate"]:
            return {**base, "outcome": "duplicate", "exception_type": "possible_duplicate",
                    "reason": dup["reason"], "duplicate_of": dup["duplicate_of"]}

    # 2. Remittance advice (by UTR, else a unique amount+date match)
    remittance, link = _find_remittance(txn)

    # 3. Narration hints via LLM — only when the narration has no reference of its own
    if use_llm and hints is None and not remittance:
        hints = narration_hints(txn)

    # 4. Candidates and scores
    excluded = get_rejected_invoice_ids(tid)
    candidates = generate_candidate_invoices(txn, hints, remittance, exclude_invoice_ids=excluded)
    base.update(remittance=remittance, remittance_link=link, narration_hints=hints, rejected_invoices=excluded)
    if not candidates:
        _, payer = _extract_from_narration(txn.get("narration") or "")
        exc = "unknown_customer" if (payer or (remittance or {}).get("customer_name")) else "missing_invoice_reference"
        return {**base, "outcome": "unmatched", "exception_type": exc,
                "reason": "No invoice reference, customer or amount match found."}

    ranked = score_candidates(txn, candidates)
    best = ranked[0]
    invoice, score, signals = best["invoice"], best["score"], best["signals"]
    tds_amount = float(signals.get("tds_amount") or 0)
    tds_section = signals.get("tds_section")
    validation = validate_allocation(credit, tds_amount, invoice, tds_section=tds_section,
                                     has_tds_certificate=False, on=txn.get("transaction_date"))
    av = validation["amount_validation"]
    implied = infer_tds_deduction(credit, invoice, on=txn.get("transaction_date")) if tds_amount == 0 and av["is_partial"] else None
    base.update(ranked=ranked, best=best, score=score, validation=validation,
                tds_amount=tds_amount, tds_section=tds_section, implied_tds=implied)

    ambiguous = len(ranked) > 1 and ranked[0]["score"] - ranked[1]["score"] < T.AMBIGUITY_MARGIN
    amount_fits = av["within_tolerance"]

    # 5. Decision gates (mirrored in training/train_matcher.decide)
    blocked = auto_block_reason(txn, best, remittance, link)
    if (not ambiguous and not blocked and score >= T.AUTO_MATCH_THRESHOLD
            and validation["overall_valid"] and not validation["requires_review"]):
        return {**base, "outcome": "matched", "reason": "High-confidence match",
                "explanation": build_explanation(txn, best, validation, link)}

    bulk = None if amount_fits and not ambiguous else _find_bulk_combo(txn, ranked, tds_amount)
    if bulk:
        return {**base, "outcome": "review", "exception_type": "bulk_payment", "bulk_invoices": bulk,
                "reason": f"Payment equals the combined balance of {', '.join(i['invoice_id'] for i in bulk)}"}

    if ambiguous:
        alt = ranked[1]
        return {**base, "outcome": "review", "exception_type": "multiple_candidate_invoices",
                "reason": (f"Top candidates {invoice['invoice_id']} ({score:.2f}) and "
                           f"{alt['invoice']['invoice_id']} ({alt['score']:.2f}) are too close to auto-match.")}

    if score >= T.REVIEW_THRESHOLD or validation["requires_review"]:
        exc = _exception_type(invoice, validation, tds_amount, implied)
        reason = _review_reason(invoice, validation, tds_amount, implied, score)
        if blocked:
            if exc == "low_confidence_match":
                exc = blocked[0]
            reason += " " + blocked[1]
        return {**base, "outcome": "review", "exception_type": exc, "reason": reason}

    return {**base, "outcome": "unmatched", "exception_type": "low_confidence_match",
            "reason": f"Best candidate {invoice['invoice_id']} scored {score:.2f}, below the review threshold "
                      f"{T.REVIEW_THRESHOLD:.2f}."}


def _exception_type(invoice: dict, validation: dict, tds_amount: float, implied: dict | None) -> str:
    av = validation["amount_validation"]
    if invoice.get("status") in ("settled", "overpaid"):
        return "invoice_already_settled"
    if tds_amount > 0 or implied:
        return "possible_tds_deduction"
    if av["is_overpayment"]:
        return "overpayment"
    if av["is_partial"]:
        return "partial_payment"
    return "low_confidence_match"


def _review_reason(invoice: dict, validation: dict, tds_amount: float, implied: dict | None, score: float) -> str:
    av = validation["amount_validation"]
    parts = [f"Best candidate {invoice['invoice_id']} (score {score:.2f})."]
    if tds_amount > 0:
        tv = validation["tds_validation"]
        parts.append(f"TDS ₹{tds_amount:,.2f} claimed — status {tv.get('tds_status')}. " + " ".join(tv.get("reasons", [])))
    elif implied:
        parts.append(f"Short by ₹{implied['tds_amount']:,.2f} = {implied['rate']:.0%} of the {implied['basis']} "
                     f"— looks like undeclared TDS ({'/'.join(implied['sections'])}).")
    if av["is_overpayment"]:
        parts.append(f"Overpaid by ₹{av['difference']:,.2f}.")
    elif av["is_partial"] and not implied:
        parts.append(f"Covers ₹{av['effective_payment']:,.2f} of ₹{invoice['outstanding_amount']:,.2f} outstanding.")
    if invoice.get("status") in ("settled", "overpaid"):
        parts.append("Invoice is already settled.")
    return " ".join(parts)


def build_explanation(txn: dict, cand: dict, validation: dict | None, remittance_link: str | None = None) -> str:
    """Deterministic, evidence-only explanation of why a candidate matches."""
    inv, sig = cand["invoice"], cand["signals"]
    bits = []
    if sig.get("invoice_ref_exact"):
        src = {"remittance": "the remittance advice", "llm_narration": "the narration (LLM-read)"}.get(
            sig.get("ref_source"), "the bank narration")
        bits.append(f"invoice reference {inv['invoice_id']} appears in {src}")
    if sig.get("customer_match"):
        how = "GSTIN" if sig.get("match_method") == "gstin_exact" else f"name similarity {sig.get('fuzzy_score', 0):.0f}%"
        payer = f"'{sig['payer_hint']}' " if sig.get("payer_hint") else ""
        bits.append(f"payer {payer}matches customer {inv.get('customer_name')} ({how})")
    eff = float(sig.get("effective_payment") or txn.get("credit_amount") or 0)
    if validation:
        av = validation["amount_validation"]
        if av["within_tolerance"]:
            diff = abs(av["difference"])
            bits.append(f"₹{eff:,.2f} equals the outstanding ₹{inv['outstanding_amount']:,.2f}"
                        + (f" (₹{diff:,.2f} rounding/bank charge)" if diff >= 0.01 else ""))
        elif av["is_partial"]:
            bits.append(f"₹{eff:,.2f} part-pays the outstanding ₹{inv['outstanding_amount']:,.2f}")
    if float(sig.get("tds_amount") or 0) > 0:
        bits.append(f"including TDS ₹{float(sig['tds_amount']):,.2f}")
    if remittance_link == "amount_and_date":
        bits.append("remittance advice linked by amount and date")
    text = "; ".join(bits) or "amount and date proximity"
    return f"{txn['transaction_id']} → {inv['invoice_id']}: {text[0].upper()}{text[1:]}. Confidence {cand['score']:.0%}."


# ═════════════════════════════════════════════════════════════════════════════
# Persistence
# ═════════════════════════════════════════════════════════════════════════════

def reconcile_transaction(transaction_id: str, *, use_llm: bool = True) -> dict:
    """Full reconciliation pipeline for a single bank transaction (evaluate + persist)."""
    txn = get_transaction(transaction_id)
    if not txn:
        return {"outcome": "error", "reason": "Transaction not found"}
    hints = narration_hints(txn) if use_llm else None          # slow call, made before locking

    with transaction():                                        # state is checked and written atomically
        txn = get_transaction(transaction_id)
        if txn["status"] in ("matched", "excluded") or any(
                a["allocation_status"] == "approved" for a in get_allocations_for_transaction(transaction_id)):
            return {"outcome": "skipped", "reason": f"{transaction_id} is already {txn['status']}"}
        ev = evaluate_transaction(txn, use_llm=False, hints=hints)
        result = _persist(txn, ev)

    if result["outcome"] == "matched" and use_llm and LLM_MATCH_EXPLANATIONS:
        result["explanation"] = _model_explanation(txn, ev, result)
    return result


def _persist(txn: dict, ev: dict) -> dict:
    transaction_id, outcome = txn["transaction_id"], ev["outcome"]
    for a in get_allocations_for_transaction(transaction_id):  # replace earlier, unapproved proposals
        if a["allocation_status"] == "proposed":
            update_allocation_status(a["allocation_id"], "superseded", "system", "Re-evaluated")
    _supersede_open_cases(transaction_id)

    if outcome == "excluded":
        update_transaction_status(transaction_id, "excluded")
        return {"outcome": "excluded", "reason": ev["reason"]}
    if outcome == "duplicate":
        update_transaction_status(transaction_id, "duplicate")
        cid = insert_review_case({
            "transaction_id": transaction_id, "exception_type": "possible_duplicate",
            "exception_summary": ev["reason"], "suggested_action": SUGGESTED_ACTIONS["possible_duplicate"]})
        create_audit_log("transaction", transaction_id, "flagged_duplicate",
                         details={"reason": ev["reason"], "duplicate_of": ev["duplicate_of"], "review_case": cid})
        return {"outcome": "duplicate", "reason": ev["reason"], "duplicate_of": ev["duplicate_of"],
                "review_case_id": cid}
    if outcome == "matched":
        return _auto_approve(txn, ev)
    if outcome == "review":
        return _send_to_review(txn, ev)
    return _mark_unmatched(txn, ev)


def _model_explanation(txn: dict, ev: dict, result: dict) -> str:
    from extraction.llm_extractor import llm_available, generate_match_explanation
    best, text = ev["best"], result["explanation"]
    if llm_available():
        try:
            text = generate_match_explanation({
                "transaction_id": txn["transaction_id"], "invoice_id": result["invoice_id"],
                "confidence_score": ev["score"],
                "signals": {k: v for k, v in best["signals"].items() if k != "invoice_refs"},
                "validation": ev["validation"], "deterministic_explanation": text,
            }).strip() or text
            update_decision_reason(result["allocation_id"], text)
        except Exception:
            pass
    return text


def _supersede_open_cases(transaction_id: str) -> None:
    for case in get_open_cases_for_transaction(transaction_id):
        update_review_case(case["case_id"], "superseded", "system", "Transaction re-evaluated")


def _add_components(aid: str, credit: float, tds: float, tds_status: str | None, tds_section: str | None) -> None:
    insert_settlement_component({"allocation_id": aid, "component_type": "bank_credit", "amount": credit})
    if tds > 0:
        insert_settlement_component({"allocation_id": aid, "component_type": "tds", "amount": tds,
                                     "tds_status": tds_status or "claimed", "tds_section": tds_section})


def _auto_approve(txn: dict, ev: dict) -> dict:
    tid = txn["transaction_id"]
    best, validation, score = ev["best"], ev["validation"], ev["score"]
    iid = best["invoice"]["invoice_id"]
    credit, tds = float(txn["credit_amount"]), float(ev["tds_amount"])
    explanation = ev.get("explanation") or build_explanation(txn, best, validation, ev.get("remittance_link"))
    # Never apply more than the invoice owes; any excess becomes customer credit.
    applied = round(min(credit + tds, float(get_invoice(iid)["outstanding_amount"])), 2)

    aid = insert_allocation({
        "transaction_id": tid, "invoice_id": iid, "allocated_amount": applied,
        "allocation_status": "approved", "confidence_score": score,
        "decision_reason": explanation, "approved_by": "system",
        "remittance_id": (ev.get("remittance") or {}).get("remittance_id"),
    })
    _add_components(aid, round(applied - tds, 2), tds, validation["tds_validation"].get("tds_status"),
                    ev["tds_section"])
    settlement = finalise_settlement(iid, audit=False)
    update_transaction_status(tid, "matched")
    sync_customer_credit(tid, "system")
    create_audit_log("transaction", tid, "auto_matched",
                     details={"invoice_id": iid, "score": score, "allocation_id": aid,
                              "reason": ev.get("reason"), "invoice_status": settlement.get("status"),
                              "rounding_writeoff": settlement.get("rounding_writeoff")})
    return {"outcome": "matched", "invoice_id": iid, "score": score, "allocation_id": aid,
            "explanation": explanation, "new_outstanding": settlement.get("outstanding")}


def _send_to_review(txn: dict, ev: dict) -> dict:
    tid = txn["transaction_id"]
    credit, tds = float(txn["credit_amount"]), float(ev["tds_amount"])
    exc = ev["exception_type"]
    best = ev["best"]
    allocation_ids: list[str] = []

    rem_id = (ev.get("remittance") or {}).get("remittance_id")
    if ev.get("bulk_invoices"):
        invoices = ev["bulk_invoices"]
        owed = [Decimal(str(i["outstanding_amount"])) for i in invoices]
        total_out, effective = sum(owed), Decimal(str(credit)) + Decimal(str(tds))
        remaining, remaining_tds = min(effective, total_out), Decimal(str(tds))
        for k, inv in enumerate(invoices):
            last = k == len(invoices) - 1
            share = owed[k] / total_out
            if effective >= total_out:
                portion = owed[k]
            else:                                   # short within tolerance: spread it
                portion = remaining if last else (effective * share).quantize(Decimal("0.01"))
            t_part = remaining_tds if last else (Decimal(str(tds)) * share).quantize(Decimal("0.01"))
            remaining -= portion
            remaining_tds -= t_part
            aid = insert_allocation({
                "transaction_id": tid, "invoice_id": inv["invoice_id"],
                "allocated_amount": float(portion), "allocation_status": "proposed",
                "confidence_score": ev["score"],
                "decision_reason": f"Bulk payment split {k + 1}/{len(invoices)}: {ev['reason']}",
                "approved_by": None, "remittance_id": rem_id,
            })
            _add_components(aid, float(portion - t_part), float(t_part), "claimed", ev["tds_section"])
            allocation_ids.append(aid)
        suggested_invoice = invoices[0]["invoice_id"]
    else:
        inv = best["invoice"]
        implied = ev.get("implied_tds")
        tds_total = tds or (implied["tds_amount"] if implied else 0.0)
        section = ev["tds_section"] or (implied["sections"][0] if implied else None)
        applied = round(min(credit + tds_total, float(inv["outstanding_amount"])), 2)
        suggested_invoice = inv["invoice_id"]
        if applied > 0:                             # nothing to propose on a settled invoice
            aid = insert_allocation({
                "transaction_id": tid, "invoice_id": inv["invoice_id"],
                "allocated_amount": applied, "allocation_status": "proposed",
                "confidence_score": ev["score"],
                "decision_reason": build_explanation(txn, best, ev["validation"], ev.get("remittance_link")),
                "approved_by": None, "remittance_id": rem_id,
            })
            tds_total = min(tds_total, applied)
            tds_status = ev["validation"]["tds_validation"].get("tds_status") if tds else "claimed"
            _add_components(aid, round(applied - tds_total, 2), tds_total, tds_status, section)
            allocation_ids.append(aid)

    alternatives = [f"{c['invoice']['invoice_id']} ({c['score']:.2f})" for c in ev["ranked"][1:4]]
    summary = ev["reason"] + (f" Other candidates: {', '.join(alternatives)}." if alternatives else "")
    if (allocation_ids and not ev.get("bulk_invoices")
            and ev["validation"]["amount_validation"]["is_overpayment"]):
        summary += " On approval the excess is held as customer credit."
    cid = insert_review_case({
        "transaction_id": tid, "invoice_id": suggested_invoice, "exception_type": exc,
        "exception_summary": summary, "suggested_action": SUGGESTED_ACTIONS.get(exc),
    })
    update_transaction_status(tid, "review")
    create_audit_log("transaction", tid, "sent_to_review",
                     details={"review_case_id": cid, "exception_type": exc, "score": ev["score"],
                              "proposed_allocations": allocation_ids})
    return {"outcome": "review", "reason": exc, "review_case_id": cid, "score": ev["score"],
            "invoice_id": suggested_invoice, "allocation_ids": allocation_ids}


def _mark_unmatched(txn: dict, ev: dict) -> dict:
    tid = txn["transaction_id"]
    exc = ev.get("exception_type") or "missing_invoice_reference"
    update_transaction_status(tid, "unmatched")
    cid = insert_review_case({
        "transaction_id": tid,
        "invoice_id": ev["best"]["invoice"]["invoice_id"] if ev.get("best") else None,
        "exception_type": exc, "exception_summary": ev.get("reason"),
        "suggested_action": SUGGESTED_ACTIONS.get(exc),
    })
    create_audit_log("transaction", tid, "unmatched", details={"review_case": cid, "reason": ev.get("reason")})
    return {"outcome": "unmatched", "review_case_id": cid, "reason": ev.get("reason"), "score": ev.get("score", 0.0)}


def pending_transactions() -> list[dict]:
    """Everything still undecided: unmatched credits and those waiting in review."""
    return [t for t in get_all_transactions()
            if t["status"] in ("unmatched", "review") and float(t["credit_amount"] or 0) > 0]


def run_batch_reconciliation(batch_id: str | None = None, *, use_llm: bool = True,
                             progress: Callable[[int, int, dict], None] | None = None) -> dict:
    """
    Run reconciliation on every undecided credit, in import order. Lines already in
    review are re-evaluated too (new invoices or remittances may have arrived) and
    their old case is superseded.
    """
    if not batch_id:
        batch_id = create_batch()

    transactions = pending_transactions()
    stats = {"total": len(transactions), "matched": 0, "needs_review": 0, "unmatched": 0, "duplicates": 0}
    try:
        for k, txn in enumerate(transactions, 1):
            try:
                result = reconcile_transaction(txn["transaction_id"], use_llm=use_llm)
            except Exception as e:                       # one bad line must not stop the batch
                result = _record_error(txn["transaction_id"], e)
            outcome = result.get("outcome", "unmatched")
            key = {"matched": "matched", "review": "needs_review", "duplicate": "duplicates"}.get(outcome, "unmatched")
            stats[key] += 1
            if progress:
                progress(k, len(transactions), result)
    except BaseException:
        set_batch_status(batch_id, "failed")
        raise

    update_batch(batch_id, stats)
    create_audit_log("batch", batch_id, "batch_completed", details=stats)
    return {"batch_id": batch_id, **stats}


def _record_error(transaction_id: str, error: Exception) -> dict:
    """A failed line must still reach a person."""
    with transaction():
        _supersede_open_cases(transaction_id)
        update_transaction_status(transaction_id, "review")
        cid = insert_review_case({
            "transaction_id": transaction_id, "exception_type": "processing_error",
            "exception_summary": f"Reconciliation failed: {error}",
            "suggested_action": SUGGESTED_ACTIONS["processing_error"]})
        create_audit_log("transaction", transaction_id, "reconcile_error",
                         details={"error": str(error), "review_case": cid})
    return {"outcome": "review", "review_case_id": cid}
