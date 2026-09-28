"""Chat-only contact flows: opt in explicitly, never invoke email delivery."""
import pytest

from app import db
from app.config import email_verification_required
from agents.nextdim.agent import NextDimAgent
from agents.nextdim.conversation import (
    CONTACT_CONFIRM, DONE, MENU, RECOVERY, RECOVERY_ID, REGISTRY, VERIFY,
)
from agents.nextdim.steps import account
from helpers import INTAKE, ScriptedClient
from tools.patients import read, update_patient


@pytest.fixture
def chat_only(monkeypatch, offline_verification):
    monkeypatch.setenv('VAST_REQUIRE_EMAIL_VERIFICATION', 'false')
    service, sender = offline_verification

    def forbidden(*args, **kwargs):
        raise AssertionError('Chat-only mode must not issue or verify email codes')

    monkeypatch.setattr(service, 'issue', forbidden)
    monkeypatch.setattr(service, 'verify', forbidden)
    yield sender
    assert sender.sent == []


def recovering(*corrections):
    return NextDimAgent(client=ScriptedClient(
        {**INTAKE, 'phone': '2125550199'}, *corrections,
    ))


def pending_update():
    agent = recovering({'email': 'changed@example.test', 'phone': '(212) 555-0199'})
    agent.handle('my details')
    agent.handle('updated email and phone')
    assert agent.step == CONTACT_CONFIRM
    return agent


@pytest.mark.parametrize('value,required', [
    (None, True), ('true', True), ('1', True), ('unexpected', True), ('', True),
    ('false', False), (' FALSE ', False), ('0', False), ('no', False), ('off', False),
])
def test_verification_is_disabled_only_by_explicit_configuration(monkeypatch, value, required):
    if value is None:
        monkeypatch.delenv('VAST_REQUIRE_EMAIL_VERIFICATION', raising=False)
    else:
        monkeypatch.setenv('VAST_REQUIRE_EMAIL_VERIFICATION', value)
    assert email_verification_required() is required


def test_exact_login_needs_no_email_code(database, chat_only):
    agent = NextDimAgent(client=ScriptedClient({**INTAKE, 'phone': '(212) 555-0100'}))
    assert 'confirmation to' not in agent.start()
    reply = agent.handle('my details')
    assert agent.step == REGISTRY and agent.patient['id'] == 1
    assert '+12125550100' in reply and 'verification code' not in reply.lower()
    assert agent.flow.challenge is None
    agent.handle('yes')
    assert agent.step == MENU
    assert 'View all my bookings' in {a['label'] for a in agent.actions}


def test_mismatch_collects_both_normalizes_and_waits_for_confirmation(database, chat_only):
    before = read(1)
    agent = recovering({'email': 'changed@example.test'}, {'phone': '(212) 555-0199'})
    reply = agent.handle('my details')
    assert agent.step == RECOVERY and 'No email will be sent' in reply
    reply = agent.handle('new email')
    assert agent.step == RECOVERY and 'both' in reply and 'verified' not in reply
    assert read(1) == before
    reply = agent.handle('new phone')
    assert agent.step == CONTACT_CONFIRM and agent.patient is None
    assert not agent.flow.verified and agent.flow.challenge is None
    assert 'changed@example.test' in reply and '+12125550199' in reply
    assert 'Account verified' not in reply
    assert read(1) == before
    agent.handle('yes')
    after = read(1)
    assert agent.step == REGISTRY and after['id'] == before['id']
    assert (after['email'], after['phone']) == ('changed@example.test', '+12125550199')
    assert after['address'] == before['address']
    assert agent.flow.contact_fingerprint is None and agent.flow.challenge is None
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM patients').fetchone()[0] == 2
        assert conn.execute('SELECT phone FROM patients WHERE id=1').fetchone()[0] == '+12125550199'


def test_corrected_contacts_are_read_back_before_the_write(database, chat_only):
    before = read(1)
    agent = recovering(
        {'email': 'changed@example.test', 'phone': '2125550199'},
        {'email': 'corrected@example.test', 'phone': '(212) 555-0188'},
    )
    agent.handle('details'); agent.handle('update')
    reply = agent.handle('use corrected email and phone instead')
    assert 'corrected@example.test' in reply and '+12125550188' in reply
    assert read(1) == before
    agent.handle('yes')
    assert (read(1)['email'], read(1)['phone']) == ('corrected@example.test', '+12125550188')


def test_recovery_history_is_blocked_until_contact_confirmation(database, chat_only):
    agent = pending_update()
    reply = agent.handle('my bookings')
    assert agent.step == CONTACT_CONFIRM
    assert 'confirm your contact details' in reply
    assert agent.booking_history is None and agent.patient is None
    assert 'verify' not in agent.handle('all clinics').lower()
    assert agent.step == CONTACT_CONFIRM
    agent.handle('yes'); agent.handle('yes')
    assert 'no bookings on record' in agent.handle('my bookings')


