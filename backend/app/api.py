import re
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, g
from .extensions import db
from .errors import error
from .models import User, BeneficiaryProfile, Campaign, Donation, Payout, audit
from .security import issue_token, require_auth, roles
from .providers import payment_provider, PayoutSimulator
from .services import money, complete_donation, reserve_payout, available_funds

api = Blueprint("api", __name__)

def ok(data, status=200, meta=None): return jsonify(data=data, meta=meta or {}), status
def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict): error("VALIDATION_ERROR", "A JSON object is required.", 400)
    return value
def currency(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value): error("VALIDATION_ERROR", "The supplied information is invalid.", 400, {"currency": ["Use an ISO 4217 code."]})
    return value
def serialize_user(u): return {"id": u.id, "email": u.email, "phone_number": u.phone_number, "role": u.role, "status": u.status}
def serialize_campaign(c): return {"id": c.id, "creator_id": c.creator_id, "beneficiary_id": c.beneficiary_id, "title": c.title, "slug": c.slug, "description": c.description, "category": c.category, "goal": {"amount": str(c.goal_amount), "currency": c.goal_currency}, "status": c.status, "review_status": c.review_status}
def serialize_donation(d): return {"id": d.id, "campaign_id": d.campaign_id, "amount": str(d.amount), "currency": d.currency, "provider": d.provider, "status": d.status, "created_at": d.created_at.isoformat()}
def serialize_payout(p): return {"id": p.id, "beneficiary_id": p.beneficiary_id, "campaign_id": p.campaign_id, "amount": str(p.amount), "currency": p.currency, "destination_type": p.destination_type, "provider": p.provider, "status": p.status}

@api.get("/health")
def health(): return ok({"status": "ok"})
@api.get("/api/v1/public/config")
def public_config(): return ok({"payment_provider": "paypal_simulator", "payout_provider": "payout_simulator", "messaging_provider": "not_configured", "simulated": True})

@api.post("/api/v1/auth/register")
def register():
    v = body(); email, phone, password = v.get("email"), v.get("phone_number"), v.get("password")
    if not password or len(password) < 12 or not (email or phone): error("VALIDATION_ERROR", "The supplied information is invalid.", 400, {"account": ["Email or phone and a 12-character password are required."]})
    if email and User.query.filter_by(email=email.lower()).first() or phone and User.query.filter_by(phone_number=phone).first(): error("CONFLICT", "An account already exists.", 409)
    u = User(email=email.lower() if email else None, phone_number=phone) # role is intentionally not client-controlled
    u.set_password(password); db.session.add(u); db.session.commit()
    return ok({"user": serialize_user(u), "access_token": issue_token(u)}, 201)

@api.post("/api/v1/auth/login")
def login():
    v = body(); identifier, password = v.get("identifier"), v.get("password")
    u = User.query.filter((User.email == str(identifier).lower()) | (User.phone_number == identifier)).first()
    if not u or not password or not u.verify_password(password): error("INVALID_CREDENTIALS", "Invalid credentials.", 401)
    if u.status != "active": error("ACCOUNT_UNAVAILABLE", "This account is unavailable.", 403)
    return ok({"user": serialize_user(u), "access_token": issue_token(u)})

@api.get("/api/v1/auth/me")
@require_auth
def me(): return ok(serialize_user(g.user))
@api.post("/api/v1/auth/logout")
@require_auth
def logout(): return ok({"status": "logged_out"}) # JWT expiry/revocation store is deployment-specific

@api.get("/api/v1/campaigns")
def campaigns():
    q = Campaign.query.filter_by(status="published")
    if request.args.get("category"): q = q.filter_by(category=request.args["category"])
    return ok([serialize_campaign(c) for c in q.order_by(Campaign.created_at.desc()).limit(50)])
@api.get("/api/v1/campaigns/<campaign_id>")
def campaign_detail(campaign_id):
    c = Campaign.query.get_or_404(campaign_id)
    if c.status != "published": error("NOT_FOUND", "Campaign not found.", 404)
    return ok(serialize_campaign(c))
