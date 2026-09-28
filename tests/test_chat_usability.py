"""Acceptance coverage for format feedback, booking intent, and action buttons."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

import pytest

from app import db
from agents.nextdim.agent import NextDimAgent
from agents.nextdim.conversation import (
    BOOK, CLINIC, COMPLAINT, CONTACT_CONFIRM, DETAILS, DONE, MENU,
    RECOVERY, REGISTRY, SLOTS,
)
from domain.email import validate_email
from domain.models import Complaint, Location, PatientIntake
from domain.phone import PhoneNumberError, normalize_chat_phone, normalize_phone
from services.contact_input import validate_contact_values
from services.date_shortcuts import date_shortcuts
from tools import available_slots as calendar
from tools.patients import read, update_patient
from helpers import INTAKE, COMPLAINT as PROBLEM, ScriptedClient

NY = ZoneInfo('America/New_York')
DAY = date(2026, 9, 30)


@pytest.fixture
def no_email(monkeypatch, offline_verification):
    monkeypatch.setenv('VAST_REQUIRE_EMAIL_VERIFICATION', 'false')
    def forbidden(*args, **kwargs):
        raise AssertionError('Email must not be sent by this update')
    monkeypatch.setattr(offline_verification[0], 'issue', forbidden)
    monkeypatch.setattr(offline_verification[0], 'verify', forbidden)


def prepared(*answers):
    agent = NextDimAgent(client=ScriptedClient(*answers))
    agent.flow.patient = read(1)
    agent.flow.verified = True
    agent.flow.complaint = Complaint(**PROBLEM)
    agent.flow.step = CLINIC
    return agent


def selected(*answers, hour=False):
    agent = prepared(*answers)
    agent.flow.duration_minutes = 60 if hour else 30
    agent.handle('Wednesday at 10 am')
    agent.handle('1')
    assert agent.step == BOOK
    return agent


def count_bookings():
    with closing(db.connect()) as conn, conn:
        return conn.execute('SELECT count(*) FROM bookings').fetchone()[0]


@pytest.mark.parametrize('value', ['2125550100', '(212) 555-0100', '212.555.0100',
                                    ' 212 555 0100 ', '\u0662\u0661\u0662\u0665\u0665\u0665\u0660\u0661\u0660\u0660'])
def test_ten_digit_chat_numbers_keep_canonical_storage(value):
    assert normalize_chat_phone(value) == '+12125550100'


@pytest.mark.parametrize('value', ['', '123', '5550100', '212555010', '21255501001',
                                  '+12125550100', '1 212 555 0100', '+91 9876543210',
                                  '2125550100 ext 1', '212555010a', '(212 555-0100'])
def test_chat_rejects_wrong_length_prefixes_letters_and_extensions(value):
    with pytest.raises(PhoneNumberError):
        normalize_chat_phone(value)


def test_persistence_normalizer_keeps_existing_international_records():
    assert normalize_phone('+919876543210') == '+919876543210'


@pytest.mark.parametrize('value', ['sam@example.com', 'sam+clinic@example.co.uk',
                                   "o'neill@example.test", 'first.last@sub.example.org'])
def test_ordinary_email_formats(value):
    assert validate_email(value) == value


@pytest.mark.parametrize('value', ['samexample.com', 'sam@example', '@example.com',
                                  'sam@@example.com', 'sam @example.com', 'sam@exa mple.com',
                                  'sam..lee@example.com', '.sam@example.com', 'sam.@example.com',
                                  'sam@-example.com', 'sam@example-.com', 'sam@exam_ple.com',
                                  'sam@example..com', 'sam@example.com..', 'sam@example.123',
                                  'a'*65 + '@example.com'])
def test_malformed_email_rejected(value):
    with pytest.raises(ValueError):
        validate_email(value)


@pytest.mark.parametrize('verification', ['true', 'false'])
def test_first_greeting_contains_no_contact_format_instruction(monkeypatch, verification):
    monkeypatch.setenv('VAST_REQUIRE_EMAIL_VERIFICATION', verification)
    welcome = NextDimAgent(client=ScriptedClient()).start()
    assert 'email' in welcome and 'phone' in welcome
    assert all(word not in welcome.lower() for word in ['digit', 'country code', 'example.com', 'format'])


def test_invalid_contacts_feedback_retains_valid_name_and_does_not_retry_model(database, no_email):
    client = ScriptedClient({**INTAKE, 'email': 'test@example', 'phone': '1234567'},
                            {'email': 'test@example.test'}, {'phone': '(212) 555-0100'})
    agent = NextDimAgent(client=client)
    reply = agent.handle('Test Patient, email test@example, phone 1234567')
    assert agent.step == DETAILS and agent.patient is None
    assert 'test@example' in reply and 'name@example.com' in reply
    assert '1234567' in reply and '7 digits' in reply and '10-digit' in reply
    assert agent.flow.intake.first_name == 'Test' and agent.flow.intake.last_name == 'Patient'
    assert agent.flow.intake.email is None and agent.flow.intake.phone is None
    assert len(client.calls) == 1
    assert agent.handle('yes') == reply and len(client.calls) == 1
    assert {a['message'] for a in agent.actions} == {'end chat'}
    reply = agent.handle('email test@example.test')
    assert '10-digit' in reply and len(client.calls) == 2
    reply = agent.handle('phone (212) 555-0100')
    assert agent.step == REGISTRY and agent.patient['id'] == 1
    assert agent.patient['phone'] == '+12125550100'
    assert not agent.flow.contact_errors


@pytest.mark.parametrize('message,expected_field', [
    ('email test@example and phone 2125550100', 'email'),
    ('email test @example.test and phone 2125550100', 'email'),
    ('email test@example.test and phone 1234567', 'phone'),
    ('email test@example.test and phone +12125550100', 'phone'),
])
def test_obvious_invalid_source_cannot_be_repaired_by_llm(database, no_email, message, expected_field):
    client = ScriptedClient(INTAKE)  # Model tries to replace malformed input with a valid value.
    agent = NextDimAgent(client=client)
    reply = agent.handle(message)
    assert expected_field in agent.flow.contact_errors
    assert agent.patient is None and agent.step == DETAILS
    assert 'You entered' in reply and len(client.calls) == 1


def test_valid_literal_wins_over_model_country_prefix(database, no_email):
    agent = NextDimAgent(client=ScriptedClient({**INTAKE, 'phone': '+12125550100'}))
    agent.handle('Test Patient test@example.test (212) 555-0100')
    assert agent.step == REGISTRY and agent.patient['id'] == 1


@pytest.mark.parametrize('field,message', [('email', 'bad.example.com'), ('phone', '12345')])
def test_null_model_cannot_hide_single_outstanding_bad_contact(database, field, message):
    agent = NextDimAgent(client=ScriptedClient({}))
    values = dict(INTAKE)
    values.pop(field)
    agent.flow.intake = PatientIntake(**values)
    reply = agent.handle(message)
    assert field in agent.flow.contact_errors and message in reply


def test_contact_errors_do_not_expose_payloads_in_trace(database):
    events = []
    agent = NextDimAgent(client=ScriptedClient({**INTAKE, 'phone': '1234567'}), on_event=events.append)
    agent.handle('Test Patient test@example.test phone 1234567')
    trace = json.dumps(events)
    assert 'test@example.test' not in trace and '1234567' not in trace
    assert 'redacted' in trace


def test_recovery_wrong_contact_cannot_save_old_pending_proposal(database, no_email):
    agent = NextDimAgent(client=ScriptedClient(
        {**INTAKE, 'phone': '2125550199'},
        {'email': 'changed@example.test', 'phone': '2125550199'},
        {'phone': '1234567'}, {'phone': '2125550188'},
    ))
    before = read(1)
    agent.handle('details'); agent.handle('new contacts')
    assert agent.step == CONTACT_CONFIRM
    reply = agent.handle('phone 1234567')
    assert '7 digits' in reply and agent.step == RECOVERY
    assert 'phone' not in agent.flow.contact_update
    assert read(1) == before
    agent.handle('yes')
    assert read(1) == before
    agent.handle('phone 2125550188')
    assert agent.step == CONTACT_CONFIRM
    assert 'changed@example.test' in agent.flow.last_reply
    agent.handle('yes')
    assert read(1)['phone'] == '+12125550188'
    assert read(1)['email'] == 'changed@example.test'


def test_registry_invalid_contact_blocks_acknowledgement(database, no_email):
    agent = NextDimAgent(client=ScriptedClient(INTAKE, {'email': 'bad@example'}, {'email': 'new@example.test'}))
    agent.handle('details')
    before = read(1)
    agent.handle('my email is bad@example')
    assert read(1) == before
    reply = agent.handle('yes')
    assert 'name@example.com' in reply and agent.step == REGISTRY
    assert not any(a['message'] == 'yes' for a in agent.actions)
    agent.handle('email new@example.test')
    assert read(1)['email'] == 'new@example.test'


def test_recovery_identity_explains_email_format_before_lookup(database, no_email):
    agent = NextDimAgent(client=ScriptedClient())
    agent.handle('recover account')
    reply = agent.handle('email test@example')
    assert 'name@example.com' in reply
    agent.handle('test@example.test')
    assert agent.step == RECOVERY


def test_email_dictionary_updates_are_also_validated(database):
    before = read(1)
    assert not update_patient(1, {'email': 'not-email'})['ok']
    assert read(1) == before


@pytest.mark.parametrize('message', [
    'I confirm this slot', 'Please confirm my booking',
    'This appointment works for me, please reserve it',
    'Yes, I confirm the appointment on Wednesday',
    'I confirm Wednesday 2026-09-30 at 10:00',
    'I confirm this slot on Wednesday 2026-09-30 from 10:00 to 10:30',
])
def test_natural_confirmation_books_exact_selected_slot_with_llm(database, monkeypatch, message):
    agent = selected({'intent': 'confirm'})
    choice = agent.flow.chosen
    def forbidden(*args, **kwargs):
        raise AssertionError('Confirmation must not search for new appointments')
    monkeypatch.setattr('agents.nextdim.steps.scheduling.rank_slots', forbidden)
    reply = agent.handle(message)
    assert agent.step == DONE and count_bookings() == 1
    assert agent.booking['clinic_id'] == choice.clinic_id
    assert agent.booking['slot_date'] == choice.date.isoformat()
    assert agent.booking['start_time'] == '10:00' and agent.booking['end_time'] == '10:30'
    assert 'Wednesday 2026-09-30' in reply and 'now closed' in reply
    assert len(agent.context.client.calls) == 1 and agent.actions == []
    payload = json.loads(agent.context.client.calls[0]['messages'][1]['content'])
    assert payload['selected_slot']['clinic_id'] == choice.clinic_id
    assert payload['message'] == message and not payload['booking_created']


def test_hour_duration_repetition_does_not_restart_search(database):
    agent = selected({'intent': 'confirm'}, hour=True)
    agent.handle('I confirm the 1 hour appointment on Wednesday at 10 am')
    assert agent.step == DONE and agent.booking['end_time'] == '11:00'


@pytest.mark.parametrize('answers', [({'intent': 'unclear'},), ('bad JSON', 'still bad'),
                                    (RuntimeError('model unavailable'),),
                                    ({'intent': 'change', 'option_number': 99},),
                                    ({'intent': 'confirm', 'clinic_id': 999},)*2])
def test_unclear_failed_or_invalid_intent_never_changes_or_books_selected(database, answers):
    agent = selected(*answers)
    choice, options = agent.flow.chosen, list(agent.flow.options)
    reply = agent.handle('Could you explain this appointment?')
    assert agent.step == BOOK and agent.flow.chosen == choice and agent.flow.options == options
    assert agent.booking is None and count_bookings() == 0
    assert 'Confirm booking' in reply
    agent.handle('yes')
    assert agent.step == DONE and count_bookings() == 1


@pytest.mark.parametrize('message', ['no', 'not yet', 'wait', "don't book it", 'do not confirm this booking'])
def test_decline_never_writes(database, message):
    agent = selected({'intent': 'confirm'})  # Even an erroneous LLM must not override a clear refusal.
    agent.handle(message)
    assert agent.booking is None and count_bookings() == 0
    assert not agent.context.client.calls


def test_llm_can_change_to_an_existing_option_but_cannot_book_it(database):
    agent = selected({'intent': 'change', 'option_number': 2})
    other = agent.flow.options[1]
    agent.handle('I meant the second appointment instead')
    assert agent.step == BOOK and agent.flow.chosen == other
    assert count_bookings() == 0
    agent.handle('yes')
    assert agent.booking['clinic_id'] == other.clinic_id


def test_conflicting_time_does_not_confirm_old_selection(database):
    agent = selected()
    agent.handle('Yes, but at 11 am instead')
    assert agent.step == SLOTS and agent.booking is None
    assert all(option.start_time.hour == 11 for option in agent.flow.options)
    assert not agent.context.client.calls


def test_duplicate_natural_confirmations_make_one_booking(database):
    agent = selected({'intent': 'confirm'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(agent.handle, ['I confirm this slot'] * 2))
    assert count_bookings() == 1 and len(agent.context.client.calls) == 1


def test_confirmation_and_change_buttons_have_exact_state_effects(database):
    agent = selected()
    actions = {a['label']: a['message'] for a in agent.actions}
    assert actions['Confirm booking'] == 'yes'
    agent.handle(actions['Choose another slot'])
    assert agent.step == SLOTS and agent.flow.chosen is None and count_bookings() == 0
    slots = [a for a in agent.actions if a.get('kind') == 'slot']
    assert len(slots) == len(agent.flow.options)
    chosen = agent.flow.options[1]
    agent.handle(slots[1]['message'])
    assert agent.flow.chosen == chosen and agent.step == BOOK
    agent.handle('change date')
    assert agent.step == CLINIC and agent.flow.preference is None and not agent.flow.options
    assert not agent.context.client.calls


def test_address_buttons_and_edit_acknowledgement_guard(database, no_email):
    agent = NextDimAgent(client=ScriptedClient({'address': 'New Street', 'city': 'New York', 'state': 'NY', 'zip': '10001'}))
    agent.flow.step = REGISTRY
    agent.flow.intake = PatientIntake(**{**INTAKE, 'email': 'new@example.test', 'phone': '2125550199'})
    agent.flow.pending = Location(address='Old Street', city='New York', state='NY', zip='10001')
    assert any(a['label'] == 'Confirm address' for a in agent.actions)
    agent.handle('change address')
    assert not any(a['message'] == 'yes' for a in agent.actions)
    assert 'correction' in agent.handle('yes')
    assert agent.patient is None
    agent.handle('My address is New Street, New York, NY 10001')
    assert agent.flow.pending.address == 'New Street'
    agent.handle('yes')
    assert agent.patient['address'] == 'New Street'


def test_complaint_buttons_skip_an_extra_classification_call(database):
    agent = prepared({**PROBLEM, 'detail': 'Since yesterday'})
    agent.flow.step = COMPLAINT
    assert any(a['label'] == 'Yes, that is correct' for a in agent.actions)
    agent.handle('change problem details')
    assert 'Keep current details' in {a['label'] for a in agent.actions}
    agent.handle('It started yesterday')
    assert agent.flow.complaint.detail == 'Since yesterday'
    assert len(agent.context.client.calls) == 1
    agent.handle('yes')
    assert agent.step == CLINIC


def test_contact_edit_button_requires_new_read_back(database, no_email):
    agent = NextDimAgent(client=ScriptedClient(
        {**INTAKE, 'phone': '2125550199'},
        {'email': 'updated@example.test', 'phone': '2125550199'},
        {'phone': '2125550188'},
    ))
    agent.handle('details'); agent.handle('updated contacts')
    before = read(1)
    agent.handle('edit contact details')
    agent.handle('yes')
    assert read(1) == before
    agent.handle('phone 2125550188')
    assert agent.step == CONTACT_CONFIRM and agent.flow.editing is None
    agent.handle('yes')
    assert read(1)['phone'] == '+12125550188'


@pytest.mark.parametrize('hour,minute,first', [(0, 0, 28), (9, 0, 28), (11, 59, 28),
                                            (12, 0, 29), (12, 1, 29), (16, 0, 29), (23, 59, 29)])
def test_shortcut_noon_boundary(hour, minute, first):
    current = datetime(2026, 9, 28, hour, minute, tzinfo=NY)
    allowed = [date(2026, 9, 28) + timedelta(days=n) for n in range(14)]
    actions = date_shortcuts(current, allowed)
    assert len(actions) == 7
    assert actions[0]['date'] == date(2026, 9, first).isoformat()
    assert actions[0]['label'].startswith('Today' if first == 28 else 'Tomorrow')
    for item in actions:
        day = date.fromisoformat(item['message'])
        assert day in allowed and item['date'] == day.isoformat()
        assert day.strftime('%A') in item['label'] and day.isoformat() in item['label']
        assert item['timezone'] == 'America/New_York'


@pytest.mark.parametrize('days', [[], [date(2026, 9, 28)],
                                  [date(2026, 9, 30), date(2026, 10, 1)],
                                  [date(2026, 9, 20)]])
def test_shortcuts_never_escape_short_expired_or_future_configured_window(days):
    result = date_shortcuts(datetime(2026, 9, 28, 14, tzinfo=NY), days)
    assert {a['date'] for a in result} == {d.isoformat() for d in days if d > date(2026, 9, 28)}


def test_shortcuts_timezone_boundary_and_dst():
    # UTC is the next day; New York is still the previous evening.
    instant = datetime(2026, 10, 31, 23, 30, tzinfo=NY)
    result = date_shortcuts(instant, [date(2026, 10, 31), date(2026, 11, 1)])
    assert result[0]['date'] == '2026-11-01'
    assert result[0]['expires_at'] == '2026-11-01T12:00:00-05:00'
    with pytest.raises(ValueError):
        date_shortcuts(datetime(2026, 9, 28), [DAY])
    assert date_shortcuts(instant, [DAY], limit=0) == []


def test_date_buttons_search_exact_payload_and_today_disappears_after_noon(database, monkeypatch):
    monkeypatch.setattr(calendar, 'FIRST_DAY', None)
    monkeypatch.setattr(calendar, 'DAYS', 7)
    agent = prepared()
    dates = [a for a in agent.actions if a.get('kind') == 'date']
    assert len(dates) == 7 and dates[0]['label'].startswith('Today')
    agent.handle(dates[0]['message'])
    assert agent.step == SLOTS and all(o.date == date(2026, 9, 28) for o in agent.flow.options)
    assert all(o.start_time.hour >= 10 for o in agent.flow.options)
    monkeypatch.setattr(calendar, 'now', lambda zone=None: datetime(2026, 9, 28, 12, 0, tzinfo=zone or NY))
    dates = [a for a in agent.actions if a.get('kind') == 'date']
    assert len(dates) == 6 and dates[0]['label'].startswith('Tomorrow')
    assert all(a['date'] != '2026-09-28' for a in dates)
    agent.handle(dates[0]['message'])
    assert all(o.date == date(2026, 9, 29) for o in agent.flow.options)


def test_any_time_button_keeps_selected_date_range(database):
    agent = prepared()
    agent.handle('Wednesday morning')
    before = (agent.flow.preference.date, agent.flow.preference.end_date)
    payload = next(a['message'] for a in agent.actions if a['label'] == 'Any time')
    agent.handle(payload)
    assert (agent.flow.preference.date, agent.flow.preference.end_date) == before
    assert agent.flow.preference.period == 'any'
    assert all(o.date == DAY for o in agent.flow.options)


def test_menu_interrupt_during_edit_keeps_menu_actions_and_can_resume(database, no_email):
    agent = NextDimAgent(client=ScriptedClient(INTAKE))
    agent.handle('details'); agent.handle('edit details')
    agent.handle('my bookings')
    assert agent.step == MENU
    assert 'Book an appointment' in {a['label'] for a in agent.actions}
    agent.handle('continue')
    assert agent.step == REGISTRY and agent.flow.editing == 'patient'
    agent.handle('keep current details')
    assert agent.flow.editing is None
    agent.handle('yes')
    agent.handle('book appointment')
    assert agent.step == COMPLAINT and agent.flow.editing is None


def test_actions_are_string_valued_for_existing_api_contract(database):
    from app.schemas import TurnOut
    agent = prepared()
    for message in ['Wednesday morning', '1', 'yes']:
        reply = agent.handle(message)
        parsed = TurnOut(session_id='test', reply=reply, step=agent.step,
                         done=agent.step == DONE, events=[], booking=agent.booking,
                         actions=agent.actions)
        assert parsed.actions == agent.actions
        assert all(isinstance(value, str) for action in parsed.actions for value in action.values())


@pytest.mark.parametrize('message', [
    'Change from 2125550100 to 2125550199',
    'My old phone is 2125550100 and my new phone is 2125550199',
])
def test_old_and_new_numbers_do_not_force_the_first_literal(message):
    result = validate_contact_values({'phone': '2125550199'}, message)
    assert result.values['phone'] == '+12125550199' and not result.errors