def test_both_changed_contacts_can_recover_using_previous_email(database, chat_only):
    agent = NextDimAgent(client=ScriptedClient(
        {**INTAKE, 'email': 'changed@example.test', 'phone': '2125550199'},
        {'email': 'changed@example.test', 'phone': '2125550199'},
    ))
    agent.handle('details')
    reply = agent.handle('recover account')
    assert agent.step == RECOVERY_ID and 'No email will be sent' in reply
    agent.handle('test@example.test')
    assert agent.step == RECOVERY
    agent.handle('updated details')
    assert agent.step == CONTACT_CONFIRM
    agent.handle('yes')
    assert agent.patient['id'] == 1 and read(1)['email'] == 'changed@example.test'


def test_ambiguous_contacts_do_not_automatically_choose_a_record(database, chat_only):
    before = read(1), read(2)
    agent = NextDimAgent(client=ScriptedClient({**INTAKE, 'phone': '2125550101'}))
    agent.handle('details')
    assert agent.step == RECOVERY_ID and agent.patient is None
    assert (read(1), read(2)) == before


def test_duplicate_email_cannot_overwrite_another_patient(database, chat_only):
    before = read(1), read(2)
    agent = recovering({'email': 'other@example.test', 'phone': '2125550199'})
    agent.handle('details'); agent.handle('update')
    assert 'cannot be saved' in agent.handle('yes')
    assert agent.step == CONTACT_CONFIRM and not agent.flow.verified
    assert (read(1), read(2)) == before


def test_stale_confirmation_rejects_concurrent_contact_change(database, chat_only):
    agent = pending_update()
    assert update_patient(1, {'phone': '2125550111'})['ok']
    reply = agent.handle('yes')
    assert 'account changed' in reply.lower() and 'verif' not in reply.lower()
    assert read(1)['phone'] == '+12125550111' and read(1)['email'] == 'test@example.test'
    assert agent.step == CONTACT_CONFIRM


def test_missing_contact_snapshot_does_not_allow_a_write(database, chat_only):
    agent = pending_update()
    before = read(1)
    agent.flow.contact_fingerprint = None
    assert 'start a new chat' in agent.handle('yes').lower()
    assert read(1) == before


def test_ending_chat_abandons_unconfirmed_contact_update(database, chat_only):
    agent = pending_update()
    before = read(1)
    agent.handle('end chat'); agent.handle('yes')
    assert agent.step == DONE and read(1) == before
    assert agent.flow.contact_fingerprint is None and agent.flow.contact_update == {}


def test_existing_bookings_remain_with_patient_after_update_and_relogin(database, chat_only):
    with db.connect() as conn:
        conn.executemany(
            'INSERT INTO bookings(clinic_id, patient_id, slot_date, start_time, end_time, status) VALUES (?, ?, ?, ?, ?, ?)',
            [(1, 1, '2026-10-01', '10:00', '10:30', 'booked'),
             (2, 1, '2026-10-02', '11:00', '11:30', 'booked'),
             (3, 2, '2026-10-03', '12:00', '12:30', 'booked')],
        )
    first = pending_update()
    first.handle('yes')
    fresh = NextDimAgent(client=ScriptedClient({**INTAKE, 'email': 'changed@example.test', 'phone': '2125550199'}))
    fresh.handle('details'); fresh.handle('yes')
    reply = fresh.handle('my bookings')
    assert len(fresh.booking_history) == 2
    assert {r['clinic_id'] for r in fresh.booking_history} == {1, 2}
    assert all(r['patient_id'] == 1 for r in fresh.booking_history)
    assert 'Thursday 2026-10-01' in reply and 'Friday 2026-10-02' in reply


def test_missing_snapshot_or_contacts_cannot_bypass_confirmation_step(database, chat_only):
    agent = NextDimAgent(client=ScriptedClient())
    before = read(1)
    assert 'contact details first' in account.save_contacts(agent.context, 'yes')
    assert read(1) == before
    agent.flow.recovery_patient_id = 1
    agent.flow.step = CONTACT_CONFIRM
    agent.flow.contact_update = {'email': 'changed@example.test'}
    assert 'both' in account.save_contacts(agent.context, 'yes')
    assert agent.step == RECOVERY and read(1) == before


def test_legacy_phone_without_area_code_can_be_replaced_in_chat(database, chat_only):
    with db.connect() as conn:
        conn.execute("UPDATE patients SET phone='+1-555-1001' WHERE id=1")
        db.normalize_patient_phones(conn)
    assert read(1)['phone'] is None
    agent = pending_update()
    assert agent.flow.contact_fingerprint == ('test@example.test', None)
    agent.handle('yes')
    assert read(1)['phone'] == '+12125550199'
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM patient_phone_issues WHERE patient_id=1').fetchone()[0] == 0


def test_disabled_email_handles_an_already_pending_verification_step(database, chat_only):
    agent = NextDimAgent(client=ScriptedClient())
    agent.flow.step = VERIFY
    agent.flow.recovery_patient_id = 1
    agent.flow.verification_purpose = 'login'
    reply = agent.handle('resend code')
    assert agent.step == REGISTRY and 'verification code' not in reply.lower()


def test_invalid_phone_is_not_saved_even_without_email(database, chat_only):
    agent = recovering(*[{'email': 'changed@example.test', 'phone': '555-0199'}] * 2)
    before = read(1)
    agent.handle('details')
    reply = agent.handle('incomplete phone')
    assert agent.step == RECOVERY and read(1) == before
    assert 'phone' in reply.lower()