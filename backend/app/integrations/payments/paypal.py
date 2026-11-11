from decimal import Decimal, InvalidOperation

import requests


class PayPalSandboxAdapter:
    """Network adapter; no browser payload can confirm a donation."""

    def __init__(self, config):
        self.config = config

    @staticmethod
    def _json_object(response):
        """Provider payloads must be JSON objects; fail before any association otherwise."""
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise ValueError("PAYMENT_PROVIDER_RESPONSE_INVALID") from exc
        if not isinstance(payload, dict):
            raise ValueError("PAYMENT_PROVIDER_RESPONSE_INVALID")
        return payload

    def _token(self):
        response = requests.post(
            f"{self.config['PAYPAL_BASE_URL']}/v1/oauth2/token",
            auth=(self.config["PAYPAL_CLIENT_ID"], self.config["PAYPAL_CLIENT_SECRET"]),
            data={"grant_type": "client_credentials"}, timeout=10,
        )
        response.raise_for_status()
        token = self._json_object(response).get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("PAYMENT_PROVIDER_RESPONSE_INVALID")
        return token

    @staticmethod
    def _validate_order_representation(order, donation):
        """Validate the canonical donation reference and money before association."""
        order_id = order.get("id")
        units = order.get("purchase_units") or []
        unit = units[0] if isinstance(units, list) and units and isinstance(units[0], dict) else {}
        amount = unit.get("amount") if isinstance(unit.get("amount"), dict) else {}
        try:
            provider_value = Decimal(str(amount.get("value")))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("PAYMENT_ORDER_MISMATCH")
        if (not isinstance(order_id, str) or not order_id or unit.get("reference_id") != donation.id
                or amount.get("currency_code") != donation.currency
                or provider_value != Decimal(donation.amount)):
            raise ValueError("PAYMENT_ORDER_MISMATCH")
        return order

    def create_order(self, donation, return_url, cancel_url):
        response = requests.post(
            f"{self.config['PAYPAL_BASE_URL']}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {self._token()}", "Prefer": "return=representation"},
            json={"intent": "CAPTURE", "purchase_units": [{"reference_id": donation.id,
                  "amount": {"currency_code": donation.currency, "value": str(donation.amount)}}],
                  "application_context": {"return_url": return_url, "cancel_url": cancel_url}},
            timeout=15,
        )
        response.raise_for_status()
        order = self._json_object(response)
        # PayPal can return minimal responses despite Prefer. Re-read the order rather
        # than associate an order that lacks an authoritative canonical representation.
        if not order.get("purchase_units"):
            order_id = order.get("id")
            if not isinstance(order_id, str) or not order_id:
                raise ValueError("PAYMENT_PROVIDER_RESPONSE_INVALID")
            order = self.get_order(order_id)
        return self._validate_order_representation(order, donation)

    def capture_order(self, order_id):
        response = requests.post(
            f"{self.config['PAYPAL_BASE_URL']}/v2/checkout/orders/{order_id}/capture",
            headers={"Authorization": f"Bearer {self._token()}"}, timeout=15,
        )
        response.raise_for_status()
        return self._json_object(response)

    def get_order(self, order_id):
        """Retrieve authoritative order state after an ambiguous capture timeout."""
        response = requests.get(
            f"{self.config['PAYPAL_BASE_URL']}/v2/checkout/orders/{order_id}",
            headers={"Authorization": f"Bearer {self._token()}"}, timeout=15,
        )
        response.raise_for_status()
        return self._json_object(response)

    def verify_webhook(self, headers, body):
        required = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID")
        if not all(self.config.get(k) for k in required):
            return False
        payload = {"auth_algo": headers.get("PAYPAL-AUTH-ALGO"), "cert_url": headers.get("PAYPAL-CERT-URL"),
                   "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"),
                   "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG"),
                   "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"),
                   "webhook_id": self.config["PAYPAL_WEBHOOK_ID"], "webhook_event": body}
        response = requests.post(
            f"{self.config['PAYPAL_BASE_URL']}/v1/notifications/verify-webhook-signature",
            headers={"Authorization": f"Bearer {self._token()}"}, json=payload, timeout=15,
        )
        return response.ok and self._json_object(response).get("verification_status") == "SUCCESS"
