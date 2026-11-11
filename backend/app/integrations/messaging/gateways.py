"""Outbound SMS gateways.

``SimulatedSmsGateway`` never contacts a network: messages go to an in-memory
outbox that the simulator page reads. Its results say ``status="simulated"`` so
nothing upstream can mistake them for delivery.

``AfricasTalkingSmsGateway`` posts to the Africa's Talking SMS API. It was
written from Africa's Talking's public documentation (POST /version1/messaging,
``apiKey`` header, form fields username/to/message/from) and has not been run
against the sandbox or live API from this repository: no credentials were
available. With ``AT_USERNAME=sandbox`` messages only reach Africa's Talking's
own simulator, not real phones. A "submitted" result means the gateway accepted
the message; it is not proof of delivery to the handset.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

import requests

from app.services.messaging.phone import mask_msisdn

log = logging.getLogger("fundbridge.messaging")


@dataclass(frozen=True)
class SendResult:
    status: str  # simulated | submitted | failed
    provider: str
    message_id: str | None = None
    detail: str | None = None


class SmsGateway(Protocol):
    name: str
    mode: str  # simulated | africastalking_sandbox | africastalking_live

    def send(self, to: str, message: str) -> SendResult: ...


@dataclass
class SimulatedSmsGateway:
    name: str = "simulator"
    mode: str = "simulated"
    max_messages: int = 500
    outbox: deque = field(default_factory=deque)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def send(self, to: str, message: str) -> SendResult:
        with self._lock:
            message_id = f"SIM-{next(self._ids):06d}"
            self.outbox.append(
                {
                    "id": message_id,
                    "to": to,
                    "message": message,
                    "status": "simulated",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            while len(self.outbox) > self.max_messages:
                self.outbox.popleft()
        log.info("simulated sms to %s (%s)", mask_msisdn(to), message_id)
        return SendResult("simulated", self.name, message_id)

    def messages_for(self, msisdn: str | None = None, limit: int = 50) -> list[dict]:
        with self._lock:
            items = [m for m in self.outbox if msisdn is None or m["to"] == msisdn]
        return list(reversed(items))[:limit]


class AfricasTalkingSmsGateway:
    name = "africastalking"

    def __init__(self, *, username: str, api_key: str, sender_id: str | None = None, timeout: float = 10.0,
                 session: requests.Session | None = None) -> None:
        if not username or not api_key:
            raise ValueError("Africa's Talking username and API key are required")
        self.username = username
        self._api_key = api_key
        self.sender_id = sender_id or None
        self.timeout = timeout
        self.mode = "africastalking_sandbox" if username == "sandbox" else "africastalking_live"
        host = "api.sandbox.africastalking.com" if username == "sandbox" else "api.africastalking.com"
        self.url = f"https://{host}/version1/messaging"
        self._session = session or requests.Session()

    def send(self, to: str, message: str) -> SendResult:
        data = {"username": self.username, "to": to, "message": message}
        if self.sender_id:
            data["from"] = self.sender_id
        try:
            response = self._session.post(
                self.url,
                data=data,
                headers={"apiKey": self._api_key, "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            log.warning("Africa's Talking request failed: %s", type(exc).__name__)
            return SendResult("failed", self.name, detail="network_error")
        if response.status_code >= 400:
            return SendResult("failed", self.name, detail=f"http_{response.status_code}")
        try:
            recipients = response.json()["SMSMessageData"]["Recipients"]
            first = recipients[0]
        except (ValueError, KeyError, IndexError, TypeError):
            return SendResult("failed", self.name, detail="unexpected_response")
        # Africa's Talking documents statusCode 100-102 as accepted (Processed / Sent / Queued).
        if first.get("statusCode") in (100, 101, 102):
            return SendResult("submitted", self.name, first.get("messageId"), first.get("status"))
        return SendResult("failed", self.name, first.get("messageId"), str(first.get("status") or "rejected"))
