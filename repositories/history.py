"""Read a single patient's bookings across every clinic, without status limits."""
from repositories import ConnectionFactory, connection


class SQLiteHistoryRepository:
    def __init__(self, connect: ConnectionFactory) -> None:
        self.connect = connect

    def for_patient(self, patient_id: int) -> list[dict]:
        with connection(self.connect) as conn:
            rows = conn.execute(
                "SELECT b.id AS booking_id, b.clinic_id, b.patient_id, b.slot_date,"
                " b.start_time, b.end_time, b.status, c.name AS clinic_name,"
                " c.speciality, c.address, c.city, c.state, c.zip"
                " FROM bookings b JOIN clinics c ON c.id = b.clinic_id"
                " WHERE b.patient_id = ? ORDER BY c.name, b.slot_date DESC, b.start_time DESC, b.id DESC",
                (patient_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clinics(self) -> list[dict]:
        with connection(self.connect) as conn:
            rows = conn.execute("SELECT id AS clinic_id, name, speciality, address, city, state, zip FROM clinics ORDER BY name, id").fetchall()
        return [dict(row) for row in rows]