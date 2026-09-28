"""Report format/repair counts without changing a database or printing contacts.

Usage: python -m scripts.audit_phones [--database path/to/vast.db]
Startup applies the migration. This command is a read-only preflight.
"""
import argparse
import json
from pathlib import Path
import sqlite3
from app import config  # Load .env for command-line use.
from app.db import DB_PATH
from domain.phone import normalize_phone


def audit(path: Path) -> dict:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    result = {"patients": 0, "canonical": 0, "normalizable": 0, "needs_update": 0, "repair_patient_ids": []}
    try:
        for patient_id, phone in conn.execute("SELECT id, phone FROM patients ORDER BY id"):
            result["patients"] += 1
            try:
                canonical = normalize_phone(phone)
            except ValueError:
                result["needs_update"] += 1
                result["repair_patient_ids"].append(patient_id)
                continue
            result["canonical" if canonical == phone else "normalizable"] += 1
    finally:
        conn.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DB_PATH)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("The database file does not exist")
    print(json.dumps(audit(args.database), indent=2))


if __name__ == "__main__":
    main()