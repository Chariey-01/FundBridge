"""Migration integrity: one Alembic head, and ``upgrade head`` yields exactly the model schema.

Regression for integration defect M-0 (2026-11-11): the messaging migration and the
backend's idempotency-scope migration both revised ``18323330d500``. That left two heads,
so ``flask db upgrade`` refused to run on a fresh deployment.

Runs on SQLite always and on PostgreSQL when ``POSTGRES_TEST_DATABASE_URL`` is set
(the PostgreSQL database is dropped and recreated schema-by-schema, so use a disposable one).
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from app import create_app
from app.extensions import db

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
POSTGRES_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL")

BASE = {
    "TESTING": True,
    "SECRET_KEY": "test-secret",
    "JWT_SECRET_KEY": "test-jwt-secret-with-at-least-thirty-two-bytes",
    "AI_PROVIDER": "disabled",
    "SMS_PROVIDER": "simulator",
}


def _script() -> ScriptDirectory:
    cfg = Config(str(MIGRATIONS / "alembic.ini"))
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return ScriptDirectory.from_config(cfg)


def test_single_alembic_head():
    heads = _script().get_heads()
    assert len(heads) == 1, f"multiple Alembic heads {heads}; chain the newest migration after the other head"


def test_upgrade_keeps_application_access_logger_enabled(tmp_path):
    """Alembic logging must not disable the application's PII-safe access logger."""
    from flask_migrate import upgrade

    url, app = _app_for("sqlite", tmp_path)
    logger = logging.getLogger("fundbridge.http")
    previous = logger.disabled
    logger.disabled = False
    with app.app_context():
        try:
            upgrade(directory=str(MIGRATIONS))
            assert logger.disabled is False
        finally:
            _dispose(url)
            logger.disabled = previous


def _reset(url: str) -> None:
    if url.startswith("postgresql"):
        engine = sa.create_engine(url)
        with engine.begin() as conn:
            conn.execute(sa.text("DROP SCHEMA public CASCADE"))
            conn.execute(sa.text("CREATE SCHEMA public"))
        engine.dispose()


def _app_for(backend, tmp_path):
    if backend == "postgresql" and not POSTGRES_URL:
        pytest.skip("set POSTGRES_TEST_DATABASE_URL to a disposable PostgreSQL database")
    url = POSTGRES_URL if backend == "postgresql" else f"sqlite:///{tmp_path / 'migr.db'}"
    _reset(url)
    return url, create_app({**BASE, "SQLALCHEMY_DATABASE_URI": url})


def _dispose(url):
    db.session.remove()
    db.engine.dispose()
    _reset(url)


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_upgrade_head_matches_models(backend, tmp_path):
    from flask_migrate import upgrade

    url, app = _app_for(backend, tmp_path)
    with app.app_context():
        try:
            upgrade(directory=str(MIGRATIONS))
            with db.engine.connect() as conn:
                diff = compare_metadata(MigrationContext.configure(conn), db.metadata)
                revision = MigrationContext.configure(conn).get_current_revision()
            # Index naming differences are cosmetic; tables, columns and constraints must match.
            material = [d for d in diff if not (isinstance(d, tuple) and d[0] in ("add_index", "remove_index"))]
            assert material == [], f"migrations and models disagree: {material}"
            assert revision == _script().get_current_head()
        finally:
            _dispose(url)


DEFECT_M2 = ("DEFECT M-2: the initial migration's downgrade drops tables but not the PostgreSQL enum types "
             "(role, campaignstatus, donationstatus, payoutstatus), so upgrade after a full rollback fails "
             "with DuplicateObject")


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_full_downgrade_then_upgrade(backend, tmp_path):
    from flask_migrate import downgrade, upgrade

    url, app = _app_for(backend, tmp_path)
    with app.app_context():
        try:
            upgrade(directory=str(MIGRATIONS))
            downgrade(directory=str(MIGRATIONS), revision="base")
            upgrade(directory=str(MIGRATIONS))
        finally:
            _dispose(url)


