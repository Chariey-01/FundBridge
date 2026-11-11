"""`flask --app run:app fundbridge-demo seed [--scenarios]`: reproducible demo data.

Without ``--scenarios``: accounts, beneficiary profiles and campaigns only (no financial records).

With ``--scenarios``: also demo donations and payouts, so every screen has something to show. These are
**not payments**: provider ``demo_seed``, order and capture ids ``DEMO-...``. They are created through the
core financial services (``mark_donation_completed``, ``reserve_payout``, ``release_payout``), so the ledger
stays consistent with every invariant the real flows keep.

Safety: refused when ``FLASK_ENV=production``; SMS notifications are suppressed while seeding, so a
configured gateway never messages the placeholder phone numbers; everything uses ``example.test``
addresses. Idempotent: re-running resets the demo passwords and creates nothing twice.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from decimal import Decimal

import click
from flask import Flask, current_app
from flask.cli import AppGroup

demo_cli = AppGroup("fundbridge-demo", help="Demo data (accounts, campaigns; --scenarios adds labelled demo money).")

DEMO_PHONE = "+254712345678"       # Amina (English); the phone simulator's default number
DEMO_PHONE_SW = "+254712345679"    # Baraka (Kiswahili)
DEMO_PROVIDER = "demo_seed"

ACCOUNTS = [  # (email local part, role)
    ("demo-creator", "creator"), ("demo-beneficiary", "beneficiary"), ("demo-beneficiary-sw", "beneficiary"),
    ("demo-agent", "agent"), ("demo-reviewer", "reviewer"), ("demo-admin", "admin"), ("demo-donor", "donor"),
]
BENEFICIARIES = [  # (account, display name, phone, language, wallet token)
    ("demo-beneficiary", "Amina (demo)", DEMO_PHONE, "en", "demo-simulator-wallet-amina"),
    ("demo-beneficiary-sw", "Baraka (demo)", DEMO_PHONE_SW, "sw", "demo-simulator-wallet-baraka"),
]
CAMPAIGNS = [  # (slug, beneficiary account, status, category, goal, title, description)
    ("demo-school-fees-amina", "demo-beneficiary", "published", "education", "400.00",
     "School fees for Amina (demo)",
     "Demo campaign. Amina is in her final year of secondary school in Kisumu and needs help with fees, books "
     "and uniform."),
    ("demo-clinic-roof", "demo-beneficiary-sw", "published", "medical", "1500.00",
     "Repair the village clinic roof (demo)",
     "Demo campaign. The community clinic roof leaks during the rains; funds cover iron sheets and labour."),
    ("demo-water-tank", "demo-beneficiary-sw", "submitted", "water_sanitation", "800.00",
     "Water tank for Baraka's school (demo)",
     "Demo campaign awaiting review. A 10,000 litre tank so pupils have clean water."),
    ("demo-library-draft", "demo-beneficiary", "draft", "education", "300.00",
     "Books for the village library (demo)",
     "Demo draft campaign. Textbooks and reading books for the community library."),
]
DONATIONS = [  # (tag, campaign slug, amount, completed?)
    ("d1", "demo-school-fees-amina", "50.00", True), ("d2", "demo-school-fees-amina", "25.00", True),
    ("d3", "demo-school-fees-amina", "75.00", True), ("d4", "demo-school-fees-amina", "20.00", False),
    ("d5", "demo-clinic-roof", "100.00", True), ("d6", "demo-clinic-roof", "60.00", True),
]
PAYOUTS = [  # (tag, campaign slug, amount, outcome); created in this order, so Amina's latest payout is the approved one
    ("p2", "demo-school-fees-amina", "15.00", "reject"),
    ("p1", "demo-school-fees-amina", "40.00", "approve"),
    ("p3", "demo-clinic-roof", "30.00", "requested"),
]


def _get_or_create_users(password: str) -> dict:
    from app.extensions import db
    from app.models.core import Role, User

    users = {}
    for local, role in ACCOUNTS:
        email = f"{local}@example.test"
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(email=email, role=Role(role))
            db.session.add(user)
        user.role, user.status = Role(role), "active"
        user.set_password(password)
        users[local] = user
    db.session.flush()
    return users


def _seed_people_and_campaigns(users: dict) -> tuple[dict, dict]:
    from app.extensions import db
    from app.models.core import BeneficiaryProfile, Campaign, CampaignStatus

    profiles = {}
    for account, name, phone, lang, token in BENEFICIARIES:
        profile = BeneficiaryProfile.query.filter_by(user_id=users[account].id).first()
        if profile is None:
            profile = BeneficiaryProfile(user_id=users[account].id, display_name=name, phone_number=phone,
                                         country_code="KE", preferred_language=lang,
                                         payout_destination_reference=token, verification_status="verified")
            db.session.add(profile)
        profiles[account] = profile
    db.session.flush()

    campaigns = {}
    for slug, account, status, category, goal, title, description in CAMPAIGNS:
        campaign = Campaign.query.filter_by(slug=slug).first()
        if campaign is None:
            published = status == "published"
            campaign = Campaign(
                creator_id=users["demo-creator"].id, beneficiary_id=profiles[account].id, slug=slug, title=title,
                category=category, goal_amount=Decimal(goal), goal_currency="USD", description=description,
                status=CampaignStatus(status),
                review_status={"published": "approved", "submitted": "pending"}.get(status, "not_submitted"),
                published_at=datetime.now(timezone.utc) if published else None,
            )
            db.session.add(campaign)
        campaigns[slug] = campaign
    db.session.flush()
    return profiles, campaigns


def _seed_scenarios(users: dict, profiles: dict, campaigns: dict) -> None:
    from app.extensions import db
    from app.models.core import AuditLog, Donation, DonationStatus, Payout, PayoutStatus
    from app.services.ledger import release_payout, reserve_payout
    from app.services.payments import mark_donation_completed

    donor = users["demo-donor"]
    for tag, slug, amount, completed in DONATIONS:
        key = f"demo-seed-{tag}"
        if Donation.query.filter_by(donor_id=donor.id, idempotency_key=key).first():
            continue
        donation = Donation(campaign_id=campaigns[slug].id, donor_id=donor.id, amount=Decimal(amount), currency="USD",
                            provider=DEMO_PROVIDER, provider_order_id=f"DEMO-ORDER-{tag}", idempotency_key=key,
                            idempotency_fingerprint="demo-seed", status=DonationStatus.pending)
        db.session.add(donation)
        db.session.flush()
        if completed:
            mark_donation_completed(donation, order_id=donation.provider_order_id, capture={
                "id": f"DEMO-CAP-{tag}", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": amount}})

    reviewer = users["demo-reviewer"]
    by_campaign = {slug: profiles[account] for slug, account, *_ in CAMPAIGNS}
    for tag, slug, amount, outcome in PAYOUTS:
        profile = by_campaign[slug]
        key = f"demo-seed-{tag}"
        if Payout.query.filter_by(requested_by=profile.user_id, idempotency_key=key).first():
            continue
        payout = Payout(campaign_id=campaigns[slug].id, beneficiary_id=profile.id, requested_by=profile.user_id,
                        amount=Decimal(amount), currency="USD", destination_type="wallet",
                        destination_reference=profile.payout_destination_reference, provider="simulator",
                        idempotency_key=key, idempotency_fingerprint="demo-seed")
        db.session.add(payout)
        db.session.flush()
        reserve_payout(payout)
        db.session.add(AuditLog(actor_id=profile.user_id, action="payout.requested", resource_type="payout",
                                resource_id=payout.id, metadata_json={"demo_seed": True}))
        if outcome == "approve":
            payout.status = PayoutStatus.approved_for_submission
        elif outcome == "reject":
            payout.status = PayoutStatus.rejected
            release_payout(payout, "rejected")
        if outcome in ("approve", "reject"):
            db.session.add(AuditLog(actor_id=reviewer.id, action=f"payout.{outcome}", resource_type="payout",
                                    resource_id=payout.id, metadata_json={"demo_seed": True}))
        db.session.flush()


@demo_cli.command("seed")
@click.option("--password", envvar="DEMO_PASSWORD", default=None, help="Password for all demo accounts.")
@click.option("--scenarios", is_flag=True, help="Also create labelled demo donations and payouts (not payments).")
def seed(password: str | None, scenarios: bool) -> None:
    from app.extensions import db
    from app.services.ledger import available_funds

    if os.environ.get("FLASK_ENV") == "production":
        raise click.ClickException("Refusing to seed demo data when FLASK_ENV=production.")
    if password is not None and len(password) < 12:
        raise click.ClickException("DEMO_PASSWORD must be at least 12 characters (the API rejects shorter ones).")
    password = password or secrets.token_urlsafe(12)

    messaging = current_app.extensions.get("fundbridge.messaging") or {}
    notifications = messaging.get("notifications_enabled")
    if messaging:
        messaging["notifications_enabled"] = False  # never text the placeholder numbers while seeding
    try:
        users = _get_or_create_users(password)
        profiles, campaigns = _seed_people_and_campaigns(users)
        if scenarios:
            _seed_scenarios(users, profiles, campaigns)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        if messaging:
            messaging["notifications_enabled"] = notifications

    click.echo("Demo data ready." + ("" if scenarios else " No donations, ledger entries or payouts were created."))
    click.echo(f"Password for every demo account: {password}")
    for local, role in ACCOUNTS:
        click.echo(f"  {role:<12} {local}@example.test")
    click.echo("Beneficiaries (USSD/SMS simulator numbers):")
    for account, name, phone, lang, _ in BENEFICIARIES:
        click.echo(f"  {name:<16} {phone}  lang={lang}  beneficiary_id={profiles[account].id}")
    click.echo("Campaigns:")
    for slug, *_ in CAMPAIGNS:
        c = campaigns[slug]
        balance = f"  available={available_funds(c.id, 'USD')}" if scenarios else ""
        click.echo(f"  {c.status.value:<10} {slug:<24} campaign_id={c.id}{balance}")
    if scenarios:
        click.echo("Demo money is labelled provider=demo_seed (DEMO-* ids). It is not a PayPal payment.")


def register_demo_cli(app: Flask) -> None:
    app.cli.add_command(demo_cli)
