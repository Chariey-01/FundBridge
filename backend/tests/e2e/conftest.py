"""Live end-to-end harness: the real API served by gunicorn over HTTP.

Setup mirrors an operator deployment and never touches the database directly:

1. ``flask db upgrade`` builds the schema from the Alembic migrations (not ``create_all``).
2. ``flask fundbridge-admin create-admin`` bootstraps the only privileged account.
3. gunicorn serves ``run:app`` with ``FLASK_ENV=production`` (1 worker x 8 threads, as documented).
4. Tests act only through HTTP: every other account, role, profile, campaign, donation and payout
   is created through the public API.

External providers are local HTTP test doubles (``provider_doubles.py``) so the real PayPal and
OpenAI adapters run end to end without credentials. SMS/USSD use the built-in simulator, labelled
as such in every response. Nothing here contacts PayPal, OpenAI or Africa's Talking.

Database: ``E2E_DATABASE_URL`` (a disposable PostgreSQL database; its public schema is dropped and
recreated) or, by default, a temporary SQLite file.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import requests

from .provider_doubles import AfricasTalkingDouble, OpenAIDouble, PayPalDouble

BACKEND = Path(__file__).resolve().parents[2]
ADMIN_EMAIL = "ops-admin@example.test"
PASSWORD = "e2e-long-enough-password"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _reset_postgres(url: str) -> None:
    import sqlalchemy as sa

    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))
    engine.dispose()


@dataclass
class Live:
    base: str
    env: dict
    paypal: PayPalDouble
    openai: OpenAIDouble
    log_path: Path
    admin_token: str = ""
    at: object = None
    session: requests.Session = field(default_factory=requests.Session)

    def call(self, method: str, path: str, token: str | None = None, **kwargs) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.session.request(method, self.base + path, headers=headers, timeout=20, **kwargs)

    def login(self, email: str, password: str = PASSWORD) -> str:
        res = self.call("POST", "/api/v1/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, res.text
        return res.json()["data"]["access_token"]

    def account(self, role: str, label: str | None = None) -> dict:
        """Register through the public API, then have the admin assign ``role`` through the API."""
        email = f"{label or role}-{uuid.uuid4().hex[:8]}@example.test"
        res = self.call("POST", "/api/v1/auth/register", json={"email": email, "password": PASSWORD})
        assert res.status_code == 201 and res.json()["data"]["role"] == "donor", res.text
        user_id = res.json()["data"]["id"]
        if role != "donor":
            res = self.call("PUT", f"/api/v1/admin/users/{user_id}/role", self.admin_token, json={"role": role})
            assert res.status_code == 200, res.text
        return {"id": user_id, "email": email, "token": self.login(email)}

    def callback_token(self) -> str:
        return self.env["MESSAGING_CALLBACK_TOKEN"]

    def server_log(self) -> str:
        return self.log_path.read_text(errors="replace")


def _start_stack(tmp: Path, db_url: str, extra_env: dict | None = None):
    """Doubles + migrations + first admin + gunicorn. Returns (Live, stop)."""
    if db_url.startswith("postgresql"):
        _reset_postgres(db_url)
    paypal = PayPalDouble("e2e-paypal-client", "e2e-paypal-secret", "WH-E2E-0001").start()
    paypal.assume_representation = True  # C-4b accommodation; see PayPalDouble and COORDINATION.md
    openai_key = "sk-e2e-" + secrets.token_hex(8)
    openai = OpenAIDouble(openai_key).start()
    port = _free_port()
    env = {
        **{k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "SYSTEMROOT")},
        "FLASK_ENV": "production",
        "SECRET_KEY": secrets.token_hex(32),
        "JWT_SECRET_KEY": secrets.token_hex(32),
        "DATABASE_URL": db_url,
        "FRONTEND_ORIGIN": "http://localhost:3000",
        "PAYPAL_CLIENT_ID": paypal.client_id,
        "PAYPAL_CLIENT_SECRET": paypal.client_secret,
        "PAYPAL_BASE_URL": paypal.url,
        "PAYPAL_WEBHOOK_ID": paypal.webhook_id,
        "PAYOUT_PROVIDER": "simulator",
        "AI_PROVIDER": "openai",
        "OPENAI_API_KEY": openai_key,
        "OPENAI_BASE_URL": openai.url + "/v1",
        "OPENAI_MODEL": "e2e-double-model",
        "AI_MAX_RETRIES": "0",
        "AI_TIMEOUT_SECONDS": "5",
        "SMS_PROVIDER": "simulator",
        "MESSAGING_CALLBACK_TOKEN": "cb-" + secrets.token_hex(16),
        "MESSAGING_SIMULATOR_ENABLED": "true",
        "PUBLIC_BASE_URL": "http://localhost:3000",
        "FUNDBRIDGE_ADMIN_PASSWORD": PASSWORD,
        # The journeys create many accounts from one IP; per-account lockout stays at its default and is tested.
        "AUTH_LOGIN_LIMIT_PER_IP_PER_MINUTE": "1000",
        "AUTH_REGISTER_LIMIT_PER_IP_PER_10_MINUTES": "1000",
        "DONATION_ORDER_LIMIT_PER_IP_PER_MINUTE": "1000",
        "PYTHONUNBUFFERED": "1",
        **(extra_env or {}),
    }
    flask = [sys.executable, "-m", "flask", "--app", "run:app"]
    for step in (["db", "upgrade", "-d", "migrations"], ["fundbridge-admin", "create-admin", "--email", ADMIN_EMAIL]):
        done = subprocess.run(flask + step, cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, f"{' '.join(step)} failed:\n{done.stdout}\n{done.stderr}"

    log_path = tmp / "server.log"
    log_file = log_path.open("w")
    if shutil.which("gunicorn") or _has_module("gunicorn"):
        cmd = [sys.executable, "-m", "gunicorn", "-w", "1", "--threads", "8", "-b", f"127.0.0.1:{port}", "run:app"]
    else:  # still a real HTTP server, but not the production one
        cmd = flask + ["run", "--port", str(port), "--with-threads"]
    server = subprocess.Popen(cmd, cwd=BACKEND, env=env, stdout=log_file, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if requests.get(base + "/health", timeout=5).status_code == 200:
                break
        except requests.RequestException:  # not listening yet, or the worker is still importing the app
            time.sleep(0.3)
    else:
        server.terminate()
        raise RuntimeError("API server did not start:\n" + log_path.read_text())

    harness = Live(base=base, env=env, paypal=paypal, openai=openai, log_path=log_path)
    harness.admin_token = harness.login(ADMIN_EMAIL)

    def stop():
        server.terminate()
        server.wait(timeout=10)
        log_file.close()
        paypal.stop()
        openai.stop()
        if db_url.startswith("postgresql"):
            _reset_postgres(db_url)

    return harness, stop


@pytest.fixture(scope="session")
def live(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    harness, stop = _start_stack(tmp, os.environ.get("E2E_DATABASE_URL") or f"sqlite:///{tmp / 'e2e.db'}")
    yield harness
    stop()


@pytest.fixture(scope="module")
def live_at(tmp_path_factory):
    """A second stack whose SMS go to an Africa's Talking double over HTTP (SQLite; the gateway path is the subject)."""
    tmp = tmp_path_factory.mktemp("e2e_at")
    at = AfricasTalkingDouble("sandbox", "at-e2e-" + secrets.token_hex(8)).start()
    harness, stop = _start_stack(tmp, f"sqlite:///{tmp / 'e2e_at.db'}", {
        "SMS_PROVIDER": "africastalking", "AT_USERNAME": at.username, "AT_API_KEY": at.api_key,
        "AT_API_BASE_URL": at.url, "AT_SENDER_ID": "40123", "MESSAGING_SIMULATOR_ENABLED": "false"})
    harness.at = at
    yield harness
    stop()
    at.stop()


def _has_module(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None
