"""Concurrent wrong USSD PINs cannot exceed the attempt limit (PostgreSQL row lock on the PIN credential).

Without the lock, parallel wrong attempts read the same failure count and overwrite each other, so an
attacker holding the handset gets more than three guesses per lock window. Needs PostgreSQL:
    POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/fundbridge_test pytest tests/integration
SQLite ignores row locks; the limitation is documented in docs/DEPLOYMENT.md.
"""

from __future__ import annotations

import os
import threading

import pytest

from app import create_app
from app.extensions import db
from app.models.messaging import MessagingPinCredential

from .conftest import BASE_CONFIG, CALLBACK_TOKEN

PG_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL")
PHONE = "+254712345678"
WORKERS = 8


@pytest.mark.skipif(not PG_URL, reason="set POSTGRES_TEST_DATABASE_URL to an isolated PostgreSQL test database")
def test_parallel_wrong_pins_cannot_exceed_attempt_limit():
    app = create_app({**BASE_CONFIG, "SQLALCHEMY_DATABASE_URI": PG_URL})
    with app.app_context():
        db.drop_all()
        db.create_all()
        from app.models.core import BeneficiaryProfile

        profile = BeneficiaryProfile(display_name="Amina", phone_number=PHONE, country_code="KE",
                                     verification_status="verified")
        db.session.add(profile)
        db.session.commit()
        profile_id = profile.id
    setup = app.test_client().post(f"/api/v1/messaging/ussd?token={CALLBACK_TOKEN}",
                                   data={"sessionId": "create", "phoneNumber": PHONE, "text": "2*4826*4826"})
    assert setup.status_code == 200

    barrier, lock, replies = threading.Barrier(WORKERS), threading.Lock(), []

    def attempt(i: int) -> None:
        client = app.test_client()
        barrier.wait()
        res = client.post(f"/api/v1/messaging/ussd?token={CALLBACK_TOKEN}",
                          data={"sessionId": f"race-{i}", "phoneNumber": PHONE, "text": f"2*{1000 + i * 111}"})
        with lock:
            replies.append(res.get_data(as_text=True))

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    wrong = [r for r in replies if r.startswith("END Wrong PIN")]
    locked = [r for r in replies if r.startswith("END Too many wrong PINs")]
    with app.app_context():
        row = db.session.get(MessagingPinCredential, profile_id)
        locked_until = row.locked_until
        db.session.remove()
        db.drop_all()
    # Serialised: two "wrong" replies, then the lock; every later attempt is refused.
    assert len(wrong) == 2 and len(locked) == WORKERS - 2, replies
    assert locked_until is not None
