import requests


class PayPalSandboxAdapter:
    """Network adapter; no browser payload can confirm a donation."""
    def __init__(self, config): self.config = config
    def _token(self):
        r = requests.post(f"{self.config['PAYPAL_BASE_URL']}/v1/oauth2/token", auth=(self.config['PAYPAL_CLIENT_ID'], self.config['PAYPAL_CLIENT_SECRET']), data={"grant_type": "client_credentials"}, timeout=10)
        r.raise_for_status(); return r.json()["access_token"]
    def create_order(self, donation, return_url, cancel_url):
        r = requests.post(f"{self.config['PAYPAL_BASE_URL']}/v2/checkout/orders", headers={"Authorization": f"Bearer {self._token()}"}, json={"intent": "CAPTURE", "purchase_units": [{"reference_id": donation.id, "amount": {"currency_code": donation.currency, "value": str(donation.amount)}}], "application_context": {"return_url": return_url, "cancel_url": cancel_url}}, timeout=15)
        r.raise_for_status(); return r.json()
    def capture_order(self, order_id):
        r = requests.post(f"{self.config['PAYPAL_BASE_URL']}/v2/checkout/orders/{order_id}/capture", headers={"Authorization": f"Bearer {self._token()}"}, timeout=15); r.raise_for_status(); return r.json()
    def get_order(self, order_id):
        """Retrieve authoritative order state after an ambiguous capture timeout."""
        r = requests.get(f"{self.config['PAYPAL_BASE_URL']}/v2/checkout/orders/{order_id}", headers={"Authorization": f"Bearer {self._token()}"}, timeout=15)
        r.raise_for_status(); return r.json()
    def verify_webhook(self, headers, body):
        required = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID")
        if not all(self.config.get(k) for k in required): return False
        payload = {"auth_algo": headers.get("PAYPAL-AUTH-ALGO"), "cert_url": headers.get("PAYPAL-CERT-URL"), "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"), "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG"), "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"), "webhook_id": self.config["PAYPAL_WEBHOOK_ID"], "webhook_event": body}
        r = requests.post(f"{self.config['PAYPAL_BASE_URL']}/v1/notifications/verify-webhook-signature", headers={"Authorization": f"Bearer {self._token()}"}, json=payload, timeout=15)
        return r.ok and r.json().get("verification_status") == "SUCCESS"
