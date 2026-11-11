"""Operational endpoints that complete the core journeys end to end.

Before these existed, the core API had no way to give an account a non-donor role,
verify or re-verify a beneficiary, or read campaign balances. The campaign, beneficiary
and payout journeys could only be completed by editing the database directly.

Core rules are reused, never re-implemented: balances come from ``ledger.available_funds``
(the same function that guards payout reservation), and every change writes ``AuditLog``.

    GET  /api/v1/admin/users?email=|phone_number=        admin       find an account
    PUT  /api/v1/admin/users/<id>/role                   admin       assign a role
    GET  /api/v1/beneficiaries?verification_status=      agent, reviewer, admin
    POST /api/v1/beneficiaries/<id>/verification         reviewer, admin
    GET  /api/v1/campaigns/<id>/funds                    public (raised) / owners + staff (full)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, abort, g, request
from sqlalchemy import func

from app.extensions import db
from app.integrations.core_adapters import jwt_actor_resolver, raised_total
from app.integrations.http_envelope import error, ok, unauthenticated
from app.models.core import (
    AuditLog,
    BeneficiaryProfile,
    Campaign,
    CampaignStatus,
    Payout,
    PayoutStatus,
    Role,
    User,
)
from app.security.auth import roles_allowed
from app.services.ledger import available_funds

bp = Blueprint("operations", __name__)

VERIFICATION_STATES = ("unverified", "verified", "reverification_required", "rejected")
# Payouts whose reservation is still held and has not reached a final provider outcome.
IN_FLIGHT = (PayoutStatus.requested, PayoutStatus.under_review, PayoutStatus.approved_for_submission,
             PayoutStatus.submitted, PayoutStatus.pending_confirmation)
CENTS = Decimal("0.01")


def _json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("VALIDATION_ERROR")
    return data


def _money(value) -> str:
    return str(Decimal(str(value or 0)).quantize(CENTS))


# ---------------------------------------------------------------- accounts and roles


def _user(u: User) -> dict:
    return {"id": u.id, "email": u.email, "phone_number": u.phone_number, "role": u.role.value, "status": u.status}


@bp.get("/admin/users")
@roles_allowed(Role.admin)
def find_users():
    email = (request.args.get("email") or "").strip().lower()
    phone = (request.args.get("phone_number") or "").strip()
    if not email and not phone:
        raise ValueError("VALIDATION_ERROR")
    query = User.query.filter(func.lower(User.email) == email) if email else User.query.filter_by(phone_number=phone)
    return ok([_user(u) for u in query.limit(20)])


@bp.put("/admin/users/<user_id>/role")
@roles_allowed(Role.admin)
def assign_role(user_id: str):
    try:
        role = Role(_json().get("role"))
    except ValueError:
        raise ValueError("VALIDATION_ERROR") from None
    user = db.session.get(User, user_id) or abort(404)
    if user.id == g.current_user.id:
        raise PermissionError("SELF_ROLE_CHANGE_FORBIDDEN")
    if user.status != "active":
        raise ValueError("ACCOUNT_INACTIVE")
    if user.role != role:
        previous = user.role.value
        user.role = role
        db.session.add(AuditLog(actor_id=g.current_user.id, action="user.role_changed", resource_type="user",
                                resource_id=user.id, metadata_json={"from": previous, "to": role.value}))
        db.session.commit()
    return ok(_user(user))


# ------------------------------------------------------------ beneficiary verification


def profile_revision(p: BeneficiaryProfile) -> str:
    """Fingerprint of the fields a verifier vouches for. Any change invalidates a pending decision."""
    material = "\x1f".join([p.id, p.display_name or "", p.phone_number or "", p.country_code or "",
                            p.payout_destination_reference or "", p.user_id or ""])
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def _profile(p: BeneficiaryProfile) -> dict:
    # The destination reference itself is never returned; staff see only whether one is on file.
    return {"id": p.id, "user_id": p.user_id, "display_name": p.display_name, "phone_number": p.phone_number,
            "country_code": p.country_code, "preferred_language": p.preferred_language,
            "verification_status": p.verification_status,
            "has_payout_destination": bool(p.payout_destination_reference), "revision": profile_revision(p)}


@bp.get("/beneficiaries")
@roles_allowed(Role.agent, Role.reviewer, Role.admin)
def list_beneficiaries():
    status = request.args.get("verification_status")
    query = BeneficiaryProfile.query
    if status:
        if status not in VERIFICATION_STATES:
            raise ValueError("VALIDATION_ERROR")
        query = query.filter_by(verification_status=status)
    return ok([_profile(p) for p in query.order_by(BeneficiaryProfile.created_at.desc()).limit(100)])


@bp.get("/beneficiaries/<profile_id>")
@roles_allowed(Role.agent, Role.reviewer, Role.admin)
def beneficiary_detail(profile_id: str):
    return ok(_profile(db.session.get(BeneficiaryProfile, profile_id) or abort(404)))


@bp.post("/beneficiaries/<profile_id>/verification")
@roles_allowed(Role.reviewer, Role.admin)
def decide_verification(profile_id: str):
    data = _json()
    decision, revision = data.get("decision"), data.get("revision")
    if decision not in ("verify", "reject") or not isinstance(revision, str):
        raise ValueError("VALIDATION_ERROR")
    reason = data.get("reason") if isinstance(data.get("reason"), str) else None
    # Row lock (PostgreSQL) so a concurrent self-service edit cannot slip between check and decision.
    profile = db.session.query(BeneficiaryProfile).filter_by(id=profile_id).with_for_update().one_or_none()
    if profile is None:
        abort(404)
    if profile.user_id and profile.user_id == g.current_user.id:
        raise PermissionError("SELF_VERIFICATION_FORBIDDEN")
    if revision != profile_revision(profile):
        db.session.rollback()
        return error("PROFILE_CHANGED", "The profile changed after it was reviewed. Review it again.", 409)
    target = "verified" if decision == "verify" else "rejected"
    if profile.verification_status != target:
        previous = profile.verification_status
        profile.verification_status = target
        db.session.add(AuditLog(
            actor_id=g.current_user.id, resource_type="beneficiary", resource_id=profile.id,
            action="beneficiary.verified" if target == "verified" else "beneficiary.verification_rejected",
            metadata_json={"from": previous, "revision": revision, "reason": (reason or "")[:200]}))
    db.session.commit()
    return ok(_profile(profile))


# ------------------------------------------------------------------ campaign balances


def _sum_payouts(campaign_id: str, currency: str, statuses) -> Decimal:
    total = (db.session.query(func.coalesce(func.sum(Payout.amount), 0))
             .filter(Payout.campaign_id == campaign_id, Payout.currency == currency, Payout.status.in_(statuses))
             .scalar())
    return Decimal(str(total))


@bp.get("/campaigns/<campaign_id>/funds")
def campaign_funds(campaign_id: str):
    campaign = db.session.get(Campaign, campaign_id) or abort(404)
    actor = jwt_actor_resolver()  # a stale token on a public read is treated as anonymous
    owner_ids = {campaign.creator_id}
    beneficiary = db.session.get(BeneficiaryProfile, campaign.beneficiary_id)
    if beneficiary and beneficiary.user_id:
        owner_ids.add(beneficiary.user_id)
    full = actor is not None and (actor.id in owner_ids or actor.role in (Role.reviewer.value, Role.admin.value))
    if campaign.status != CampaignStatus.published and not full:
        return unauthenticated() if actor is None else error("FORBIDDEN", "You are not authorized to perform this action.", 403)

    currency = campaign.goal_currency
    balance = {"currency": currency, "raised": raised_total(campaign.id, currency).amount}
    if full:
        balance.update({
            "reserved_for_payouts": _money(_sum_payouts(campaign.id, currency, IN_FLIGHT)),
            "paid_out": _money(_sum_payouts(campaign.id, currency, (PayoutStatus.succeeded,))),
            "available": _money(available_funds(campaign.id, currency)),
        })
    return ok({"campaign_id": campaign.id, "goal": {"amount": _money(campaign.goal_amount), "currency": currency},
               "balance": balance, "visibility": "full" if full else "public",
               "source": "ledger", "as_of": datetime.now(timezone.utc).isoformat()})


def init_operations(app) -> None:
    app.register_blueprint(bp, url_prefix="/api/v1")
