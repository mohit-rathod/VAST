"""SQLite connection helper."""

import sqlite3
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
    phone         TEXT NOT NULL,
    date_of_birth TEXT NOT NULL,
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
"""


def connect() -> sqlite3.Connection:
    """Open a connection to the SQLite database, creating the file if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create the database file and tables."""
    with connect() as conn:
        conn.executescript(SCHEMA)
