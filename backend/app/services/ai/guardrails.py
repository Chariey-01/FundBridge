"""Input minimisation and output checks for AI features.

Everything a model returns is untrusted text. These helpers remove personal
data before it leaves the server, strip markup and links from model output, and
flag statements that could be mistaken for authoritative financial facts.
"""

from __future__ import annotations

import html
import re
import unicodedata
from decimal import Decimal, InvalidOperation

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Phone numbers: optional +, then 9-15 digits possibly separated by spaces, dots or dashes.
_PHONE_RE = re.compile(r"(?<!\w)(?<!\d[.,])\+?\d(?:[\s.-]?\d){8,14}(?!\w)(?![.,]\d)")
# Long digit runs (national ID, account and card numbers) not already caught above.
_LONG_NUMBER_RE = re.compile(r"(?<!\w)(?<!\d[.,])\d{7,19}(?!\w)(?![.,]\d)")
# Uppercase alphanumeric references: M-Pesa transaction codes (e.g. QFT4H7K2LP), passport and
# document numbers (e.g. A1234567). Filtered in _is_reference to spare words like COVID19 or KCSE2025.
_REF_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z0-9]{8,12}(?![A-Za-z0-9])")
_YEAR_SUFFIX_RE = re.compile(r"^[A-Z]+(?:19|20)\d\d$")
_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"]+")
_TAG_RE = re.compile(r"<[^>]{0,500}>")
_PLACEHOLDER_RE = re.compile(r"\[(?:PHONE|EMAIL|NUMBER|REF)_\d{1,3}\]")
_CONTROL_RE = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f​-‏‪-‮⁦-⁩]")

# Statements an AI must never make on its own authority: that money moved,
# that something was approved or verified, or that an outcome is guaranteed.
# One character inside a sentence: anything but . ! ? or a newline, except a decimal point
# between digits ("40.00 USD"), which must not end the sentence early and hide the claim.
_IN_SENTENCE = r"(?:[^.!?\n]|(?<=\d)\.(?=\d))"

_UNSAFE_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "financial_completion",
        re.compile(
            r"(?i)\b(payout|payment|transfer|money|funds?|donations?|withdrawal|m-?pesa)\b"
            rf"{_IN_SENTENCE}{{0,60}}\b(has|have|was|were|is|are|been)\b{_IN_SENTENCE}{{0,20}}"
            r"\b(sent|completed|approved|received|confirmed|processed|disbursed|credited|paid|released|deposited)\b"
        ),
    ),
    (
        "financial_completion",
        re.compile(
            rf"(?i)\byou(?:'ve| have)?\s+(?:received|been paid|been sent|got)\b{_IN_SENTENCE}{{0,40}}"
            r"(?:\d|\b(?:usd|kes|ksh|eur|gbp|money|funds|payment|payout|donation)\b)"
        ),
    ),
    (
        "approval_or_verification",
        re.compile(
            r"(?i)\b(verified|approved|vetted|endorsed|certified)\s+by\s+fundbridge\b"
            r"|\bfundbridge\s+(has\s+)?(verified|approved|vetted|guarantees?|certified)\b"
        ),
    ),
    ("guarantee", re.compile(r"(?i)\b(guarantee[ds]?|100\s*%\s*(safe|secure|legit)|risk[- ]free)\b")),
    # Kiswahili perfect-tense passives: "-metumwa" (has been sent), "-melipwa" (has been paid),
    # "-meidhinishwa" (approved), "-methibitishwa" (confirmed), "-mepokelewa" (received), "-mekamilika"
    # (completed), "-meingizwa"/"-mewekwa" (deposited). The subject prefix follows the noun class, so all
    # of them are matched: "pesa imetumwa", "pesa zimetumwa", "malipo yamelipwa", "mchango umethibitishwa".
    # Plus "you/he/she have received / been sent": "umepokea", "mmepokea", "amepokea", "umetumiwa".
    # Native-speaker review: docs/integration/kiswahili-review.md.
    (
        "financial_completion",
        re.compile(
            r"(?i)\b(?:i|zi|ya|u|li|ki|vi|wa|a|m)me"
            r"(?:tumwa|tumiwa|lipwa|idhinishwa|thibitishwa|pokelewa|kamilika|ingizwa|wekwa)\b"
            r"|\b(?:u|m|a)mepokea\b"
        ),
    ),
)

