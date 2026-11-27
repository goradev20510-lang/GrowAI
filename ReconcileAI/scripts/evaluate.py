"""
End-to-end evaluation of the *real* engine on freshly generated synthetic batches
(a different seed from the training data). Offline; uses throw-away databases.

Run:  python -m scripts.evaluate --batches 60 --seed 2026
"""
from __future__ import annotations
import argparse
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["LLM_ENABLED"] = "0"


def evaluate(n_batches: int, seed: int) -> dict:
    from data.synthetic.generate_training_data import generate
    from database.db import set_database_path, initialise_database, get_connection, reset_database
    from database.repositories import (insert_invoice, insert_transaction, insert_remittance,
                                       get_allocations_for_transaction, get_transaction)
    from decision.decision_engine import run_batch_reconciliation
    from reporting.ledger import check_ledger

    totals, wrong, per = Counter(), [], {}
    with tempfile.TemporaryDirectory() as tmp:
        set_database_path(Path(tmp) / "eval.db")
        initialise_database()
        for batch in generate(n_batches, seed):
            reset_database()
            conn = get_connection()
            for c in batch["customers"]:
                conn.execute("INSERT INTO customers(customer_id,name,gstin) VALUES(?,?,?)",
                             (c["customer_id"], c["name"], c["gstin"]))
            conn.commit()
            for inv in batch["invoices"]:
                insert_invoice(inv)
            for r in batch["remittances"]:
                insert_remittance(r)
            for t in batch["transactions"]:
                insert_transaction(t)
            run_batch_reconciliation(use_llm=False)
            for label in batch["labels"]:
                tid = label["transaction_id"]
                status = get_transaction(tid)["status"]
                allocs = get_allocations_for_transaction(tid)
                applied = {a["invoice_id"] for a in allocs if a["allocation_status"] == "approved"}
                proposed = {a["invoice_id"] for a in allocs if a["allocation_status"] == "proposed"}
                truth = set(label["true_invoice_ids"])
                row = per.setdefault(label["scenario"], Counter())
                row[status] += 1
                totals["transactions"] += 1
                totals[status] += 1
                if status == "matched":
                    if applied != truth:
                        wrong.append((label["scenario"], tid, sorted(applied), sorted(truth)))
                    elif not label["auto_ok"]:
                        totals["auto_matched_but_policy_wants_review"] += 1
                if status == "review" and truth:
                    totals["review_with_truth"] += 1
                    totals["review_suggestion_correct"] += bool(proposed & truth)
            totals["unbalanced_ledgers"] += not check_ledger()["balanced"]
        set_database_path(None)
    return {"totals": dict(totals), "wrong_auto_matches": wrong, "per_scenario": per}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batches", type=int, default=60)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    r = evaluate(args.batches, args.seed)
    t = r["totals"]
    n, auto = t["transactions"], t.get("matched", 0)
    print(f"Synthetic evaluation: {args.batches} batches, {n} credits, seed {args.seed}")
    print(f"  auto-matched      {auto:>5}  ({auto / n:.1%})")
    print(f"  wrong auto-match  {len(r['wrong_auto_matches']):>5}")
    print(f"  auto, policy wants review {t.get('auto_matched_but_policy_wants_review', 0)}")
    print(f"  review            {t.get('review', 0):>5}  (suggestion correct "
          f"{t.get('review_suggestion_correct', 0)}/{t.get('review_with_truth', 0)})")
    print(f"  unmatched         {t.get('unmatched', 0):>5}\n  duplicate         {t.get('duplicate', 0):>5}")
    print(f"  unbalanced ledgers {t.get('unbalanced_ledgers', 0)}\n")
    print(f"{'scenario':<28}{'matched':>9}{'review':>9}{'unmatched':>11}")
    for name, c in sorted(r["per_scenario"].items()):
        print(f"{name:<28}{c['matched']:>9}{c['review']:>9}{c['unmatched']:>11}")
    for w in r["wrong_auto_matches"][:10]:
        print("WRONG:", w)
    return 1 if r["wrong_auto_matches"] or t.get("unbalanced_ledgers") else 0


if __name__ == "__main__":
    raise SystemExit(main())
