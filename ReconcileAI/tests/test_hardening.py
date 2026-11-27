"""Regression tests for money-safety, parsing, ledger, security and intake behaviour."""
import base64
import io
import sqlite3

import pytest

from database.repositories import (
    get_invoice, get_transaction, insert_invoice, insert_transaction, insert_remittance, upsert_customer,
    get_allocations_for_transaction, get_open_credit_for_transaction, get_reconciliation_summary,
    get_tds_components, get_settlement_component, verify_audit_chain, get_open_cases_for_transaction,
    get_all_transactions,
)
from decision import adjustments as adj
from decision import review_manager as rm
from decision.decision_engine import reconcile_transaction as reconcile, run_batch_reconciliation
from reporting.ledger import check_ledger

APEX = "Apex Solutions Pvt Ltd"


def invoice(iid, total, customer=APEX, **extra):
    cid = upsert_customer(customer)
    insert_invoice({"invoice_id": iid, "customer_id": cid, "customer_name": customer, "total_amount": total, **extra})
    return cid


def credit(tid, amount, narration, utr=None, date="2026-10-10"):
    insert_transaction({"transaction_id": tid, "credit_amount": amount, "narration": narration,
                        "utr": utr or f"UTR{tid}", "transaction_date": date})
    return tid


def balance(iid):
    i = get_invoice(iid)
    return i["status"], i["outstanding_amount"]


def case_of(tid):
    return get_open_cases_for_transaction(tid)[0]


def balanced():
    report = check_ledger()
    assert report["balanced"], report


# ── references, dates, amounts ───────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [("INV-101", "INV-11"), ("INV-100", "INV-10"), ("INV-1005", "INV-105")])
def test_zeros_inside_invoice_numbers_matter(db, a, b):
    invoice(b, 5000)
    assert reconcile(credit("T1", 5000, f"NEFT/APEX/{a}"), use_llm=False)["outcome"] != "matched"
    assert balance(b) == ("open", 5000)


@pytest.mark.parametrize("number,text", [
    ("INV/24-25/0012", "NEFT/APEX/INV/24-25/0012"), ("SI-00123", "NEFT/APEX/SI 123"),
    ("INV-2024-001", "NEFT/APEX/INV-2024-001/97200"),
])
def test_any_invoice_format_is_found(db, number, text):
    invoice(number, 1000)
    res = reconcile(credit("T1", 1000, text), use_llm=False)
    assert res["outcome"] == "matched" and res["invoice_id"] == number


def test_shorter_number_is_not_found_inside_longer(db):
    invoice("INV-2024", 1000)
    assert reconcile(credit("T1", 1000, "NEFT/APEX/INV-2024-001"), use_llm=False)["outcome"] != "matched"


@pytest.mark.parametrize("raw", ["2026-03-05", "2026-03-05 00:00:00", "05/03/2026", "05-Mar-2026"])
def test_dates_are_not_swapped(raw):
    from utils.dates import to_iso
    assert to_iso(raw) == "2026-03-05"


@pytest.mark.parametrize("raw,value", [
    ("1,200.00 Cr", 1200), ("Rs. 500", 500), ("₹ 1,00,000", 100000), ("(500)", -500), ("500 Dr", -500),
    ("", 0), ("abc", None),
])
def test_amount_formats(raw, value):
    from extraction.bank_parser import _clean_amount
    assert _clean_amount(raw) == value


def test_statement_keeps_repeat_payments_and_reports_bad_rows(db):
    from extraction.ingestion import ingest_bank_statement
    data = (b"Date,Narration,Ref No,Credit,Debit\n01/10/2026,UPI/Apex,111111111111,500,\n"
            b"01/10/2026,UPI/Apex,222222222222,500,\n01/10/2026,UPI/Apex,222222222222,500,\n"
            b"02/10/2026,BAD,,five hundred,\nTotal,,,1500,\n")
    res = ingest_bank_statement("a.csv", data)
    assert res["transactions_imported"] == 3 and len(res["rejected_rows"]) == 2
    overlap = ingest_bank_statement("b.csv", data + b"\n")
    assert overlap["transactions_imported"] == 0 and overlap["already_present"] == 3


