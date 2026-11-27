"""Outgoing payments: bank debits linked to vendor bills by a named person."""
import pytest
from fastapi.testclient import TestClient

from api.main import app

WHO = {"X-Reviewer": "Test Reviewer"}


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        assert c.post("/api/demo/load").status_code == 200
        yield c


def _debit(client, text):
    return next(t for t in client.get("/api/statement").json() if t["direction"] == "out" and text in t["narration"])


def _bill(client, number):
    return next(b for b in client.get("/api/vendor-bills").json() if b["bill_number"] == number)


def _link(client, debit, bill, headers=WHO):
    return client.post(f"/api/debits/{debit['transaction_id']}/link", json={"bill_id": bill["bill_id"]},
                       headers=headers)


def test_nothing_is_linked_until_a_person_confirms(client):
    s = client.get("/api/summary").json()
    assert (s["vendor_bills"], s["vendor_paid"], s["debit_unlinked_count"]) == (5, 0, 5)
    debit = _debit(client, "APX-1042")
    suggestion = client.get(f"/api/debits/{debit['transaction_id']}").json()["suggestions"][0]
    assert suggestion["bill_number"] == "APX-1042" and len(suggestion["reasons"]) == 3


def test_link_part_pay_and_undo(client):
    debit, bill = _debit(client, "BLL-337"), _bill(client, "BLL-337")
    assert _link(client, debit, bill, headers={}).status_code == 400          # a name is required
    linked = _link(client, debit, bill).json()
    assert linked["amount"] == 60000
    after = _bill(client, "BLL-337")
    assert (after["status"], after["pending"]) == ("part_paid", 66000)
    assert _link(client, debit, bill).status_code == 409                      # debit already used up

    url = f"/api/payments/{linked['payment_id']}/unlink"
    assert client.post(url, json={"notes": ""}, headers=WHO).status_code == 400
    assert client.post(url, json={"notes": "wrong bill"}, headers=WHO).status_code == 200
    assert _bill(client, "BLL-337")["status"] == "unpaid"
    assert client.get("/api/audit-chain").json()["ok"]


def test_a_debit_never_overpays_a_bill(client):
    big, small = _debit(client, "NIMBUS"), _bill(client, "KPW-88")
    assert _link(client, big, small).json()["amount"] == 32500
    assert _debit(client, "NIMBUS")["unlinked"] == 51500
    assert _link(client, _debit(client, "UPI DR"), small).status_code == 409  # bill already paid


def test_non_vendor_debit_and_receivables_untouched(client):
    before = client.get("/api/summary").json()
    charge = _debit(client, "BANK CHARGES")
    url = f"/api/debits/{charge['transaction_id']}/not-vendor"
    assert client.post(url, json={"notes": "monthly charge"}, headers=WHO).status_code == 200
    after = client.get("/api/summary").json()
    assert _debit(client, "BANK CHARGES")["status"] == "not_vendor"
    assert after["debit_unlinked_count"] == 4
    for key in ("amount_received", "total_transactions", "outstanding_value"):
        assert after[key] == before[key]


def test_bill_register_import_and_on_file(client):
    csv = b"Vendor,Bill No,Amount\nTest Vendor,TV-1,\"1,500\"\n,TV-2,10\n"
    r = client.post("/api/import/vendor_bill", files={"file": ("bills.csv", csv)}).json()
    assert r["bills_imported"] == 1 and len(r["rejected_rows"]) == 1
    bill = _bill(client, "TV-1")
    assert bill["amount"] == 1500 and not bill["bill_on_file"]
    client.post(f"/api/vendor-bills/{bill['bill_id']}/on-file", json={"on_file": True}, headers=WHO)
    assert _bill(client, "TV-1")["bill_on_file"]
