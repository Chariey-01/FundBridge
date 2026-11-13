"""Independent financial-integrity checks against the live server (run last in the e2e session).

1. Concurrency: parallel captures, parallel reconciliations and parallel order creation with one idempotency
   key must never create a second ledger credit or a second donation.
2. Ledger audit: after every e2e journey (including the failure and rollback paths), the ledger must be
   consistent with donations and payouts. Reads the e2e database directly; it never writes.

Meaningful on PostgreSQL (E2E_DATABASE_URL); on SQLite the server serialises writes anyway.
"""

from __future__ import annotations

import threading
import uuid
from collections import Counter, defaultdict
from decimal import Decimal

import pytest
import sqlalchemy as sa

from .test_journeys import _donate, _funds, _ok, _published_campaign

PARALLEL = 8


def _parallel(fn, n=PARALLEL):
    barrier, lock, results = threading.Barrier(n), threading.Lock(), []

    def run(i):
        barrier.wait()
        try:
            out = fn(i)
        except Exception as exc:  # a transport error is a result too
            out = exc
        with lock:
            results.append(out)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return results


def _statuses(results):
    return Counter(getattr(r, "status_code", type(r).__name__) for r in results)


def test_parallel_captures_credit_once(live):
    world = _published_campaign(live, title_word="Parallel")
    donor = live.account("donor")
    order, _ = _donate(live, donor, world["campaign"]["id"], "11.00", capture=False)  # approved, not captured
    results = _parallel(lambda i: live.call("POST", f"/api/v1/donations/{order['id']}/capture", donor["token"]))
    codes = _statuses(results)
    assert codes[200] >= 1 and set(codes) <= {200, 400, 502}, codes  # never 500
    assert _funds(live, world["campaign"]["id"])["raised"] == "11.00", codes
    assert _ok(live.call("GET", f"/api/v1/donations/{order['id']}", donor["token"]))["status"] == "completed"


def test_parallel_reconciliations_credit_once(live):
    world = _published_campaign(live, title_word="Reconciled")
    donor = live.account("donor")
    order, order_id = _donate(live, donor, world["campaign"]["id"], "13.00", capture=False)
    live.paypal.capture_out_of_band(order_id)
    results = _parallel(lambda i: live.call("POST", f"/api/v1/donations/{order['id']}/reconcile", donor["token"]))
    codes = _statuses(results)
    assert _funds(live, world["campaign"]["id"])["raised"] == "13.00", codes  # exactly one credit
    assert codes[200] >= 1, codes
    assert _ok(live.call("GET", f"/api/v1/donations/{order['id']}", donor["token"]))["status"] == "completed"


def test_parallel_reconciliations_never_return_500(live):
    """R-2 regression: fixed in feat/backend-core 4bae876/7115094 (row lock + populate_existing in reconcile)."""
    donor = live.account("donor")
    seen = Counter()
    for _ in range(2):
        world = _published_campaign(live, title_word="Race")
        order, order_id = _donate(live, donor, world["campaign"]["id"], "2.00", capture=False)
        live.paypal.capture_out_of_band(order_id)
        seen += _statuses(_parallel(
            lambda i: live.call("POST", f"/api/v1/donations/{order['id']}/reconcile", donor["token"])))
    assert seen[500] == 0, seen


def test_parallel_orders_with_one_idempotency_key_create_one_donation(live):
    world = _published_campaign(live, title_word="Idempotent")
    donor = live.account("donor")
    key = uuid.uuid4().hex
    body = {"campaign_id": world["campaign"]["id"], "amount": "3.00", "currency": "USD"}
    results = _parallel(lambda i: live.call("POST", "/api/v1/donations/orders", donor["token"],
                                            headers={"Idempotency-Key": key}, json=body))
    codes = _statuses(results)
    ids = {r.json()["data"]["id"] for r in results if getattr(r, "status_code", 0) in (200, 201)}
    assert len(ids) == 1 and codes[201] == 1, codes  # one donation, whatever the other responses were
    mine = [d for d in _ok(live.call("GET", "/api/v1/me/donations", donor["token"]))]
    assert len(mine) == 1


def test_parallel_orders_with_one_key_replay_instead_of_500(live):
    """S-5 regression: fixed in feat/backend-core 4bae876 (per-donor/key advisory lock before the provider call)."""
    world = _published_campaign(live, title_word="Replay")
    donor = live.account("donor")
    seen = Counter()
    for _ in range(2):
        key = uuid.uuid4().hex
        body = {"campaign_id": world["campaign"]["id"], "amount": "1.00", "currency": "USD"}
        seen += _statuses(_parallel(lambda i: live.call("POST", "/api/v1/donations/orders", donor["token"],
                                                        headers={"Idempotency-Key": key}, json=body)))
    assert seen[500] == 0 and seen[201] == 2, seen


def test_ledger_is_consistent_after_every_journey(live):
    engine = sa.create_engine(live.env["DATABASE_URL"])
    with engine.connect() as conn:
        donations = {r.id: r for r in conn.execute(sa.text("SELECT id, campaign_id, amount, currency, status FROM donation"))}
        payouts = {r.id: r for r in conn.execute(sa.text("SELECT id, campaign_id, amount, currency, status FROM payout"))}
        ledger = list(conn.execute(sa.text(
            "SELECT id, campaign_id, donation_id, payout_id, entry_type, amount, currency FROM financial_ledger_entry")))
    engine.dispose()
    assert donations and payouts and ledger

    credits = defaultdict(list)
    reserved, released = defaultdict(list), defaultdict(list)
    for e in ledger:
        if e.entry_type == "donation_completed":
            assert e.donation_id in donations, f"credit without donation: {e.id}"
            credits[e.donation_id].append(e)
        elif e.entry_type == "payout_reserved":
            assert e.payout_id in payouts, f"reservation without payout: {e.id}"
            reserved[e.payout_id].append(e)
        elif e.entry_type == "payout_released":
            assert e.payout_id in payouts, f"release without payout: {e.id}"
            released[e.payout_id].append(e)
        else:
            raise AssertionError(f"unexpected ledger entry type {e.entry_type}")

    for d in donations.values():
        entries = credits.get(d.id, [])
        if d.status == "completed":
            assert len(entries) == 1, f"donation {d.id} credited {len(entries)} times"
            e = entries[0]
            assert (Decimal(e.amount), e.currency, e.campaign_id) == (Decimal(d.amount), d.currency, d.campaign_id)
        else:
            assert not entries, f"{d.status} donation {d.id} has a ledger credit"

    for p in payouts.values():
        assert len(reserved.get(p.id, [])) == 1, f"payout {p.id} reserved {len(reserved.get(p.id, []))} times"
        assert Decimal(reserved[p.id][0].amount) == Decimal(p.amount)
        expected_releases = 1 if p.status in ("rejected", "failed") else 0
        assert len(released.get(p.id, [])) == expected_releases, f"payout {p.id} ({p.status}) releases"

    balance = defaultdict(Decimal)
    for e in ledger:
        sign = {"donation_completed": 1, "payout_reserved": -1, "payout_released": 1}[e.entry_type]
        balance[(e.campaign_id, e.currency)] += sign * Decimal(e.amount)
    assert all(v >= 0 for v in balance.values()), {k: v for k, v in balance.items() if v < 0}

    # The API reports the same numbers the ledger holds.
    campaign_id, currency = next(k for k, v in balance.items() if v > 0)
    raised = sum((Decimal(e.amount) for e in ledger if e.entry_type == "donation_completed"
                  and e.campaign_id == campaign_id and e.currency == currency), Decimal("0"))
    assert Decimal(_funds(live, campaign_id)["raised"]) == raised
