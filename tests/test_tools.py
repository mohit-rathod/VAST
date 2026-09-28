from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
import sqlite3

import pytest
from app import db
from app.geo import coordinates_of
from domain.models import Location, PatientIntake, PatientUpdate
from tools.available_slots import available_slots, bookable_days, in_period, slots_of_day, window, zone_for
from tools.book import book_appointment
from tools.match_clinics import nearest_clinics, suggest_clinics
from tools.patients import find_patient, read, register_patient, update_patient
from tools.rank_slots import rank_slots, sort_key
from helpers import ScriptedClient

DAY = '2026-09-30'


def test_calendar_contract():
    assert [str(day) for day in window()] == ['2026-09-30', '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04']
    slots = slots_of_day(date.fromisoformat(DAY))
    assert len(slots) == 16 and slots[0] == ('09:00', '09:30') and slots[-1] == ('16:30', '17:00')
    assert bookable_days()[0] == dict(date=DAY, weekday='Wednesday', in_days=2, bookable=True)
    assert zone_for(None).key == zone_for('99999').key == 'America/New_York'


@pytest.mark.parametrize('clock,period,expected', [('11:30','morning',True),('12:00','morning',False),('16:30','afternoon',True),('17:00','afternoon',False),('16:30','evening',False),('09:00','any',True)])
def test_period_boundaries(clock, period, expected):
    assert in_period(clock, period) is expected


@pytest.mark.parametrize('status,busy', [('booked',True),('confirmed',True),('cancelled',False),('completed',False)])
def test_available_slots_statuses(database, status, busy):
    result = book_appointment(1, 1, DAY, '09:00', status)
    assert result['ok']
    free = available_slots(1, DAY)
    assert len(free) == 16 - int(busy)
    assert ('09:00' in {row['start_time'] for row in free}) is not busy


def test_available_slots_window_and_unknown_clinic(database):
    assert len(available_slots(1)) == 80
    assert available_slots(999, '2020-01-01') == []


def test_booking_results_and_conflicts(database):
    assert book_appointment(1, 1, DAY, '09:15') == {'ok': False, 'error': '09:15 is not a slot on 2026-09-30'}
    expected = dict(ok=True, booking_id=1, clinic_id=1, patient_id=1, slot_date=DAY, start_time='09:00', end_time='09:30', status='booked')
    assert book_appointment(1, 1, DAY, '09:00') == expected
    assert book_appointment(1, 2, DAY, '09:00') == dict(ok=False, error='clinic 1 is already booked on 2026-09-30 at 09:00', taken=True)


@pytest.mark.parametrize('clinic,patient', [(999,1),(1,999)])
def test_booking_foreign_keys(database, clinic, patient):
    assert book_appointment(clinic, patient, DAY, '09:00') == dict(ok=False, error='FOREIGN KEY constraint failed', taken=True)


def test_cancelled_booking_still_has_unique_constraint(database):
    assert book_appointment(1, 1, DAY, '09:00', 'cancelled')['ok']
    result = book_appointment(1, 2, DAY, '09:00')
    assert result['taken'] and not result['ok'] and 'UNIQUE constraint failed' in result['error']


def test_direct_booking_rejects_outside_window_and_arbitrary_status(database):
    assert not book_appointment(1, 1, '2020-01-01', '09:00', 'custom')['ok']
    assert not book_appointment(1, 1, DAY, '09:00', 'custom')['ok']


def test_booking_race_has_one_winner(database):
    count = 8
    barrier = Barrier(count)
    def attempt(_):
        barrier.wait(timeout=10)
        return book_appointment(1, 1, DAY, '10:00')
    with ThreadPoolExecutor(max_workers=count) as executor:
        results = list(executor.map(attempt, range(count)))
    assert sum(result['ok'] for result in results) == 1
    assert all(result.get('taken') for result in results if not result['ok'])
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM bookings').fetchone()[0] == 1


def test_patient_identity_and_read(database):
    assert find_patient('test@example.test', '2125550100')['id'] == 1
    assert find_patient('test@example.test', '2125550999') is None
    assert find_patient('unknown@example.test', '2125550100') is None
    assert read(999) == {}


def new_patient(zip_code='10001', email='new@example.test'):
    return PatientIntake(first_name='New', last_name='Patient', email=email, phone='2125550102'), Location(address='New Street', city='New York', state='NY', zip=zip_code)


