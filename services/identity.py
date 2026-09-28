"""Identify candidates without disclosing an unverified patient's record."""
from dataclasses import dataclass
from typing import Literal
from domain.phone import normalize_phone
from domain.ports import PatientSession


@dataclass(frozen=True)
class IdentityResult:
    status: Literal["exact", "mismatch", "ambiguous", "missing"]
    patient_id: int | None = None


class IdentityService:
    def __init__(self, session: PatientSession) -> None:
        self.session = session

    def identify(self, email: str, phone: str) -> IdentityResult:
        email, phone = email.strip(), normalize_phone(phone)
        with self.session() as repo:
            candidates = repo.identity_candidates(email, phone)
        exact = [r for r in candidates if r["email"] == email and r["phone"] == phone]
        if len(exact) == 1:
            return IdentityResult("exact", exact[0]["id"])
        if len(candidates) == 1:
            return IdentityResult("mismatch", candidates[0]["id"])
        return IdentityResult("ambiguous" if candidates else "missing")

    def recovery_candidate(self, email: str) -> int | None:
        with self.session() as repo:
            row = repo.by_email(email)
        return row["id"] if row else None