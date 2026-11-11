from decimal import Decimal
from unittest.mock import Mock, patch
import pytest

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


def test_minimal_create_response_is_reconciled_before_order_association():
    donation = Mock(id="donation-2", currency="USD", amount=Decimal("8.00"))
    minimal = Mock(); minimal.json.return_value = {"id": "order-2", "status": "CREATED", "links": [{"rel": "approve", "href": "https://paypal.test/approve"}]}; minimal.raise_for_status.return_value = None
    authoritative = {"id": "order-2", "status": "CREATED", "purchase_units": [{"reference_id": "donation-2", "amount": {"currency_code": "USD", "value": "8.00"}}]}
    adapter = PayPalSandboxAdapter({"PAYPAL_BASE_URL": "https://paypal.test", "PAYPAL_CLIENT_ID": "id", "PAYPAL_CLIENT_SECRET": "secret"})
    with patch.object(adapter, "_token", return_value="token"), patch.object(adapter, "get_order", return_value=authoritative) as get_order, patch("app.integrations.payments.paypal.requests.post", return_value=minimal):
        result = adapter.create_order(donation, "https://app.test/return", "https://app.test/cancel")
    assert result["links"] == [{"rel": "approve", "href": "https://paypal.test/approve"}]
    get_order.assert_called_once_with("order-2")


def test_mismatched_order_response_fails_closed():
    donation = Mock(id="donation-3", currency="USD", amount=Decimal("8.00"))
    response = Mock(); response.json.return_value = {"id": "order-3", "purchase_units": [{"reference_id": "wrong", "amount": {"currency_code": "USD", "value": "8.00"}}]}; response.raise_for_status.return_value = None
    adapter = PayPalSandboxAdapter({"PAYPAL_BASE_URL": "https://paypal.test", "PAYPAL_CLIENT_ID": "id", "PAYPAL_CLIENT_SECRET": "secret"})
    with patch.object(adapter, "_token", return_value="token"), patch("app.integrations.payments.paypal.requests.post", return_value=response), pytest.raises(ValueError, match="PAYMENT_ORDER_MISMATCH"):
        adapter.create_order(donation, "https://app.test/return", "https://app.test/cancel")
