"""
Users, passwords and roles. Passwords are stored as salted PBKDF2 hashes.
Roles: viewer (read) < reviewer (decide, import) < admin (users, demo data).
"""
from __future__ import annotations
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time

from config import settings
from database.db import get_connection, commit
from database.repositories import create_audit_log

ROLES = ("viewer", "reviewer", "admin")
_ITERATIONS = 600_000
MIN_PASSWORD = 10
MAX_PASSWORD = 128
_EMAIL = re.compile(r"^[^@\s:]+@[^@\s:]+\.[^@\s:]+$")
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
    get_connection().execute("DELETE FROM sessions WHERE username=?", (username,))
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


# ── website sign-up and sessions ─────────────────────────────────────────────

class UsernameTaken(ValueError):
    pass


def normalise_username(username: str) -> str:
    """Email addresses are case-insensitive; other usernames are kept as typed."""
    name = (username or "").strip()
    return name.lower() if "@" in name else name


def register(email: str, password: str) -> dict:
    """Self-service sign-up. Unlike create_user, never overwrites an existing account."""
    name = normalise_username(email)
    if len(name) > 254 or not _EMAIL.match(name):
        raise ValueError("Enter a valid email address")
    if not MIN_PASSWORD <= len(password or "") <= MAX_PASSWORD:
        raise ValueError(f"Password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters")
    role = settings.SIGNUP_ROLE if settings.SIGNUP_ROLE in ("viewer", "reviewer") else "viewer"
    try:
        get_connection().execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                                 (name, _hash(password), role))
    except sqlite3.IntegrityError:
        get_connection().rollback()
        raise UsernameTaken("An account with this email already exists. Sign in instead.")
    commit()
    create_audit_log("user", name, "user_registered", actor=name, details={"role": role})
    return {"username": name, "role": role}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(username: str) -> str:
    token, now = secrets.token_urlsafe(32), int(time.time())
    conn = get_connection()
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    conn.execute("INSERT INTO sessions(token_hash,username,expires_at) VALUES(?,?,?)",
                 (_token_hash(token), username, now + settings.SESSION_DAYS * 86_400))
    commit()
    return token


def session_user(token: str) -> dict | None:
    if not token:
        return None
    row = get_connection().execute(
        """SELECT u.username, u.role FROM sessions s JOIN users u ON u.username = s.username
           WHERE s.token_hash=? AND s.expires_at > ?""", (_token_hash(token), int(time.time()))).fetchone()
    return {"username": row["username"], "role": row["role"]} if row else None


def end_session(token: str) -> None:
    get_connection().execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
    commit()


def ensure_demo_account() -> bool:
    """Create the shared demo login if configured. Reviewer role: it cannot manage users."""
    name, password = settings.DEMO_USER, settings.DEMO_PASSWORD
    if not (name and password):
        return False
    row = get_connection().execute("SELECT * FROM users WHERE username=?", (name,)).fetchone()
    current = row and row["role"] == "reviewer" and hmac.compare_digest(
        _hash(password, bytes.fromhex(row["password_hash"].split("$")[0])), row["password_hash"])
    if not current:
        create_user(name, password, "reviewer")
    return True
