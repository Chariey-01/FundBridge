from decimal import Decimal

from app.services.ai.guardrails import (
    extract_amounts,
    find_unsafe_claims,
    redact_pii,
    remove_links,
    restore_placeholders,
    sanitize_text,
)
from app.services.ai.rate_limit import SlidingWindowRateLimiter


def test_redact_pii_replaces_contacts_and_ids_and_restores():
    text = "Call me on +254 712 345 678 or 0712345678, email amina@example.org, ID 12345678."
    redacted, mapping = redact_pii(text)
    assert "712" not in redacted and "example.org" not in redacted and "12345678" not in redacted
    assert "[PHONE_1]" in redacted and "[EMAIL_1]" in redacted
    restored, missing = restore_placeholders(redacted, mapping)
    assert restored == text and missing == []


def test_redact_keeps_ordinary_amounts():
    redacted, mapping = redact_pii("We need USD 1,500.00 for 3 months of rent and 250 bags.")
    assert mapping == {}
    assert "1,500.00" in redacted


def test_sanitize_strips_markup_bidi_and_truncates():
    value = sanitize_text("<script>alert(1)</script><b>Hello</b>&lt;img src=x onerror=1&gt;‮evil", max_length=200)
    assert "<" not in value and "script" not in value.lower().replace("alert", "")
    assert "‮" not in value
    long = sanitize_text("word " * 100, max_length=50)
    assert len(long) <= 50 and long.endswith("…")


def test_remove_links():
    cleaned, had = remove_links("Donate at https://evil.example/pay or www.evil.example now")
    assert had and "evil" not in cleaned


def test_unsafe_claims_detected_in_english_and_kiswahili():
    assert "financial_completion" in find_unsafe_claims("Your payout has been sent to M-Pesa.")
    assert "financial_completion" in find_unsafe_claims("You have received USD 50 today")
    assert "financial_completion" in find_unsafe_claims("Malipo yako imetumwa")
    assert "approval_or_verification" in find_unsafe_claims("This campaign is verified by FundBridge")
    assert "guarantee" in find_unsafe_claims("Your gift is 100% safe and guaranteed")
    assert find_unsafe_claims("Open Payout status to see confirmed details.") == []


def test_kiswahili_completion_claims_in_every_noun_class():
    """Regression: only i-class forms ("imetumwa") were caught, so "malipo yameidhinishwa" passed."""
    for claim in ("Malipo yako yameidhinishwa.", "Pesa zimetumwa kwenye M-Pesa yako.", "Malipo yamelipwa.",
                  "Mchango umethibitishwa.", "Malipo yamekamilika.", "Pesa imeingizwa kwenye akaunti yako.",
                  "Mmepokea michango.", "Amina amepokea pesa.", "Umetumiwa KES 500.", "Wamelipwa leo."):
        assert "financial_completion" in find_unsafe_claims(claim), claim
    for safe in ("Fungua Hali ya malipo uone taarifa zilizothibitishwa.", "Malipo yanasubiri ukaguzi.",
                 "Wasiliana na wakala wako.", "Mmea huu unahitaji maji.", "Kampeni inakaguliwa."):
        assert find_unsafe_claims(safe) == [], safe


def test_kiswahili_fallback_replies_do_not_trip_the_guardrail():
    from app.services.ai.fallback import _ASSISTANT_REPLIES

    for reply in _ASSISTANT_REPLIES["sw"].values():
        assert find_unsafe_claims(reply) == [], reply


def test_extract_amounts():
    assert extract_amounts("We need $1,500.50 and KES 2000 plus 30 dollars") == [
        Decimal("1500.50"), Decimal("2000"), Decimal("30")
    ]


def test_rate_limiter_window():
    now = [0.0]
    limiter = SlidingWindowRateLimiter(2, window_seconds=60, clock=lambda: now[0])
    assert limiter.hit("a").allowed and limiter.hit("a").allowed
    blocked = limiter.hit("a")
    assert not blocked.allowed and blocked.retry_after_seconds == 60
    assert limiter.hit("b").allowed
    now[0] = 61
    assert limiter.hit("a").allowed


def test_redact_transaction_codes_and_document_numbers():
    text = "M-Pesa code QFT4H7K2LP, passport A1234567, ref [x] COVID19 KCSE2025 SCHOOL2 FUNDBRIDGE"
    redacted, mapping = redact_pii(text)
    assert "QFT4H7K2LP" not in redacted and "A1234567" not in redacted
    assert sorted(mapping.values()) == ["A1234567", "QFT4H7K2LP"]
    for kept in ("COVID19", "KCSE2025", "SCHOOL2", "FUNDBRIDGE"):
        assert kept in redacted
    restored, missing = restore_placeholders(redacted, mapping)
    assert restored == text and missing == []

