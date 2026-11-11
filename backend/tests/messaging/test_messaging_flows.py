from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.messaging.gateways import SimulatedSmsGateway
from app.services.ai.ports import InMemoryCampaignCatalog, Money, PublicCampaignSummary
from app.services.messaging.memory import InMemoryBeneficiaryDirectory, InMemoryMessagingStore
from app.services.messaging.phone import mask_msisdn, normalize_msisdn
from app.services.messaging.ports import BeneficiaryRecord, CampaignStatusView, PayoutStatusView
from app.services.messaging.service import MessagingService, MessagingSettings, parse_steps

PHONE = "+254712345678"
OTHER = "+254700000001"


def usd(amount: str) -> Money:
    return Money(amount, "USD")


@pytest.fixture
def world():
    directory = InMemoryBeneficiaryDirectory()
    directory.beneficiaries[PHONE] = BeneficiaryRecord("b1", "Amina", PHONE, "en", "verified")
    directory.campaigns["b1"] = [
        CampaignStatusView("c1", "school-fees", "School fees for Amina", "published", usd("400.00"), usd("120.00"))
    ]
    directory.payouts["b1"] = PayoutStatusView("p1", usd("100.00"), "pending_confirmation",
                                               datetime(2026, 11, 11, tzinfo=timezone.utc))
    store = InMemoryMessagingStore()
    catalog = InMemoryCampaignCatalog([
        PublicCampaignSummary("c1", "school-fees", "School fees for Amina", "Secondary school fees", "education",
                              "KE", usd("400.00"), usd("120.00")),
        PublicCampaignSummary("c2", "clinic-roof", "Clinic roof repair", "Village clinic", "medical", "KE",
                              usd("900.00"), usd("10.00")),
    ])
    gateway = SimulatedSmsGateway()
    service = MessagingService(directory=directory, store=store, catalog=catalog, gateway=gateway,
                               settings=MessagingSettings(public_base_url="https://fundbridge.test"))
    return service, directory, store, gateway


def ussd(service, text, phone=PHONE):
    return service.handle_ussd(phone_number=phone, text=text, session_id="s1")


# ----------------------------------------------------------------------- basics


def test_phone_normalisation_and_masking():
    assert normalize_msisdn("0712 345 678") == PHONE
    assert normalize_msisdn("254712345678") == PHONE
    assert normalize_msisdn("+256 772 000111") == "+256772000111"
    assert normalize_msisdn("12") is None and normalize_msisdn("abc") is None
    assert mask_msisdn(PHONE) == "+254******678"


def test_parse_steps_back_and_home():
    assert parse_steps("") == []
    assert parse_steps("1*2*0") == ["1"]
    assert parse_steps("2*1234*00*3") == ["3"]


def test_main_menu(world):
    service, *_ = world
    reply = ussd(service, "")
    assert reply.render().startswith("CON FundBridge\n1. My campaign")
    assert len(reply.text) <= 182


# --------------------------------------------------------------------- campaign


def test_campaign_status_uses_directory_figures(world):
    service, *_ = world
    reply = ussd(service, "1")
    assert reply.end
    assert "Status: Live" in reply.text and "Raised: USD 120.00 of USD 400.00" in reply.text


def test_unknown_number_is_not_linked(world):
    service, *_ = world
    assert "not linked" in ussd(service, "1", phone=OTHER).text
    assert "not linked" in ussd(service, "2", phone=OTHER).text


def test_multiple_campaigns_menu(world):
    service, directory, *_ = world
    directory.campaigns["b1"].append(
        CampaignStatusView("c3", "roof", "Roof for Amina's family", "submitted", usd("50.00"), usd("0.00")))
    menu = ussd(service, "1")
    assert not menu.end and "2. Roof" in menu.text
    assert "In review" in ussd(service, "1*2").text
    assert "Invalid" in ussd(service, "1*9").text


# ----------------------------------------------------------------------- payout


def test_payout_requires_pin_creation_then_shows_status(world):
    service, *_ = world
    first = ussd(service, "2")
    assert not first.end and "Create a 4-digit PIN" in first.text and "100.00" not in first.text
    assert "too easy" in ussd(service, "2*1234").text
    assert "Enter the same PIN" in ussd(service, "2*4826").text
    assert "did not match" in ussd(service, "2*4826*4827").text
    shown = ussd(service, "2*4826*4826")
    assert shown.end and "USD 100.00" in shown.text
    assert "Awaiting confirmation. Do not request again" in shown.text
    assert "Paid" not in shown.text


def test_pin_verification_and_lockout(world):
    service, *_ = world
    ussd(service, "2*4826*4826")
    assert "Enter your 4-digit" in ussd(service, "2").text
    assert "2 attempt(s) left" in ussd(service, "2*1111").text
    assert "1 attempt(s) left" in ussd(service, "2*2222").text
    locked = ussd(service, "2*3333")
    assert "Too many wrong PINs" in locked.text
    # Even the right PIN is refused while locked, and nothing about the payout leaks.
    still = ussd(service, "2*4826")
    assert "Too many wrong PINs" in still.text and "100.00" not in still.text


def test_lock_expires(world):
    service, *_ = world
    ussd(service, "2*4826*4826")
    for pin in ("1111", "2222", "3333"):
        ussd(service, f"2*{pin}")
    service.pins.clock = lambda: datetime.now(timezone.utc) + timedelta(minutes=31)
    assert "USD 100.00" in ussd(service, "2*4826").text


