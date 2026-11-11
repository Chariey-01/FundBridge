"""GSM 7-bit text for USSD screens and SMS.

Feature phones and networks expect the GSM 03.38 alphabet. A single character outside it (an
ellipsis, a curly quote, an emoji in a campaign title) switches the whole message to UCS-2: a USSD
screen then holds about 91 characters instead of 182, an SMS segment 70 instead of 160, and some
handsets show garbage. Everything sent to a phone passes through ``to_gsm7``.

USSD screens are capped at 182 GSM characters (the GSM USSD maximum). Africa's Talking's own limit
was not confirmed in its public docs, so 182 is treated as a hard ceiling.
"""

from __future__ import annotations

import re
import unicodedata

USSD_MAX = 182
SMS_SEGMENT = 160
SMS_MAX_SEGMENTS = 2

_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_EXTENSION = set("^{}\\[~]|€")  # each costs two septets
_REPLACEMENTS = {
    "…": "...", "‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"', "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", "•": "-", "·": "-", "×": "x", "\t": " ",
}


def to_gsm7(text: str) -> str:
    """Map text into the GSM 7-bit alphabet: common punctuation is replaced, accents are dropped when the
    accented letter is not in GSM (é stays, ő becomes o), and anything else (emoji, other scripts) is removed."""
    out: list[str] = []
    for ch in unicodedata.normalize("NFC", text or ""):
        if ch in _BASIC or ch in _EXTENSION:
            out.append(ch)
        elif ch in _REPLACEMENTS:
            out.append(_REPLACEMENTS[ch])
        else:
            base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
            out.append("".join(c for c in base if c in _BASIC))
    return re.sub(r"[ ]{2,}", " ", "".join(out))


def gsm7_length(text: str) -> int:
    return sum(2 if ch in _EXTENSION else 1 for ch in text)


def is_gsm7(text: str) -> bool:
    return all(ch in _BASIC or ch in _EXTENSION for ch in text)


def shorten(text: str, limit: int) -> str:
    """Shorten to ``limit`` GSM characters on a word boundary where possible, marking the cut with '...'."""
    text = to_gsm7(text).strip()
    if gsm7_length(text) <= limit:
        return text
    cut = text[: max(1, limit - 3)]
    space = cut.rfind(" ")
    if space >= limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "..."


def fit(text: str, limit: int) -> str:
    """Final guard for a whole screen or message: keeps line breaks, never exceeds ``limit``."""
    text = to_gsm7(text)
    if gsm7_length(text) <= limit:
        return text
    return shorten(text, limit)
