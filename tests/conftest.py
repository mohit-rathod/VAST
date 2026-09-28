"""Temporary databases and explicit offline SDK bootstrap for regression tests."""
import os
import sys
import types
from pathlib import Path

# Baseline verification can point the same tests at the unmodified upload.
ROOT = Path(os.environ.get('VAST_REPO_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
if os.getenv('VAST_TEST_STUB_OPENAI') == '1':
    sdk = types.ModuleType('openai')
    class UnavailableOpenAI:
        def __init__(self, *args, **kwargs):
            raise AssertionError('Live OpenAI calls are disabled in offline tests')
    sdk.OpenAI = UnavailableOpenAI
    sys.modules['openai'] = sdk

import pytest
from app import db


@pytest.fixture
def database(tmp_path, monkeypatch):
    """Never open or modify the supplied data/vast.db during tests."""
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'vast.db')
    db.init_db()
    with db.connect() as conn:
        conn.executemany(
            'INSERT INTO clinics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                (1, 'Clinic A', 'ENT', 'A Street', 'New York', 'NY', '10001', 40.7549, -73.9844),
                (2, 'Clinic B', 'ENT', 'B Street', 'New York', 'NY', '11215', 40.6724, -73.9778),
                (3, 'Clinic C', 'ENT', 'C Street', 'New York', 'NY', '10032', 40.8477, -73.9390),
                (4, 'Clinic D', 'cardiology', 'D Street', 'New York', 'NY', '10004', 40.7075, -74.0113),
            ],
        )
        conn.executemany(
            'INSERT INTO patients VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                (1, 'Test', 'Patient', 'test@example.test', '2125550100', None, 'Home Street', 'New York', 'NY', '10001', 40.7549, -73.9844, 'Ear trouble'),
                (2, 'Other', 'Patient', 'other@example.test', '2125550101', '1990-01-01', 'Other Street', 'New York', 'NY', '11215', 40.6724, -73.9778, 'Checkup'),
            ],
        )
    return db.DB_PATH


@pytest.fixture(autouse=True)
def frozen_portal_clock(monkeypatch):
    from datetime import datetime, date
    from tools import available_slots as calendar
    monkeypatch.setattr(calendar, 'FIRST_DAY', date(2026, 9, 30))
    monkeypatch.setattr(calendar, 'DAYS', 5)
    monkeypatch.setattr(calendar, 'now', lambda zone=None: datetime(2026, 9, 28, 10, 0, tzinfo=zone or calendar.PORTAL_ZONE))


@pytest.fixture(autouse=True)
def offline_verification(monkeypatch):
    monkeypatch.setenv('VAST_REQUIRE_EMAIL_VERIFICATION', 'true')
    from app import email_delivery
    from services.verification import VerificationService
    from helpers import MemorySender
    sender = MemorySender()
    service = VerificationService(sender)
    monkeypatch.setattr(email_delivery, 'verification_service', lambda: service)
    # Codes are deterministic only in tests and never in production.
    monkeypatch.setattr('services.verification.secrets.randbelow', lambda _: 246810)
    return service, sender
