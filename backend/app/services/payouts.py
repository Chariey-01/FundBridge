from app.extensions import db
from app.models.core import AuditLog, PayoutStatus
from app.services.ledger import release_payout


def apply_provider_status(payout, status, *, actor_id=None, failure_reason=None):
    """Provider callbacks are idempotent; ambiguous timeouts never release funds."""
    if status == "PENDING":
        if payout.status in (PayoutStatus.submitted, PayoutStatus.pending_confirmation):
            payout.status = PayoutStatus.pending_confirmation
        return payout
    if status == "SUCCEEDED":
        if payout.status == PayoutStatus.succeeded: return payout
        if payout.status not in (PayoutStatus.submitted, PayoutStatus.pending_confirmation): raise ValueError("INVALID_PAYOUT_TRANSITION")
        payout.status = PayoutStatus.succeeded
    elif status == "FAILED":
        if payout.status == PayoutStatus.failed: return payout
        if payout.status not in (PayoutStatus.submitted, PayoutStatus.pending_confirmation): raise ValueError("INVALID_PAYOUT_TRANSITION")
        payout.status = PayoutStatus.failed; payout.failure_reason_code = failure_reason or "provider_failed"; release_payout(payout, "failed")
    else: raise ValueError("INVALID_PROVIDER_PAYOUT_STATUS")
    db.session.add(AuditLog(actor_id=actor_id, action=f"payout.{payout.status.value}", resource_type="payout", resource_id=payout.id))
    return payout
