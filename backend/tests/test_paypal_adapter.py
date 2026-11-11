from decimal import Decimal
from unittest.mock import Mock, patch

from app.integrations.payments.paypal import PayPalSandboxAdapter


def test_create_order_requests_full_representation_and_returns_fixture():
    donation = Mock(id="donation-1", currency="USD", amount=Decimal("12.34"))
    response = Mock(ok=True)
    response.json.return_value = {
        "id": "order-1", "status": "CREATED",
        "purchase_units": [{"reference_id": "donation-1", "amount": {"currency_code": "USD", "value": "12.34"}}],
        "links": [{"rel": "approve", "href": "https://paypal.test/approve/order-1"}],
    }
    response.raise_for_status.return_value = None
    adapter = PayPalSandboxAdapter({"PAYPAL_BASE_URL": "https://paypal.test", "PAYPAL_CLIENT_ID": "id", "PAYPAL_CLIENT_SECRET": "secret"})
    with patch.object(adapter, "_token", return_value="token"), patch("app.integrations.payments.paypal.requests.post", return_value=response) as post:
        result = adapter.create_order(donation, "https://app.test/return", "https://app.test/cancel")
    assert result["id"] == "order-1"
    assert post.call_args.kwargs["headers"]["Prefer"] == "return=representation"
    assert post.call_args.kwargs["json"]["purchase_units"][0]["reference_id"] == "donation-1"
