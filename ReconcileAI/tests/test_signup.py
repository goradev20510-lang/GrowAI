"""Website sign-up, sign-in, sessions and the shared demo account."""
import pytest
from fastapi.testclient import TestClient

from config import settings

PASSWORD = "a-long-password"


@pytest.fixture()
def client(db, monkeypatch):
    for key, value in (("AUTH_ENABLED", True), ("SIGNUP_ENABLED", True), ("SIGNUP_ROLE", "reviewer"),
                       ("SESSION_DAYS", 7), ("DEMO_USER", ""), ("DEMO_PASSWORD", "")):
        monkeypatch.setattr(settings, key, value)
    monkeypatch.delenv("CLERK_PUBLISHABLE_KEY", raising=False)
    from api.main import app
    with TestClient(app) as c:
        yield c


def _sign(c, kind, username, password=PASSWORD):
    return c.post(f"/api/auth/{kind}", json={"username": username, "password": password})


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_signup_signin_signout(client):
    assert client.get("/api/summary").status_code == 401
    made = _sign(client, "signup", "Asha@Example.com")
    assert made.status_code == 200
    assert made.json()["user"] == {"username": "asha@example.com", "role": "reviewer"}
    token = _sign(client, "signin", "ASHA@example.com").json()["token"]
    assert client.get("/api/summary", headers=_bearer(token)).status_code == 200
    assert client.post("/api/demo/load", headers=_bearer(token)).status_code == 403
    client.post("/api/auth/signout", headers=_bearer(token))
    refused = client.get("/api/summary", headers=_bearer(token))
    assert refused.status_code == 401 and refused.headers["www-authenticate"] == "Bearer"


def test_signup_never_overwrites_an_account(client):
    _sign(client, "signup", "asha@example.com")
    assert _sign(client, "signup", "asha@example.com", "another-password").status_code == 409
    assert _sign(client, "signin", "asha@example.com").status_code == 200
    assert _sign(client, "signin", "asha@example.com", "another-password").status_code == 401


@pytest.mark.parametrize("username,password", [("not-an-email", PASSWORD), ("a@b.co", "short"),
                                               ("a@b.co", "x" * 129)])
def test_signup_validation(client, username, password):
    assert _sign(client, "signup", username, password).status_code == 400


def test_signup_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(settings, "SIGNUP_ENABLED", False)
    assert _sign(client, "signup", "asha@example.com").status_code == 403


def test_signup_cannot_grant_admin(client, monkeypatch):
    monkeypatch.setattr(settings, "SIGNUP_ROLE", "admin")
    assert _sign(client, "signup", "asha@example.com").json()["user"]["role"] == "viewer"


def test_expired_session_is_refused(client, monkeypatch):
    monkeypatch.setattr(settings, "SESSION_DAYS", -1)
    token = _sign(client, "signup", "asha@example.com").json()["token"]
    assert client.get("/api/summary", headers=_bearer(token)).status_code == 401


def test_foreign_origin_cannot_sign_in(client):
    res = client.post("/api/auth/signin", json={"username": "a@b.co", "password": PASSWORD},
                      headers={"Origin": "https://evil.example"})
    assert res.status_code == 403


def test_demo_account_has_data(db, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "DEMO_USER", "demo@reconcileai.example")
    monkeypatch.setattr(settings, "DEMO_PASSWORD", PASSWORD)
    monkeypatch.delenv("CLERK_PUBLISHABLE_KEY", raising=False)
    from api.main import app
    with TestClient(app) as c:
        assert c.get("/api/auth/session").json()["demo"]["username"] == "demo@reconcileai.example"
        token = _sign(c, "signin", "demo@reconcileai.example").json()["token"]
        summary = c.get("/api/summary", headers=_bearer(token)).json()
    assert summary["invoices_total"] > 0 and summary["matched"] > 0 and summary["review_queue"] > 0
