"""Local HTTP test doubles for PayPal Orders v2 and the OpenAI Chat Completions API.

TEST DOUBLES ONLY. They let the end-to-end suite drive the backend's real provider adapters
(``PayPalSandboxAdapter``, ``OpenAIProvider``) over real HTTP, so request construction, error
handling and response parsing are exercised without credentials. They are not PayPal or OpenAI,
prove nothing about live provider behaviour, and must never be presented as a live integration.

PayPal behaviours modelled (Orders v2): OAuth client-credentials token; create order (CREATED,
with an ``approve`` link); buyer approval (test-only endpoint standing in for the PayPal checkout
page); capture (422 ORDER_NOT_APPROVED before approval, 422 ORDER_ALREADY_CAPTURED on repeat);
webhook signature verification (SUCCESS only for the double's own signature).
"""

from __future__ import annotations

import base64
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

VALID_WEBHOOK_SIGNATURE = "e2e-double-valid-signature"


class _Handler(BaseHTTPRequestHandler):
    double: "_Double"

    def log_message(self, *args):  # keep test output quiet
        return

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")
        if "json" in ctype and raw:
            return json.loads(raw)
        return raw.decode()

    def _send(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):  # noqa: N802
        status, body = self.double.handle(self.command, self.path, dict(self.headers), self._body())
        self._send(status, body)

    def do_GET(self):  # noqa: N802
        status, body = self.double.handle(self.command, self.path, dict(self.headers), None)
        self._send(status, body)


class _Double:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests: list[dict] = []
        self.server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "_Double":
        handler = type("Handler", (_Handler,), {"double": self})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()

    def handle(self, method, path, headers, body):  # pragma: no cover - overridden
        raise NotImplementedError


class PayPalDouble(_Double):
    def __init__(self, client_id: str, client_secret: str, webhook_id: str):
        super().__init__()
        self.client_id, self.client_secret, self.webhook_id = client_id, client_secret, webhook_id
        self.orders: dict[str, dict] = {}
        self.tokens: set[str] = set()
        self.capture_override: dict[str, dict] = {}  # order id -> fields to tamper in the capture response
        # PayPal answers create-order with a minimal body (id, status, links) unless the request sends
        # "Prefer: return=representation" (PayPal's documented default). Keep this False: it is what makes the
        # e2e suite catch a regression of C-4b. True exists only to diagnose other failures.
        self.assume_representation = False

    def _authorized(self, headers) -> bool:
        return headers.get("Authorization", "").removeprefix("Bearer ") in self.tokens

    def approve(self, order_id: str) -> None:
        """Stands in for the donor approving the payment on PayPal's checkout page."""
        with self.lock:
            self.orders[order_id]["status"] = "APPROVED"

    def capture_out_of_band(self, order_id: str, capture_status: str = "COMPLETED") -> None:
        """PayPal captured the order but the backend never saw the response (for example a timeout).
        ``capture_status="PENDING"`` models a capture PayPal is still holding (order COMPLETED, capture PENDING)."""
        with self.lock:
            order = self.orders[order_id]
            order["status"] = "COMPLETED"
            order["capture"] = {"id": "CAP-OOB-" + uuid.uuid4().hex[:8].upper(), "status": capture_status,
                                "amount": dict(order["unit"]["amount"])}

    def handle(self, method, path, headers, body):
        with self.lock:
            self.requests.append({"method": method, "path": path})
        if path.startswith("/test/orders/") and path.endswith("/approve"):  # double-only: the donor approves at PayPal
            order_id = path.split("/")[3]
            if order_id not in self.orders:
                return 404, {"name": "RESOURCE_NOT_FOUND"}
            self.approve(order_id)
            return 200, {"id": order_id, "status": "APPROVED"}
        if path.startswith("/test/orders/") and path.endswith("/capture-out-of-band"):  # double-only: lost response
            order_id = path.split("/")[3]
            if order_id not in self.orders:
                return 404, {"name": "RESOURCE_NOT_FOUND"}
            self.capture_out_of_band(order_id)
            return 200, {"id": order_id, "status": "COMPLETED"}
        if path == "/v1/oauth2/token":
            expected = "Basic " + base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            if headers.get("Authorization") != expected or "grant_type=client_credentials" not in (body or ""):
                return 401, {"error": "invalid_client", "error_description": "Client Authentication failed"}
            token = "A21-e2e-" + uuid.uuid4().hex
            with self.lock:
                self.tokens.add(token)
            return 200, {"access_token": token, "token_type": "Bearer", "expires_in": 32400}
        if not self._authorized(headers):
            return 401, {"name": "AUTHENTICATION_FAILURE", "message": "Authentication failed due to invalid credentials"}

        if path == "/v2/checkout/orders" and method == "POST":
            unit = body["purchase_units"][0]
            assert body["intent"] == "CAPTURE" and unit["reference_id"] and unit["amount"]["currency_code"]
            order_id = uuid.uuid4().hex[:17].upper()
            with self.lock:
                self.orders[order_id] = {"id": order_id, "status": "CREATED", "unit": unit}
            full = self.assume_representation or "return=representation" in headers.get("Prefer", "")
            extra = {"intent": "CAPTURE", "purchase_units": [{"reference_id": unit["reference_id"],
                                                              "amount": dict(unit["amount"])}]} if full else {}
            return 201, {"id": order_id, "status": "CREATED", **extra, "links": [
                {"href": f"{self.url}/v2/checkout/orders/{order_id}", "rel": "self", "method": "GET"},
                {"href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}", "rel": "approve", "method": "GET"},
                {"href": f"{self.url}/v2/checkout/orders/{order_id}/capture", "rel": "capture", "method": "POST"}]}

        if path.startswith("/v2/checkout/orders/") and method == "GET":  # order details (used by reconciliation)
            order_id = path.split("/")[4]
            with self.lock:
                order = self.orders.get(order_id)
                if order is None:
                    return 404, {"name": "RESOURCE_NOT_FOUND", "details": [{"issue": "INVALID_RESOURCE_ID"}]}
                unit = {"reference_id": order["unit"]["reference_id"], "amount": order["unit"]["amount"]}
                if "capture" in order:
                    unit["payments"] = {"captures": [order["capture"]]}
                return 200, {"id": order_id, "status": order["status"], "purchase_units": [unit]}

        if path.startswith("/v2/checkout/orders/") and path.endswith("/capture"):
            order_id = path.split("/")[4]
            with self.lock:
                order = self.orders.get(order_id)
                if order is None:
                    return 404, {"name": "RESOURCE_NOT_FOUND", "details": [{"issue": "INVALID_RESOURCE_ID"}]}
                if order["status"] == "COMPLETED":
                    return 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_ALREADY_CAPTURED"}]}
                if order["status"] != "APPROVED":
                    return 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_NOT_APPROVED"}]}
                order["status"] = "COMPLETED"
                capture = {"id": "CAP-" + uuid.uuid4().hex[:12].upper(), "status": "COMPLETED",
                           "amount": dict(order["unit"]["amount"])}
                capture.update(self.capture_override.get(order_id, {}))
                order["capture"] = capture
            return 201, {"id": order_id, "status": "COMPLETED", "purchase_units": [{
                "reference_id": order["unit"]["reference_id"], "payments": {"captures": [capture]}}]}

        if path == "/v1/notifications/verify-webhook-signature":
            ok = body.get("transmission_sig") == VALID_WEBHOOK_SIGNATURE and body.get("webhook_id") == self.webhook_id
            return 200, {"verification_status": "SUCCESS" if ok else "FAILURE"}
        return 404, {"name": "RESOURCE_NOT_FOUND"}


