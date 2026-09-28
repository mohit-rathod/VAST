"""Read the records required for clinic matching without applying ranking rules."""

from repositories import ConnectionFactory, connection
from domain.phone import phone_for_sql


class SQLiteClinicRepository:
    def __init__(self, connect: ConnectionFactory) -> None:
        self.connect = connect

    def patient(self, patient_id: int) -> dict | None:
        with connection(self.connect) as conn:
            row = conn.execute(
                "SELECT * FROM patients WHERE id = ?", (patient_id,)
            ).fetchone()
        return {**dict(row), "phone": phone_for_sql(row["phone"])} if row else None

    def candidates(
        self, patient_id: int, speciality: str | None
    ) -> tuple[dict, list[dict]]:
        query = "SELECT * FROM clinics"
        parameters: tuple = ()
        if speciality:
            query += " WHERE speciality = ?"
            parameters = (speciality,)
        with connection(self.connect) as conn:
            patient = conn.execute(
                "SELECT * FROM patients WHERE id = ?", (patient_id,)
            ).fetchone()
            if patient is None:
                raise ValueError(f"no patient {patient_id}")
            clinics = conn.execute(query, parameters).fetchall()
        return {**dict(patient), "phone": phone_for_sql(patient["phone"])}, [dict(clinic) for clinic in clinics]