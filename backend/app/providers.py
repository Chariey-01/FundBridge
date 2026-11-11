import hashlib
import json
from decimal import Decimal
from .errors import error


class PayPalSimulator:
    """Deterministic development adapter. It never marks payments complete itself."""
    name = "paypal_simulator"
    def create_order(self, donation, return_url=None, cancel_url=None):
        order_id = "SIM-ORDER-" + donation.id
        return {"id": order_id, "status": "CREATED", "approval_url": None, "simulated": True}
    def capture_order(self, provider_order_id):
        return {"id": "SIM-CAPTURE-" + provider_order_id, "status": "PENDING", "simulated": True}
    def verify_webhook(self, headers, body):
        # Local simulation requires an explicit test-only marker; production must use PayPal verification.
        return headers.get("X-FundBridge-Simulator") == "verified"


def payment_provider(): return PayPalSimulator()


class PayoutSimulator:
    name = "payout_simulator"
    def submit_payout(self, payout): return {"reference": "SIM-PAYOUT-" + payout.id, "status": "PENDING", "simulated": True}
    def get_payout_status(self, reference): return {"reference": reference, "status": "PENDING", "simulated": True}
    def verify_callback(self, headers, body): return headers.get("X-FundBridge-Simulator") == "verified"
