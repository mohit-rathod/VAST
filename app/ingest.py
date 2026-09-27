"""Load the CSV files in data/ into SQLite.

Every row is validated with the matching domain model before it is inserted.

Usage: python -m app.ingest
"""

import csv
from pathlib import Path

from pydantic import BaseModel, ValidationError

from domain.models import Booking, Clinic, Patient

from .db import connect, init_db

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# csv file, table, model, csv column -> column
SOURCES = [
    (
        "clinics",
        "clinics",
        Clinic,
        {
            "clinic_id": "id",
            "name": "name",
            "speciality": "speciality",
            "address": "address",
            "city": "city",
            "state": "state",
            "zip": "zip",
            "latitude": "latitude",
            "longitude": "longitude",
        },
    ),
    (
        "patients",
        "patients",
        Patient,
        {
            "patient_id": "id",
            "first_name": "first_name",
            "last_name": "last_name",
            "email": "email",
            "phone": "phone",
            "date_of_birth": "date_of_birth",
            "address": "address",
            "city": "city",
            "state": "state",
            "zip": "zip",
            "latitude": "latitude",
            "longitude": "longitude",
            "complaints": "complaints",
        },
    ),
    (
        "bookings",
        "bookings",
        Booking,
        {
            "booking_id": "id",
            "clinic_id": "clinic_id",
            "patient_id": "patient_id",
            "slot_date": "slot_date",
            "start_time": "start_time",
            "end_time": "end_time",
            "status": "status",
        },
    ),
]


def load(conn, table: str, columns: dict, model: type[BaseModel], path: Path) -> int:
    """Validate then insert every row of a CSV file. Re-running replaces existing rows."""
    names = ", ".join(columns.values())
    marks = ", ".join("?" * len(columns))
    count = 0
    with path.open(newline="") as file:
        for line, raw in enumerate(csv.DictReader(file), start=2):
            try:
                row = model.model_validate(raw).model_dump(mode="json")
            except ValidationError as error:
                raise SystemExit(f"{path.name} line {line}: {error}")
            conn.execute(
                f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({marks})",
                [row[column] for column in columns],
            )
            count += 1
    return count


def main() -> None:
    init_db()
    with connect() as conn:
        for filename, table, model, columns in SOURCES:
            count = load(conn, table, columns, model, DATA_DIR / f"{filename}.csv")
            print(f"{filename}.csv -> {table}: {count} rows")


if __name__ == "__main__":
    main()
