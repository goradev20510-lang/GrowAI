"""Create or update a login.  Run:  python -m scripts.create_user NAME --role reviewer"""
from __future__ import annotations
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("username")
    ap.add_argument("--role", default="reviewer", choices=["viewer", "reviewer", "admin"])
    args = ap.parse_args()
    from database.db import initialise_database
    from security.auth import create_user
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match")
        return 1
    initialise_database()
    try:
        create_user(args.username, password, args.role)
    except ValueError as e:
        print(e)
        return 1
    print(f"Saved {args.username} ({args.role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
