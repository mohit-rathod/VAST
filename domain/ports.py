"""Small structural interfaces consumed by application services.

Adapters need not inherit these protocols. Tests can supply ordinary objects
that implement only the operations the service needs.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Protocol

Record = dict
EventHandler = Callable[[dict], None]
Coordinates = Callable[[str], tuple[float, float] | None]
SlotGrid = Callable[[date], list[tuple[str, str]]]


class PatientRepository(Protocol):
    def find(self, email: str, phone: str) -> Record | None: ...
    def read(self, patient_id: int) -> Record: ...
    def identity_candidates(self, email: str, phone: str) -> list[Record]: ...
    def by_email(self, email: str) -> Record | None: ...
    def replace_contacts(self, patient_id: int, email: str, phone: str,
                         expected: tuple[str, str | None]) -> bool: ...
    def location(self, patient_id: int) -> Record | None: ...
    def insert(self, values: Record) -> int: ...
    def update(self, patient_id: int, values: Record) -> None: ...


PatientSession = Callable[[], AbstractContextManager[PatientRepository]]


class ClinicRepository(Protocol):
    def patient(self, patient_id: int) -> Record | None: ...
    def candidates(
        self, patient_id: int, speciality: str | None
    ) -> tuple[Record, list[Record]]: ...


class AvailabilityRepository(Protocol):
    def taken_times(
        self, clinic_id: int, days: list[date], busy_statuses: tuple[str, ...]
    ) -> dict[str, set[str]]: ...


class BookingRepository(Protocol):
    def reserve(
        self,
        clinic_id: int,
        patient_id: int,
        day: date,
        start_time: str,
        end_time: str,
        status: str,
        busy_statuses: tuple[str, ...],
    ) -> int: ...


class ChatAgent(Protocol):
    on_event: EventHandler | None

    @property
    def step(self) -> str: ...
    @property
    def booking(self) -> Record | None: ...
    def start(self) -> str: ...
    def handle(self, message: str) -> str: ...


class SessionStore(Protocol):
    def new_session(
        self, on_event: EventHandler | None = None
    ) -> tuple[str, ChatAgent]: ...
    def get_session(self, session_id: str) -> ChatAgent | None: ...
    def drop_session(self, session_id: str) -> None: ...


class HistoryRepository(Protocol):
    def for_patient(self, patient_id: int) -> list[Record]: ...
    def clinics(self) -> list[Record]: ...