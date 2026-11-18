"""Start the real FundBridge API for the browser journeys (Playwright `webServer`).

Mirrors backend/tests/e2e/conftest.py, like an operator deployment:
  1. `flask db upgrade` builds the schema from the Alembic migrations.
  2. `flask fundbridge-admin create-admin` creates the only privileged account.
  3. gunicorn serves `run:app` with FLASK_ENV=production.
Every other account, role, profile, campaign, donation and payout is created through the HTTP API by
the tests themselves.

PayPal is the repository's local PayPal Orders v2 test double (backend/tests/e2e/provider_doubles.py).
It is NOT PayPal: no PayPal system is contacted and no money moves. Payouts use the backend's own
simulator and SMS/USSD the built-in simulator. The browser tests assert that the UI labels all of this.

Environment:
  E2E_DATABASE_URL   disposable database; a PostgreSQL public schema is DROPPED and recreated.
                     Default: a fresh SQLite file in a temporary directory.
  E2E_API_PORT       API port (default 5051)
  E2E_PAYPAL_PORT    PayPal double port (default 58301)
  E2E_ADMIN_EMAIL / E2E_PASSWORD   the bootstrap admin's credentials
"""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND / "tests" / "e2e"))
from provider_doubles import PayPalDouble, _Handler  # noqa: E402

API_PORT = int(os.environ.get("E2E_API_PORT", "5051"))
PAYPAL_PORT = int(os.environ.get("E2E_PAYPAL_PORT", "58301"))
ADMIN_EMAIL = os.environ.get("E2E_ADMIN_EMAIL", "ops-admin@example.test")
PASSWORD = os.environ.get("E2E_PASSWORD", "e2e-long-enough-password")


def reset_postgres(url: str) -> None:
    import sqlalchemy as sa

    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))
    engine.dispose()


def start_paypal_double() -> PayPalDouble:
    double = PayPalDouble("e2e-paypal-client", "e2e-paypal-secret", "WH-E2E-0001")
    handler = type("Handler", (_Handler,), {"double": double})
    double.server = ThreadingHTTPServer(("127.0.0.1", PAYPAL_PORT), handler)
    threading.Thread(target=double.server.serve_forever, daemon=True).start()
    return double


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fundbridge-web-e2e-"))
    db_url = os.environ.get("E2E_DATABASE_URL") or f"sqlite:///{tmp / 'e2e.db'}"
    if db_url.startswith("postgresql"):
        reset_postgres(db_url)
    paypal = start_paypal_double()
    env = {
        **{k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "SYSTEMROOT")},
        "FLASK_ENV": "production",
        "SECRET_KEY": secrets.token_hex(32),
        "JWT_SECRET_KEY": secrets.token_hex(32),
        "DATABASE_URL": db_url,
        "FRONTEND_ORIGIN": "http://127.0.0.1:4173",
        "PAYPAL_CLIENT_ID": paypal.client_id,
        "PAYPAL_CLIENT_SECRET": paypal.client_secret,
        "PAYPAL_BASE_URL": paypal.url,
        "PAYPAL_WEBHOOK_ID": paypal.webhook_id,
        "PAYOUT_PROVIDER": "simulator",
        "AI_PROVIDER": "disabled",
        "SMS_PROVIDER": "simulator",
        "MESSAGING_CALLBACK_TOKEN": "cb-" + secrets.token_hex(16),
        "MESSAGING_SIMULATOR_ENABLED": "true",
        "PUBLIC_BASE_URL": "http://127.0.0.1:4173",
        "FUNDBRIDGE_ADMIN_PASSWORD": PASSWORD,
        # The journeys create many accounts from one IP; per-account lockout keeps its default.
        "AUTH_LOGIN_LIMIT_PER_IP_PER_MINUTE": "1000",
        "AUTH_REGISTER_LIMIT_PER_IP_PER_10_MINUTES": "1000",
        "DONATION_ORDER_LIMIT_PER_IP_PER_MINUTE": "1000",
        "PYTHONUNBUFFERED": "1",
    }
    flask = [sys.executable, "-m", "flask", "--app", "run:app"]
    for step in (["db", "upgrade", "-d", "migrations"], ["fundbridge-admin", "create-admin", "--email", ADMIN_EMAIL]):
        done = subprocess.run(flask + step, cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180)
        if done.returncode != 0:
            print(f"{' '.join(step)} failed:\n{done.stdout}\n{done.stderr}", file=sys.stderr)
            return 1

    log_path = tmp / "server.log"
    log = log_path.open("w")
    server = subprocess.Popen(
        [sys.executable, "-m", "gunicorn", "-w", "1", "--threads", "8", "-b", f"127.0.0.1:{API_PORT}", "run:app"],
        cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT,
    )

    def stop(*_):
        server.terminate()
        try:
            server.wait(timeout=10)
        finally:
            paypal.stop()
            paypal.server.server_close()
            log.close()
            print(f"API log kept at {log_path}", flush=True)
            sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/health", timeout=3) as r:
                if r.status == 200:
                    break
        except OSError:
            time.sleep(0.3)
    else:
        server.terminate()
        print("API did not start:\n" + log_path.read_text(), file=sys.stderr)
        return 1
    print(f"FundBridge API on http://127.0.0.1:{API_PORT} ({'PostgreSQL' if db_url.startswith('postgresql') else 'SQLite'}); "
          f"PayPal TEST DOUBLE (not PayPal) on {paypal.url}; log {log_path}", flush=True)
    server.wait()
    return server.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
