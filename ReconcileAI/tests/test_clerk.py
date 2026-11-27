"""Clerk session tokens on the API, checked with a locally generated key (no network)."""
import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from security import clerk

ISSUER = "https://example.clerk.accounts.dev"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def client(db, monkeypatch):
    pk = "pk_test_" + base64.b64encode(b"example.clerk.accounts.dev$").decode()
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", pk)
    monkeypatch.delenv("CLERK_DEFAULT_ROLE", raising=False)
    monkeypatch.delenv("CLERK_ADMIN_IDS", raising=False)
    monkeypatch.setattr(clerk, "_signing_key", lambda token: KEY.public_key())
    from api.main import app
    return TestClient(app)


def bearer(key=KEY, **claims):
    body = {"sub": "user_1", "iss": ISSUER, "exp": int(time.time()) + 60,
            "azp": "http://localhost:3000", **claims}
    return {"Authorization": "Bearer " + jwt.encode(body, key, algorithm="RS256")}


def test_requires_a_valid_token(client):
    assert client.get("/api/summary").status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/summary", headers=bearer()).status_code == 200
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for bad in (bearer(key=other), bearer(exp=int(time.time()) - 60),
                bearer(iss="https://evil.example"), bearer(azp="https://evil.example")):
        assert client.get("/api/summary", headers=bad).status_code == 401


def test_roles(client, monkeypatch):
    assert client.post("/api/demo/load", headers=bearer()).status_code == 403
    monkeypatch.setenv("CLERK_ADMIN_IDS", "user_1")
    assert client.post("/api/demo/load", headers=bearer()).status_code == 200
