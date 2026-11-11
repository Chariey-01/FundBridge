import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from flask import Blueprint, current_app, g, jsonify, request
from flask_jwt_extended import create_access_token
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.integrations.payments.paypal import PayPalSandboxAdapter
from app.integrations.payouts.simulator import PayoutSimulator
from app.models.core import (AuditLog, BeneficiaryProfile, Campaign, CampaignStatus, Donation, DonationStatus, Payout, PayoutStatus, Role, User)
from app.security.auth import current_user, roles_allowed
from app.services.ledger import release_payout, reserve_payout
from app.services.payments import mark_donation_completed

api = Blueprint("api_v1", __name__)
MONEY = Decimal("0.01")

def ok(data, status=200, meta=None): return jsonify(data=data, meta=meta or {}), status
def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict): raise ValueError("VALIDATION_ERROR")
    return value
def money(value):
    try: amount = Decimal(str(value)).quantize(MONEY)
    except (InvalidOperation, ValueError): raise ValueError("VALIDATION_ERROR")
    if amount <= 0: raise ValueError("VALIDATION_ERROR")
    return amount
def currency(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value): raise ValueError("VALIDATION_ERROR")
    return value
def serialize_campaign(x): return {"id":x.id,"title":x.title,"slug":x.slug,"description":x.description,"category":x.category,"goal":{"amount":str(x.goal_amount),"currency":x.goal_currency},"status":x.status.value,"review_status":x.review_status}
def serialize_donation(x): return {"id":x.id,"campaign_id":x.campaign_id,"amount":str(x.amount),"currency":x.currency,"status":x.status.value,"provider":x.provider}
def serialize_payout(x): return {"id":x.id,"campaign_id":x.campaign_id,"beneficiary_id":x.beneficiary_id,"amount":str(x.amount),"currency":x.currency,"status":x.status.value,"provider":x.provider}

@api.get("/public/config")
def public_config():
    return ok({"payments":{"paypal":{"mode":"sandbox" if current_app.config.get("PAYPAL_CLIENT_ID") else "unconfigured"}}, "payouts":{"provider":current_app.config["PAYOUT_PROVIDER"],"mode":"simulator" if current_app.config["PAYOUT_PROVIDER"] == "simulator" else "unconfigured"}, "feature_phone":{"sms":False,"ussd":False}})

@api.post("/auth/register")
def register():
    data=body(); email=data.get("email"); phone=data.get("phone_number"); password=data.get("password")
    if not password or len(password) < 12 or not (email or phone): raise ValueError("VALIDATION_ERROR")
    user=User(email=email, phone_number=phone, role=Role.donor); user.set_password(password)
    try: db.session.add(user); db.session.commit()
    except IntegrityError: db.session.rollback(); raise ValueError("ACCOUNT_ALREADY_EXISTS")
    return ok({"id":user.id,"role":user.role.value},201)

@api.post("/auth/login")
def login():
    data=body(); identity=data.get("email") or data.get("phone_number"); password=data.get("password", "")
    user=User.query.filter((User.email==identity) | (User.phone_number==identity)).first()
    if not user or user.status != "active" or not user.check_password(password): raise PermissionError("INVALID_CREDENTIALS")
    return ok({"access_token":create_access_token(identity=user.id),"user":{"id":user.id,"role":user.role.value}})

@api.get("/auth/me")
def me():
    u=current_user(); return ok({"id":u.id,"email":u.email,"phone_number":u.phone_number,"role":u.role.value})

@api.get("/campaigns")
def list_campaigns():
    q=Campaign.query.filter_by(status=CampaignStatus.published)
    if request.args.get("category"): q=q.filter_by(category=request.args["category"])
    return ok([serialize_campaign(x) for x in q.order_by(Campaign.published_at.desc()).limit(50)])

@api.get("/campaigns/<campaign_id>")
def campaign_detail(campaign_id):
    x=Campaign.query.get_or_404(campaign_id)
    if x.status != CampaignStatus.published:
        u=current_user()
        if u.id != x.creator_id and u.role not in (Role.reviewer,Role.admin): raise PermissionError("FORBIDDEN")
    return ok(serialize_campaign(x))