def test_single_amount_column_with_dr_cr(db):
    from extraction.ingestion import ingest_bank_statement
    res = ingest_bank_statement("a.csv", b"Txn Date,Description,Amount,Dr/Cr\n01/10/2026,NEFT IN,500,CR\n"
                                         b"02/10/2026,ATM,200,DR\n")
    assert (res["credits_imported"], res["debits_excluded"]) == (1, 1)


def test_account_number_is_not_a_utr():
    from extraction.bank_parser import _extract_utr_from_narration as utr
    assert utr("NEFT/50100123456789/APEX") is None
    assert utr("RTGS/HDFCR52024101500123/APEX") == "HDFCR52024101500123"
    assert utr("UPI/412345678901/APEX") == "412345678901"


# ── state checks and balances ────────────────────────────────────────────────

def test_matched_credit_cannot_be_reconciled_again(db):
    invoice("INV-101", 1000)
    reconcile(credit("T1", 1000, "NEFT/Apex/INV-101"), use_llm=False)
    assert reconcile("T1", use_llm=False)["outcome"] == "skipped"
    assert [a["allocation_status"] for a in get_allocations_for_transaction("T1")] == ["approved"]


def test_closed_cases_refuse_every_action(db):
    invoice("INV-101", 1000)
    reconcile(credit("T1", 400, "NEFT/Apex/INV-101"), use_llm=False)
    cid = case_of("T1")["case_id"]
    rm.approve_match(cid, reviewer="a")
    for action in (lambda: rm.correct_match(cid, "T1", "INV-101"), lambda: rm.correct_match(None, "T1", "INV-101"),
                   lambda: rm.dismiss_transaction(cid), lambda: rm.reject_match(cid),
                   lambda: rm.release_duplicate(cid), lambda: rm.confirm_duplicate(cid)):
        with pytest.raises(rm.ReviewError):
            action()
    assert balance("INV-101") == ("partially_paid", 600) and get_transaction("T1")["status"] == "matched"
    balanced()


def test_second_proposal_cannot_overpay(db):
    invoice("INV-101", 1000)
    reconcile(credit("T1", 850, "NEFT/Apex/INV-101"), use_llm=False)
    reconcile(credit("T2", 850, "IMPS/Apex/INV-101", date="2026-10-12"), use_llm=False)
    rm.approve_match(case_of("T1")["case_id"])
    with pytest.raises(rm.ReviewError):
        rm.approve_match(case_of("T2")["case_id"])
    reconcile("T2", use_llm=False)
    rm.approve_match(case_of("T2")["case_id"])
    assert balance("INV-101") == ("settled", 0)
    assert get_open_credit_for_transaction("T2")["remaining"] == 700
    balanced()


def test_imported_part_payment_is_remembered(db):
    from extraction.ingestion import ingest_invoice
    ingest_invoice("i.csv", b"Invoice No,Customer Name,Total,Outstanding\nINV-101,Apex Solutions,1000,300\n")
    reconcile(credit("T1", 100, "NEFT/Apex Solutions/INV-101"), use_llm=False)
    rm.approve_match(case_of("T1")["case_id"])
    assert balance("INV-101") == ("partially_paid", 200)
    rm.reverse_transaction("T1")
    assert balance("INV-101") == ("partially_paid", 300)
    balanced()


def test_failure_part_way_changes_nothing(db, monkeypatch):
    invoice("INV-101", 1000)
    reconcile(credit("T1", 400, "NEFT/Apex/INV-101"), use_llm=False)

    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(rm, "update_review_case", boom)
    with pytest.raises(RuntimeError):
        rm.approve_match(case_of("T1")["case_id"])
    assert balance("INV-101") == ("open", 1000) and get_transaction("T1")["status"] == "review"
    assert [a["allocation_status"] for a in get_allocations_for_transaction("T1")] == ["proposed"]
    balanced()


def test_processing_error_reaches_a_person(db, monkeypatch):
    import decision.decision_engine as de
    invoice("INV-101", 1000)
    credit("T1", 1000, "NEFT/Apex/INV-101")
    monkeypatch.setattr(de, "score_candidates", lambda *a: 1 / 0)
    assert run_batch_reconciliation(use_llm=False)["needs_review"] == 1
    assert case_of("T1")["exception_type"] == "processing_error"


