"""The demo runbook, executed: seed the live stack with the CLI, then run scripts/smoke_test.py against it."""

from __future__ import annotations

import subprocess
import sys

from .conftest import BACKEND

DEMO_PASSWORD = "e2e-demo-password-123"


def test_seed_then_smoke_test_against_live_server(live):
    env = {**live.env, "FLASK_ENV": "development", "DEMO_PASSWORD": DEMO_PASSWORD}  # seeding refuses production
    seeded = subprocess.run([sys.executable, "-m", "flask", "--app", "run:app", "fundbridge-demo", "seed", "--scenarios"],
                            cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    assert "campaign_id=" in seeded.stdout and "not a PayPal payment" in seeded.stdout

    smoke = subprocess.run([sys.executable, "scripts/smoke_test.py", "--base-url", live.base, "--password", DEMO_PASSWORD,
                            "--callback-token", live.callback_token(), "--try-donation"],
                           cwd=BACKEND, capture_output=True, text=True, timeout=180)
    out = smoke.stdout
    print(out)  # visible with pytest -rP
    assert smoke.returncode == 0, out + smoke.stderr
    assert "FAIL " not in out and " 0 failed" in out
    for step in ("sign in as beneficiary", "AI campaign draft", "USSD callback (main menu)", "donation order (PayPal)",
                 "campaign balance (public, from the ledger)", "beneficiary payouts"):
        assert f"PASS  {step}" in out, step
    assert DEMO_PASSWORD not in out and live.callback_token() not in out and "eyJ" not in out
