"""The HTTP API the React frontend uses: every endpoint answers against the demo dataset."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(db):
    from api.main import app
    return TestClient(app)


def test_demo_reconcile_summary_flow(client):
    assert client.post("/api/demo/load").status_code == 200
    stats = client.post("/api/reconcile").json()
    assert stats["total"] > 0
    s = client.get("/api/summary").json()
    assert s["matched"] + s["needs_review"] + s["unmatched"] + s["duplicates"] <= s["total_transactions"]
    assert s["review_queue"] == len(client.get("/api/review").json())


def test_read_endpoints(client):
    client.post("/api/demo/load")
    client.post("/api/reconcile")
    for path in ["/api/meta", "/api/transactions", "/api/invoices", "/api/invoices/open?credit=1000",
                 "/api/review/resolved", "/api/documents", "/api/reports/aging", "/api/reports/customers",
                 "/api/reports/tds", "/api/audit?limit=20"]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.text)
    tid = client.get("/api/transactions").json()[0]["transaction_id"]
    assert client.get(f"/api/transactions/{tid}").json()["transaction"]["transaction_id"] == tid
    r = client.get("/api/reports/export.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_review_decision_needs_reviewer_and_records_it(client):
    client.post("/api/demo/load")
    client.post("/api/reconcile")
    queue = client.get("/api/review").json()
    case = next(c for c in queue if c["exception_type"] != "possible_duplicate")
    detail = client.get(f"/api/review/{case['case_id']}").json()
    assert detail["transaction"]["transaction_id"] == case["transaction_id"]

    no_name = client.post(f"/api/review/{case['case_id']}/decide", json={"action": "reject", "notes": "x"})
    assert no_name.status_code == 400
    no_note = client.post(f"/api/review/{case['case_id']}/decide", json={"action": "reject"},
                          headers={"X-Reviewer": "Asha"})
    assert no_note.status_code == 400

    action = "reject" if detail["proposed"] else "dismiss"
    ok = client.post(f"/api/review/{case['case_id']}/decide", json={"action": action, "notes": "test"},
                     headers={"X-Reviewer": "Asha"})
    assert ok.status_code == 200, ok.text
    again = client.post(f"/api/review/{case['case_id']}/decide", json={"action": action, "notes": "test"},
                        headers={"X-Reviewer": "Asha"})
    assert again.status_code == 409


def test_ask(client):
    client.post("/api/demo/load")
    client.post("/api/reconcile")
    r = client.post("/api/ask", json={"query": "Which credits are still unmatched?"}).json()
    assert r["answer"]