def test_batch_re_evaluates_review_items(db):
    invoice("INV-101", 1000)
    credit("T1", 1000, "NEFT/CMS PAYOUT")
    run_batch_reconciliation(use_llm=False)
    insert_remittance({"utr": "UTRT1", "invoice_references": ["INV-101"], "payment_amount": 1000,
                       "customer_name": APEX})
    assert run_batch_reconciliation(use_llm=False)["matched"] == 1


# ── safe matching ────────────────────────────────────────────────────────────

def test_wrong_payer_goes_to_review(db):
    invoice("INV-101", 1000, "Nova Traders")
    assert reconcile(credit("T1", 1000, "NEFT/Completely Different Co/INV-101"), use_llm=False)["outcome"] == "review"
    assert case_of("T1")["exception_type"] == "payer_mismatch"


@pytest.mark.parametrize("payer,customer", [
    ("Ravi Kumar Private Limited", "Nova Traders Pvt Ltd"),
    ("Zen Solutions", "Apex Solutions Ltd"), ("Private Limited", "Nova Traders Private Limited"),
])
def test_shared_business_words_do_not_match(payer, customer):
    from matching.fuzzy_match import name_similarity
    assert name_similarity(payer, customer) < 75


@pytest.mark.parametrize("payer,customer", [
    ("XYZTECHNOLOGIES", "XYZ Technologies Pvt Ltd"), ("APEX", "Apex Solutions Ltd"),
    ("ORBIT LOG", "Orbit Logistics Pvt Ltd"), ("STERLING CORP", "Sterling Global Corporation"),
])
def test_real_variants_still_match(payer, customer):
    from matching.fuzzy_match import name_similarity
    assert name_similarity(payer, customer) >= 75


def test_large_shortfall_is_not_written_off(db):
    invoice("INV-101", 1_000_000)
    assert reconcile(credit("T1", 995_100, "NEFT/Apex/INV-101"), use_llm=False)["outcome"] == "review"
    assert balance("INV-101") == ("open", 1_000_000)


def test_small_bank_charge_is_recorded_as_rounding(db):
    invoice("INV-101", 100_000)
    assert reconcile(credit("T1", 99_988.2, "NEFT/Apex/INV-101"), use_llm=False)["outcome"] == "matched"
    assert get_invoice("INV-101")["rounding_writeoff"] == pytest.approx(11.8)
    balanced()


def test_model_guessed_reference_never_auto_matches(db):
    from decision.decision_engine import evaluate_transaction
    invoice("INV-101", 1000)
    credit("T1", 1000, "NEFT/Apex/OCT")
    ev = evaluate_transaction("T1", use_llm=False, hints={"invoice_references": ["INV-101"]})
    assert ev["outcome"] == "review" and ev["exception_type"] == "unverified_evidence"


def test_unconfirmed_invoice_waits_for_a_person(db):
    invoice("INV-101", 1000, verified=False)
    credit("T1", 1000, "NEFT/Apex/INV-101")
    assert reconcile("T1", use_llm=False)["outcome"] == "review"
    rm.confirm_invoice("INV-101", "a")
    assert reconcile("T1", use_llm=False)["outcome"] == "matched"


def test_model_output_must_appear_in_the_document():
    from extraction.grounding import ground
    out, dropped = ground({"total_amount": 999999.0, "invoice_id": "INV-7", "invoice_references": ["INV-7", "INV-8"]},
                          "Invoice No INV-7 Total 1,000.00", ("total_amount",), ("invoice_id",))
    assert out["total_amount"] is None and out["invoice_id"] == "INV-7"
    assert out["invoice_references"] == ["INV-7"] and "total_amount" in dropped


def test_remittance_is_not_reused_and_amount_must_agree(db):
    invoice("INV-101", 1000)
    insert_remittance({"payment_amount": 1000, "invoice_references": ["INV-101"], "customer_name": APEX})
    first = reconcile(credit("T1", 1000, "NEFT/CMS"), use_llm=False)
    second = reconcile(credit("T2", 1000, "NEFT/OTHER CMS", date="2027-03-01"), use_llm=False)
    assert first["outcome"] == "review" and second["outcome"] == "unmatched"
    invoice("INV-102", 700)
    insert_remittance({"utr": "UTRT3", "payment_amount": 5000, "invoice_references": ["INV-102"]})
    assert reconcile(credit("T3", 700, "NEFT/Apex/INV-102"), use_llm=False)["outcome"] == "review"


