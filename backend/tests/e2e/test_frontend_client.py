"""Runs the TypeScript frontend client (contracts/fundbridge-client.ts) offline and against the live API.

Skipped when Node.js 22.6+ is not installed (the tests run TypeScript directly with type stripping).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from .conftest import PASSWORD
from .test_journeys import _donate, _ok, _published_campaign

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def _node() -> list[str]:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    major, minor = (int(x) for x in re.match(r"v(\d+)\.(\d+)", version).groups())
    if (major, minor) < (22, 6):
        pytest.skip(f"Node.js {version} cannot run TypeScript directly")
    return [node, "--disable-warning=ExperimentalWarning"] + (["--experimental-strip-types"] if major < 23 else [])


def _run(cmd: list[str], env: dict | None = None) -> None:
    done = subprocess.run(cmd, cwd=CONTRACTS, capture_output=True, text=True, timeout=120,
                          env={**os.environ, **(env or {})})
    assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-2000:]


def test_client_presentation_rules_offline():
    _run(_node() + ["--test", "fundbridge-client.test.ts"])


def test_client_against_live_api(live):
    node = _node()
    world = _published_campaign(live, title_word="Textbooks")
    cid = world["campaign"]["id"]
    _donate(live, live.account("donor"), cid, "50.00")
    payout = _ok(live.call("POST", "/api/v1/payouts", world["beneficiary"]["token"],
                           headers={"Idempotency-Key": uuid.uuid4().hex},
                           json={"campaign_id": cid, "beneficiary_id": world["profile"]["id"], "amount": "20.00",
                                 "currency": "USD"}), 201)
    _ok(live.call("POST", f"/api/v1/payouts/{payout['id']}/review", world["reviewer"]["token"],
                  json={"decision": "approve"}))
    donor = live.account("donor", "client-donor")
    _run(node + ["--test", "fundbridge-client.live.test.ts"], env={
        "FB_API": live.base, "FB_PAYPAL_DOUBLE": live.paypal.url, "FB_CAMPAIGN_ID": cid,
        "FB_DONOR_EMAIL": donor["email"], "FB_BENEFICIARY_EMAIL": world["beneficiary"]["email"],
        "FB_PASSWORD": PASSWORD, "FB_PAYOUT_ID": payout["id"]})


def test_contracts_and_examples_typecheck():
    tsc = CONTRACTS / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        pytest.skip("run `npm ci` in contracts/ to type-check the client, contracts and examples")
    _run([str(tsc), "-p", "."])