SEED_AT_18323330 = [
    "INSERT INTO \"user\" (id, email, role, status, created_at, updated_at) VALUES "
    "('u1', 'd@example.test', 'donor', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
    "('u2', 'c@example.test', 'creator', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
    "('u3', 'b@example.test', 'beneficiary', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    "INSERT INTO beneficiary_profile (id, user_id, display_name, phone_number, preferred_language, country_code, "
    "verification_status, payout_destination_reference, created_at, updated_at) VALUES ('b1', 'u3', 'B', "
    "'+254700000001', 'en', 'KE', 'verified', 'tok', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    "INSERT INTO campaign (id, creator_id, beneficiary_id, title, slug, description, category, goal_amount, "
    "goal_currency, status, review_status, created_at, updated_at) VALUES ('c1', 'u2', 'b1', 'Title', 'slug-one', "
    "'a long enough description', 'health', 100, 'USD', 'published', 'approved', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    "INSERT INTO donation (id, campaign_id, donor_id, amount, currency, provider, provider_order_id, "
    "provider_capture_id, status, idempotency_key, created_at, updated_at) VALUES "
    "('d1', 'c1', 'u1', 25.50, 'USD', 'paypal', 'ORDER-1', 'CAP-1', 'completed', 'k1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
    "('d2', 'c1', 'u1', 5.00, 'USD', 'paypal', 'ORDER-2', NULL, 'pending', 'k2', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    "INSERT INTO financial_ledger_entry (id, campaign_id, donation_id, payout_id, entry_type, amount, currency, "
    "reference, created_at) VALUES ('l1', 'c1', 'd1', NULL, 'donation_completed', 25.50, 'USD', 'donation-capture:CAP-1', "
    "CURRENT_TIMESTAMP)",
    "INSERT INTO payout (id, beneficiary_id, campaign_id, amount, currency, destination_type, destination_reference, "
    "provider, status, idempotency_key, created_at, updated_at) VALUES ('p1', 'b1', 'c1', 10.00, 'USD', 'wallet', "
    "'tok', 'simulator', 'requested', 'pk1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    "INSERT INTO financial_ledger_entry (id, campaign_id, donation_id, payout_id, entry_type, amount, currency, "
    "reference, created_at) VALUES ('l2', 'c1', NULL, 'p1', 'payout_reserved', 10.00, 'USD', 'payout-reservation:p1', "
    "CURRENT_TIMESTAMP)",
]
FINANCIAL = {
    "donation": "SELECT id, amount, currency, status, provider_order_id, provider_capture_id, idempotency_key FROM donation",
    "ledger": "SELECT id, entry_type, amount, currency, reference, donation_id, payout_id FROM financial_ledger_entry",
    "payout": "SELECT id, amount, currency, status, destination_reference, idempotency_key FROM payout",
}


def _financial_rows(conn):
    return {name: sorted(tuple(str(v) for v in row) for row in conn.execute(sa.text(sql)))
            for name, sql in FINANCIAL.items()}


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_upgrade_preserves_existing_financial_data(backend, tmp_path):
    """Was DEFECT M-1 (NOT NULL fingerprint without default); fixed in feat/backend-core ee43660 by backfilling."""
    from flask_migrate import upgrade

    url, app = _app_for(backend, tmp_path)
    with app.app_context():
        try:
            upgrade(directory=str(MIGRATIONS), revision="18323330d500")
            with db.engine.begin() as conn:
                for statement in SEED_AT_18323330:
                    conn.execute(sa.text(statement))
                before = _financial_rows(conn)
            upgrade(directory=str(MIGRATIONS))
            with db.engine.connect() as conn:
                assert _financial_rows(conn) == before  # nothing lost or altered
                fingerprints = dict(conn.execute(sa.text("SELECT id, idempotency_fingerprint FROM donation")).all())
                assert fingerprints == {"d1": "legacy-d1", "d2": "legacy-d2"}
                assert conn.execute(sa.text("SELECT requested_by FROM payout")).scalar() is None
        finally:
            _dispose(url)


DEFECT_M1B = ("DEFECT M-1b: a database built from the original a0d4581f14e2 (before c3e4e3a edited it in place) keeps "
              "the global UNIQUE(idempotency_key) on donation and payout after upgrading to head, so two users who send "
              "the same Idempotency-Key collide (IntegrityError, HTTP 500) instead of getting independent requests")


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_upgrade_from_original_initial_schema_drops_global_key_uniqueness(backend, tmp_path):
    from flask_migrate import upgrade

    url, app = _app_for(backend, tmp_path)
    with app.app_context():
        try:
            upgrade(directory=str(MIGRATIONS), revision="18323330d500")
            with db.engine.begin() as conn:
                # Recreate what the original initial migration (git show 1a3a9d9) created.
                if backend == "postgresql":
                    conn.execute(sa.text("ALTER TABLE donation ADD CONSTRAINT donation_idempotency_key_key "
                                         "UNIQUE (idempotency_key)"))
                else:
                    conn.execute(sa.text("CREATE UNIQUE INDEX donation_idempotency_key_key ON donation (idempotency_key)"))
                for statement in SEED_AT_18323330[:3]:
                    conn.execute(sa.text(statement))
                conn.execute(sa.text(
                    "INSERT INTO donation (id, campaign_id, donor_id, amount, currency, provider, status, "
                    "idempotency_key, created_at, updated_at) VALUES ('d1', 'c1', 'u1', 5, 'USD', 'paypal', "
                    "'pending', 'shared-key', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            upgrade(directory=str(MIGRATIONS))
            with db.engine.begin() as conn:  # a different donor reusing the key must be allowed after the upgrade
                conn.execute(sa.text(
                    "INSERT INTO donation (id, campaign_id, donor_id, amount, currency, provider, status, "
                    "idempotency_key, idempotency_fingerprint, created_at, updated_at) VALUES ('d2', 'c1', 'u2', 5, "
                    "'USD', 'paypal', 'pending', 'shared-key', 'fp', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        finally:
            _dispose(url)