# ── credits, adjustments, TDS ────────────────────────────────────────────────

def test_overpayment_credit_can_be_applied_and_reversed(db):
    invoice("INV-101", 1000)
    invoice("INV-102", 800)
    reconcile(credit("T1", 1500, "NEFT/Apex/INV-101"), use_llm=False)
    rm.approve_match(case_of("T1")["case_id"])
    held = get_open_credit_for_transaction("T1")
    assert held["remaining"] == 500 and balance("INV-101") == ("settled", 0)
    adj.apply_credit(held["credit_id"], "INV-102", "a", "customer asked")
    assert balance("INV-102") == ("partially_paid", 300)
    assert get_reconciliation_summary()["unapplied_credit"] == 0
    with pytest.raises(rm.ReviewError):
        adj.apply_credit(held["credit_id"], "INV-102", "a", "again")
    balanced()
    rm.reverse_transaction("T1")
    assert balance("INV-101") == ("open", 1000) and balance("INV-102") == ("open", 800)
    assert get_reconciliation_summary()["unapplied_credit"] == 0
    balanced()


def test_credit_stays_with_its_customer(db):
    invoice("INV-101", 1000)
    invoice("INV-900", 800, "Nova Traders")
    reconcile(credit("T1", 1500, "NEFT/Apex/INV-101"), use_llm=False)
    rm.approve_match(case_of("T1")["case_id"])
    with pytest.raises(rm.ReviewError):
        adj.apply_credit(get_open_credit_for_transaction("T1")["credit_id"], "INV-900", "a", "n")


def test_hold_receipt_as_advance(db):
    cid = invoice("INV-101", 1000)
    reconcile(credit("T1", 250, "NEFT/Apex/ADVANCE"), use_llm=False)
    adj.hold_as_credit(case_of("T1")["case_id"], cid, "a", "advance for November")
    assert get_open_credit_for_transaction("T1")["remaining"] == 250
    balanced()
    rm.reverse_transaction("T1")
    assert get_transaction("T1")["status"] == "unmatched"
    balanced()


def test_adjustments(db):
    invoice("INV-101", 1000)
    first = adj.add_adjustment("INV-101", "credit_note", 100, "a", "returned goods", "CN-1")
    adj.add_adjustment("INV-101", "write_off", 900, "a", "uncollectable")
    assert balance("INV-101") == ("settled", 0)
    with pytest.raises(rm.ReviewError):
        adj.add_adjustment("INV-101", "bank_charge", 1, "a", "too much")
    adj.reverse_adjustment(first["adjustment_id"], "a", "wrong")
    assert balance("INV-101") == ("partially_paid", 100)
    balanced()


def _tds_case():
    invoice("INV-101", 1000, taxable_amount=1000)
    reconcile(credit("T1", 900, "NEFT/Apex/INV-101"), use_llm=False)
    rm.approve_match(case_of("T1")["case_id"])
    return get_tds_components()[0]["component_id"]


def test_rejected_tds_is_not_pending_and_cannot_be_verified(db):
    comp = _tds_case()
    rm.reject_tds(comp, notes="no certificate")
    assert get_reconciliation_summary()["tds_pending"] == 0
    with pytest.raises(rm.ReviewError):
        rm.verify_tds(comp, notes="late")
    assert get_settlement_component(comp)["tds_status"] == "rejected"
    balanced()


def test_tds_verification_needs_evidence(db):
    comp = _tds_case()
    with pytest.raises(rm.ReviewError):
        rm.verify_tds(comp)


def test_26as_matching(db):
    from reporting.tds_26as import read_26as, match_26as, apply_26as
    comp = _tds_case()
    rows = read_26as("a.csv", b"Deductor Name,Section,TDS Amount,Transaction Date\n"
                              b"APEX SOLUTIONS PVT LTD,194J,100.00,10/10/2026\nSomeone Else,194J,100,10/10/2026\n")
    assert len(match_26as(rows)["matched"]) == 1
    assert get_settlement_component(comp)["tds_status"] != "verified"       # preview only
    apply_26as(rows, "a")
    assert get_settlement_component(comp)["tds_status"] == "verified"


def test_tds_rates_follow_the_payment_date():
    from decimal import Decimal
    from config.thresholds import tds_rates
    assert tds_rates("194H", "2024-09-30") == (Decimal("0.05"),)
    assert tds_rates("194H", "2024-10-01") == (Decimal("0.02"),)


