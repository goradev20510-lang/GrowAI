"""
Import payment advices from a mailbox over IMAP (SSL). Read-only: messages are not
marked read, moved or deleted. Re-running is safe (identical messages are skipped).

Set IMAP_HOST, IMAP_USER, IMAP_PASSWORD (an app password) and optionally
IMAP_FOLDER (default INBOX).  Run:  python -m scripts.fetch_remittances --days 7
"""
from __future__ import annotations
import argparse
import imaplib
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def fetch(mailbox, days: int = 7, folder: str = "INBOX", limit: int = 200) -> dict:
    """`mailbox` is a logged-in imaplib connection."""
    from extraction.ingestion import ingest_remittance
    status, _ = mailbox.select(folder, readonly=True)
    if status != "OK":
        raise RuntimeError(f"Cannot open folder {folder}")
    since = date.today() - timedelta(days=days)
    _, data = mailbox.search(None, "SINCE", f"{since.day:02d}-{_MONTHS[since.month - 1]}-{since.year}")
    stats = {"seen": 0, "imported": 0, "duplicates": 0, "ignored": 0}
    for number in data[0].split()[-limit:]:
        _, parts = mailbox.fetch(number, "(BODY.PEEK[])")
        raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
        if not raw:
            continue
        stats["seen"] += 1
        try:
            result = ingest_remittance(f"mail-{number.decode()}.eml", raw)
        except Exception as e:                       # one bad message must not stop the run
            print(f"message {number.decode()}: {e}")
            result = {"success": False}
        key = "imported" if result.get("success") else "duplicates" if result.get("duplicate_file") else "ignored"
        stats[key] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    from database.db import initialise_database
    missing = [v for v in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD") if not os.getenv(v)]
    if missing:
        print(f"Set {', '.join(missing)}")
        return 1
    initialise_database()
    with imaplib.IMAP4_SSL(os.environ["IMAP_HOST"], timeout=30) as box:
        box.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
        print(fetch(box, args.days, os.getenv("IMAP_FOLDER", "INBOX")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