def test_succeeded_label_only_for_succeeded_state(world):
    service, directory, *_ = world
    ussd(service, "2*4826*4826")
    for status, expected in [("submitted", "awaiting confirmation"), ("failed", "Not completed"),
                             ("succeeded", "Paid to your mobile money account"), ("weird", "Status unavailable")]:
        directory.payouts["b1"] = PayoutStatusView("p1", usd("100.00"), status, datetime.now(timezone.utc))
        assert expected in ussd(service, "2*4826").text


# ------------------------------------------------------------ search/help/lang


def test_search_and_donate_info(world):
    service, *_ = world
    assert not ussd(service, "3").end
    found = ussd(service, "3*clinic")
    assert "Clinic roof repair" in found.text and "https://fundbridge.test/campaigns" in found.text
    assert "No live campaigns" in ussd(service, "3*zzzz").text
    assert "PayPal" in ussd(service, "4").text


def test_help_opens_support_requests(world):
    service, _, store, _ = world
    reply = ussd(service, "5*3")
    assert reply.end and "verify your identity" in reply.text
    assert store.support_requests[-1]["topic"] == "sim_change" and store.support_requests[-1]["priority"] == "high"
    assert "Ref HLP-" in ussd(service, "5*1", phone=OTHER).text


def test_language_switch_persists(world):
    service, *_ = world
    assert ussd(service, "6*2").text == "Lugha imewekwa: Kiswahili."
    assert ussd(service, "").text.startswith("FundBridge\n1. Kampeni yangu")
    assert "Hali: Iko hewani" in ussd(service, "1").text


def test_invalid_choice_and_bad_phone(world):
    service, *_ = world
    assert "Invalid choice" in ussd(service, "9").text
    assert ussd(service, "", phone="not-a-phone").end


def test_flow_errors_end_session_without_leaking(world):
    service, directory, *_ = world

    def boom(_):
        raise RuntimeError("db password=secret")

    directory.campaigns_for = boom
    reply = ussd(service, "1")
    assert reply.end and "secret" not in reply.text and "temporarily unavailable" in reply.text


# --------------------------------------------------------------------------- SMS


def sms(service, text, phone=PHONE):
    return service.handle_inbound_sms(phone_number=phone, text=text)


def test_sms_commands(world):
    service, _, store, gateway = world
    assert "STATUS" in sms(service, "help")[0]
    assert "School fees for Amina" in sms(service, "STATUS")[0]
    assert "Clinic roof repair" in sms(service, "find clinic")[0]
    assert "FIND school" in sms(service, "FIND")[0]
    assert "Ref HLP-" in sms(service, "AGENT")[0]
    # Payout details are never sent over SMS; the user is sent to the PIN-protected USSD menu.
    payout = sms(service, "PAYOUT 4826")[0]
    assert "PIN" in payout and "100.00" not in payout
    assert len(gateway.messages_for(PHONE)) == 6


def test_sms_language_and_opt_out(world):
    service, _, store, gateway = world
    assert sms(service, "LANG SW")[0] == "Lugha imewekwa: Kiswahili."
    assert "HALI" in sms(service, "MSAADA")[0]
    sms(service, "STOP")
    assert store.get_preference(PHONE).opted_out
    assert service.notify(msisdn=PHONE, template="notify_published", title="X", url="u") is False
    assert service.notify(msisdn=PHONE, template="notify_payout", amount="USD 1.00", status="failed",
                          essential=True) is True
    assert "Hayakukamilika" in gateway.messages_for(PHONE)[0]["message"]
    sms(service, "START")
    assert not store.get_preference(PHONE).opted_out


def test_sms_free_text_uses_assistant_and_falls_back(world):
    service, *_ = world
    assert "STATUS" in sms(service, "when will i get money")[0]  # no assistant configured: command list
    service.assistant = lambda msisdn, text, lang: "I cannot see your balance."
    assert sms(service, "when will i get money")[0].startswith("FundBridge (auto-reply): I cannot see")
    service.assistant = lambda msisdn, text, lang: None
    assert "STATUS" in sms(service, "when will i get money")[0]


def test_simulated_gateway_labels_messages(world):
    _, _, _, gateway = world
    result = gateway.send(PHONE, "hi")
    assert result.status == "simulated" and result.message_id.startswith("SIM-")


def test_abandoned_or_timed_out_session_leaves_no_partial_state(world):
    """USSD sessions are stateless on the server: each callback carries the whole input so far (Africa's Talking
    format), and the telco ends idle sessions. A session dropped mid-PIN-setup must not leave a half-created PIN,
    and a new session starts again from the main menu."""
    service, *_ = world
    assert "Enter the same PIN" in service.handle_ussd(phone_number=PHONE, text="2*4826", session_id="dropped").text
    # The handset times out here. A new session (new sessionId, empty text) starts fresh.
    fresh = service.handle_ussd(phone_number=PHONE, text="", session_id="new-session")
    assert not fresh.end and fresh.text.startswith("FundBridge")
    again = service.handle_ussd(phone_number=PHONE, text="2", session_id="new-session")
    assert "Create a 4-digit PIN" in again.text  # nothing was saved by the abandoned session
    # Continuing within a session works from the cumulative text, without server-side session storage.
    assert "USD 100.00" in service.handle_ussd(phone_number=PHONE, text="2*4826*4826", session_id="new-session").text
    assert "Enter your 4-digit" in service.handle_ussd(phone_number=PHONE, text="2", session_id="third").text