@api.post("/api/v1/campaigns")
@require_auth
@roles("creator", "admin")
def create_campaign():
    v = body(); beneficiary = BeneficiaryProfile.query.get(v.get("beneficiary_id")); amount = money(v.get("goal_amount")); curr = currency(v.get("goal_currency")); title = str(v.get("title", "")).strip(); desc = str(v.get("description", "")).strip(); category = str(v.get("category", "")).strip()
    if not beneficiary or not title or not desc or not category: error("VALIDATION_ERROR", "The supplied information is invalid.", 400)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") + "-" + __import__("uuid").uuid4().hex[:8]
    c = Campaign(creator_id=g.user.id, beneficiary_id=beneficiary.id, title=title, slug=slug, description=desc, category=category, goal_amount=amount, goal_currency=curr)
    db.session.add(c); audit(g.user.id, "campaign.created", "campaign", c.id); db.session.commit(); return ok(serialize_campaign(c), 201)
@api.post("/api/v1/campaigns/<campaign_id>/submit")
@require_auth
def submit_campaign(campaign_id):
    c = Campaign.query.get_or_404(campaign_id)
    if c.creator_id != g.user.id or c.status != "draft": error("FORBIDDEN", "Only the draft owner may submit this campaign.", 403)
    c.status, c.review_status = "submitted", "pending"; audit(g.user.id, "campaign.submitted", "campaign", c.id); db.session.commit(); return ok(serialize_campaign(c))
@api.get("/api/v1/me/campaigns")
@require_auth
def my_campaigns(): return ok([serialize_campaign(c) for c in Campaign.query.filter_by(creator_id=g.user.id).all()])

@api.get("/api/v1/beneficiaries/me")
@require_auth
def my_beneficiary():
    b = BeneficiaryProfile.query.filter_by(user_id=g.user.id).first()
    if not b: error("NOT_FOUND", "Beneficiary profile not found.", 404)
    return ok({"id": b.id, "display_name": b.display_name, "phone_number": b.phone_number, "preferred_language": b.preferred_language, "country_code": b.country_code, "verification_status": b.verification_status})
@api.post("/api/v1/beneficiaries")
@require_auth
@roles("community_agent", "admin")
def create_beneficiary():
    v = body()
    if not v.get("display_name") or not v.get("country_code"): error("VALIDATION_ERROR", "The supplied information is invalid.", 400)
    b = BeneficiaryProfile(user_id=v.get("user_id"), display_name=v["display_name"], phone_number=v.get("phone_number"), country_code=v["country_code"].upper(), preferred_language=v.get("preferred_language", "en"))
    db.session.add(b); db.session.commit(); return ok({"id": b.id, "display_name": b.display_name, "verification_status": b.verification_status}, 201)
@api.patch("/api/v1/beneficiaries/me")
@require_auth
def update_beneficiary():
    b = BeneficiaryProfile.query.filter_by(user_id=g.user.id).first()
    if not b: error("NOT_FOUND", "Beneficiary profile not found.", 404)
    v = body()
    for field in ("display_name", "phone_number", "preferred_language"):
        if field in v: setattr(b, field, v[field])
    db.session.commit(); return ok({"id": b.id, "display_name": b.display_name, "phone_number": b.phone_number, "preferred_language": b.preferred_language, "country_code": b.country_code, "verification_status": b.verification_status})

@api.post("/api/v1/donations/orders")
@require_auth
def donation_order():
    v = body(); key = request.headers.get("Idempotency-Key")
    if not key: error("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.", 400)
    existing = Donation.query.filter_by(idempotency_key=key).first()
    if existing: return ok(serialize_donation(existing))
    c = Campaign.query.get(v.get("campaign_id")); amount = money(v.get("amount")); curr = currency(v.get("currency"))
    if not c or c.status != "published": error("CAMPAIGN_UNAVAILABLE", "Campaign is unavailable for donations.", 409)
    d = Donation(campaign_id=c.id, donor_id=g.user.id, amount=amount, currency=curr, provider="paypal_simulator", idempotency_key=key, status="pending")
    db.session.add(d); db.session.flush(); order = payment_provider().create_order(d); d.provider_order_id = order["id"]; audit(g.user.id, "donation.order_created", "donation", d.id); db.session.commit()
    return ok({**serialize_donation(d), "provider_order": order}, 201)
