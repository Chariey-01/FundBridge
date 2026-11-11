"""Data the phone channels need from the core backend, and the store they own."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from app.services.ai.ports import Money


@dataclass(frozen=True)
class BeneficiaryRecord:
    id: str
    display_name: str
    msisdn: str
    preferred_language: str
    verification_status: str


@dataclass(frozen=True)
class CampaignStatusView:
    id: str
    slug: str
    title: str
    status: str  # draft | submitted | published | closed
    goal: Money
    raised: Money  # from the ledger


@dataclass(frozen=True)
class PayoutStatusView:
    id: str
    amount: Money
    status: str  # shared payout state machine value
    updated_at: datetime


@dataclass
class PinRecord:
    pin_hash: str
    failed_attempts: int = 0
    locked_until: datetime | None = None


@dataclass
class Preference:
    language: str | None = None
    opted_out: bool = False


class BeneficiaryDirectory(Protocol):
    def find_by_phone(self, msisdn: str) -> BeneficiaryRecord | None: ...

    def campaigns_for(self, beneficiary_id: str) -> Sequence[CampaignStatusView]: ...

    def latest_payout(self, beneficiary_id: str) -> PayoutStatusView | None: ...


class MessagingStore(Protocol):
    def get_pin(self, beneficiary_id: str) -> PinRecord | None: ...

    def save_pin(self, beneficiary_id: str, record: PinRecord) -> None: ...

    def delete_pin(self, beneficiary_id: str) -> None: ...

    def get_preference(self, msisdn: str) -> Preference: ...

    def save_preference(self, msisdn: str, preference: Preference) -> None: ...

    def open_support_request(
        self, *, msisdn: str, beneficiary_id: str | None, channel: str, topic: str, priority: str
    ) -> str: ...
