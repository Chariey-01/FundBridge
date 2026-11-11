"""In-memory directory and store for tests and the clearly labelled offline demo."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field, replace

from .ports import BeneficiaryRecord, CampaignStatusView, PayoutStatusView, PinRecord, Preference


@dataclass
class InMemoryBeneficiaryDirectory:
    beneficiaries: dict[str, BeneficiaryRecord] = field(default_factory=dict)  # by msisdn
    campaigns: dict[str, list[CampaignStatusView]] = field(default_factory=dict)  # by beneficiary id
    payouts: dict[str, PayoutStatusView] = field(default_factory=dict)  # latest, by beneficiary id

    def find_by_phone(self, msisdn: str) -> BeneficiaryRecord | None:
        return self.beneficiaries.get(msisdn)

    def campaigns_for(self, beneficiary_id: str) -> list[CampaignStatusView]:
        return list(self.campaigns.get(beneficiary_id, []))

    def latest_payout(self, beneficiary_id: str) -> PayoutStatusView | None:
        return self.payouts.get(beneficiary_id)


@dataclass
class InMemoryMessagingStore:
    pins: dict[str, PinRecord] = field(default_factory=dict)
    preferences: dict[str, Preference] = field(default_factory=dict)
    support_requests: list[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get_pin(self, beneficiary_id: str) -> PinRecord | None:
        record = self.pins.get(beneficiary_id)
        return replace(record) if record else None

    def save_pin(self, beneficiary_id: str, record: PinRecord) -> None:
        self.pins[beneficiary_id] = replace(record)

    def delete_pin(self, beneficiary_id: str) -> None:
        self.pins.pop(beneficiary_id, None)

    def get_preference(self, msisdn: str) -> Preference:
        pref = self.preferences.get(msisdn)
        return replace(pref) if pref else Preference()

    def save_preference(self, msisdn: str, preference: Preference) -> None:
        self.preferences[msisdn] = replace(preference)

    def first_delivery(self, channel: str, key: str) -> bool:
        with self._lock:
            seen = self.__dict__.setdefault("_deliveries", set())
            if (channel, key) in seen:
                return False
            seen.add((channel, key))
            return True

    def open_support_request(self, *, msisdn, beneficiary_id, channel, topic, priority) -> str:
        with self._lock:
            for existing in self.support_requests:  # repeated dial or a gateway retry: one open request
                if (existing["msisdn"], existing["topic"], existing["channel"], existing["status"]) == (
                        msisdn, topic, channel, "open"):
                    return existing["reference"]
            reference = "HLP-" + secrets.token_hex(3).upper()
            self.support_requests.append(
                {"reference": reference, "msisdn": msisdn, "beneficiary_id": beneficiary_id, "channel": channel,
                 "topic": topic, "priority": priority, "status": "open"}
            )
        return reference
