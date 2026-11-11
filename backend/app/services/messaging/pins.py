"""PIN protection for payout information on the phone channels.

The PIN only unlocks read-only payout status. It cannot move money, change a
payout destination or approve anything; those actions do not exist on the phone
channels. A PIN is created on first use (trust on first use) and an agent can
reset it. Three wrong entries lock the PIN for 30 minutes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from werkzeug.security import check_password_hash, generate_password_hash

from .ports import MessagingStore, PinRecord

MAX_ATTEMPTS = 3
LOCK_MINUTES = 30
_WEAK = {"0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999", "1234", "4321", "1212",
         "0123", "2580", "1122", "6969"}


@dataclass(frozen=True)
class PinCheck:
    outcome: str  # ok | invalid | locked | not_set
    attempts_left: int = 0
    minutes_locked: int = 0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)  # SQLite drops tzinfo
    return value


class PinService:
    def __init__(self, store: MessagingStore, clock: Callable[[], datetime] = _utcnow) -> None:
        self.store = store
        self.clock = clock

    @staticmethod
    def is_valid_format(pin: str) -> bool:
        return len(pin) == 4 and pin.isdigit()

    @staticmethod
    def is_weak(pin: str) -> bool:
        return pin in _WEAK

    def has_pin(self, beneficiary_id: str) -> bool:
        return self.store.get_pin(beneficiary_id) is not None

    def create(self, beneficiary_id: str, pin: str) -> bool:
        if not self.is_valid_format(pin) or self.is_weak(pin) or self.has_pin(beneficiary_id):
            return False
        self.store.save_pin(beneficiary_id, PinRecord(pin_hash=generate_password_hash(pin)))
        return True

    def reset(self, beneficiary_id: str) -> None:
        """Agent/admin action: the beneficiary creates a new PIN on next use."""
        self.store.delete_pin(beneficiary_id)

    def verify(self, beneficiary_id: str, pin: str) -> PinCheck:
        record = self.store.get_pin(beneficiary_id)
        if record is None:
            return PinCheck("not_set")
        now = self.clock()
        locked_until = _aware(record.locked_until)
        if locked_until and locked_until > now:
            return PinCheck("locked", minutes_locked=max(1, int((locked_until - now).total_seconds() // 60) + 1))
        if self.is_valid_format(pin) and check_password_hash(record.pin_hash, pin):
            if record.failed_attempts or record.locked_until:
                record.failed_attempts, record.locked_until = 0, None
                self.store.save_pin(beneficiary_id, record)
            return PinCheck("ok")
        record.failed_attempts = (0 if locked_until else record.failed_attempts) + 1
        record.locked_until = None
        if record.failed_attempts >= MAX_ATTEMPTS:
            record.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            record.failed_attempts = 0
            self.store.save_pin(beneficiary_id, record)
            return PinCheck("locked", minutes_locked=LOCK_MINUTES)
        self.store.save_pin(beneficiary_id, record)
        return PinCheck("invalid", attempts_left=MAX_ATTEMPTS - record.failed_attempts)
