"""Hash observable outputs on a private copy of a repository's supplied database.

Run this through compare_repositories.py. No patient records are written to the
report; only output hashes are retained. No live model calls are made.
"""
import argparse
import hashlib
import importlib
import inspect
import json
import shutil
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path


def digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository', type=Path)
    parser.add_argument('--stub-openai', action='store_true', help='Explicitly replace the SDK import; any real client construction fails.')
    args = parser.parse_args()
    root = args.repository.resolve()
    if not (root / 'app' / 'db.py').is_file():
        parser.error(f'Not a VAST repository: {root}')
    sys.path.insert(0, str(root))
    if args.stub_openai:
        sdk = types.ModuleType('openai')
        class NoLiveOpenAI:
            def __init__(self, *args, **kwargs):
                raise AssertionError('The parity probe must not call the live SDK')
        sdk.OpenAI = NoLiveOpenAI
        sys.modules['openai'] = sdk

    from app import db
    from app.main import app
    from tools import available_slots as calendar
    from tools.book import book_appointment
    from tools.match_clinics import nearest_candidates, nearest_clinics
    from tools.patients import read, update_patient
    from tools.rank_slots import rank_slots

    cases = {'openapi': digest(app.openapi())}
    public = {
        'tools.available_slots': ('window', 'zone_for', 'now', 'moment', 'bookable_days', 'slots_of_day', 'as_date', 'minutes_of', 'in_period', 'available_slots'),
        'tools.book': ('book_appointment', '_is_taken'),
        'tools.patients': ('find_patient', 'register_patient', 'update_patient', 'read', '_address', '_on_file', 'reason_for'),
        'tools.match_clinics': ('distance_km', 'nearest_clinics', 'nearest_candidates', 'suggest_clinics'),
        'tools.rank_slots': ('rank_slots', 'sort_key', '_slots_of', '_drift', '_row'),
        'app.chat': ('chat', 'reset', 'index', 'config'),
    }
    for module_name, names in public.items():
        module = importlib.import_module(module_name)
        for name in names:
            signature = inspect.signature(getattr(module, name))
            # Moving a schema to another module must not change call conventions.
            shape = [(p.name, p.kind.name, repr(p.default)) for p in signature.parameters.values()]
            cases[f'signature:{module_name}.{name}'] = digest(shape)

    def record(label, function, *args, **kwargs):
        try:
            result = {'result': function(*args, **kwargs)}
        except Exception as error:
            result = {'exception': type(error).__name__, 'message': str(error)}
        cases[label] = digest(result)

    with tempfile.TemporaryDirectory(prefix='vast-parity-') as directory:
        private_db = Path(directory) / 'vast.db'
        shutil.copy2(root / 'data' / 'vast.db', private_db)
        db.DB_PATH = private_db
        db.init_db()
        calendar.now = lambda zone=None: datetime(2026, 9, 28, 10, 0, tzinfo=zone or calendar.PORTAL_ZONE)
        conn = db.connect()
        try:
            clinic_ids = [row[0] for row in conn.execute('SELECT id FROM clinics ORDER BY id')]
            patient_ids = [row[0] for row in conn.execute('SELECT id FROM patients ORDER BY id')]
            counts = {table: conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('clinics', 'patients', 'bookings')}
        finally:
            conn.close()
        cases['initial_counts'] = digest(counts)
        for clinic in clinic_ids:
            for day in [*calendar.window(), None, '2020-01-01']:
                record(f'available:{clinic}:{day}', calendar.available_slots, clinic, day)
        sample_patients = patient_ids[::max(1, len(patient_ids) // 8)][:9]
        for patient in sample_patients:
            for count in (None, 0, 3, -1):
                record(f'nearest:{patient}:{count}', nearest_clinics, patient, count)
            record(f'candidates:{patient}', nearest_candidates, patient, '2026-09-30')
            for period in ('any', 'morning', 'afternoon', 'evening'):
                for day in (None, '2026-09-30'):
                    for at in (None, '11:30'):
                        events = []
                        def ranked():
                            rows = rank_slots(patient, day, 'ENT', period, at, on_event=events.append)
                            return {'rows': rows, 'events': events}
                        record(f'rank:{patient}:{period}:{day}:{at}', ranked)
        record('unknown_patient', nearest_clinics, -1)
        record('unknown_clinic', calendar.available_slots, -1, '2026-09-30')
        if clinic_ids and patient_ids:
            clinic, patient = clinic_ids[0], patient_ids[0]
            record('booking_invalid', book_appointment, clinic, patient, '2020-01-01', '09:15')
            record('booking_outside_window', book_appointment, clinic, patient, '2020-01-01', '09:00')
            record('booking_conflict', book_appointment, clinic, patient, '2020-01-01', '09:00')
            record('patient_before', read, patient)
            record('patient_noop', update_patient, patient, {'first_name': None})
            record('patient_change', update_patient, patient, {'complaints': 'Parity-check synthetic text'})
            record('patient_after', read, patient)
        conn = db.connect()
        try:
            for table in ('clinics', 'patients', 'bookings'):
                cases[f'final_table:{table}'] = digest([dict(row) for row in conn.execute(f'SELECT * FROM {table} ORDER BY id')])
        finally:
            conn.close()
    print(json.dumps({'case_count': len(cases), 'cases': cases}, sort_keys=True))


if __name__ == '__main__':
    main()
