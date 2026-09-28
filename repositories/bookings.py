"""Booking SQL, including the original atomic reservation boundary."""

import sqlite3
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta

from domain.errors import SlotTaken, StorageConflict
from repositories import ConnectionFactory, connection


class SQLiteAvailabilityRepository:
    def __init__(self, connect: ConnectionFactory) -> None:
        self.connect = connect

    def clinic_zip(self, clinic_id: int) -> str | None:
        with connection(self.connect) as conn:
            row = conn.execute("SELECT zip FROM clinics WHERE id = ?", (clinic_id,)).fetchone()
        return row[0] if row else None

    def taken_times(
        self, clinic_id: int, days: list[date], busy_statuses: tuple[str, ...]
    ) -> dict[str, set[str]]:
        marks = ", ".join("?" for _ in busy_statuses)
        taken = {}
        with connection(self.connect) as conn:
            for day in days:
                occupied = set()
                rows = conn.execute(
                    "SELECT start_time, end_time FROM bookings WHERE clinic_id = ?"
                    f" AND slot_date = ? AND status IN ({marks})",
                    (clinic_id, day.isoformat(), *busy_statuses),
                )
                for start, end in rows:
                    # Mark any grid cell intersected by an existing interval.
                    for minute in range(0, 24 * 60, 30):
                        cell_start = f"{minute // 60:02d}:{minute % 60:02d}"
                        cell_end = f"{(minute + 30) // 60:02d}:{(minute + 30) % 60:02d}"
                        if cell_start < end and cell_end > start:
                            occupied.add(cell_start)
                taken[day.isoformat()] = occupied
        return taken


class SQLiteBookingRepository:
    def __init__(self, connect: ConnectionFactory, lock: AbstractContextManager) -> None:
        self.connect = connect
        self.lock = lock

    @staticmethod
    def is_taken(
        conn: sqlite3.Connection, clinic_id: int, day: date,
        start_time: str, busy_statuses: tuple[str, ...], end_time: str | None = None,
    ) -> bool:
        marks = ", ".join("?" * len(busy_statuses))
        if end_time is None:
            end_time = (datetime.fromisoformat(f"{day}T{start_time}") + timedelta(minutes=30)).strftime("%H:%M")
        return conn.execute(
            "SELECT 1 FROM bookings"
            " WHERE clinic_id = ? AND slot_date = ? AND start_time < ? AND end_time > ?"
            f" AND status IN ({marks})",
            (clinic_id, day.isoformat(), end_time, start_time, *busy_statuses),
        ).fetchone() is not None

    def reserve(
        self, clinic_id: int, patient_id: int, day: date, start_time: str,
        end_time: str, status: str, busy_statuses: tuple[str, ...],
    ) -> int:
        with self.lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                if self.is_taken(conn, clinic_id, day, start_time, busy_statuses, end_time):
                    conn.rollback()
                    raise SlotTaken
                cursor = conn.execute(
                    "INSERT INTO bookings"
                    " (clinic_id, patient_id, slot_date, start_time, end_time, status)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (clinic_id, patient_id, day.isoformat(), start_time, end_time, status),
                )
                conn.commit()
                return cursor.lastrowid
            except sqlite3.IntegrityError as error:
                conn.rollback()
                raise StorageConflict(str(error)) from error
            finally:
                conn.close()