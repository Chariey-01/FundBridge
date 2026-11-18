"""Plain-language explanations of one donation or payout, built from the backend's own record.

Flow: the core backend's record -> ``StatusFacts`` (read-only copy) -> a deterministic *verified text* in English or
Kiswahili -> optionally an AI rewording (en/sw) or faithful translation (other languages) -> guardrails.

The verified text is always returned, so the UI can show what FundBridge's records mean even when AI is off or its
output is rejected. The status, amount and ``confirmed`` flag in the response come from the record, never from AI.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.services.messaging.i18n import PAYOUT_STATUS

from .guardrails import (
    _IN_SENTENCE,
    _UNSAFE_CLAIM_PATTERNS,
    extract_amounts,
    find_unsafe_claims,
    redact_pii,
    remove_links,
    sanitize_text,
)
from .ports import StatusFacts

# Only these states mean the money actually moved, as recorded by the backend.
CONFIRMED = {("donation", "completed"), ("payout", "succeeded")}
FINAL = {
    ("donation", s) for s in ("completed", "failed", "cancelled", "refunded", "partially_refunded")
} | {("payout", s) for s in ("rejected", "succeeded", "failed")}
GUARDED_LANGUAGES = ("en", "sw")  # languages the claim guardrails understand; others are translated, not rewritten

DONATION_LABELS = {
    "en": {"created": "Started, not paid", "pending": "Waiting for PayPal confirmation", "completed": "Confirmed",
           "failed": "Not completed", "cancelled": "Cancelled", "refunded": "Refunded",
           "partially_refunded": "Partly refunded"},
    "sw": {"created": "Umeanzishwa, haujalipwa", "pending": "Unasubiri uthibitisho wa PayPal",
           "completed": "Umethibitishwa", "failed": "Haukukamilika", "cancelled": "Umeghairiwa",
           "refunded": "Umerejeshwa", "partially_refunded": "Umerejeshwa kwa sehemu"},
}

# The authoritative meaning of each state. {amount} and {title} are filled from the record.
DONATION_TEXT = {
    "en": {
        "pending": "Your donation of {amount} to \"{title}\" is not confirmed yet. PayPal has not confirmed the payment "
                   "to FundBridge, so it is not counted in the campaign total. If you approved it in PayPal, check "
                   "again in a moment. Do not pay again unless this donation shows as not completed.",
        "completed": "Your donation of {amount} to \"{title}\" is confirmed. PayPal confirmed the payment and FundBridge "
                     "recorded it, so it counts in the campaign's confirmed total{raised}. This does not mean the "
                     "beneficiary has been paid yet: payouts are reviewed separately.",
        "failed": "Your donation of {amount} to \"{title}\" was not completed. PayPal did not confirm the payment, so "
                  "nothing was counted for the campaign. You can try again.",
        "cancelled": "Your donation of {amount} to \"{title}\" was cancelled before the payment was confirmed. Nothing "
                     "was counted for the campaign.",
        "refunded": "Your donation of {amount} to \"{title}\" was refunded. It no longer counts in the campaign total.",
        "partially_refunded": "Part of your donation of {amount} to \"{title}\" was refunded. Only the confirmed "
                              "remainder counts in the campaign total.",
    },
    "sw": {
        "pending": "Mchango wako wa {amount} kwa \"{title}\" bado haujathibitishwa. PayPal bado haijathibitisha malipo "
                   "kwa FundBridge, kwa hivyo haujahesabiwa kwenye jumla ya kampeni. Ikiwa uliidhinisha kwenye PayPal, "
                   "angalia tena baada ya muda mfupi. Usilipe tena isipokuwa mchango huu uonyeshe haukukamilika.",
        "completed": "Mchango wako wa {amount} kwa \"{title}\" umethibitishwa. PayPal ilithibitisha malipo na FundBridge "
                     "imeyarekodi, kwa hivyo unahesabiwa kwenye jumla iliyothibitishwa ya kampeni{raised}. Hii "
                     "haimaanishi kwamba mnufaika ameshalipwa: malipo kwa mnufaika hukaguliwa kando.",
        "failed": "Mchango wako wa {amount} kwa \"{title}\" haukukamilika. PayPal haikuthibitisha malipo, kwa hivyo "
                  "hakuna kilichohesabiwa kwa kampeni. Unaweza kujaribu tena.",
        "cancelled": "Mchango wako wa {amount} kwa \"{title}\" ulighairiwa kabla ya malipo kuthibitishwa. Hakuna "
                     "kilichohesabiwa kwa kampeni.",
        "refunded": "Mchango wako wa {amount} kwa \"{title}\" ulirejeshwa. Hauhesabiwi tena kwenye jumla ya kampeni.",
        "partially_refunded": "Sehemu ya mchango wako wa {amount} kwa \"{title}\" ilirejeshwa. Kiasi kilichobaki "
                              "kilichothibitishwa ndicho kinachohesabiwa kwenye jumla ya kampeni.",
    },
}
DONATION_TEXT["en"]["created"] = DONATION_TEXT["en"]["pending"]
DONATION_TEXT["sw"]["created"] = DONATION_TEXT["sw"]["pending"]

PAYOUT_TEXT = {
    "en": {
        "requested": "Your payout of {amount} from \"{title}\" is waiting for FundBridge review. No money has been sent yet.",
        "under_review": "Your payout of {amount} from \"{title}\" is being reviewed by FundBridge. No money has been sent yet.",
        "rejected": "Your payout of {amount} from \"{title}\" was not approved, so no money will be sent for this request. "
                    "Contact your community agent to find out why.",
        "approved_for_submission": "Your payout of {amount} from \"{title}\" is approved and being prepared. It has not "
                                   "been sent to the mobile-money provider yet, so the money has not arrived.",
        "submitted": "Your payout of {amount} from \"{title}\" was handed to the mobile-money provider. FundBridge is "
                     "waiting for the provider to confirm it. Do not request it again.",
        "pending_confirmation": "Your payout of {amount} from \"{title}\" is waiting for the mobile-money provider's "
                                "confirmation. The result is not known yet. Do not request it again; this status will "
                                "be updated.",
        "succeeded": "Your payout of {amount} from \"{title}\" is paid. The mobile-money provider confirmed the payment "
                     "to your verified number.",
        "failed": "Your payout of {amount} from \"{title}\" was not completed by the mobile-money provider. Your "
                  "community agent will help you.",
    },
    "sw": {
        "requested": "Malipo yako ya {amount} kutoka \"{title}\" yanasubiri ukaguzi wa FundBridge. Hakuna pesa "
                     "iliyotumwa bado.",
        "under_review": "Malipo yako ya {amount} kutoka \"{title}\" yanakaguliwa na FundBridge. Hakuna pesa iliyotumwa bado.",
        "rejected": "Malipo yako ya {amount} kutoka \"{title}\" hayakuidhinishwa, kwa hivyo hakuna pesa itakayotumwa kwa "
                    "ombi hili. Wasiliana na wakala wako kujua sababu.",
        "approved_for_submission": "Malipo yako ya {amount} kutoka \"{title}\" yameidhinishwa na yanaandaliwa. Bado "
                                   "hayajatumwa kwa mtoa huduma wa pesa kwa simu, kwa hivyo pesa haijafika.",
        "submitted": "Malipo yako ya {amount} kutoka \"{title}\" yamekabidhiwa kwa mtoa huduma wa pesa kwa simu. "
                     "FundBridge inasubiri uthibitisho wake. Usiombe tena.",
        "pending_confirmation": "Malipo yako ya {amount} kutoka \"{title}\" yanasubiri uthibitisho wa mtoa huduma wa "
                                "pesa kwa simu. Matokeo bado hayajajulikana. Usiombe tena; hali hii itasasishwa.",
        "succeeded": "Malipo yako ya {amount} kutoka \"{title}\" yamelipwa. Mtoa huduma wa pesa kwa simu amethibitisha "
                     "malipo kwenye nambari yako iliyothibitishwa.",
        "failed": "Malipo yako ya {amount} kutoka \"{title}\" hayakukamilishwa na mtoa huduma wa pesa kwa simu. Wakala "
                  "wako atakusaidia.",
    },
}
UNKNOWN_TEXT = {
    "en": "FundBridge cannot explain this status yet. Check again later or contact your community agent.",
    "sw": "FundBridge haiwezi kueleza hali hii bado. Angalia tena baadaye au wasiliana na wakala wako.",
}
NOTICE = {
    "ai": "Explanation written with AI from FundBridge's records. The status, amount and \"confirmed\" flag come "
          "from the records; if the explanation seems to disagree, the verified text is correct.",
    "fallback": "AI is unavailable, so this is FundBridge's standard explanation of the record.",
    "fallback_language": "AI is unavailable, so the standard explanation is shown in English.",
}

# A confirmed donation is not a payout: generated text must not say the beneficiary got the money.
_PAYOUT_CLAIM_RE = re.compile(
    rf"(?i)\b(payout|withdrawal|mobile[- ]money|m-?pesa)\b{_IN_SENTENCE}{{0,60}}\b(has|have|was|were|is|are|been)\b"
    rf"{_IN_SENTENCE}{{0,20}}\b(sent|completed|received|paid|released|disbursed|deposited|credited)\b"
    r"|\bbeneficiar(y|ies)\s+(has|have|already)\s+(received|been\s+paid|got)\b"
    r"|\bmnufaika\s+a(me|sha)(pokea|lipwa)\b"
)
_NEGATION_RE = re.compile(r"(?i)\b(not|never|no|haimaanishi|si|bado)\b|n't\b")
# "approved" is true for approved_for_submission; it must not count as a claim that money moved.
_APPROVED_RE = re.compile(r"(?i)\b(approved|yameidhinishwa|imeidhinishwa|umeidhinishwa)\b")


_NEGATED_BEFORE_RE = re.compile(r"(?i)(?:\b(?:not|no|never|before|until|unless|haimaanishi)|n't)\s+(?:\w+\s+){0,2}$")
_NEGATED_INSIDE_RE = re.compile(r"(?i)\b(?:not|never)\b|n't\b")


def _asserts_completion(text: str) -> bool:
    """Like find_unsafe_claims' financial_completion, but "No money has been sent yet" is not a claim.

    A match counts unless a negation is inside it or at most two words before it, so
    "Don't worry, your payout has been sent" is still caught.
    """
    for kind, pattern in _UNSAFE_CLAIM_PATTERNS:
        if kind != "financial_completion":
            continue
        for match in pattern.finditer(text):
            if _NEGATED_INSIDE_RE.search(match.group(0)) or _NEGATED_BEFORE_RE.search(text[:match.start()]):
                continue
            return True
    return False


def _asserts_beneficiary_paid(text: str) -> bool:
    """True if some payout/beneficiary-paid phrase is not negated in the 40 characters before it."""
    for match in _PAYOUT_CLAIM_RE.finditer(text):
        if not _NEGATION_RE.search(text[max(0, match.start() - 40):match.start()]):
            return True
    return False


# A confirmed record must not be described as failed or unconfirmed.
_NEGATIVE_RE = re.compile(
    r"(?i)\b(failed|not\s+(been\s+)?(completed|confirmed|approved)|rejected|cancelled|"
    r"haukukamilika|hayakukamilika|haujathibitishwa|hayajathibitishwa|hayakuidhinishwa)\b"
)


def _money(facts_amount) -> str:
    return f"{facts_amount.amount} {facts_amount.currency}"


def status_label(facts: StatusFacts, lang: str) -> str:
    lang = lang if lang in GUARDED_LANGUAGES else "en"
    labels = DONATION_LABELS[lang] if facts.kind == "donation" else PAYOUT_STATUS[lang]
    return labels.get(facts.status, "Status unavailable" if lang == "en" else "Hali haipatikani")


def verified_text(facts: StatusFacts, lang: str) -> tuple[str, str]:
    """(text, language). Deterministic, from the record only. English for languages without fixed text."""
    lang = lang if lang in GUARDED_LANGUAGES else "en"
    table = DONATION_TEXT if facts.kind == "donation" else PAYOUT_TEXT
    template = table[lang].get(facts.status)
    if template is None:
        return UNKNOWN_TEXT[lang], lang
    raised = ""
    if facts.campaign_raised is not None:
        raised = (f" ({_money(facts.campaign_raised)} confirmed so far)" if lang == "en"
                  else f" ({_money(facts.campaign_raised)} zimethibitishwa hadi sasa)")
    title = sanitize_text(facts.campaign_title, max_length=80, allow_newlines=False)
    return template.format(amount=_money(facts.amount), title=title, raised=raised), lang


def facts_prompt(facts: StatusFacts, language_name: str, lang: str, verified: str) -> str:
    """User content for the model. No personal data: no names of people, phone numbers or payment references."""
    lines = [
        f"Requested language: {language_name} ({lang})",
        f"Task: {'reword in plain words' if lang in GUARDED_LANGUAGES else 'translate faithfully'}",
        "FACTS (from FundBridge records):",
        f"- record: {facts.kind}",
        f"- status: {facts.status}",
        f"- amount: {_money(facts.amount)}",
        f"- campaign: {sanitize_text(facts.campaign_title, max_length=80, allow_newlines=False)}",
    ]
    if facts.campaign_raised is not None:
        lines.append(f"- campaign confirmed total: {_money(facts.campaign_raised)}")
    lines.append(f"- confirmed outcome: {'yes' if (facts.kind, facts.status) in CONFIRMED else 'no'}")
    lines.append("MEANING (authoritative; restate, do not contradict):")
    lines.append(verified)
    return "\n".join(lines)


def check_generated(text: str, facts: StatusFacts, lang: str) -> tuple[str | None, str | None]:
    """Return (clean text, None) or (None, reason) when the generated text must be replaced."""
    text, had_links = remove_links(text)
    if had_links:
        return None, "links"
    text = sanitize_text(text, max_length=600)
    if not text:
        return None, "empty"
    if redact_pii(text)[1]:
        return None, "personal_data"
    allowed = {Decimal(facts.amount.amount)}
    if facts.campaign_raised is not None:
        allowed.add(Decimal(facts.campaign_raised.amount))
    try:
        if any(a not in allowed for a in extract_amounts(text)):
            return None, "amount_mismatch"
    except InvalidOperation:  # pragma: no cover - extract_amounts only yields valid decimals
        return None, "amount_mismatch"
    confirmed = (facts.kind, facts.status) in CONFIRMED
    probe = _APPROVED_RE.sub("", text) if (facts.kind, facts.status) == ("payout", "approved_for_submission") else text
    claims = set(find_unsafe_claims(probe))
    if claims & {"approval_or_verification", "guarantee"}:
        return None, "unsafe_claim"
    if not confirmed and _asserts_completion(probe):
        return None, "claims_unconfirmed_outcome"
    if facts.kind == "donation" and _asserts_beneficiary_paid(text):
        return None, "claims_beneficiary_paid"
    if confirmed and _NEGATIVE_RE.search(text):
        return None, "contradicts_confirmed_record"
    return text, None
