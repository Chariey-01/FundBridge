class PayoutSimulator:
    """Explicit demo adapter: submission is never confirmation or beneficiary receipt."""
    name = "simulator"
    def submit_payout(self, payout): return {"reference": f"sim-{payout.id}", "status": "submitted"}
    def get_payout_status(self, reference): return {"reference": reference, "status": "pending_confirmation"}
    def verify_callback(self, headers, body): return False
