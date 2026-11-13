"""Fallbacks say plainly that AI is unavailable; the daily cap protects the provider budget; status explanations
work without AI (verified text) and say which language they are in."""

from __future__ import annotations

from app.integrations.ai.base import AIProviderTimeout
from app.services.ai.ports import InMemoryStatusReader, Money, StatusFacts

from .conftest import AUTH, FakeProvider, make_app

DRAFT = {"story_notes": "Juma is a farmer in Kitui. Drought killed his crops and he needs seeds to replant.",
         "goal": {"amount": "300.00", "currency": "USD"}}
GOOD_DRAFT = {"title": "Help Juma replant", "summary": "Seeds for Juma.", "story": "Juma needs seeds. The goal is 300.00 USD.",
              "suggested_category": "agriculture", "missing_information": []}


def test_template_draft_does_not_call_itself_ai():
    for provider in (None, FakeProvider({"campaign_draft": AIProviderTimeout("slow")})):
        res = make_app(provider).test_client().post("/api/v1/ai/campaign-draft", json=DRAFT, headers=AUTH).get_json()
        assert res["meta"]["ai_generated"] is False
        assert res["data"]["disclaimer"].startswith("AI is unavailable") and "not an AI draft" in res["data"]["disclaimer"]
    live = make_app(FakeProvider({"campaign_draft": GOOD_DRAFT})).test_client()
    res = live.post("/api/v1/ai/campaign-draft", json=DRAFT, headers=AUTH).get_json()
    assert res["meta"]["ai_generated"] is True and res["data"]["disclaimer"].startswith("AI-assisted draft")


def test_assistant_and_search_fallbacks_say_ai_is_unavailable():
    client = make_app(None).test_client()
    reply = client.post("/api/v1/ai/beneficiary-assistant", json={"message": "Where is my payout?"}, headers=AUTH)
    assert reply.get_json()["data"]["notice"].startswith("AI is unavailable")
    search = client.post("/api/v1/ai/campaign-search", json={"query": "school fees in Kenya"}).get_json()["data"]
    assert search["notice"] == "AI search is unavailable, so results use simple keyword matching."
    live = make_app(FakeProvider({"campaign_search": {"keywords": ["school"], "category": None,
                                                      "country_code": None}})).test_client()
    assert live.post("/api/v1/ai/campaign-search", json={"query": "school"}).get_json()["data"]["notice"] is None


def test_daily_request_limit_falls_back_and_is_reported():
    provider = FakeProvider({"campaign_search": {"keywords": ["school"], "category": None, "country_code": None}})
    client = make_app(provider, config={"AI_DAILY_REQUEST_LIMIT": 2}).test_client()
    metas = [client.post("/api/v1/ai/campaign-search", json={"query": "school"}).get_json()["meta"] for _ in range(3)]
    assert [m["ai_generated"] for m in metas] == [True, True, False]
    assert metas[2]["fallback_reason"] == "AI_DAILY_LIMIT_REACHED" and metas[2]["degraded"] is True
    assert len(provider.calls) == 2  # the third request never reached the provider
    status = client.get("/api/v1/ai/status").get_json()["data"]
    assert status["daily_request_limit"] == 2 and status["last_error"]["code"] == "AI_DAILY_LIMIT_REACHED"


def test_daily_limit_zero_means_unlimited():
    provider = FakeProvider({"campaign_search": {"keywords": ["school"], "category": None, "country_code": None}})
    client = make_app(provider, config={"AI_DAILY_REQUEST_LIMIT": 0}).test_client()
    for _ in range(3):
        assert client.post("/api/v1/ai/campaign-search", json={"query": "school"},
                           headers=AUTH).get_json()["meta"]["ai_generated"] is True


def _reader():
    fact = StatusFacts("payout", "p1", "pending_confirmation", Money("40.00", "USD"), "School fees for Amina", None,
                       "simulator", "2026-11-11T10:00:00+00:00")
    return InMemoryStatusReader({"p1": fact}, {"p1": {"user-1"}})


def test_status_explanation_without_ai_returns_the_verified_text_in_en_sw_or_english():
    client = make_app(None, status_reader=_reader()).test_client()
    for lang, expected_lang, notice in (("en", "en", "AI is unavailable, so this is"),
                                        ("sw", "sw", "AI is unavailable, so this is"),
                                        ("fr", "en", "AI is unavailable, so the standard explanation is shown in English")):
        body = client.post("/api/v1/ai/status-explanation", json={"kind": "payout", "id": "p1", "language": lang},
                           headers=AUTH).get_json()
        data = body["data"]
        assert data["status"] == "pending_confirmation" and data["confirmed"] is False and data["final"] is False
        assert data["language"] == expected_lang and data["explanation"] == data["verified_text"]
        assert data["notice"].startswith(notice) and body["meta"]["ai_generated"] is False
    assert "Usiombe tena" in client.post("/api/v1/ai/status-explanation", json={"kind": "payout", "id": "p1",
                                         "language": "sw"}, headers=AUTH).get_json()["data"]["explanation"]


def test_status_explanation_translates_for_other_languages_with_amount_check():
    provider = FakeProvider({"status_explanation": {"explanation": "Votre paiement de 40.00 USD attend la confirmation."}})
    client = make_app(provider, status_reader=_reader()).test_client()
    body = client.post("/api/v1/ai/status-explanation", json={"kind": "payout", "id": "p1", "language": "fr"},
                       headers=AUTH).get_json()
    assert body["data"]["language"] == "fr" and body["meta"]["ai_generated"] is True
    assert body["data"]["verified_text_language"] == "en"  # the reference stays available to show
    assert "translate faithfully" in provider.calls[-1].user_content
    provider.responses["status_explanation"] = {"explanation": "Votre paiement de 4000.00 USD est en route."}
    body = client.post("/api/v1/ai/status-explanation", json={"kind": "payout", "id": "p1", "language": "fr"},
                       headers=AUTH).get_json()
    assert body["meta"]["guardrail_reason"] == "amount_mismatch" and body["data"]["language"] == "en"


def test_status_explanation_hides_records_the_caller_cannot_see():
    client = make_app(None, status_reader=_reader()).test_client()
    stranger = {"X-Test-Actor": "user-2:beneficiary"}
    assert client.post("/api/v1/ai/status-explanation", json={"kind": "payout", "id": "p1"},
                       headers=stranger).status_code == 403
    assert client.post("/api/v1/ai/status-explanation", json={"kind": "donation", "id": "p1"},
                       headers=AUTH).status_code == 404
    assert client.post("/api/v1/ai/status-explanation", json={"kind": "payout", "id": "p1"}).status_code == 401
    assert client.post("/api/v1/ai/status-explanation", json={"kind": "payout", "id": "../etc"},
                       headers=AUTH).status_code == 400