@api.post("/campaigns")
@roles_allowed(Role.creator, Role.admin)
def create_campaign():
    data=body(); title=data.get("title","").strip(); description=data.get("description","").strip(); slug=data.get("slug","").strip().lower()
    if not (3<=len(title)<=160 and len(description)>=20 and re.fullmatch(r"[a-z0-9-]{3,180}",slug) and data.get("category")): raise ValueError("VALIDATION_ERROR")
    beneficiary=BeneficiaryProfile.query.get(data.get("beneficiary_id"))
    if not beneficiary: raise ValueError("BENEFICIARY_NOT_FOUND")
    x=Campaign(creator_id=g.current_user.id,beneficiary_id=beneficiary.id,title=title,slug=slug,description=description,category=data["category"],goal_amount=money(data.get("goal_amount")),goal_currency=currency(data.get("goal_currency")))
    db.session.add(x); db.session.add(AuditLog(actor_id=g.current_user.id,action="campaign.created",resource_type="campaign",resource_id=x.id)); db.session.commit(); return ok(serialize_campaign(x),201)

@api.patch("/campaigns/<campaign_id>")
def update_campaign(campaign_id):
    u=current_user(); x=Campaign.query.get_or_404(campaign_id)
    if u.id != x.creator_id or x.status != CampaignStatus.draft: raise PermissionError("FORBIDDEN")
    data=body()
    for key in ("title","description","category"):
        if key in data and isinstance(data[key],str) and data[key].strip(): setattr(x,key,data[key].strip())
    db.session.add(AuditLog(actor_id=u.id,action="campaign.updated",resource_type="campaign",resource_id=x.id)); db.session.commit(); return ok(serialize_campaign(x))

@api.post("/campaigns/<campaign_id>/submit")
def submit_campaign(campaign_id):
    u=current_user(); x=Campaign.query.get_or_404(campaign_id)
    if u.id != x.creator_id or x.status != CampaignStatus.draft: raise PermissionError("FORBIDDEN")
    x.status=CampaignStatus.submitted; x.review_status="pending"; db.session.add(AuditLog(actor_id=u.id,action="campaign.submitted",resource_type="campaign",resource_id=x.id)); db.session.commit(); return ok(serialize_campaign(x))

@api.post("/beneficiaries")
@roles_allowed(Role.agent,Role.admin)
def assisted_beneficiary():
    data=body()
    if not data.get("display_name") or not data.get("phone_number") or not re.fullmatch(r"[A-Z]{2}",data.get("country_code","")): raise ValueError("VALIDATION_ERROR")
    x=BeneficiaryProfile(display_name=data["display_name"],phone_number=data["phone_number"],country_code=data["country_code"],preferred_language=data.get("preferred_language","en"),payout_destination_reference=data.get("payout_destination_reference"))
    db.session.add(x); db.session.commit(); return ok({"id":x.id,"verification_status":x.verification_status},201)

@api.post("/donations/orders")
def donation_order():
    # Guest payment requires a separately designed, non-enumerable ownership capability.
    # It is unavailable until that contract is approved; invalid tokens must never fall back.
    donor=current_user()
    data=body(); key=request.headers.get("Idempotency-Key")
    if not key: raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
    existing=Donation.query.filter_by(idempotency_key=key).first()
    if existing: return ok(serialize_donation(existing))
    campaign=Campaign.query.get(data.get("campaign_id"))
    if not campaign or campaign.status != CampaignStatus.published: raise ValueError("CAMPAIGN_NOT_AVAILABLE")
    donation=Donation(campaign_id=campaign.id,donor_id=donor.id,amount=money(data.get("amount")),currency=currency(data.get("currency")),provider="paypal",idempotency_key=key,status=DonationStatus.pending)
    adapter=PayPalSandboxAdapter(current_app.config)
    if not current_app.config.get("PAYPAL_CLIENT_ID"): raise ValueError("PAYMENT_PROVIDER_UNCONFIGURED")
    order=adapter.create_order(donation,data.get("return_url",""),data.get("cancel_url","")); donation.provider_order_id=order["id"]
    db.session.add(donation); db.session.commit(); return ok({**serialize_donation(donation),"approval_url":next((l["href"] for l in order.get("links",[]) if l.get("rel")=="approve"),None)},201)

