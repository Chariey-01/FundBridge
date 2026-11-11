"""Every USSD screen and SMS fits a feature phone: GSM 7-bit only, USSD <= 182 characters, SMS <= 2 segments.

Regression for H-4 (2026-11-11): with realistic data (long campaign titles, five campaigns, a production
URL) 14 USSD screens exceeded 182 characters, and truncated titles ended in "…", which is not a GSM
character and silently switches a message to UCS-2 (about 91 characters per USSD screen, 70 per SMS).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.integrations.messaging.gateways import SMS_MAX_CHARS, SimulatedSmsGateway
from app.services.ai.ports import InMemoryCampaignCatalog, Money, PublicCampaignSummary
from app.services.messaging import i18n
from app.services.messaging.memory import InMemoryBeneficiaryDirectory, InMemoryMessagingStore
from app.services.messaging.ports import BeneficiaryRecord, CampaignStatusView, PayoutStatusView
from app.services.messaging.service import MessagingService, MessagingSettings
from app.services.messaging.text import USSD_MAX, gsm7_length, is_gsm7, shorten, to_gsm7

LONG = "Emergency surgery 🙏 and “recovery” costs for Grandmother Wanjikũ – Nyeri County"
PAYOUT_STATES = ("requested", "under_review", "rejected", "approved_for_submission", "submitted",
                 "pending_confirmation", "failed", "succeeded")
PATHS = ["", "1", "1*1", "1*9", "2", "2*1234", "2*4826", "2*4826*1111", "2*4826*4826", "2*9999", "3", "3*school",
         "3*zzzz", "4", "5", "5*1", "5*2", "5*3", "6", "6*1", "6*2", "9", "1*2*3*4*5*6*7"]
SMS = ["HELP", "HALI", "STATUS", "FIND school", "TAFUTA shule", "FIND zzzz", "AGENT", "PAYOUT", "LANG sw", "STOP",
       "START", "random words here"]


def _money(a):
    return Money(a, "USD")


@pytest.fixture()
def phone_world():
    directory = InMemoryBeneficiaryDirectory()
    phones = {"many": "+254712345678", "one": "+254700000009", "unverified": "+254700000010"}
    directory.beneficiaries[phones["many"]] = BeneficiaryRecord("b1", "Amina", phones["many"], "en", "verified")
    directory.beneficiaries[phones["one"]] = BeneficiaryRecord("b2", "Baraka", phones["one"], "sw", "verified")
    directory.beneficiaries[phones["unverified"]] = BeneficiaryRecord("b3", "C", phones["unverified"], "en",
                                                                      "reverification_required")
    directory.campaigns["b1"] = [CampaignStatusView(f"c{i}", f"s{i}", f"{LONG} {i}", "published",
                                                    _money("12345678.90"), _money("1234567.89")) for i in range(5)]
    directory.campaigns["b2"] = [CampaignStatusView("c9", "s9", LONG, "submitted", _money("12345678.90"),
                                                    _money("1234567.89"))]
    catalog = InMemoryCampaignCatalog([PublicCampaignSummary(f"x{i}", f"x{i}", f"{LONG} school {i}", "s",
                                                             "education", "KE", _money("12345678.90"),
                                                             _money("1234567.89")) for i in range(3)])
    gateway = SimulatedSmsGateway()
    service = MessagingService(directory=directory, store=InMemoryMessagingStore(), catalog=catalog, gateway=gateway,
                               settings=MessagingSettings(public_base_url="https://fundbridge-production.up.railway.app"))
    return service, directory, gateway, list(phones.values()) + ["+254799999999"]


def _screens(service, directory, phones, lang):
    for phone in phones:
        pref = service.store.get_preference(phone)
        pref.language = lang
        service.store.save_preference(phone, pref)
    for phone in phones:
        for path in PATHS:
            yield f"{lang} {phone[-2:]} {path!r}", service.handle_ussd(phone_number=phone, text=path, session_id=path)
    for state in PAYOUT_STATES:
        directory.payouts["b1"] = PayoutStatusView("p", _money("1234567.89"), state, datetime(2026, 11, 11, tzinfo=timezone.utc))
        yield f"{lang} payout {state}", service.handle_ussd(phone_number=phones[0], text="2*4826", session_id=state)


@pytest.mark.parametrize("lang", ["en", "sw"])
def test_every_ussd_screen_fits_a_feature_phone(phone_world, lang):
    service, directory, _, phones = phone_world
    checked = 0
    for label, reply in _screens(service, directory, phones, lang):
        rendered = reply.render()
        body = rendered[4:]
        assert rendered[:4] in ("CON ", "END "), label
        assert is_gsm7(body), f"{label}: non-GSM characters in {body!r}"
        assert gsm7_length(body) <= USSD_MAX, f"{label}: {gsm7_length(body)} characters: {body!r}"
        checked += 1
    assert checked >= 100


@pytest.mark.parametrize("lang", ["en", "sw"])
def test_every_sms_reply_and_notification_fits_two_segments(phone_world, lang):
    service, _, gateway, phones = phone_world
    for phone in phones:
        pref = service.store.get_preference(phone)
        pref.language = lang
        service.store.save_preference(phone, pref)
        for command in SMS:
            service.handle_inbound_sms(phone_number=phone, text=command)
    service.notify(msisdn=phones[0], template="notify_donation", title=LONG, amount="USD 1234567.89",
                   raised="USD 1234567.89")
    service.notify(msisdn=phones[0], template="notify_payout", amount="USD 1234567.89", status="pending_confirmation",
                   essential=True)
    sent = [m["message"] for m in gateway.messages_for()]
    assert len(sent) > 30
    for message in sent:
        assert is_gsm7(message), repr(message)
        assert gsm7_length(message) <= SMS_MAX_CHARS, f"{gsm7_length(message)}: {message!r}"


def test_english_and_kiswahili_have_the_same_messages():
    tables = [v for v in vars(i18n).values()
              if isinstance(v, dict) and {"en", "sw"} <= set(v) and isinstance(v["en"], dict)]
    assert tables
    for table in tables:
        en, sw = table["en"], table["sw"]
        assert set(en) == set(sw), set(en) ^ set(sw)
        for key in en:
            if isinstance(en[key], str):
                assert is_gsm7(en[key]) and is_gsm7(sw[key]), key


def test_gsm7_conversion():
    assert to_gsm7("Wanjikũ’s “roof” – done… 🙏") == "Wanjiku's \"roof\" - done... "
    assert to_gsm7("Café Ñandú") == "Café Ñandu"  # é and Ñ are GSM characters; ú is not
    assert is_gsm7(to_gsm7("Ünïcödé ⚽ ąčęė"))
    assert gsm7_length("€[") == 4
    assert shorten("Emergency surgery and recovery costs", 20) == "Emergency surgery..."
