"""
ReconcileAI – Application Settings
All configuration is read from environment variables (.env file).
"""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (real environment variables take precedence)
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# ── LLM ──────────────────────────────────────────────────────────────────────
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openrouter").strip().lower()   # openrouter | openai | gemini
_DEFAULT_MODELS = {
    "openrouter": "google/gemini-2.5-flash",
    "openai":     "gpt-4o-mini",
    "gemini":     "gemini-2.5-flash",
}
LLM_MODEL: str = (os.getenv("LLM_MODEL") or os.getenv("OPENROUTER_MODEL")
                  or _DEFAULT_MODELS.get(LLM_PROVIDER, "gpt-4o-mini"))

OPENAI_API_KEY:      str | None = os.getenv("OPENAI_API_KEY") or None
OPENROUTER_API_KEY:  str | None = os.getenv("OPENROUTER_API_KEY") or None
OPENROUTER_BASE_URL: str        = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
GEMINI_API_KEY:      str | None = os.getenv("GEMINI_API_KEY") or None
LLM_TIMEOUT_SECONDS: float      = float(os.getenv("LLM_TIMEOUT_SECONDS", 60))

# Master switch. When off (or no key is configured) every LLM feature falls back
# to deterministic rule-based extraction and template explanations.
APP_ENV:   str = os.getenv("APP_ENV",   "development")
# In production, sending document text to a model provider needs explicit consent.
LLM_DATA_CONSENT: bool = _flag("LLM_DATA_CONSENT", APP_ENV != "production")
LLM_ENABLED: bool = _flag("LLM_ENABLED", True) and LLM_DATA_CONSENT
LLM_MASK_SENSITIVE: bool = _flag("LLM_MASK_SENSITIVE", True)
# Ask the LLM to read bank narrations that carry no invoice reference (one call per such line).
LLM_NARRATION_HINTS: bool = _flag("LLM_NARRATION_HINTS", True)
# Ask the LLM to phrase match explanations (one call per auto-match). Off by default:
# the deterministic explanation is precise and free; turn on for prose.
LLM_MATCH_EXPLANATIONS: bool = _flag("LLM_MATCH_EXPLANATIONS", False)

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_PATH: Path = ROOT_DIR / os.getenv("DATABASE_PATH", "database/reconcile.db")

# ── File upload limits ────────────────────────────────────────────────────────
MAX_FILE_SIZE_BYTES: int = int(os.getenv("MAX_FILE_SIZE_MB", 25)) * 1024 * 1024
ALLOWED_EXTENSIONS = {
    "bank_statement":  {".csv", ".xlsx", ".xls"},
    "invoice":         {".pdf", ".xlsx", ".xls", ".csv"},
    "remittance":      {".eml", ".txt", ".pdf"},
    "tds_certificate": {".pdf", ".png", ".jpg", ".jpeg"},
}

# ── Application ───────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
DEFAULT_REVIEWER: str = os.getenv("DEFAULT_REVIEWER", "Finance Team")

# ── Login ─────────────────────────────────────────────────────────────────────
# Off unless RECONCILE_LOGIN=1 (the public demo has no sign-in). The old RECONCILE_AUTH
# variable is ignored on purpose, so a stale value in a hosting dashboard cannot turn it on.
# Users come from scripts/create_user.py or RECONCILE_ADMIN_USER / RECONCILE_ADMIN_PASSWORD.
AUTH_ENABLED: bool = _flag("RECONCILE_LOGIN", False)
# Self-service sign-up on the website. Off in production unless switched on.
SIGNUP_ENABLED: bool = _flag("RECONCILE_SIGNUP", APP_ENV != "production")
SIGNUP_ROLE: str = os.getenv("RECONCILE_SIGNUP_ROLE", "reviewer").strip().lower()
SESSION_DAYS: int = int(os.getenv("RECONCILE_SESSION_DAYS", 7))
# Shared demo login for product walk-throughs. Setting both shows the credentials on the
# sign-in page and fills an empty database with synthetic data. Never use with real data.
DEMO_USER: str = os.getenv("RECONCILE_DEMO_USER", "").strip().lower()
DEMO_PASSWORD: str = os.getenv("RECONCILE_DEMO_PASSWORD", "")
# Fill an empty database with the synthetic dataset on start-up (for a public demo with
# login off, where the database is wiped on every cold restart). Never use with real data.
# On by default for a production deploy with login off, i.e. the public demo.
DEMO_DATA: bool = _flag("RECONCILE_DEMO_DATA", APP_ENV == "production" and not AUTH_ENABLED)

# ── Directories ───────────────────────────────────────────────────────────────
DATA_RAW_DIR: Path = ROOT_DIR / "data" / "raw"
DATA_SYNTHETIC_DIR: Path = ROOT_DIR / "data" / "synthetic"
DATA_PROCESSED_DIR: Path = ROOT_DIR / "data" / "processed"
UPLOADS_DIR: Path = ROOT_DIR / "data" / "uploads"