class OpenAIDouble(_Double):
    """Answers ``POST /v1/chat/completions`` with schema-valid JSON per task, or fails on demand."""

    CANNED = {
        "campaign_draft": {"title": "Help Amina finish secondary school",
                           "summary": "Amina needs support with her final-year school fees in Kisumu.",
                           "story": "Amina is in her final year of secondary school in Kisumu. Her family has "
                                    "covered what it can, and the remaining fees, books and uniform are beyond reach.",
                           "suggested_category": "education", "missing_information": ["school name"]},
        "translate": {"translated_text": "Amina anahitaji msaada wa karo ya shule.", "detected_source_language": "en"},
        "beneficiary_assistant": {"reply": "You can check your payout status from the menu.",
                                  "suggested_actions": ["view_payout_status"], "escalate_to_human": False},
        "campaign_search": {"keywords": ["school", "fees"], "category": "education", "country_code": "KE"},
        # No amounts and no outcome claims, so the server's guardrails accept it for any status.
        "status_explanation": {"explanation": "Here is what FundBridge's records show for this request."},
    }

    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key
        self.fail = False
        self.bodies: list[dict] = []

    def handle(self, method, path, headers, body):
        if headers.get("Authorization") != f"Bearer {self.api_key}":
            return 401, {"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}}
        if path != "/v1/chat/completions":
            return 404, {"error": {"message": "not found"}}
        with self.lock:
            self.bodies.append(body)
            failing = self.fail
        if failing:
            return 500, {"error": {"message": "The server had an error", "type": "server_error"}}
        fmt = body["response_format"]
        assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True and body["store"] is False
        task = fmt["json_schema"]["name"]
        return 200, {"id": "chatcmpl-e2e", "object": "chat.completion", "created": 0, "model": body["model"],
                     "choices": [{"index": 0, "finish_reason": "stop", "message": {
                         "role": "assistant", "content": json.dumps(self.CANNED[task]), "refusal": None}}],
                     "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


class AfricasTalkingDouble(_Double):
    """Answers ``POST /version1/messaging`` like Africa's Talking's SMS API (form fields, ``apiKey`` header).

    ``mode``: "ok" (statusCode 101 Success), "insufficient_balance" (405 for the recipient) or "auth_error" (HTTP 401).
    TEST DOUBLE ONLY: it says nothing about Africa's Talking's live behaviour.
    """

    def __init__(self, username: str, api_key: str):
        super().__init__()
        self.username, self.api_key, self.mode = username, api_key, "ok"
        self.messages: list[dict] = []

    def handle(self, method, path, headers, body):
        from urllib.parse import parse_qs

        if path != "/version1/messaging" or method != "POST":
            return 404, {"error": "not found"}
        if headers.get("apiKey") != self.api_key or self.mode == "auth_error":
            return 401, {"error": "The supplied authentication is invalid"}
        form = {k: v[0] for k, v in parse_qs(body if isinstance(body, str) else "").items()}
        assert form.get("username") == self.username and form.get("to") and form.get("message")
        with self.lock:
            self.messages.append(form)
            count = len(self.messages)
        if self.mode == "insufficient_balance":
            recipient = {"statusCode": 405, "number": form["to"], "status": "InsufficientBalance", "cost": "0",
                         "messageId": "None"}
        else:
            recipient = {"statusCode": 101, "number": form["to"], "status": "Success", "cost": "KES 0.8000",
                         "messageId": f"ATXid_{count:06d}"}
        return 201, {"SMSMessageData": {"Message": "Sent to 1/1", "Recipients": [recipient]}}

    def to(self, number: str) -> list[str]:
        with self.lock:
            return [m["message"] for m in self.messages if m["to"] == number]
