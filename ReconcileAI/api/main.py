"""
ReconcileAI – HTTP API for the React frontend.

A thin layer: every endpoint calls a function the Streamlit app already uses.
No money logic lives here. Run with:  uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import base64
import binascii
import json
import math
import os
import sys
import threading
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402
from config.thresholds import TDS_SECTION_RATES  # noqa: E402
from database.db import initialise_database  # noqa: E402
from database.repositories import (  # noqa: E402
    get_all_documents, get_all_invoices, get_all_review_cases, get_all_transactions,
    get_allocations_for_transaction, get_audit_actions, get_audit_logs, get_invoice,
    get_open_review_cases, get_reconciliation_summary, get_remittance_by_utr,
    get_settlement_components, get_tds_components, get_transaction,
)
from decision import adjustments as adj  # noqa: E402
from decision import review_manager as rm  # noqa: E402
from decision import vendor_payments as vp  # noqa: E402
from database import repositories as repo  # noqa: E402
from security import auth, clerk  # noqa: E402

@asynccontextmanager
async def _lifespan(_app):
    initialise_database()
    auth.bootstrap_admin()
    if auth.ensure_demo_account():
        from data.demo_seed import seed_if_empty
        seed_if_empty()
    yield


app = FastAPI(title="ReconcileAI API", version="1.0", lifespan=_lifespan)
ORIGINS = [o.strip() for o in
           os.getenv("RECONCILE_CORS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]


# Reachable without signing in. Each handler checks what it needs itself.
PUBLIC_PATHS = {"/api/health", "/api/auth/session", "/api/auth/signin", "/api/auth/signup", "/api/auth/signout"}


def _required_role(method: str, path: str) -> str:
    if path.startswith(("/api/users", "/api/demo")):
        return "admin"
    if method in ("GET", "HEAD") or path == "/api/ask":
        return "viewer"
    return "reviewer"


@app.middleware("http")
async def _guard_requests(request: Request, call_next):
    """Login (Clerk when configured, else HTTP Basic) and cross-site request protection."""
    method, path = request.method, request.url.path
    if method == "OPTIONS":
        return await call_next(request)
    origin = request.headers.get("origin")
    if method not in ("GET", "HEAD") and origin and origin not in ORIGINS:
        return JSONResponse({"detail": "Requests from this origin are not allowed."}, status_code=403)
    if path in PUBLIC_PATHS:
        return await call_next(request)
    if settings.AUTH_ENABLED or clerk.enabled():
        user = None
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if clerk.enabled():
            if scheme.lower() == "bearer":
                user = await run_in_threadpool(clerk.authenticate, token, ORIGINS)
        elif scheme.lower() == "bearer":
            user = await run_in_threadpool(auth.session_user, token)
        elif scheme.lower() == "basic":
            try:
                name, _, password = base64.b64decode(token).decode("utf-8").partition(":")
                user = auth.authenticate(name, password)
            except (binascii.Error, UnicodeDecodeError, ValueError):
                user = None
        if not user:
            # A Basic challenge would make browsers pop a dialog over the website's own sign-in.
            challenge = "Bearer" if clerk.enabled() or scheme.lower() == "bearer" else 'Basic realm="ReconcileAI"'
            return JSONResponse({"detail": "Sign in to continue."}, status_code=401,
                                headers={"WWW-Authenticate": challenge})
        if not auth.has_role(user, _required_role(method, path)):
            return JSONResponse({"detail": "Your role does not allow this."}, status_code=403)
        request.state.user = user["username"]
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"],
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _clean(v: Any) -> Any:
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (pd.Timestamp, date)):
        return v.isoformat()
    if hasattr(v, "item"):  # numpy scalar
        return _clean(v.item())
    return v


def records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return [{str(k): _clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


def _reviewer(request: Request, x_reviewer: str | None) -> str:
    """The signed-in user when login is on; otherwise the name the client sends."""
    user = getattr(request.state, "user", None)
    name = (x_reviewer or "").strip()
    if user and clerk.enabled():
        # The id is verified; the typed name only makes the audit trail readable.
        return f"{name} [{user}]" if name else user
    who = user or name
    if not who:
        raise HTTPException(400, "Enter your name as reviewer first. Every decision is recorded against it.")
    return who


def _need_note(note: str) -> str:
    note = (note or "").strip()
    if not note:
        raise HTTPException(400, "Add a note for the audit trail first. It's required for this decision.")
    return note


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except rm.ReviewError as e:
        raise HTTPException(409, str(e))


def review_queue(cases: list[dict]) -> list[dict]:
    """One entry per credit: newest open case, older ones under `stale` (mirrors app.py)."""
    by_txn: dict[str, list[dict]] = {}
    for c in cases:
        by_txn.setdefault(c["transaction_id"], []).append(c)
    out = []
    for group in by_txn.values():
        group.sort(key=lambda c: c.get("created_at") or "")
        out.append({**group[-1], "stale": [c["case_id"] for c in group[:-1]]})
    return out


def allocation_rows(allocs: list[dict]) -> list[dict]:
    rows = []
    for a in allocs:
        comps = get_settlement_components(a["allocation_id"])
        tds = [c for c in comps if c["component_type"] == "tds"]
        rows.append({
            "allocation_id": a["allocation_id"],
            "invoice_id": a["invoice_id"],
            "bank_credit": sum(float(c["amount"]) for c in comps if c["component_type"] == "bank_credit"),
            "tds": sum(float(c["amount"]) for c in tds),
            "tds_section": ", ".join(sorted({c["tds_section"] for c in tds if c.get("tds_section")})) or None,
            "applied": float(a["allocated_amount"] or 0),
            "score": float(a.get("confidence_score") or 0),
            "status": a.get("allocation_status"),
            "decided_by": a.get("approved_by"),
            "decision_reason": a.get("decision_reason"),
        })
    return rows


def _remittance(utr: str | None) -> dict | None:
    rem = get_remittance_by_utr(utr) if utr else None
    if not rem:
        return None
    return {**rem,
            "invoice_references": sorted(set(json.loads(rem.get("invoice_references") or "[]"))),
            "evidence_text": json.loads(rem.get("evidence_text") or "[]")}


# ── website sign-in ─────────────────────────────────────────────────────────

class CredentialsBody(BaseModel):
    username: str
    password: str


def _local_auth_only() -> None:
    if clerk.enabled():
        raise HTTPException(404, "Sign-in is handled by Clerk.")


def _bearer(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    return token if scheme.lower() == "bearer" else ""


def _signed_in(user: dict) -> dict:
    return {"token": auth.start_session(user["username"]), "user": user}


@app.get("/api/auth/session")
def auth_session(authorization: str | None = Header(None)) -> dict:
    _local_auth_only()
    demo = bool(settings.DEMO_USER and settings.DEMO_PASSWORD)
    return {"auth_required": settings.AUTH_ENABLED,
            "signup_enabled": settings.SIGNUP_ENABLED,
            "demo": {"username": settings.DEMO_USER, "password": settings.DEMO_PASSWORD} if demo else None,
            "user": auth.session_user(_bearer(authorization))}


@app.post("/api/auth/signup")
def auth_signup(body: CredentialsBody) -> dict:
    _local_auth_only()
    if not settings.SIGNUP_ENABLED:
        raise HTTPException(403, "Sign-up is switched off. Ask an administrator for an account.")
    try:
        return _signed_in(auth.register(body.username, body.password))
    except auth.UsernameTaken as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/auth/signin")
def auth_signin(body: CredentialsBody) -> dict:
    _local_auth_only()
    user = None
    if len(body.password) <= auth.MAX_PASSWORD:
        user = auth.authenticate(auth.normalise_username(body.username), body.password)
    if not user:
        raise HTTPException(401, "Wrong email or password, or too many attempts. Try again in a few minutes.")
    return _signed_in(user)


@app.post("/api/auth/signout")
def auth_signout(authorization: str | None = Header(None)) -> dict:
    _local_auth_only()
    token = _bearer(authorization)
    if token:
        auth.end_session(token)
    return {"signed_out": True}


# ── overview ────────────────────────────────────────────────────────────────

@app.get("/api/summary")
def summary() -> dict:
    s = get_reconciliation_summary()
    txns = get_all_transactions()
    s["amount_duplicate"] = round(sum(float(t["credit_amount"] or 0) for t in txns if t["status"] == "duplicate"), 2)
    s["review_queue"] = len(review_queue(get_open_review_cases()))
    s.update(vp.payables_summary())
    return s


@app.get("/api/meta")
def meta() -> dict:
    return {"tds_sections": {k: v for k, v in TDS_SECTION_RATES.items() if k != "DEFAULT"},
            "audit_actions": get_audit_actions()}


# ── bank credits ────────────────────────────────────────────────────────────

@app.get("/api/transactions")
def transactions() -> list[dict]:
    rows = get_all_transactions()
    rows.sort(key=lambda t: (t.get("transaction_date") or "", t["transaction_id"]), reverse=True)
    return rows


@app.get("/api/transactions/{tid}")
def transaction_detail(tid: str) -> dict:
    txn = get_transaction(tid)
    if not txn:
        raise HTTPException(404, f"No bank credit {tid}")
    return {"transaction": txn, "allocations": allocation_rows(get_allocations_for_transaction(tid))}


@app.post("/api/transactions/{tid}/reconcile")
def transaction_reconcile(tid: str) -> dict:
    from decision.decision_engine import reconcile_transaction
    return reconcile_transaction(tid)


class NoteBody(BaseModel):
    notes: str = ""


@app.post("/api/transactions/{tid}/reverse")
def transaction_reverse(tid: str, body: NoteBody, request: Request,
                        x_reviewer: str | None = Header(None)) -> dict:
    return _guard(rm.reverse_transaction, tid, reviewer=_reviewer(request, x_reviewer),
                  notes=_need_note(body.notes))


# ── statement and outgoing payments ─────────────────────────────────────────

@app.get("/api/statement")
def statement() -> list[dict]:
    return vp.statement()


@app.get("/api/vendor-bills")
def vendor_bills() -> list[dict]:
    return vp.list_bills()


@app.get("/api/debits/{tid}")
def debit_detail(tid: str) -> dict:
    return _guard(vp.debit_detail, tid)


class LinkBody(BaseModel):
    bill_id: str
    notes: str = ""


class OnFileBody(BaseModel):
    on_file: bool


@app.post("/api/debits/{tid}/link")
def debit_link(tid: str, body: LinkBody, request: Request, x_reviewer: str | None = Header(None)) -> dict:
    return _guard(vp.link_payment, tid, body.bill_id, reviewer=_reviewer(request, x_reviewer), notes=body.notes)


@app.post("/api/debits/{tid}/not-vendor")
def debit_not_vendor(tid: str, body: NoteBody, request: Request, x_reviewer: str | None = Header(None)) -> dict:
    return _guard(vp.mark_not_vendor, tid, reviewer=_reviewer(request, x_reviewer), notes=_need_note(body.notes))


@app.post("/api/payments/{payment_id}/unlink")
def payment_unlink(payment_id: str, body: NoteBody, request: Request,
                   x_reviewer: str | None = Header(None)) -> dict:
    return _guard(vp.unlink_payment, payment_id, reviewer=_reviewer(request, x_reviewer),
                  notes=_need_note(body.notes))


@app.post("/api/vendor-bills/{bill_id}/on-file")
def bill_on_file(bill_id: str, body: OnFileBody, request: Request, x_reviewer: str | None = Header(None)) -> dict:
    return _guard(vp.set_bill_on_file, bill_id, body.on_file, reviewer=_reviewer(request, x_reviewer))


# ── invoices ────────────────────────────────────────────────────────────────

@app.get("/api/invoices")
def invoices() -> list[dict]:
    return get_all_invoices()


@app.get("/api/invoices/open")
def open_invoices(credit: float = 0.0) -> list[dict]:
    """Open invoices, closest outstanding balance to the credit first (mirrors app.py)."""
    rows = [i for i in get_all_invoices() if i["status"] in ("open", "partially_paid")]
    rows.sort(key=lambda i: abs(float(i["outstanding_amount"] or 0) - credit))
    return rows


# ── review ──────────────────────────────────────────────────────────────────

@app.get("/api/review")
def review_list() -> list[dict]:
    txns = {t["transaction_id"]: t for t in get_all_transactions()}
    queue = review_queue(get_open_review_cases())
    for c in queue:
        c["amount"] = float((txns.get(c["transaction_id"]) or {}).get("credit_amount") or 0)
    queue.sort(key=lambda c: -c["amount"])
    return queue


@app.get("/api/review/resolved")
def review_resolved() -> list[dict]:
    done = [c for c in get_all_review_cases() if c["status"] != "open"]
    done.sort(key=lambda c: c.get("reviewed_at") or "", reverse=True)
    return done


@app.get("/api/review/{case_id}")
def review_detail(case_id: str) -> dict:
    case = next((c for c in get_all_review_cases() if c["case_id"] == case_id), None)
    if not case:
        raise HTTPException(404, f"No review case {case_id}")
    txn = get_transaction(case["transaction_id"])
    proposed = [a for a in get_allocations_for_transaction(case["transaction_id"])
                if a["allocation_status"] == "proposed"]
    inv = get_invoice(case["invoice_id"]) if case.get("invoice_id") else None
    return {"case": case, "transaction": txn, "invoice": inv or None,
            "proposed": allocation_rows(proposed), "remittance": _remittance(txn.get("utr"))}


class DecisionBody(BaseModel):
    action: str                       # approve | reject | dismiss | dup_confirm | dup_release | assign
    notes: str = ""
    invoice_ids: list[str] = []
    tds_amount: float = 0.0
    tds_section: str | None = None


@app.post("/api/review/{case_id}/decide")
def review_decide(case_id: str, body: DecisionBody, request: Request,
                  x_reviewer: str | None = Header(None)) -> dict:
    who = _reviewer(request, x_reviewer)
    a = body.action
    if a not in ("approve", "dup_confirm"):
        _need_note(body.notes)
    if a == "approve":
        return _guard(rm.approve_match, case_id, reviewer=who, notes=body.notes)
    if a == "reject":
        return _guard(rm.reject_match, case_id, reviewer=who, notes=body.notes)
    if a == "dismiss":
        return _guard(rm.dismiss_transaction, case_id, reviewer=who, notes=body.notes)
    if a == "dup_confirm":
        return _guard(rm.confirm_duplicate, case_id, reviewer=who, notes=body.notes)
    if a == "dup_release":
        return _guard(rm.release_duplicate, case_id, reviewer=who, notes=body.notes)
    if a == "assign":
        if not body.invoice_ids:
            raise HTTPException(400, "Pick at least one invoice.")
        if body.tds_amount > 0 and not body.tds_section:
            raise HTTPException(400, "Pick the TDS section the customer deducted under.")
        case = next((c for c in get_all_review_cases() if c["case_id"] == case_id), None)
        if not case:
            raise HTTPException(404, f"No review case {case_id}")
        tid = case["transaction_id"]
        return _guard(rm.correct_match, case_id, tid, body.invoice_ids, reviewer=who, notes=body.notes,
                      tds_amount=body.tds_amount,
                      tds_section=body.tds_section if body.tds_amount > 0 else None)
    raise HTTPException(400, f"Unknown action {a}")


# ── batch / demo ────────────────────────────────────────────────────────────

@app.post("/api/demo/load")
def demo_load() -> dict:
    from extraction.ingestion import load_synthetic_dataset
    from extraction.vendor_bills import load_sample
    return {**load_synthetic_dataset(), "vendor": load_sample()}


_batch_lock = threading.Lock()


def _run_batch(batch_id: str) -> None:
    from decision.decision_engine import run_batch_reconciliation
    try:
        run_batch_reconciliation(batch_id)
    finally:
        _batch_lock.release()


@app.post("/api/reconcile")
def reconcile_all(tasks: BackgroundTasks, background: bool = False) -> dict:
    """Run now, or with ?background=true return a job to poll at /api/jobs/{batch_id}."""
    if not _batch_lock.acquire(blocking=False):
        raise HTTPException(409, "A reconciliation run is already in progress.")
    from decision.decision_engine import run_batch_reconciliation
    if background:
        try:
            batch_id = repo.create_batch()
        except Exception:
            _batch_lock.release()
            raise
        tasks.add_task(_run_batch, batch_id)
        return {"batch_id": batch_id, "status": "running"}
    try:
        return run_batch_reconciliation()
    finally:
        _batch_lock.release()


@app.get("/api/jobs/{batch_id}")
def job_status(batch_id: str) -> dict:
    batch = repo.get_batch(batch_id)
    if not batch:
        raise HTTPException(404, f"No run {batch_id}")
    return batch


# ── import ──────────────────────────────────────────────────────────────────

async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read(settings.MAX_FILE_SIZE_BYTES + 1)       # never read an unbounded upload
    if len(content) > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(413, f"File exceeds {settings.MAX_FILE_SIZE_BYTES // 1024 // 1024} MB.")
    return content


@app.post("/api/import/{kind}")
async def import_file(kind: str, file: UploadFile | None = File(None), bank_name: str = Form("AXIS Bank"),
                      text: str = Form("")) -> dict:
    from extraction.ingestion import ingest_bank_statement, ingest_invoice, ingest_remittance
    if file is not None:
        name, content = file.filename or "upload", await _read_upload(file)
    elif kind == "remittance" and text.strip():
        name, content = "pasted_email.txt", text.encode("utf-8")
    else:
        raise HTTPException(400, "Choose a file to import.")
    if kind == "vendor_bill":
        from extraction.vendor_bills import ingest_vendor_bills
        return ingest_vendor_bills(name, content)
    if kind == "bank":
        return ingest_bank_statement(name, content, bank_name=bank_name)
    if kind == "invoice":
        return ingest_invoice(name, content)
    if kind == "remittance":
        return ingest_remittance(name, content)
    raise HTTPException(404, f"Unknown import type {kind}")


@app.get("/api/documents")
def documents() -> list[dict]:
    rows = get_all_documents()
    rows.sort(key=lambda d: d.get("upload_time") or "", reverse=True)
    return rows


# ── reports ─────────────────────────────────────────────────────────────────

@app.get("/api/reports/aging")
def reports_aging() -> dict:
    from reporting.report_generator import AGING_BUCKETS, aging_report, aging_summary
    today = date.today()
    detail = aging_report(today)
    buckets = []
    if not detail.empty:
        g = detail.groupby("bucket")["outstanding_amount"].agg(["count", "sum"]).reindex(AGING_BUCKETS, fill_value=0)
        buckets = [{"bucket": b, "invoices": int(r["count"]), "outstanding": float(r["sum"])} for b, r in g.iterrows()]
    return {"as_of": today.isoformat(), "buckets": buckets,
            "by_customer": records(aging_summary(today)), "detail": records(detail)}


@app.get("/api/reports/customers")
def reports_customers() -> list[dict]:
    from reporting.report_generator import customer_balances
    return records(customer_balances())


@app.get("/api/reports/tds")
def reports_tds() -> list[dict]:
    return get_tds_components()


@app.post("/api/tds/{component_id}/verify")
async def tds_verify(component_id: str, request: Request, notes: str = Form(""),
                     certificate: UploadFile | None = File(None), x_reviewer: str | None = Header(None)) -> dict:
    who = _reviewer(request, x_reviewer)
    doc_id = None
    if certificate is not None:
        from extraction.ingestion import store_supporting_document
        stored = store_supporting_document(certificate.filename or "form16a", await _read_upload(certificate))
        if not stored.get("success"):
            raise HTTPException(400, stored.get("reason", "Could not store the certificate."))
        doc_id = stored["document_id"]
    return _guard(rm.verify_tds, component_id, reviewer=who, certificate_document_id=doc_id, notes=notes)


@app.post("/api/tds/{component_id}/reject")
def tds_reject(component_id: str, body: NoteBody, request: Request,
               x_reviewer: str | None = Header(None)) -> dict:
    return _guard(rm.reject_tds, component_id, reviewer=_reviewer(request, x_reviewer),
                  notes=_need_note(body.notes))


@app.post("/api/reports/draft-summary")
def reports_draft_summary() -> dict:
    s = get_reconciliation_summary()
    try:
        from extraction.llm_extractor import generate_reconciliation_report_summary
        return {"text": generate_reconciliation_report_summary(s), "used_llm": True}
    except Exception as e:  # model not configured / unavailable
        total = s["total_transactions"] or 1
        return {"used_llm": False, "error": str(e),
                "text": (f"{s['total_transactions']} credits processed, {s['matched']} matched "
                         f"({s['matched'] / total:.0%}), {s['needs_review']} awaiting review and "
                         f"{s['unmatched']} unmatched.")}


@app.get("/api/reports/export.xlsx")
def reports_export() -> Response:
    from reporting.report_generator import build_report_workbook
    name = f"reconciliation_{date.today():%Y-%m-%d}.xlsx"
    return Response(build_report_workbook(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ── audit / ask ─────────────────────────────────────────────────────────────

@app.get("/api/audit")
def audit(q: str | None = None, entity: str | None = None, action: str | None = None, limit: int = 500) -> list[dict]:
    rows = get_audit_logs(search=q or None, entity_type=entity or None, action=action or None, limit=limit)
    for r in rows:
        try:
            r["details"] = json.loads(r["details"]) if r.get("details") else {}
        except (ValueError, TypeError):
            pass
    return rows


class AskBody(BaseModel):
    query: str


@app.post("/api/ask")
def ask(body: AskBody) -> dict:
    from reporting.report_generator import answer_finance_query
    res = answer_finance_query(body.query)
    raw = res.get("raw_data")
    if isinstance(raw, pd.DataFrame):
        raw = records(raw)
    return {"answer": res.get("answer"), "used_llm": bool(res.get("used_llm")),
            "source": res.get("backend_function"), "rows": raw}


# ── ledger: credits, adjustments, invoice checks ─────────────────────────────

class AdjustmentBody(BaseModel):
    kind: str                         # credit_note | write_off | bank_charge
    amount: float
    notes: str = ""
    reference: str | None = None


class HoldBody(BaseModel):
    customer_id: str
    notes: str = ""


class ApplyBody(BaseModel):
    invoice_id: str
    notes: str = ""
    amount: float | None = None


@app.get("/api/health")
def health() -> dict:
    repo.get_reconciliation_summary()
    return {"status": "ok"}


@app.get("/api/customers")
def customers() -> list[dict]:
    return repo.get_all_customers()


@app.get("/api/credits")
def credits_list() -> list[dict]:
    return repo.get_credits()


@app.post("/api/credits/{credit_id}/apply")
def credit_apply(credit_id: str, body: ApplyBody, request: Request, x_reviewer: str | None = Header(None)) -> dict:
    return _guard(adj.apply_credit, credit_id, body.invoice_id, reviewer=_reviewer(request, x_reviewer),
                  notes=_need_note(body.notes), amount=body.amount)


@app.post("/api/review/{case_id}/hold")
def review_hold(case_id: str, body: HoldBody, request: Request, x_reviewer: str | None = Header(None)) -> dict:
    return _guard(adj.hold_as_credit, case_id, body.customer_id, reviewer=_reviewer(request, x_reviewer),
                  notes=_need_note(body.notes))


@app.get("/api/invoices/{invoice_id:path}/adjustments")
def adjustments_list(invoice_id: str) -> list[dict]:
    return repo.get_adjustments(invoice_id, active_only=False)


@app.post("/api/invoices/{invoice_id:path}/adjustments")
def adjustments_add(invoice_id: str, body: AdjustmentBody, request: Request,
                    x_reviewer: str | None = Header(None)) -> dict:
    return _guard(adj.add_adjustment, invoice_id, body.kind, body.amount, reviewer=_reviewer(request, x_reviewer),
                  notes=_need_note(body.notes), reference=body.reference)


@app.post("/api/adjustments/{adjustment_id}/reverse")
def adjustment_reverse(adjustment_id: str, body: NoteBody, request: Request,
                       x_reviewer: str | None = Header(None)) -> dict:
    return _guard(adj.reverse_adjustment, adjustment_id, reviewer=_reviewer(request, x_reviewer),
                  notes=_need_note(body.notes))


@app.post("/api/invoices/{invoice_id:path}/confirm")
def invoice_confirm(invoice_id: str, body: NoteBody, request: Request,
                    x_reviewer: str | None = Header(None)) -> dict:
    return _guard(rm.confirm_invoice, invoice_id, reviewer=_reviewer(request, x_reviewer), notes=body.notes)


@app.get("/api/ledger/check")
def ledger_check() -> dict:
    from reporting.ledger import check_ledger
    return check_ledger()


@app.get("/api/audit-chain")
def audit_chain() -> dict:
    return repo.verify_audit_chain()


@app.get("/api/reports/reminders")
def reminders(min_days: int = 1) -> list[dict]:
    from reporting.reminders import draft_reminders
    return draft_reminders(min_days_overdue=min_days)


@app.post("/api/tds/26as")
async def tds_26as(request: Request, file: UploadFile = File(...), apply: bool = Form(False),
                   x_reviewer: str | None = Header(None)) -> dict:
    """Preview matches against a 26AS register; apply=true marks the unambiguous ones verified."""
    from reporting.tds_26as import read_26as, match_26as, apply_26as
    try:
        rows = read_26as(file.filename or "26as.csv", await _read_upload(file))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if apply:
        return _guard(apply_26as, rows, _reviewer(request, x_reviewer))
    return match_26as(rows)


class UserBody(BaseModel):
    username: str
    password: str
    role: str = "viewer"


@app.post("/api/users")
def users_save(body: UserBody, request: Request) -> dict:
    try:
        auth.create_user(body.username, body.password, body.role,
                         actor=getattr(request.state, "user", "system"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"saved": body.username, "role": body.role}