_AMOUNT_RE = re.compile(
    r"(?i)(?:\b(?:usd|kes|ksh|eur|gbp)\s?|[$€£])\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?"
    r"|(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s?(?:usd|kes|ksh|shillings|dollars|eur|gbp)\b"
)


def redact_pii(text: str) -> tuple[str, dict[str, str]]:
    """Replace e-mail addresses, phone numbers, long digit runs and ID/transaction codes with placeholders.

    Returns the redacted text and a placeholder -> original mapping. The mapping
    stays on the server; it is only used to restore values after translation.
    """
    mapping: dict[str, str] = {}
    counters = {"EMAIL": 0, "PHONE": 0, "NUMBER": 0, "REF": 0}

    def _sub(kind: str, pattern: re.Pattern[str], value: str, keep=None) -> str:
        def repl(match: re.Match[str]) -> str:
            if keep is not None and keep(match.group(0)):
                return match.group(0)
            counters[kind] += 1
            key = f"[{kind}_{counters[kind]}]"
            mapping[key] = match.group(0)
            return key

        return pattern.sub(repl, value)

    redacted = _sub("EMAIL", _EMAIL_RE, text)
    redacted = _sub("PHONE", _PHONE_RE, redacted)
    redacted = _sub("NUMBER", _LONG_NUMBER_RE, redacted)
    redacted = _sub("REF", _REF_CANDIDATE_RE, redacted, keep=lambda token: not _is_reference(token))
    return redacted, mapping


def _is_reference(token: str) -> bool:
    digits = sum(c.isdigit() for c in token)
    letters = len(token) - digits
    return letters >= 1 and digits >= 3 and not _YEAR_SUFFIX_RE.match(token)


def restore_placeholders(text: str, mapping: dict[str, str]) -> tuple[str, list[str]]:
    """Put redacted values back. Returns the text and any placeholders the model dropped."""
    missing = [key for key in mapping if key not in text]
    for key, original in mapping.items():
        text = text.replace(key, original)
    return text, missing


def strip_placeholders(text: str) -> str:
    return _PLACEHOLDER_RE.sub("", text)


def sanitize_text(text: str, *, max_length: int, allow_newlines: bool = True) -> str:
    """Normalise model output into plain text that is safe to store and render.

    HTML tags are removed and entities decoded (the frontend must still escape on
    render), control and bidi-override characters are removed, whitespace is
    collapsed, and the result is truncated on a word boundary.
    """
    value = unicodedata.normalize("NFC", text or "")
    value = _TAG_RE.sub("", value)
    value = html.unescape(value)
    value = _TAG_RE.sub("", value)  # entities may have decoded into tags
    value = _CONTROL_RE.sub("", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if allow_newlines:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
        value = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    else:
        value = re.sub(r"\s+", " ", value).strip()
    if len(value) > max_length:
        cut = value[: max_length - 1]
        space = cut.rfind(" ")
        if space > max_length * 0.6:
            cut = cut[:space]
        value = cut.rstrip(" ,;:-") + "…"
    return value


def remove_links(text: str) -> tuple[str, bool]:
    cleaned, count = _URL_RE.subn("", text)
    return cleaned, count > 0


def find_unsafe_claims(text: str) -> list[str]:
    """Return the categories of unsafe statements present in ``text`` (deduplicated)."""
    found: list[str] = []
    for category, pattern in _UNSAFE_CLAIM_PATTERNS:
        if pattern.search(text or "") and category not in found:
            found.append(category)
    return found


def extract_amounts(text: str) -> list[Decimal]:
    amounts: list[Decimal] = []
    for match in _AMOUNT_RE.finditer(text or ""):
        whole = match.group(1) or match.group(3)
        cents = match.group(2) or match.group(4)
        if not whole:
            continue
        raw = whole.replace(",", "") + (f".{cents}" if cents else "")
        try:
            amounts.append(Decimal(raw))
        except InvalidOperation:
            continue
    return amounts
