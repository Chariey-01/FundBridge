"""`flask --app run:app fundbridge-demo seed`: demo accounts and campaigns for the phone demo.

Creates people and campaigns only. It never creates donations, ledger entries or
payouts: raised totals stay at 0 until real PayPal sandbox payments are captured.
All records use example.test addresses and are marked as demo data.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from decimal import Decimal

import click
from flask import Flask
from flask.cli import AppGroup

demo_cli = AppGroup("fundbridge-demo", help="Demo data for the feature-phone and AI demo (no financial records).")

DEMO_PHONE = "+254712345678"


@demo_cli.command("seed")
@click.option("--password", envvar="DEMO_PASSWORD", default=None, help="Password for all demo accounts.")
def seed(password: str | None) -> None:
    from app.extensions import db
    from app.models.core import BeneficiaryProfile, Campaign, CampaignStatus, Role, User

    if os.environ.get("FLASK_ENV") == "production":
        raise click.ClickException("Refusing to seed demo data when FLASK_ENV=production.")
    password = password or secrets.token_urlsafe(12)
    accounts = {}
    for role in (Role.creator, Role.beneficiary, Role.agent, Role.reviewer, Role.admin, Role.donor):
        email = f"demo-{role.value}@example.test"
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(email=email, role=role)
            db.session.add(user)
        user.set_password(password)
        accounts[role.value] = user
    db.session.flush()

    beneficiary = BeneficiaryProfile.query.filter_by(user_id=accounts["beneficiary"].id).first()
    if beneficiary is None:
        beneficiary = BeneficiaryProfile(
            user_id=accounts["beneficiary"].id, display_name="Amina (demo)", phone_number=DEMO_PHONE,
            country_code="KE", preferred_language="en", verification_status="verified",
            payout_destination_reference="demo-simulator-wallet-token",
        )
        db.session.add(beneficiary)
        db.session.flush()

    campaigns = [
        ("demo-school-fees-amina", "School fees for Amina (demo)", "education", "400.00",
         "Demo campaign. Amina is in her final year of secondary school in Kisumu and needs help with fees, "
         "books and uniform."),
        ("demo-clinic-roof", "Repair the village clinic roof (demo)", "medical", "1500.00",
         "Demo campaign. The community clinic roof leaks during the rains; funds cover iron sheets and labour."),
    ]
    for slug, title, category, goal, description in campaigns:
        if Campaign.query.filter_by(slug=slug).first():
            continue
        db.session.add(Campaign(
            creator_id=accounts["creator"].id, beneficiary_id=beneficiary.id, slug=slug, title=title,
            category=category, goal_amount=Decimal(goal), goal_currency="USD", description=description,
            status=CampaignStatus.published, review_status="demo_seeded", published_at=datetime.now(timezone.utc),
        ))
    db.session.commit()
    click.echo("Demo data ready (no donations, ledger entries or payouts were created).")
    click.echo(f"Beneficiary phone for USSD/SMS simulator: {DEMO_PHONE}")
    for role, user in accounts.items():
        click.echo(f"  {role:<12} {user.email}")
    click.echo(f"Password for all demo accounts: {password}")


def register_demo_cli(app: Flask) -> None:
    app.cli.add_command(demo_cli)