# ── invoices, uploads, reports ───────────────────────────────────────────────

def test_same_number_for_two_customers_is_kept_and_ambiguous(db):
    from extraction.ingestion import ingest_invoice
    ingest_invoice("a.csv", b"Invoice No,Customer Name,Total\nINV-1,Apex Solutions,1000\n")
    res = ingest_invoice("b.csv", b"Invoice No,Customer Name,Total\nINV-1,Nova Traders,1000\n")
    assert res["invoice_ids"] == ["INV-1~2"]
    out = reconcile(credit("T1", 1000, "NEFT/Nova Traders/INV-1"), use_llm=False)
    assert get_allocations_for_transaction("T1")[0]["invoice_id"] == "INV-1~2", out


def test_zoho_style_register(db):
    from extraction.ingestion import ingest_invoice
    res = ingest_invoice("z.csv", b"Invoice Number,Customer Name,Invoice Date,Total,Balance,Invoice Status\n"
                                  b"INV-1,Apex,2026-10-01,1000,400,PartiallyPaid\nINV-1,Apex,2026-10-01,1000,400,x\n"
                                  b"INV-2,Apex,2026-10-01,500,500,Void\n")
    assert res["invoice_ids"] == ["INV-1"] and balance("INV-1") == ("partially_paid", 400)


def test_failed_upload_can_be_retried(db):
    from extraction.ingestion import ingest_invoice
    bad = b"Inv,Foo\n1,2\n"
    ingest_invoice("b.csv", bad)
    assert not ingest_invoice("b.csv", bad).get("duplicate_file")


def test_excel_export_has_no_formulas(db):
    import openpyxl
    from reporting.report_generator import build_report_workbook
    invoice("INV-101", 1000, '=HYPERLINK("http://x","a")')
    book = openpyxl.load_workbook(io.BytesIO(build_report_workbook()))
    assert not [c for ws in book for row in ws.iter_rows() for c in row if c.data_type == "f"]


def test_assistant_answers_about_the_named_customer(db):
    from reporting.report_generator import answer_finance_query as ask
    invoice("INV-101", 1000)
    invoice("INV-102", 500, "Nova Traders")
    res = ask("how much does Apex Solutions owe?")
    assert res["backend_function"] == "get_customer_invoices" and "INV-102" not in res["answer"]
    assert ask("who has paid invoices?")["backend_function"] == "get_settled_invoices"


def test_reminders_are_drafts_and_flag_held_credit(db):
    from datetime import date
    from reporting.reminders import draft_reminders
    invoice("INV-101", 1000, due_date="2026-10-01")
    drafts = draft_reminders(date(2026, 11, 1))
    assert drafts[0]["total_overdue"] == 1000 and "INV-101" in drafts[0]["body"]


# ── audit, privacy, login, intake, backup, migration ─────────────────────────

def test_audit_log_is_tamper_evident(db):
    from database.db import get_connection
    invoice("INV-101", 1000)
    reconcile(credit("T1", 1000, "NEFT/Apex/INV-101"), use_llm=False)
    assert verify_audit_chain()["ok"]
    conn = get_connection()
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE audit_logs SET actor='x'")
    conn.rollback()
    conn.execute("DROP TRIGGER audit_no_update")
    conn.execute("UPDATE audit_logs SET actor='x' WHERE rowid=1")
    conn.commit()
    assert not verify_audit_chain()["ok"]


def test_sensitive_values_are_masked_and_restored():
    from extraction.privacy import mask_sensitive, unmask
    text = "A/c 50100123456789, PAN ABCDE1234F, mail a@b.com, phone 9876543210, total 1,18,000.00"
    masked, mapping = mask_sensitive(text)
    for secret in ("50100123456789", "ABCDE1234F", "a@b.com", "9876543210"):
        assert secret not in masked
    assert "1,18,000.00" in masked and unmask(masked, mapping) == text


