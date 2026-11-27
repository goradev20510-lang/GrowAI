"""
Consistent copy of the live database (safe while the app is running), plus an audit
chain check.  Run:  python -m scripts.backup_db [--dir backups] [--keep 14]
"""
from __future__ import annotations
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def backup(directory: Path, keep: int = 14) -> Path:
    from database.db import get_connection, get_database_path
    source = get_database_path()
    if not source.exists():
        raise FileNotFoundError(f"No database at {source}")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"reconcile-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    copy = sqlite3.connect(target)
    try:
        get_connection().backup(copy)
        if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"Backup {target} failed its integrity check")
    finally:
        copy.close()
    for old in sorted(directory.glob("reconcile-*.db"))[:-max(keep, 1)]:
        old.unlink()
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", type=Path, default=Path("backups"))
    ap.add_argument("--keep", type=int, default=14)
    args = ap.parse_args()
    path = backup(args.dir, args.keep)
    from database.repositories import verify_audit_chain
    from database.db import initialise_database
    initialise_database()
    chain = verify_audit_chain()
    print(f"Saved {path}\nAudit chain: {chain}")
    return 0 if chain["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
