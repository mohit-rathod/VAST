"""Patient SQL only; registration and address rules belong to the service."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from domain.errors import StorageConflict
from domain.phone import normalize_phone, phone_for_sql
from repositories import ConnectionFactory, connection

COLUMNS = (
    "first_name", "last_name", "email", "phone", "date_of_birth",
    "address", "city", "state", "zip", "latitude", "longitude", "complaints",
)


class SQLitePatientRepository:
    """One patient repository bound to a caller-owned transaction."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        if isinstance(conn, sqlite3.Connection):
            conn.create_function("canonical_phone", 1, phone_for_sql, deterministic=True)

    def find(self, email: str, phone: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM patients WHERE email = ? AND canonical_phone(phone) = ?", (email.strip(), normalize_phone(phone))
        ).fetchone()
        return self._record(row) if row else None

    def read(self, patient_id: int) -> dict:
        row = self.conn.execute(
            "SELECT * FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        return self._record(row) if row else {}

    @staticmethod
    def _record(row) -> dict:
        result = dict(row)
        if "phone" in result:
            result["phone"] = phone_for_sql(result["phone"])
            result["phone_needs_update"] = result["phone"] is None
        return result

    def identity_candidates(self, email: str, phone: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, email, phone FROM patients WHERE email = ? OR canonical_phone(phone) = ?",
            (email.strip(), normalize_phone(phone)),
        ).fetchall()
        return [self._record(row) for row in rows]

    def by_email(self, email: str) -> dict | None:
        row = self.conn.execute("SELECT id FROM patients WHERE email = ?", (email.strip(),)).fetchone()
        return dict(row) if row else None

    def replace_contacts(self, patient_id: int, email: str, phone: str,
                         expected: tuple[str, str | None]) -> bool:
        try:
            cursor = self.conn.execute(
                "UPDATE patients SET email = ?, phone = ? WHERE id = ?"
                " AND email = ? AND canonical_phone(phone) IS ?",
                (email, normalize_phone(phone), patient_id, *expected),
            )
            if cursor.rowcount == 1:
                self.conn.execute("DELETE FROM patient_phone_issues WHERE patient_id = ?", (patient_id,))
                return True
            return False
        except sqlite3.IntegrityError as error:
            raise StorageConflict(str(error)) from error

    def location(self, patient_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT address, city, state, zip FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        return self._record(row) if row else None

    def insert(self, values: dict) -> int:
        values = {**values, "phone": normalize_phone(values["phone"])}
        names = ", ".join(COLUMNS)
        marks = ", ".join("?" * len(COLUMNS))
        try:
            cursor = self.conn.execute(
                f"INSERT INTO patients ({names}) VALUES ({marks})",
                [values[column] for column in COLUMNS],
            )
        except sqlite3.IntegrityError as error:
            raise StorageConflict(str(error)) from error
        return cursor.lastrowid

    def update(self, patient_id: int, values: dict) -> None:
        if not values or not set(values).issubset(COLUMNS):
            raise ValueError("Unknown or empty patient fields")
        values = dict(values)
        if "phone" in values:
            values["phone"] = normalize_phone(values["phone"])
        sets = ", ".join(f"{name} = ?" for name in values)
        try:
            self.conn.execute(
                f"UPDATE patients SET {sets} WHERE id = ?",
                [*values.values(), patient_id],
            )
            if "phone" in values:
                self.conn.execute("DELETE FROM patient_phone_issues WHERE patient_id = ?", (patient_id,))
        except sqlite3.IntegrityError as error:
            raise StorageConflict(str(error)) from error


@contextmanager
def patient_session(factory: ConnectionFactory) -> Iterator[SQLitePatientRepository]:
    """Keep reads and a write in the same transaction and close it afterward."""
    with connection(factory) as conn:
        yield SQLitePatientRepository(conn)