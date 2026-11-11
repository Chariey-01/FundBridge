"""Migration integrity: one Alembic head, and ``upgrade head`` yields exactly the model schema.

Regression for integration defect M-0 (2026-11-11): the messaging migration and the
backend's idempotency-scope migration both revised ``18323330d500``. That left two heads,
so ``flask db upgrade`` refused to run on a fresh deployment.

Runs on SQLite always and on PostgreSQL when ``POSTGRES_TEST_DATABASE_URL`` is set
(the PostgreSQL database is dropped and recreated schema-by-schema, so use a disposable one).
"""

from __future__ import annotations

import os
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


@pytest.mark.parametrize("backend", ["sqlite", pytest.param("postgresql", marks=pytest.mark.xfail(strict=True, reason=DEFECT_M2))])
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


DEFECT_M1 = ("DEFECT M-1: d7f2b35d0ed5 adds NOT NULL idempotency_fingerprint without a server default, so "
             "upgrading a database that already holds donations fails (and a database created from the original "
             "a0d4581f14e2 keeps the old global idempotency_key unique constraints, because that migration was "
             "edited in place)")


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
@pytest.mark.xfail(strict=True, reason=DEFECT_M1)
def test_upgrade_with_existing_donation_rows(backend, tmp_path):
    from flask_migrate import upgrade

    url, app = _app_for(backend, tmp_path)
    with app.app_context():
        try:
            upgrade(directory=str(MIGRATIONS), revision="18323330d500")
            with db.engine.begin() as conn:
                conn.execute(sa.text(
                    "INSERT INTO \"user\" (id, email, role, status, created_at, updated_at) "
                    "VALUES ('u1', 'd@example.test', 'donor', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                    "('u2', 'c@example.test', 'creator', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
                conn.execute(sa.text(
                    "INSERT INTO beneficiary_profile (id, display_name, phone_number, preferred_language, country_code, "
                    "verification_status, created_at, updated_at) VALUES ('b1', 'B', '+254700000001', 'en', 'KE', "
                    "'verified', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
                conn.execute(sa.text(
                    "INSERT INTO campaign (id, creator_id, beneficiary_id, title, slug, description, category, goal_amount, "
                    "goal_currency, status, review_status, created_at, updated_at) VALUES ('c1', 'u2', 'b1', 'Title', "
                    "'slug-one', 'a long enough description', 'health', 100, 'USD', 'published', 'approved', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
                conn.execute(sa.text(
                    "INSERT INTO donation (id, campaign_id, donor_id, amount, currency, provider, status, idempotency_key, "
                    "created_at, updated_at) VALUES ('d1', 'c1', 'u1', 5, 'USD', 'paypal', 'pending', 'k1', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            upgrade(directory=str(MIGRATIONS))
        finally:
            _dispose(url)
