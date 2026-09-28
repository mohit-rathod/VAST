"""Refactor-only tests: application services work without a database or HTTP."""
from contextlib import contextmanager
from datetime import date
import sqlite3

import pytest
from domain.errors import AgentRuntimeFailure, AgentValueFailure, SlotTaken, StorageConflict
from domain.models import Location, PatientIntake
from repositories import connection
from repositories.patients import SQLitePatientRepository
from services.availability import AvailabilityService
from services.booking import BookingService
from services.chat import ChatService
from services.clinics import ClinicService
from services.patients import PatientService, reason_for

DAY = date(2026, 9, 30)
BUSY = ('booked', 'confirmed')


class MemoryBookingRepository:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def reserve(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return 42


def test_booking_service_uses_injected_repository_and_grid():
    repository = MemoryBookingRepository()
    service = BookingService(repository, lambda day: [('09:00', '09:30')])
    result = service.book(1, 2, DAY, '09:00', 'booked', BUSY)
    assert result['ok'] and result['booking_id'] == 42
    assert repository.calls == [(1, 2, DAY, '09:00', '09:30', 'booked', BUSY)]


def test_invalid_slot_never_calls_repository():
    repository = MemoryBookingRepository()
    service = BookingService(repository, lambda day: [('09:00', '09:30')])
    assert not service.book(1, 2, DAY, '09:15', 'booked', BUSY)['ok']
    assert repository.calls == []


@pytest.mark.parametrize('error,expected', [
    (SlotTaken(), 'clinic 1 is already booked on 2026-09-30 at 09:00'),
    (StorageConflict('constraint'), 'constraint'),
])
def test_booking_conflicts_are_values(error, expected):
    service = BookingService(MemoryBookingRepository(error), lambda day: [('09:00', '09:30')])
    assert service.book(1, 2, DAY, '09:00', 'booked', BUSY) == dict(ok=False, error=expected, taken=True)


def test_unexpected_storage_errors_propagate():
    service = BookingService(MemoryBookingRepository(RuntimeError('offline')), lambda day: [('09:00', '09:30')])
    with pytest.raises(RuntimeError, match='offline'):
        service.book(1, 2, DAY, '09:00', 'booked', BUSY)


def test_availability_with_read_only_repository():
    class Available:
        def taken_times(self, clinic_id, days, statuses):
            assert (clinic_id, days, statuses) == (1, [DAY], BUSY)
            return {DAY.isoformat(): {'09:00'}}
    service = AvailabilityService(Available(), lambda day: [('09:00', '09:30'), ('09:30', '10:00')])
    assert service.available(1, [DAY], BUSY) == [dict(clinic_id=1, date=str(DAY), start_time='09:30', end_time='10:00')]


class MemoryPatients:
    def __init__(self, error=None):
        self.rows = {}
        self.error = error
        self.events = []

    @contextmanager
    def session(self):
        self.events.append('open')
        try:
            yield self
        finally:
            self.events.append('close')

    def find(self, email, phone):
        return next((row for row in self.rows.values() if row['email'] == email and row['phone'] == phone), None)

    def read(self, patient_id):
        self.events.append('read')
        return self.rows.get(patient_id, {}).copy()

    def location(self, patient_id):
        row = self.rows.get(patient_id)
        return {key: row[key] for key in ('address', 'city', 'state', 'zip')} if row else None

    def insert(self, values):
        self.events.append('insert')
        if self.error:
            raise self.error
        self.rows[1] = {'id': 1, **values}
        return 1

    def update(self, patient_id, values):
        if self.error:
            raise self.error
        if patient_id in self.rows:
            self.rows[patient_id].update(values)


def patient_inputs():
    return (
        PatientIntake(first_name='Test', last_name='Patient', email='test@example.test', phone='2125550100'),
        Location(address='Test Street', city='New York', state='NY', zip='10001'),
    )


def test_patient_service_closes_write_before_rereading():
    repository = MemoryPatients()
    service = PatientService(repository.session, lambda zip_code: (1.0, 2.0))
    assert service.register(*patient_inputs())['patient']['latitude'] == 1.0
    assert repository.events == ['open', 'insert', 'close', 'open', 'read', 'close']
    assert service.find('test@example.test', '2125550100')['id'] == 1


def test_patient_service_update_without_database():
    repository = MemoryPatients()
    service = PatientService(repository.session, lambda zip_code: (1.0, 2.0))
    service.register(*patient_inputs())
    assert service.update(1, {'first_name': 'Changed'})['patient']['first_name'] == 'Changed'
    assert service.update(1, {'address': 'Other Street'})['patient']['address'] == 'Other Street'
    assert service.update(1, {'first_name': None})['patient']['first_name'] == 'Changed'


def test_patient_service_translates_conflict():
    repository = MemoryPatients(StorageConflict('UNIQUE constraint failed: patients.email'))
    service = PatientService(repository.session, lambda zip_code: (1.0, 2.0))
    result = service.register(*patient_inputs())
    assert result == dict(ok=False, error='that email is already registered to a different phone number')


@pytest.mark.parametrize('error,expected', [
    ('FOREIGN KEY constraint failed', 'that clinic or patient is not on file'),
    ('email conflict', 'that email is already registered to a different phone number'),
    ('other constraint', 'other constraint'),
])
def test_backend_neutral_patient_error_messages(error, expected):
    assert reason_for(StorageConflict(error)) == expected


def test_clinic_service_without_sql():
    patient = dict(latitude=0.0, longitude=0.0)
    clinics = [
        dict(id=1, name='Far', speciality='ENT', address='A', city='City', state='NY', zip='10001', latitude=2.0, longitude=0.0),
        dict(id=2, name='Near', speciality='ENT', address='B', city='City', state='NY', zip='10001', latitude=1.0, longitude=0.0),
    ]
    class Clinics:
        def patient(self, patient_id): return patient
        def candidates(self, patient_id, speciality): return patient, clinics
    service = ClinicService(
        Clinics(), lambda clinic, day: [dict(start_time='09:00', end_time='09:30')],
        lambda zip_code: 'Test/Zone', lambda lat1, lon1, lat2, lon2: lat2,
    )
    rows = service.nearest(1, None)
    assert [row['clinic_id'] for row in rows] == [2, 1]
    assert rows[0]['zone'] == 'Test/Zone'
    found, candidates = service.candidates(1, DAY, 1)
    assert found == patient and candidates[0]['free_slots'] == ['09:00-09:30']


class MemoryAgent:
    step = 'details'
    booking = None
    on_event = None

    def start(self): return 'Welcome'

    def handle(self, message):
        if self.on_event:
            self.on_event({'kind': 'step', 'title': message})
        return f'Reply: {message}'


class MemorySessions:
    def __init__(self):
        self.agents = {}
        self.counter = 0

    def new_session(self, on_event=None):
        self.counter += 1
        key = str(self.counter)
        agent = MemoryAgent()
        agent.on_event = on_event
        self.agents[key] = agent
        return key, agent

    def get_session(self, key): return self.agents.get(key)
    def drop_session(self, key): self.agents.pop(key, None)


def test_chat_service_and_per_turn_events_without_http():
    store = MemorySessions()
    service = ChatService(store)
    first = service.turn(None, 'one')
    second = service.turn(first['session_id'], 'two')
    assert first['events'] == [{'kind': 'step', 'title': 'one'}]
    assert second['events'] == [{'kind': 'step', 'title': 'two'}]
    assert second['reply'] == 'Reply: two' and not second['done']
    fresh = service.reset(first['session_id'])
    assert fresh == {'session_id': '2', 'reply': 'Welcome'}
    assert '1' not in store.agents


@pytest.mark.parametrize('error,expected', [(RuntimeError('failure'), AgentRuntimeFailure), (ValueError('bad'), AgentValueFailure)])
def test_chat_service_wraps_only_agent_failures(error, expected):
    store = MemorySessions()
    key, agent = store.new_session()
    def fail(_): raise error
    agent.handle = fail
    with pytest.raises(expected, match=str(error)):
        ChatService(store).turn(key, 'hello')


def test_chat_service_does_not_wrap_session_failures():
    store = MemorySessions()
    def fail(*args, **kwargs): raise RuntimeError('session failed')
    store.new_session = fail
    with pytest.raises(RuntimeError, match='session failed'):
        ChatService(store).turn(None, 'hello')


@pytest.mark.parametrize('fail', [False, True])
def test_connection_closes_on_success_and_failure(fail):
    conn = sqlite3.connect(':memory:')
    def use():
        with connection(lambda: conn) as current:
            assert current is conn
            if fail:
                raise ValueError('abort')
    if fail:
        with pytest.raises(ValueError, match='abort'): use()
    else:
        use()
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        conn.execute('SELECT 1')


def test_repository_only_translates_integrity_error():
    class Broken:
        def __init__(self, error): self.error = error
        def execute(self, *args): raise self.error
    with pytest.raises(StorageConflict, match='constraint'):
        SQLitePatientRepository(Broken(sqlite3.IntegrityError('constraint'))).update(1, {'phone':'2125550100'})
    with pytest.raises(sqlite3.OperationalError, match='disk'):
        SQLitePatientRepository(Broken(sqlite3.OperationalError('disk'))).update(1, {'phone':'2125550100'})