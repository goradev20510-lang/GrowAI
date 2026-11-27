"""
Users, passwords and roles. Passwords are stored as salted PBKDF2 hashes.
Roles: viewer (read) < reviewer (decide, import) < admin (users, demo data).
"""
from __future__ import annotations
import hashlib
import hmac
import os
import secrets
import threading
import time

from database.db import get_connection, commit
from database.repositories import create_audit_log

ROLES = ("viewer", "reviewer", "admin")
_ITERATIONS = 600_000
MIN_PASSWORD = 10
MAX_FAILURES, LOCK_SECONDS = 5, 300

_failures: dict[str, list[float]] = {}
_verified: dict[str, str] = {}          # avoids re-running PBKDF2 on every request
_lock = threading.Lock()
_CACHE_KEY = secrets.token_bytes(32)


def _hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def create_user(username: str, password: str, role: str = "viewer", actor: str = "system") -> None:
    username = (username or "").strip()
    if not username or ":" in username:
        raise ValueError("Username must be non-empty and must not contain ':'")
    if role not in ROLES:
        raise ValueError(f"Role must be one of {', '.join(ROLES)}")
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters")
    get_connection().execute(
        """INSERT INTO users(username,password_hash,role) VALUES(?,?,?)
           ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash, role=excluded.role""",
        (username, _hash(password), role))
    commit()
    _verified.pop(username, None)
    create_audit_log("user", username, "user_saved", actor=actor, details={"role": role})


def bootstrap_admin() -> None:
    """Create the first admin from the environment, if there are no users yet."""
    name, password = os.getenv("RECONCILE_ADMIN_USER"), os.getenv("RECONCILE_ADMIN_PASSWORD")
    if name and password and not get_connection().execute("SELECT 1 FROM users LIMIT 1").fetchone():
        create_user(name, password, "admin")


def authenticate(username: str, password: str) -> dict | None:
    """{"username", "role"} for a correct password; None otherwise or while locked out."""
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(username, []) if now - t < LOCK_SECONDS]
        _failures[username] = recent
        if len(recent) >= MAX_FAILURES:
            return None
    row = get_connection().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    ok = False
    if row:
        fingerprint = hmac.new(_CACHE_KEY, f"{row['password_hash']}:{password}".encode(), "sha256").hexdigest()
        if hmac.compare_digest(_verified.get(username, ""), fingerprint):
            ok = True
        else:
            salt = bytes.fromhex(row["password_hash"].split("$")[0])
            ok = hmac.compare_digest(_hash(password, salt), row["password_hash"])
            if ok:
                _verified[username] = fingerprint
    else:
        _hash(password)                      # same work for unknown users
    if not ok:
        with _lock:
            _failures.setdefault(username, []).append(now)
        return None
    return {"username": row["username"], "role": row["role"]}


def has_role(user: dict, needed: str) -> bool:
    return ROLES.index(user["role"]) >= ROLES.index(needed)