@api.post("/webhooks/paypal")
def paypal_webhook():
    payload=body(); adapter=PayPalSandboxAdapter(current_app.config)
    if not adapter.verify_webhook(request.headers,payload): raise PermissionError("INVALID_WEBHOOK_SIGNATURE")
    if payload.get("event_type") == "PAYMENT.CAPTURE.COMPLETED":
        resource=payload.get("resource",{}); order_id=resource.get("supplementary_data",{}).get("related_ids",{}).get("order_id"); d=Donation.query.filter_by(provider_order_id=order_id).first()
        if not d: raise ValueError("PAYMENT_ORDER_MISMATCH")
        mark_donation_completed(d, order_id=order_id, capture=resource); db.session.commit()
    return "",204

@api.post("/donations/<donation_id>/capture")
def capture_donation(donation_id):
    """Server-side capture; redirect/query parameters are never accepted as proof."""
    donation=Donation.query.get_or_404(donation_id)
    u=current_user()
    if donation.donor_id != u.id and u.role not in (Role.admin,): raise PermissionError("FORBIDDEN")
    if donation.status == DonationStatus.completed: return ok(serialize_donation(donation))
    if donation.status != DonationStatus.pending or not donation.provider_order_id: raise ValueError("INVALID_DONATION_TRANSITION")
    result=PayPalSandboxAdapter(current_app.config).capture_order(donation.provider_order_id)
    if result.get("status") != "COMPLETED": raise ValueError("PAYMENT_NOT_CONFIRMED")
    unit=result.get("purchase_units", [{}])[0]
    if unit.get("reference_id") != donation.id: raise ValueError("PAYMENT_ORDER_MISMATCH")
    captures=unit.get("payments", {}).get("captures", [])
    if not captures or captures[0].get("status") != "COMPLETED": raise ValueError("PAYMENT_NOT_CONFIRMED")
    mark_donation_completed(donation,order_id=donation.provider_order_id,capture=captures[0],actor_id=u.id); db.session.commit()
    return ok(serialize_donation(donation))

@api.post("/payouts")
@roles_allowed(Role.beneficiary,Role.admin)
def request_payout():
    data=body(); key=request.headers.get("Idempotency-Key")
    if not key: raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
    existing=Payout.query.filter_by(idempotency_key=key).first()
    if existing: return ok(serialize_payout(existing))
    campaign=Campaign.query.get(data.get("campaign_id")); beneficiary=BeneficiaryProfile.query.get(data.get("beneficiary_id"))
    if not campaign or not beneficiary or campaign.beneficiary_id != beneficiary.id: raise ValueError("VALIDATION_ERROR")
    if g.current_user.role == Role.beneficiary and beneficiary.user_id != g.current_user.id: raise PermissionError("FORBIDDEN")
    # row lock serializes reservations for this campaign on PostgreSQL.
    db.session.query(Campaign).filter_by(id=campaign.id).with_for_update().one()
    p=Payout(campaign_id=campaign.id,beneficiary_id=beneficiary.id,amount=money(data.get("amount")),currency=currency(data.get("currency")),destination_type=data.get("destination_type","wallet"),destination_reference=beneficiary.payout_destination_reference or "",provider=current_app.config["PAYOUT_PROVIDER"],idempotency_key=key)
    if not p.destination_reference: raise ValueError("PAYOUT_DESTINATION_UNVERIFIED")
    db.session.add(p); db.session.flush(); reserve_payout(p); db.session.add(AuditLog(actor_id=g.current_user.id,action="payout.requested",resource_type="payout",resource_id=p.id)); db.session.commit(); return ok(serialize_payout(p),201)

@api.post("/payouts/<payout_id>/review")
@roles_allowed(Role.reviewer,Role.admin)
def review_payout(payout_id):
    p=Payout.query.get_or_404(payout_id); data=body(); decision=data.get("decision")
    if p.status != PayoutStatus.requested: raise ValueError("INVALID_PAYOUT_TRANSITION")
    if decision == "reject": p.status=PayoutStatus.rejected; release_payout(p,"rejected")
    elif decision == "approve": p.status=PayoutStatus.approved_for_submission
    else: raise ValueError("VALIDATION_ERROR")
    db.session.add(AuditLog(actor_id=g.current_user.id,action=f"payout.{decision}",resource_type="payout",resource_id=p.id)); db.session.commit(); return ok(serialize_payout(p))
