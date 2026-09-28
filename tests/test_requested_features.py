"""Acceptance/regression coverage for the six requested behavior changes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from threading import Barrier
from zoneinfo import ZoneInfo
import json
import sqlite3

import pytest
from app import db
from agents.nextdim.agent import NextDimAgent
from agents.nextdim.conversation import (BOOK, CLINIC, COMPLAINT, CONTACT_CONFIRM,
                                        DETAILS, DONE, END_CONFIRM, MENU, RECOVERY,
                                        RECOVERY_ID, REGISTRY, SLOTS, VERIFY)
from domain.models import PatientIntake, PatientUpdate, Complaint
from domain.phone import PhoneNumberError, normalize_phone
from services.date_resolver import DateResolver, resolve_time
from services.duration import appointment_duration
from services.verification import VerificationService, VerificationUnavailable
from tools import available_slots as calendar
from tools.book import book_appointment
from tools.history import patient_bookings, all_clinics
from tools.patients import identify_patient, find_patient, read, update_patient
from tools.rank_slots import rank_slots
from helpers import INTAKE, COMPLAINT as PROBLEM, MemorySender, ScriptedClient

NY = ZoneInfo('America/New_York')
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=NY)
DAY = '2026-09-30'


@pytest.mark.parametrize('value,expected', [
    ('2125550100', '+12125550100'), ('(212) 555-0100', '+12125550100'),
    ('1 (212) 555.0100', '+12125550100'), ('+1 212-555-0100', '+12125550100'),
    ('001 212 555 0100', '+12125550100'), ('011 44 20 8366 1177', '+442083661177'),
    ('+91 98765 43210', '+919876543210'), ('0091 9876543210', '+919876543210'),
    ('+44 (20) 8366 1177', '+442083661177'), ('  212 555 0100  ', '+12125550100'),
    ('+\u0661 \u0662\u0661\u0662 \u0665\u0665\u0665 \u0660\u0661\u0660\u0660', '+12125550100'),
])
def test_phone_canonical_forms(value, expected):
    assert normalize_phone(value) == expected
    assert normalize_phone(normalize_phone(value)) == expected


@pytest.mark.parametrize('value', ['', '5550100', '2125550100 ext 123', '1-800-FLOWERS',
                                  '++12125550100', '+0123456789', '+123', '+1234567890123456',
                                  '(212 555-0100', 'call 2125550100'])
def test_phone_unsafe_or_incomplete_values_are_rejected(value):
    with pytest.raises(PhoneNumberError):
        normalize_phone(value)


def test_non_us_local_number_requires_country_code():
    with pytest.raises(PhoneNumberError):
        normalize_phone('9876543210', region='IN')
    assert normalize_phone('+919876543210', region='IN') == '+919876543210'


def test_model_and_dictionary_update_paths_normalize_phone(database):
    assert PatientIntake(phone='(212) 555-0100').phone == '+12125550100'
    assert PatientUpdate(phone='212.555.0199').phone == '+12125550199'
    assert update_patient(1, {'phone': '(212) 555-0100'})['ok']
    with db.connect() as conn:
        assert conn.execute('SELECT phone FROM patients WHERE id=1').fetchone()[0] == '+12125550100'
    assert find_patient('test@example.test', '1 212 555 0100')['id'] == 1
    before = read(1)
    assert not update_patient(1, {'phone': 'garbage'})['ok']
    assert read(1) == before


def test_legacy_numbers_are_canonicalized_before_lookup_and_display(database):
    assert read(1)['phone'] == '+12125550100'
    assert find_patient('test@example.test', '(212) 555-0100')['phone'] == '+12125550100'
    with db.connect() as conn:
        assert db.normalize_patient_phones(conn) == 2
        assert db.normalize_patient_phones(conn) == 0


def test_phone_migration_quarantines_incomplete_data_without_guessing(database):
    with db.connect() as conn:
        conn.execute("UPDATE patients SET phone='+1-555-1001' WHERE id=2")
        assert db.normalize_patient_phones(conn) == 1
        assert conn.execute('SELECT phone FROM patients WHERE id=1').fetchone()[0] == '+12125550100'
        assert conn.execute('SELECT phone FROM patients WHERE id=2').fetchone()[0] is None
        issue = conn.execute('SELECT original_phone FROM patient_phone_issues WHERE patient_id=2').fetchone()
        assert issue[0] == '+1-555-1001'
    assert read(2)['phone'] is None and read(2)['phone_needs_update']
    assert identify_patient('other@example.test', '2125550199').status == 'mismatch'
    assert update_patient(2, {'phone': '2125550199'})['ok']
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM patient_phone_issues').fetchone()[0] == 0


@pytest.mark.parametrize('email,phone,status,patient', [
    ('test@example.test', '(212) 555-0100', 'exact', 1),
    ('test@example.test', '2125550199', 'mismatch', 1),
    ('changed@example.test', '2125550100', 'mismatch', 1),
    ('test@example.test', '2125550101', 'ambiguous', None),
    ('unknown@example.test', '2125550199', 'missing', None),
])
def test_identity_matches_require_both_contacts(email, phone, status, patient, database):
    result = identify_patient(email, phone)
    assert (result.status, result.patient_id) == (status, patient)


def test_shared_phone_is_not_enough_to_choose_a_patient(database):
    update_patient(2, {'phone': '2125550100'})
    result = identify_patient('new@example.test', '2125550100')
    assert result.status == 'ambiguous' and result.patient_id is None


def test_returning_patient_is_not_disclosed_before_verification(database, offline_verification):
    agent = NextDimAgent(client=ScriptedClient(INTAKE))
    reply = agent.handle('my details')
    assert agent.step == VERIFY and agent.patient is None
    assert 'Home Street' not in reply and 'test@example.test' not in reply
    assert offline_verification[1].sent[0][0] == 'test@example.test'
    assert agent.handle('wrong') and agent.patient is None
    agent.handle('246810')
    assert agent.step == REGISTRY and agent.patient['id'] == 1
    agent.handle('yes')
    assert agent.step == MENU and 'bookings' in agent.flow.last_reply


def test_mismatch_collects_both_new_contacts_and_updates_after_verification_and_confirmation(database, offline_verification):
    original = read(1)
    agent = NextDimAgent(client=ScriptedClient(
        {**INTAKE, 'phone': '2125550199'}, {'email': 'changed@example.test'},
        {'phone': '(212) 555-0199'},
    ))
    reply = agent.handle('my details')
    assert agent.step == RECOVERY and 'both' in reply and agent.patient is None
    agent.handle('my new email')
    assert agent.step == RECOVERY and offline_verification[1].sent == []
    agent.handle('my new phone')
    assert agent.step == VERIFY and read(1) == original
    assert offline_verification[1].sent[0][0] == original['email']
    agent.handle('246810')
    assert agent.step == CONTACT_CONFIRM and read(1) == original
    agent.handle('yes')
    result = read(1)
    assert (result['id'], result['email'], result['phone']) == (1, 'changed@example.test', '+12125550199')
    assert result['address'] == original['address']
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM patients').fetchone()[0] == 2


def test_both_changed_contacts_can_use_explicit_recovery(database):
    agent = NextDimAgent(client=ScriptedClient(
        {**INTAKE, 'email': 'changed@example.test', 'phone': '2125550199'},
        {'email': 'changed@example.test', 'phone': '2125550199'},
    ))
    agent.handle('my details')
    assert agent.step == REGISTRY and agent.patient is None
    agent.handle('recover account')
    assert agent.step == RECOVERY_ID
    agent.handle('test@example.test')
    assert agent.step == RECOVERY
    agent.handle('new details')
    assert agent.step == VERIFY


def test_recovery_does_not_overwrite_another_patients_email(database):
    agent = NextDimAgent(client=ScriptedClient(
        {**INTAKE, 'phone': '2125550199'},
        {'email': 'other@example.test', 'phone': '2125550199'},
    ))
    agent.handle('details'); agent.handle('new details'); agent.handle('246810')
    reply = agent.handle('yes')
    assert agent.step == CONTACT_CONFIRM and 'cannot be saved' in reply
    assert read(1)['email'] == 'test@example.test' and read(2)['email'] == 'other@example.test'


def test_stale_contact_confirmation_cannot_overwrite_concurrent_change(database):
    agent = NextDimAgent(client=ScriptedClient(
        {**INTAKE, 'phone': '2125550199'}, {'email': 'changed@example.test', 'phone': '2125550199'}))
    agent.handle('details'); agent.handle('update'); agent.handle('246810')
    update_patient(1, {'phone': '2125550111'})
    assert 'account changed' in agent.handle('yes').lower()
    assert read(1)['phone'] == '+12125550111'


def test_verification_code_never_appears_in_events(database):
    events = []
    agent = NextDimAgent(client=ScriptedClient(INTAKE), on_event=events.append)
    agent.handle('my details with (212) 555-0100')
    agent.handle('246810')
    serialized = json.dumps(events)
    assert '246810' not in serialized and '(212) 555-0100' not in serialized
    assert 'test@example.test' not in serialized


def test_verification_is_single_use_expiring_and_attempt_limited(database):
    sender, clock = MemorySender(), [100.0]
    service = VerificationService(sender, clock=lambda: clock[0], ttl_seconds=10)
    challenge = service.issue(read(1), 'login')
    code = sender.sent[-1][1]
    assert service.verify(challenge, code)
    assert not service.verify(challenge, code)
    clock[0] += 61
    expired = service.issue(read(1), 'login')
    clock[0] += 11
    assert not service.verify(expired, sender.sent[-1][1])
    clock[0] += 61
    limited = service.issue(read(1), 'login')
    for _ in range(5):
        assert not service.verify(limited, 'wrong')
    assert not service.verify(limited, sender.sent[-1][1])


def test_verification_delivery_failure_is_closed(database):
    class FailingSender:
        def send(self, *_): raise RuntimeError('SMTP password secret')
    service = VerificationService(FailingSender())
    agent = NextDimAgent(client=ScriptedClient(INTAKE), verification=service)
    response = agent.handle('details')
    assert agent.patient is None and not agent.flow.verified
    assert 'unavailable' in response and 'secret' not in response


def test_verification_resend_rate_limit(database):
    clock, sender = [10.0], MemorySender()
    service = VerificationService(sender, clock=lambda: clock[0])
    service.issue(read(1), 'login')
    with pytest.raises(VerificationUnavailable):
        service.issue(read(1), 'login')
    for _ in range(4):
        clock[0] += 61
        service.issue(read(1), 'login')
    clock[0] += 61
    with pytest.raises(VerificationUnavailable):
        service.issue(read(1), 'login')
    assert len(sender.sent) == 5


@pytest.mark.parametrize('text,start,end', [
    ('today', '2026-09-28', None), ('tomorrow morning', '2026-09-29', None),
    ('day after tomorrow', '2026-09-30', None), ('yesterday', '2026-09-27', None),
    ('in 3 days', '2026-10-01', None), ('in two days', '2026-09-30', None),
    ('Friday', '2026-10-02', None), ('this Friday', '2026-10-02', None),
    ('next Friday', '2026-10-09', None), ('next week Friday', '2026-10-09', None),
    ('this week', '2026-09-28', '2026-10-04'), ('next week', '2026-10-05', '2026-10-11'),
    ('this weekend', '2026-10-03', '2026-10-04'), ('next weekend', '2026-10-10', '2026-10-11'),
    ('September 30, 2026', '2026-09-30', '2026-09-30'),
    ('30 September 2026', '2026-09-30', '2026-09-30'),
    ('Wednesday 2026-09-30', '2026-09-30', '2026-09-30'),
    ('2026-09-30 through 2026-10-02', '2026-09-30', '2026-10-02'),
    ('Wednesday through Friday', '2026-09-30', '2026-10-02'),
])
def test_relative_and_absolute_date_resolution(text, start, end):
    result = DateResolver().resolve(text, NOW)
    assert result.recognized and not result.error
    assert result.start.isoformat() == start
    assert (result.end.isoformat() if result.end else None) == end


@pytest.mark.parametrize('text', ['09/10/2026', '2026-02-30', 'Friday 2026-09-30',
                                   'tomorrow 2026-10-02', 'today 2026-10-02',
                                   '2026-10-02 to 2026-09-30', 'today or tomorrow',
                                   '2026-10-01 and 2026-10-03'])
def test_ambiguous_or_inconsistent_dates_require_clarification(text):
    assert DateResolver().resolve(text, NOW).error


def test_date_resolution_respects_clinic_midnight_and_dst():
    utc = datetime(2026, 9, 29, 1, 0, tzinfo=ZoneInfo('UTC'))
    assert DateResolver().resolve('today', utc.astimezone(NY)).start == date(2026, 9, 28)
    assert DateResolver().resolve('today', utc).start == date(2026, 9, 29)
    before = datetime(2026, 10, 31, 22, 30, tzinfo=NY)
    assert DateResolver().resolve('tomorrow', before).start == date(2026, 11, 1)
    assert DateResolver().resolve('tomorrow', datetime(2026, 12, 31, 23, 30, tzinfo=NY)).start == date(2027, 1, 1)
    with pytest.raises(ValueError, match='aware'):
        DateResolver().resolve('today', datetime(2026, 9, 28))


@pytest.mark.parametrize('text,clock,period', [('2pm','14:00','afternoon'),('2:30 pm','14:30','afternoon'),
                                           ('14:30','14:30','afternoon'),('noon','12:00','afternoon'),
                                           ('midnight','00:00','morning'),('first thing','09:00','morning')])
def test_time_resolution(text, clock, period):
    result = resolve_time(text)
    assert result.at == clock and result.period == period


@pytest.mark.parametrize('text', ['at 2', '25:00', '12:99', '13pm', 'morning and afternoon'])
def test_time_ambiguity_and_validation(text):
    assert resolve_time(text).error


@pytest.fixture
def rolling(monkeypatch):
    monkeypatch.setattr(calendar, 'FIRST_DAY', None)
    monkeypatch.setattr(calendar, 'DAYS', 14)


def scheduling_agent():
    agent = NextDimAgent(client=ScriptedClient())
    agent.flow.patient = read(1)
    agent.flow.verified = True
    agent.flow.complaint = Complaint(**PROBLEM)
    agent.flow.step = CLINIC
    return agent


def test_today_tomorrow_and_week_search_are_real_ranges(database, rolling):
    assert calendar.window()[0] == date(2026, 9, 28)
    agent = scheduling_agent()
    response = agent.handle('today afternoon')
    assert agent.step == SLOTS and 'Monday 2026-09-28' in response
    assert all(o.date == date(2026, 9, 28) for o in agent.flow.options)
    response = agent.handle('tomorrow 2pm')
    assert agent.step == SLOTS and 'Tuesday 2026-09-29' in response
    assert all(o.start_time.hour == 14 for o in agent.flow.options)
    response = agent.handle('this week')
    assert 'Monday 2026-09-28' in response and 'Sunday 2026-10-04' in response
    assert agent.flow.preference.end_date == date(2026, 10, 4)
    assert not agent.context.client.calls


def test_past_and_outside_dates_are_refused_not_moved(database, rolling):
    agent = scheduling_agent()
    for text in ('yesterday', '2026-12-30'):
        reply = agent.handle(text)
        assert 'past or outside' in reply and agent.step == CLINIC
        assert agent.booking is None
    assert not calendar.available_slots(1, '2020-01-01')
    assert not book_appointment(1, 1, '2020-01-01', '10:00')['ok']


def test_elapsed_same_day_slots_are_not_offered_or_booked(database, rolling):
    free = calendar.available_slots(1, '2026-09-28')
    assert all(r['start_time'] > '10:00' for r in free)
    assert not book_appointment(1, 1, '2026-09-28', '09:30')['ok']
    assert not book_appointment(1, 1, '2026-09-28', '10:00')['ok']


@pytest.mark.parametrize('number', [1, 2, 3])
def test_displayed_option_number_selects_exactly_that_option(database, number):
    agent = scheduling_agent()
    agent.handle('Wednesday morning')
    option = agent.flow.options[number-1]
    reply = agent.handle(str(number))
    assert agent.flow.chosen == option and agent.step == BOOK
    assert f'Wednesday {DAY}' in reply
    agent.handle('yes')
    assert agent.booking['clinic_id'] == option.clinic_id
    assert agent.booking['start_time'] == option.start_time.strftime('%H:%M')


def test_yes_with_new_date_does_not_confirm_old_booking(database):
    agent = scheduling_agent()
    agent.handle('Wednesday morning'); agent.handle('1')
    reply = agent.handle('yes but Thursday instead')
    assert agent.booking is None and agent.step == SLOTS
    assert all(o.date == date(2026, 10, 1) for o in agent.flow.options)
    assert 'Thursday 2026-10-01' in reply


def test_expired_selected_slot_is_rechecked_at_booking_time(database, rolling, monkeypatch):
    agent = scheduling_agent()
    agent.handle('today 2pm'); agent.handle('1')
    monkeypatch.setattr(calendar, 'now', lambda zone=None: datetime(2026,9,28,15,0,tzinfo=zone or NY))
    agent.handle('yes')
    assert agent.booking is None and agent.step != DONE


@pytest.mark.parametrize('text,minutes', [('two people',60),('for 2 people',60),('both of us',60),
                                        ('book for me and my wife',60),('one hour',60),('1 hour',60),
                                        ('30 minutes',30),('half an hour',30)])
def test_duration_policy(text, minutes):
    assert appointment_duration(text, scheduling=True).minutes == minutes


@pytest.mark.parametrize('text', ['book for 2 hours', '90 minutes', '1.5 hours',
                                  'one and a half hours', 'for three people'])
def test_more_than_one_hour_is_refused(text):
    result = appointment_duration(text, scheduling=True)
    assert result.error and 'cannot book for more than one hour' in result.error.lower()


def test_symptom_duration_is_not_a_booking_duration():
    assert appointment_duration('I have had pain for 2 hours').minutes is None
    assert appointment_duration('I have had pain for 2 hours', scheduling=True).error == ''


def test_group_request_uses_duration_only_in_reply_and_persistence(database):
    agent = scheduling_agent()
    response = agent.handle('two people on Wednesday morning')
    assert 'I am trying to find a slot for 1 hour.' in response
    assert 'two people' not in response.lower()
    assert agent.flow.duration_minutes == 60 and agent.step == SLOTS
    agent.handle('1'); agent.handle('yes')
    booking = agent.booking
    assert booking['start_time'] == '10:00' and booking['end_time'] == '11:00'
    free = {r['start_time'] for r in calendar.available_slots(booking['clinic_id'], DAY)}
    assert '10:00' not in free and '10:30' not in free and '11:00' in free


def test_hour_booking_rejects_occupied_second_half_and_closing_overflow(database):
    assert book_appointment(1, 2, DAY, '10:30')['ok']
    assert not book_appointment(1, 1, DAY, '10:00', duration_minutes=60)['ok']
    free = calendar.available_slots(1, DAY, duration_minutes=60)
    assert not any(r['start_time'] in ('10:00','10:30') for r in free)
    assert not book_appointment(1, 1, DAY, '16:30', duration_minutes=60)['ok']
    assert not book_appointment(2, 1, DAY, '10:00', duration_minutes=90)['ok']


def test_overlapping_hour_and_half_hour_race_has_one_winner(database):
    barrier = Barrier(2)
    def attempt(args):
        barrier.wait(timeout=5)
        return book_appointment(1,1,DAY,args[0],duration_minutes=args[1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [('10:00',60),('10:30',30)]))
    assert sum(r['ok'] for r in results) == 1
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM bookings').fetchone()[0] == 1


@pytest.mark.parametrize('step', [DETAILS, REGISTRY, VERIFY, RECOVERY, MENU, COMPLAINT, CLINIC, SLOTS, BOOK])
def test_end_requires_one_confirmation_in_every_active_step(step):
    agent = NextDimAgent(client=ScriptedClient())
    agent.flow.step = step
    agent.flow.last_reply = 'Previous prompt'
    reply = agent.handle('please end the chat')
    assert agent.step == END_CONFIRM and 'End the chat without booking?' in reply
    assert agent.handle('maybe') and agent.step == END_CONFIRM
    agent.handle('no')
    assert agent.step == step and 'Previous prompt' in agent.flow.last_reply
    agent.handle('end chat'); result = agent.handle('yes')
    assert agent.step == DONE and agent.booking is None and 'without creating' in result
    assert agent.actions == [] and agent.flow.end_reason == 'ended'
    assert 'has ended' in agent.handle('hello') and not agent.context.client.calls


def test_booking_closes_automatically_and_cannot_be_replayed(database):
    agent = scheduling_agent()
    agent.handle('Wednesday morning'); agent.handle('1')
    reply = agent.handle('yes')
    assert agent.step == DONE and agent.actions == [] and 'now closed' in reply
    for message in ('yes', 'end chat', 'book another'):
        assert 'closed' in agent.handle(message)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM bookings').fetchone()[0] == 1


def test_all_patient_bookings_across_clinics_and_statuses_are_returned(database):
    with db.connect() as conn:
        conn.executemany('INSERT INTO bookings(clinic_id,patient_id,slot_date,start_time,end_time,status) VALUES(?,?,?,?,?,?)', [
            (1,1,'2020-01-01','09:00','09:30','completed'),
            (2,1,'2026-10-01','10:00','10:30','booked'),
            (3,1,'2026-10-02','11:00','12:00','cancelled'),
            (4,2,'2026-10-02','11:00','11:30','booked'),
        ])
    with pytest.raises(PermissionError):
        patient_bookings(1, verified=False)
    records = patient_bookings(1, verified=True)
    assert len(records)==3 and {r['clinic_id'] for r in records} == {1,2,3}
    assert all(r['patient_id']==1 and r['weekday'] and r['zone']=='America/New_York' for r in records)
    agent = NextDimAgent(client=ScriptedClient(INTAKE))
    agent.handle('details'); agent.handle('246810'); agent.handle('yes')
    response = agent.handle('my bookings')
    assert 'Wednesday 2020-01-01' in response and 'Thursday 2026-10-01' in response
    assert 'Friday 2026-10-02' in response and 'cancelled' in response
    assert agent.booking_history == records
    assert len(all_clinics()) == 4 and 'Clinic D' in agent.handle('all clinics')
    agent.handle('end chat'); agent.handle('yes')
    assert len(patient_bookings(1, verified=True)) == 3


def test_relogin_reads_persisted_booking_in_a_fresh_session(database, offline_verification):
    first = scheduling_agent()
    first.handle('Wednesday morning'); first.handle('1'); first.handle('yes')
    returning = NextDimAgent(client=ScriptedClient(INTAKE))
    returning.handle('details'); returning.handle('246810'); returning.handle('yes')
    reply = returning.handle('view bookings')
    assert str(first.booking['booking_id']) in reply
    assert len(returning.booking_history) == 1
    assert returning.booking_history[0]['clinic_id'] == first.booking['clinic_id']


def test_empty_history_is_explicit(database):
    agent = scheduling_agent()
    assert 'no bookings on record' in agent.handle('my bookings')


@pytest.mark.parametrize('text', ['book for an hour and a half', 'book 1 hour and 30 minutes',
                                  'book 1h30m', 'book 2h', 'book for more than one hour',
                                  'book for longer than an hour', 'book 10am to 12pm', 'book for two days'])
def test_compound_long_durations_are_explicitly_refused(text):
    result = appointment_duration(text, scheduling=True)
    assert 'cannot book for more than one hour' in result.error.lower()


def test_duration_alternatives_need_a_choice_and_group_requests_use_one_hour():
    assert appointment_duration('30 minutes or 1 hour', scheduling=True).error
    assert appointment_duration('two people for 30 minutes', scheduling=True).minutes == 60
    assert appointment_duration('no more than one hour', scheduling=True).minutes == 60
    assert appointment_duration('book in two days').minutes is None
    assert appointment_duration('not for two people', scheduling=True).error


def test_half_hour_and_hour_time_ranges_are_recognized(database):
    agent = scheduling_agent()
    reply = agent.handle('Wednesday from 10am to 11am')
    assert agent.flow.duration_minutes == 60 and agent.step == SLOTS
    assert 'Wednesday 2026-09-30' in reply and '10:00 to 11:00' in reply


@pytest.mark.parametrize('message', ['Friday 2026-09-30', 'yesterday', 'not tomorrow', 'book for 2 hours'])
def test_invalid_changed_request_invalidates_the_old_confirmation(database, message):
    agent = scheduling_agent()
    agent.handle('Wednesday morning'); agent.handle('1')
    agent.handle(message)
    assert agent.step == CLINIC and agent.flow.chosen is None and agent.flow.options == []
    agent.handle('yes')
    assert agent.booking is None and agent.step != DONE


def test_second_one_is_never_misread_as_first_one(database):
    agent = scheduling_agent()
    agent.handle('Wednesday morning')
    expected = agent.flow.options[1]
    agent.handle('the second one')
    assert agent.flow.chosen == expected


def test_menu_interrupt_preserves_booking_without_reinterpreting_menu_numbers(database):
    agent = scheduling_agent()
    agent.handle('Wednesday morning'); agent.handle('1')
    selected = agent.flow.chosen
    agent.handle('my bookings')
    assert agent.step == MENU and agent.flow.account_return_step == BOOK
    agent.handle('1')  # Menu item 1 is history, not confirmation of the old slot.
    assert agent.step == MENU and agent.booking is None
    agent.handle('continue')
    assert agent.step == BOOK and agent.flow.chosen == selected
    agent.handle('yes')
    assert agent.step == DONE and agent.booking


def test_legacy_phone_recovery_preserves_bookings(database):
    assert book_appointment(1, 1, DAY, '09:00')['ok']
    with db.connect() as conn:
        conn.execute("UPDATE patients SET phone='+1-555-1001' WHERE id=1")
        db.normalize_patient_phones(conn)
    agent = NextDimAgent(client=ScriptedClient(
        {**INTAKE, 'phone': '2125550199'},
        {'email': 'updated@example.test', 'phone': '(212) 555-0199'}))
    agent.handle('details'); agent.handle('new contacts'); agent.handle('246810')
    assert agent.step == CONTACT_CONFIRM
    agent.handle('yes')
    assert agent.patient['phone'] == '+12125550199' and not agent.patient['phone_needs_update']
    assert len(patient_bookings(1, verified=True)) == 1
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM patient_phone_issues').fetchone()[0] == 0


def test_new_patient_can_explicitly_register_with_a_shared_number(database):
    agent = NextDimAgent(client=ScriptedClient(
        {**INTAKE,'first_name':'New','email':'new@example.test'},
        {'address':'New Street','city':'New York','state':'NY','zip':'10001'}))
    agent.handle('details')
    assert agent.step == RECOVERY
    agent.handle('register new patient')
    assert agent.step == REGISTRY
    agent.handle('my address'); agent.handle('yes')
    assert agent.patient['id'] == 3 and read(1)['email'] == 'test@example.test'


def test_legacy_schema_migration_preserves_bookings_and_foreign_keys(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.db'
    conn = sqlite3.connect(path)
    old_schema = db.SCHEMA.replace('phone         TEXT,', 'phone         TEXT NOT NULL,').replace('date_of_birth TEXT,', 'date_of_birth TEXT NOT NULL,')
    conn.executescript(old_schema)
    conn.execute("INSERT INTO clinics VALUES(1,'Clinic','ENT','Road','New York','NY','10001',40,-73)")
    conn.execute("INSERT INTO patients VALUES(1,'Test','Patient','test@example.test','+1-555-1001','1990-01-01','Road','New York','NY','10001',40,-73,'Ear trouble')")
    conn.execute("INSERT INTO bookings VALUES(1,1,1,'2026-09-30','10:00','10:30','booked')")
    conn.commit(); conn.close()
    monkeypatch.setattr(db,'DB_PATH',path)
    db.init_db(); db.init_db()
    with db.connect() as conn:
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert conn.execute('SELECT patient_id FROM bookings').fetchone()[0] == 1
        assert conn.execute('SELECT phone FROM patients').fetchone()[0] is None
        columns = {r['name']:r for r in conn.execute('PRAGMA table_info(patients)')}
        assert not columns['phone']['notnull'] and not columns['date_of_birth']['notnull']
        assert conn.execute('SELECT count(*) FROM patient_phone_issues').fetchone()[0] == 1


def test_legacy_csv_phone_is_quarantined_on_import(database, tmp_path):
    from app.ingest import load, SOURCES
    import csv
    _, table, model, columns = SOURCES[1]
    values = {'patient_id': 10, 'first_name':'CSV','last_name':'Patient','email':'csv@example.test',
              'phone':'+1-555-1001','date_of_birth':'1990-01-01','address':'Road','city':'New York',
              'state':'NY','zip':'10001','latitude':40.75,'longitude':-73.98,'complaints':'Checkup'}
    source = tmp_path / 'patients.csv'
    with source.open('w',newline='') as file:
        writer=csv.DictWriter(file, fieldnames=list(values)); writer.writeheader(); writer.writerow(values)
    with db.connect() as conn:
        assert load(conn,table,columns,model,source)==1
        assert conn.execute('SELECT phone FROM patients WHERE id=10').fetchone()[0] is None
        assert conn.execute('SELECT original_phone FROM patient_phone_issues WHERE patient_id=10').fetchone()[0] == '+1-555-1001'


@pytest.mark.parametrize('text', ['tomorrow to today', 'day after tomorrow Monday', 'after Friday', 'before tomorrow', 'after 2026-09-30'])
def test_relative_conflicts_and_boundaries_require_clarification(text):
    assert DateResolver().resolve(text, NOW).error


def test_multiword_relative_date_agrees_with_explicit_day():
    resolved = DateResolver().resolve('day after tomorrow Wednesday 2026-09-30', NOW)
    assert not resolved.error and resolved.start == date(2026, 9, 30)
    resolved = DateResolver().resolve('yesterday through tomorrow', NOW)
    assert not resolved.error and resolved.start == date(2026, 9, 27) and resolved.end == date(2026, 9, 29)


def test_smtp_adapter_requires_starttls_before_authentication_and_sending(monkeypatch):
    from app.email_delivery import SMTPCodeSender
    calls = []
    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(('connect', host, port, timeout))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            calls.append(('closed',))
        def starttls(self, context):
            assert context.check_hostname
            calls.append(('starttls',))
        def login(self, username, password):
            calls.append(('login', username, password))
        def send_message(self, message):
            calls.append(('send', message))
    for name, value in {'HOST':'smtp.example.test', 'PORT':'587', 'FROM':'portal@example.test', 'USERNAME':'user', 'PASSWORD':'test-secret'}.items():
        monkeypatch.setenv('VAST_SMTP_' + name, value)
    monkeypatch.setattr('app.email_delivery.smtplib.SMTP', FakeSMTP)
    SMTPCodeSender().send('patient@example.test', '123456')
    assert [c[0] for c in calls] == ['connect', 'starttls', 'login', 'send', 'closed']
    message = calls[3][1]
    assert message['To'] == 'patient@example.test'
    assert message['From'] == 'portal@example.test'
    assert '123456' in message.get_content() and '10 minutes' in message.get_content()


def test_smtp_adapter_fails_closed_without_configuration(monkeypatch):
    from app.email_delivery import SMTPCodeSender
    monkeypatch.delenv('VAST_SMTP_HOST', raising=False)
    with pytest.raises(RuntimeError, match='not configured'):
        SMTPCodeSender().send('patient@example.test', '123456')