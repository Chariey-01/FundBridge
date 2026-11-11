"""Request validation, provider output validation and shared vocabularies for AI features."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Languages offered for AI assistance and translation. Deterministic phone menus
# (USSD/SMS) are only maintained in English and Kiswahili.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "sw": "Kiswahili",
    "fr": "French",
    "ar": "Arabic",
    "es": "Spanish",
    "pt": "Portuguese",
    "am": "Amharic",
    "so": "Somali",
    "ha": "Hausa",
    "yo": "Yoruba",
    "lg": "Luganda",
    "rw": "Kinyarwanda",
    "zu": "isiZulu",
}
LanguageCode = Literal[tuple(SUPPORTED_LANGUAGES)]  # type: ignore[valid-type]

# Proposed shared campaign category enum (see docs/integration/ai-messaging.md).
CAMPAIGN_CATEGORIES: tuple[str, ...] = (
    "medical",
    "education",
    "emergency",
    "community",
    "agriculture",
    "small_business",
    "housing",
    "water_sanitation",
    "other",
)
CampaignCategory = Literal[CAMPAIGN_CATEGORIES]  # type: ignore[valid-type]

# Navigation hints the assistant may suggest. The UI decides what each one opens;
# none of them performs an action.
ASSISTANT_ACTIONS: tuple[str, ...] = (
    "view_campaign_status",
    "view_payout_status",
    "contact_community_agent",
    "edit_campaign_draft",
    "verify_phone_number",
    "learn_about_fees",
    "learn_about_payouts",
    "learn_about_donating",
)
AssistantAction = Literal[ASSISTANT_ACTIONS]  # type: ignore[valid-type]

ASSISTANT_TOPICS = ("general", "payouts", "campaign", "account", "donations")


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MoneyIn(_Request):
    amount: str = Field(pattern=r"^\d{1,12}(\.\d{1,2})?$", description="Decimal string, e.g. '500.00'")
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 code")


class CampaignDraftRequest(_Request):
    story_notes: str = Field(min_length=20, max_length=3000)
    category: CampaignCategory | None = None
    beneficiary_first_name: str | None = Field(default=None, max_length=60)
    location: str | None = Field(default=None, max_length=80, description="Town or region, never a street address")
    goal: MoneyIn | None = None
    language: LanguageCode = "en"


class TranslateRequest(_Request):
    text: str = Field(min_length=1, max_length=2000)
    target_language: LanguageCode
    source_language: LanguageCode | None = None


class AssistantRequest(_Request):
    message: str = Field(min_length=1, max_length=1000)
    language: LanguageCode = "en"
    topic: Literal[ASSISTANT_TOPICS] = "general"  # type: ignore[valid-type]


class CampaignSearchRequest(_Request):
    query: str = Field(min_length=2, max_length=300)
    language: LanguageCode = "en"
    limit: int = Field(default=10, ge=1, le=20)


# ---------------------------------------------------------------------------
# Provider output models. Validated after every model call; anything that does
# not fit is treated as a provider failure and the deterministic fallback runs.
# ---------------------------------------------------------------------------


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftOutput(_Output):
    title: str = Field(min_length=5, max_length=120)
    summary: str = Field(min_length=10, max_length=400)
    story: str = Field(min_length=40, max_length=6000)
    suggested_category: CampaignCategory
    missing_information: list[str] = Field(default_factory=list, max_length=8)


class TranslateOutput(_Output):
    translated_text: str = Field(min_length=1, max_length=6000)
    detected_source_language: str = Field(min_length=2, max_length=12)


class AssistantOutput(_Output):
    reply: str = Field(min_length=1, max_length=1500)
    suggested_actions: list[AssistantAction] = Field(default_factory=list, max_length=3)
    escalate_to_human: bool


class SearchOutput(_Output):
    keywords: list[str] = Field(default_factory=list, max_length=8)
    category: CampaignCategory | None = None
    country_code: str | None = None

    @field_validator("country_code")
    @classmethod
    def _country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha() or not value.isascii():
            return None
        return value


def _strict_object(properties: dict, *, descriptions: dict[str, str] | None = None) -> dict:
    props = {}
    for key, schema in properties.items():
        schema = dict(schema)
        if descriptions and key in descriptions:
            schema["description"] = descriptions[key]
        props[key] = schema
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": props,
        "required": list(props),
    }


DRAFT_JSON_SCHEMA = _strict_object(
    {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "story": {"type": "string"},
        "suggested_category": {"type": "string", "enum": list(CAMPAIGN_CATEGORIES)},
        "missing_information": {"type": "array", "items": {"type": "string"}},
    },
    descriptions={
        "title": "Campaign title, at most 80 characters.",
        "summary": "One or two sentences, at most 280 characters.",
        "story": "Campaign story in plain paragraphs, at most 3500 characters.",
        "missing_information": "Facts a donor would expect that the notes do not provide.",
    },
)

TRANSLATE_JSON_SCHEMA = _strict_object(
    {
        "translated_text": {"type": "string"},
        "detected_source_language": {"type": "string"},
    },
    descriptions={"detected_source_language": "ISO 639-1 code of the input language."},
)

ASSISTANT_JSON_SCHEMA = _strict_object(
    {
        "reply": {"type": "string"},
        "suggested_actions": {"type": "array", "items": {"type": "string", "enum": list(ASSISTANT_ACTIONS)}},
        "escalate_to_human": {"type": "boolean"},
    },
    descriptions={
        "reply": "Answer in the requested language, at most 600 characters.",
        "suggested_actions": "Up to three screens the person could open next.",
        "escalate_to_human": "True when a community agent or reviewer should follow up.",
    },
)

SEARCH_JSON_SCHEMA = _strict_object(
    {
        "keywords": {"type": "array", "items": {"type": "string"}},
        "category": {"anyOf": [{"type": "string", "enum": list(CAMPAIGN_CATEGORIES)}, {"type": "null"}]},
        "country_code": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    descriptions={
        "keywords": "Up to 6 short English search keywords.",
        "country_code": "ISO 3166-1 alpha-2 code if the query names a country, otherwise null.",
    },
)
