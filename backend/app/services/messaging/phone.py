"""Phone number normalisation (E.164) and masking."""

from __future__ import annotations

import re

COUNTRY_DIAL_CODES = {"KE": "254", "UG": "256", "TZ": "255", "RW": "250"}


def normalize_msisdn(raw: str | None, default_country: str = "KE") -> str | None:
    """Return +<digits> in E.164 form, or None if the value cannot be a phone number."""
    if not raw:
        return None
    value = re.sub(r"[\s\-().]", "", str(raw))
    if value.startswith("00"):
        value = "+" + value[2:]
    if value.startswith("+"):
        digits = value[1:]
    elif value.startswith("0"):
        code = COUNTRY_DIAL_CODES.get(default_country.upper())
        if not code:
            return None
        digits = code + value[1:]
    else:
        digits = value
    if not digits.isdigit() or not 9 <= len(digits) <= 15:
        return None
    return "+" + digits


def phone_variants(msisdn: str, default_country: str = "KE") -> list[str]:
    """Forms a stored, un-normalised phone number might take (for lookups against legacy data)."""
    variants = {msisdn, msisdn[1:]}
    code = COUNTRY_DIAL_CODES.get(default_country.upper())
    if code and msisdn.startswith("+" + code):
        variants.add("0" + msisdn[len(code) + 1:])
    return sorted(variants)


def mask_msisdn(msisdn: str) -> str:
    if len(msisdn) < 7:
        return "***"
    return msisdn[:4] + "*" * (len(msisdn) - 7) + msisdn[-3:]