@api.post("/api/v1/donations/<donation_id>/capture")
@require_auth
def capture_donation(donation_id):
    d = Donation.query.get_or_404(donation_id)
    if d.donor_id != g.user.id: error("FORBIDDEN", "Donation access denied.", 403)
    # Browser capture requests only initiate/reconcile; never complete the donation.
    return ok({**serialize_donation(d), "provider_result": payment_provider().capture_order(d.provider_order_id)})
@api.get("/api/v1/donations/<donation_id>")
@require_auth
def donation_detail(donation_id):
    d = Donation.query.get_or_404(donation_id)
    if d.donor_id != g.user.id and g.user.role not in {"admin", "reviewer"}: error("FORBIDDEN", "Donation access denied.", 403)
    return ok(serialize_donation(d))
@api.get("/api/v1/me/donations")
@require_auth
def my_donations(): return ok([serialize_donation(d) for d in Donation.query.filter_by(donor_id=g.user.id).all()])
@api.post("/api/v1/webhooks/paypal")
def paypal_webhook():
    v = body()
    if not payment_provider().verify_webhook(request.headers, v): error("INVALID_WEBHOOK", "Webhook verification failed.", 401)
    d = Donation.query.filter_by(provider_order_id=v.get("order_id")).first()
    if not d: error("NOT_FOUND", "Donation not found.", 404)
    if v.get("event_type") == "PAYMENT.CAPTURE.COMPLETED": complete_donation(d, v.get("capture_id"), None); db.session.commit()
    return ok({"status": "accepted"})

@api.post("/api/v1/payouts")
@require_auth
def request_payout():
    v = body(); key = request.headers.get("Idempotency-Key")
    if not key: error("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.", 400)
    old = Payout.query.filter_by(idempotency_key=key).first()
    if old: return ok(serialize_payout(old))
    b = BeneficiaryProfile.query.get(v.get("beneficiary_id")); c = Campaign.query.get(v.get("campaign_id")); amount = money(v.get("amount")); curr = currency(v.get("currency"))
    if not b or not c or c.beneficiary_id != b.id: error("VALIDATION_ERROR", "Campaign and beneficiary do not match.", 400)
    if b.user_id != g.user.id and g.user.role not in {"admin", "community_agent"}: error("FORBIDDEN", "Payout access denied.", 403)
    p = Payout(beneficiary_id=b.id, campaign_id=c.id, amount=amount, currency=curr, destination_type=v.get("destination_type", "wallet"), destination_reference=v.get("destination_reference", ""), idempotency_key=key)
    if not p.destination_reference: error("VALIDATION_ERROR", "A payout destination is required.", 400)
    db.session.add(p); reserve_payout(p, g.user.id); db.session.commit(); return ok(serialize_payout(p), 201)
@api.get("/api/v1/payouts")
@require_auth
def list_payouts():
    q = Payout.query
    if g.user.role not in {"admin", "reviewer"}:
        b = BeneficiaryProfile.query.filter_by(user_id=g.user.id).first()
        q = q.filter_by(beneficiary_id=b.id) if b else q.filter(False)
    return ok([serialize_payout(p) for p in q.all()])
@api.get("/api/v1/payouts/<payout_id>")
@require_auth
def payout_detail(payout_id):
    p = Payout.query.get_or_404(payout_id)
    b = BeneficiaryProfile.query.filter_by(user_id=g.user.id).first()
    if g.user.role not in {"admin", "reviewer"} and (not b or b.id != p.beneficiary_id): error("FORBIDDEN", "Payout access denied.", 403)
    return ok(serialize_payout(p))
@api.post("/api/v1/payouts/<payout_id>/review")
@require_auth
@roles("reviewer", "admin")
def review_payout(payout_id):
    p = Payout.query.get_or_404(payout_id); v = body(); action = v.get("action")
    if p.status != "under_review": error("INVALID_STATE", "Payout is not awaiting review.", 409)
    if action == "approve": p.status = "approved_for_submission"
    elif action == "reject": p.status = "rejected"
    else: error("VALIDATION_ERROR", "Review action must be approve or reject.", 400)
    audit(g.user.id, "payout." + action, "payout", p.id); db.session.commit(); return ok(serialize_payout(p))