def test_register_and_duplicate_email(database):
    result = register_patient(*new_patient())
    assert result['ok'] and result['patient']['id'] == 3
    assert result['patient']['date_of_birth'] is None and result['patient']['complaints'] == ''
    assert register_patient(*new_patient()) == dict(ok=False, error='that email is already registered to a different phone number')


def test_unknown_zip_registration_returns_explained_error(database):
    result = register_patient(*new_patient('99999'))
    assert not result['ok'] and 'no coordinates' in result['error']


def test_patient_updates(database):
    assert update_patient(1, PatientUpdate(phone='2125550999'))['patient']['phone'] == '+12125550999'
    assert update_patient(1, {'first_name': None})['patient']['first_name'] == 'Test'
    assert update_patient(1, {'complaints':'Updated'})['patient']['complaints'] == 'Updated'
    assert update_patient(999, {}) == dict(ok=True, patient={})
    assert update_patient(999, {'first_name':'Nobody'}) == dict(ok=True, patient={})
    assert update_patient(1, {'email':'other@example.test'}) == dict(ok=False, error='that email is already registered to a different phone number')


def test_unknown_zip_update_result(database):
    assert update_patient(1, {'zip':'99999'}) == dict(ok=False, error='no coordinates for that ZIP, so I cannot match clinics to it: 99999')


def test_zip_update_refreshes_coordinates(database):
    result = update_patient(1, {'zip':'11215'})['patient']
    assert result['zip'] == '11215'
    assert (result['latitude'], result['longitude']) == coordinates_of('11215')


def test_unknown_update_column_still_raises(database):
    with pytest.raises(ValueError, match='Unknown'):
        update_patient(1, {'unexpected':'value'})


def test_nearest_clinics_filters_and_limits(database):
    rows = nearest_clinics(1, count=None, speciality='ENT')
    assert [row['clinic_id'] for row in rows] == [1,2,3]
    assert rows[0]['distance_km'] == 0.0 and rows[0]['zone'] == 'America/New_York'
    assert nearest_clinics(1, count=0) == []
    assert nearest_clinics(1, speciality='oncology') == []
    with pytest.raises(ValueError, match='no patient 999'):
        nearest_clinics(999)


@pytest.mark.parametrize('period,time', [('morning','10:00'),('afternoon','14:00'),('any','12:00')])
def test_ranking_periods(database, period, time):
    rows = rank_slots(1, DAY, 'ENT', period=period)
    assert [row['clinic_id'] for row in rows] == [1,2,3]
    assert all(row['start_time']==time and not row['widened'] for row in rows)


def test_explicit_time_controls_ranking(database):
    rows = rank_slots(1, DAY, 'ENT', period='morning', at='11:30')
    assert all(row['start_time']=='11:30' for row in rows)


def test_ranking_widening_and_evening(database):
    for clinic in (1,2,3):
        for hour in range(9,12):
            for minute in ('00','30'):
                assert book_appointment(clinic,1,DAY,f'{hour:02d}:{minute}')['ok']
    events=[]
    rows = rank_slots(1,DAY,'ENT','morning',on_event=events.append)
    assert rows[0]['date']=='2026-10-01' and all(row['widened'] for row in rows)
    assert len(events)==2
    assert rank_slots(1,DAY,'ENT','evening')==[]


def test_speciality_fallback(database):
    events=[]
    rows=rank_slots(1,DAY,'oncology',on_event=events.append)
    assert rows and events[0]['kind']=='note'


def test_suggest_clinics_filters_invented_ids_but_keeps_slot_strings(database):
    client=ScriptedClient({'clinics':[{'clinic_id':999,'reason':'bad'}, {'clinic_id':1,'reason':'near','suggested_slots':['99:99-99:99']}]})
    events=[]
    result=suggest_clinics(1,DAY,client=client,on_event=events.append)
    assert len(result)==1 and result[0]['clinic_id']==1
    assert result[0]['suggested_slots']==['99:99-99:99']
    assert events[-1]['kind']=='note'


def test_sort_key():
    row=dict(day_gap=1,drift_minutes=30,distance_km=2.0,free_slots=5)
    assert sort_key(row)==(1,2.0,30,-5)
    assert sort_key(row,True)==(1,30,2.0,-5)