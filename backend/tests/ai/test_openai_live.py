"""Real OpenAI requests for every AI feature. Opt-in; skipped unless both are set:

    FUNDBRIDGE_LIVE_OPENAI_TESTS=1  OPENAI_API_KEY=sk-...  [OPENAI_MODEL=...]

A skip here means no real OpenAI request was made. Only a pass means the live integration works.
"""

from __future__ import annotations

import os

import pytest

from app.integrations.ai.factory import build_ai_provider
from app.services.ai.ports import Actor
from app.services.ai.schemas import AssistantRequest, CampaignDraftRequest, CampaignSearchRequest, TranslateRequest
from app.services.ai.service import AIService

from .conftest import sample_catalog

pytestmark = pytest.mark.skipif(
    os.environ.get("FUNDBRIDGE_LIVE_OPENAI_TESTS") != "1" or not os.environ.get("OPENAI_API_KEY"),
    reason="live OpenAI tests are opt-in: set FUNDBRIDGE_LIVE_OPENAI_TESTS=1 and OPENAI_API_KEY",
)


@pytest.fixture(scope="module")
def service() -> AIService:
    provider = build_ai_provider({"AI_PROVIDER": "openai"})
    assert provider is not None
    return AIService(provider, campaign_catalog=sample_catalog())


def _live(meta: dict) -> None:
    assert meta["ai_generated"] is True and meta["degraded"] is False, f"fell back: {meta}"


def test_live_campaign_draft(service):
    out = service.campaign_draft(Actor("live-test", "creator"), CampaignDraftRequest(
        story_notes="My daughter is in her final year of secondary school in Kisumu. We cannot pay the last term's "
                    "fees. Call me on 0712345678.", category="education", language="en"))
    _live(out["meta"])
    assert out["data"]["title"] and "0712345678" not in out["data"]["story"]


def test_live_translation_to_kiswahili(service):
    out = service.translate("live-test", TranslateRequest(text="Thank you for supporting Amina's school fees.",
                                                          target_language="sw"))
    _live(out["meta"])
    assert out["data"]["translated_text"] and out["data"]["machine_translation"] is True


def test_live_beneficiary_assistant(service):
    out = service.beneficiary_assistant("live-test", AssistantRequest(message="When will my payout arrive?"))
    _live(out["meta"])
    assert out["data"]["reply"]


def test_live_campaign_search(service):
    out = service.campaign_search("live-test", CampaignSearchRequest(query="help a student with school fees in Kenya"))
    _live(out["meta"])
    assert out["data"]["interpreted_filters"]["keywords"]
