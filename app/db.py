"""SQLite connection helper."""

import sqlite3
from contextlib import closing

from domain.phone import normalize_phone, phone_for_sql
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "vast.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clinics (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    speciality TEXT NOT NULL,
    address    TEXT NOT NULL,
    city       TEXT NOT NULL,
    state      TEXT NOT NULL,
    zip        TEXT NOT NULL,
    latitude   REAL NOT NULL,
    longitude  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS patients (
    id            INTEGER PRIMARY KEY,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    phone         TEXT,
    date_of_birth TEXT,
    address       TEXT NOT NULL,
    city          TEXT NOT NULL,
    state         TEXT NOT NULL,
    zip           TEXT NOT NULL,
    latitude      REAL NOT NULL,
    longitude     REAL NOT NULL,
    complaints    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    id         INTEGER PRIMARY KEY,
    clinic_id  INTEGER NOT NULL REFERENCES clinics(id),
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    slot_date  TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'booked',
    UNIQUE (clinic_id, slot_date, start_time)
);

CREATE INDEX IF NOT EXISTS idx_bookings_patient ON bookings (patient_id);

CREATE TABLE IF NOT EXISTS patient_phone_issues (
    patient_id     INTEGER PRIMARY KEY REFERENCES patients(id),
    original_phone TEXT NOT NULL,
    reason         TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    """Open a connection to the SQLite database, creating the file if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("canonical_phone", 1, phone_for_sql, deterministic=True)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Initialize schema, preserve foreign keys, then normalize legacy contacts."""
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)
        migrate(conn)
        with conn:
            normalize_patient_phones(conn)


def migrate(conn: sqlite3.Connection) -> None:
    """Relax legacy NOT NULL constraints without renaming the referenced parent.

    Keeping the name `patients` stable for foreign-key declarations avoids
    retargeting bookings to a temporary table. The entire rebuild is atomic.
    """
    columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(patients)")}
    if not any(columns.get(name) and columns[name]["notnull"] for name in ("phone", "date_of_birth")):
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        statement = SCHEMA.split("CREATE TABLE IF NOT EXISTS patients (", 1)[1].split(");", 1)[0]
        conn.execute("CREATE TABLE patients_migration (" + statement + ");")
        names = ", ".join('"' + name.replace('"', '""') + '"' for name in columns)
        conn.execute(f"INSERT INTO patients_migration ({names}) SELECT {names} FROM patients")
        conn.execute("DROP TABLE patients")
        conn.execute("ALTER TABLE patients_migration RENAME TO patients")
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Foreign-key validation failed; schema migration rolled back")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def normalize_patient_phones(conn: sqlite3.Connection) -> int:
    """Normalize valid contacts; quarantine incomplete ones instead of guessing.

    Unusable legacy values are preserved in patient_phone_issues, while the live
    patient.phone becomes NULL. They can never be used for matching or display.
    The existing email is still available for verified contact recovery.
    """
    changed = 0
    for row in conn.execute("SELECT id, phone FROM patients").fetchall():
        if row["phone"] is None:
            continue
        try:
            canonical = normalize_phone(row["phone"])
        except ValueError as error:
            conn.execute(
                "INSERT INTO patient_phone_issues(patient_id, original_phone, reason) VALUES (?, ?, ?)"
                " ON CONFLICT(patient_id) DO UPDATE SET original_phone=excluded.original_phone, reason=excluded.reason",
                (row["id"], row["phone"], str(error)),
            )
            conn.execute("UPDATE patients SET phone = NULL WHERE id = ?", (row["id"],))
            continue
        if canonical != row["phone"]:
            conn.execute("UPDATE patients SET phone = ? WHERE id = ?", (canonical, row["id"]))
            changed += 1
        conn.execute("DELETE FROM patient_phone_issues WHERE patient_id = ?", (row["id"],))
    return changed