def _basic(name, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{name}:{password}".encode()).decode()}


def test_api_login_roles_and_origin(db, monkeypatch):
    from fastapi.testclient import TestClient
    from api.main import app
    from config import settings
    from security import auth
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    auth.create_user("vi", "viewer-password", "viewer")
    auth.create_user("ra", "reviewer-password", "reviewer")
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/summary").status_code == 401
        assert c.get("/api/summary", headers=_basic("vi", "wrong-password")).status_code == 401
        assert c.get("/api/summary", headers=_basic("vi", "viewer-password")).status_code == 200
        assert c.post("/api/reconcile", headers=_basic("vi", "viewer-password")).status_code == 403
        assert c.post("/api/demo/load", headers=_basic("ra", "reviewer-password")).status_code == 403
        evil = {**_basic("ra", "reviewer-password"), "Origin": "https://evil.example"}
        assert c.post("/api/reconcile", headers=evil).status_code == 403
        invoice("INV-101", 1000)
        reconcile(credit("T1", 400, "NEFT/Apex/INV-101"), use_llm=False)
        r = c.post(f"/api/review/{case_of('T1')['case_id']}/decide", json={"action": "approve"},
                   headers={**_basic("ra", "reviewer-password"), "X-Reviewer": "Somebody Else"})
        assert r.status_code == 200
        assert get_allocations_for_transaction("T1")[0]["approved_by"] == "ra"
        job = c.post("/api/reconcile?background=true", headers=_basic("ra", "reviewer-password")).json()
        status = c.get(f"/api/jobs/{job['batch_id']}", headers=_basic("vi", "viewer-password")).json()
        assert status["status"] == "completed"
        for path in ("/api/credits", "/api/ledger/check", "/api/audit-chain", "/api/reports/reminders"):
            assert c.get(path, headers=_basic("vi", "viewer-password")).status_code == 200, path


def test_repeated_wrong_passwords_lock_the_account(db):
    from security import auth
    auth.create_user("lock", "correct-password", "viewer")
    for _ in range(auth.MAX_FAILURES):
        assert auth.authenticate("lock", "nope") is None
    assert auth.authenticate("lock", "correct-password") is None


def test_mailbox_import_is_read_only_and_repeatable(db):
    from scripts.fetch_remittances import fetch
    message = (b"Subject: advice\nContent-Type: text/plain\n\nWe have paid Rs. 500.00 against INV-1. "
               b"UTR No: HDFCN52026110599999\nApex Solutions")

    class Box:
        def select(self, folder, readonly):
            assert readonly
            return "OK", [b"1"]
        def search(self, *a):
            return "OK", [b"1"]
        def fetch(self, number, what):
            assert "PEEK" in what
            return "OK", [(b"1", message), b")"]
    assert fetch(Box())["imported"] == 1 and fetch(Box())["duplicates"] == 1


def test_backup_is_a_readable_copy(db, tmp_path):
    from scripts.backup_db import backup
    invoice("INV-101", 1000)
    copy = sqlite3.connect(backup(tmp_path / "b"))
    assert copy.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1


def test_upgrade_of_an_existing_database_keeps_balances(tmp_path):
    from database.db import set_database_path, initialise_database, close_connection, get_connection
    from validation.settlement import finalise_settlement
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE invoices (invoice_id TEXT PRIMARY KEY, customer_id TEXT, supplier_name TEXT, customer_name TEXT,
          customer_gstin TEXT, invoice_date TEXT, due_date TEXT, taxable_amount REAL DEFAULT 0,
          gst_amount REAL DEFAULT 0, total_amount REAL, outstanding_amount REAL, currency TEXT DEFAULT 'INR',
          status TEXT, source_document_id TEXT, created_at TEXT DEFAULT '');
        INSERT INTO invoices(invoice_id,total_amount,outstanding_amount,status) VALUES('INV-1',1000,300,'partially_paid');
        CREATE TABLE audit_logs (log_id TEXT PRIMARY KEY, entity_type TEXT, entity_id TEXT, action TEXT,
          actor TEXT, details TEXT, created_at TEXT);
        INSERT INTO audit_logs VALUES('L0','invoice','INV-1','imported','system','{}','2026-01-01');
    """)
    old.commit()
    old.close()
    try:
        set_database_path(path)
        initialise_database()
        initialise_database()                      # idempotent
        assert get_invoice("INV-1")["opening_paid"] == 700
        assert finalise_settlement("INV-1")["outstanding"] == 300
        chain = verify_audit_chain()
        assert chain["ok"] and chain["unprotected"] == 1
    finally:
        close_connection()
        set_database_path(None)
