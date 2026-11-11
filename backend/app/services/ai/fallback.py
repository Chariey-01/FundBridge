"""Deterministic behaviour used when no AI provider is configured or a call fails.

Nothing here calls a network service, so these paths always work in a demo and
in tests. Responses produced here are labelled ``provider: "fallback"`` and
``ai_generated: false``.
"""

from __future__ import annotations

import re

from .guardrails import sanitize_text, strip_placeholders
from .ports import SearchFilters
from .schemas import CampaignDraftRequest

CATEGORY_LABELS = {
    "en": {
        "medical": "medical care",
        "education": "education",
        "emergency": "emergency recovery",
        "community": "a community project",
        "agriculture": "farming",
        "small_business": "a small business",
        "housing": "safe housing",
        "water_sanitation": "clean water",
        "other": "an urgent need",
    },
    "sw": {
        "medical": "matibabu",
        "education": "elimu",
        "emergency": "kujikwamua baada ya dharura",
        "community": "mradi wa jamii",
        "agriculture": "kilimo",
        "small_business": "biashara ndogo",
        "housing": "makazi salama",
        "water_sanitation": "maji safi",
        "other": "hitaji la dharura",
    },
}

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "medical": ("hospital", "clinic", "medical", "surgery", "treatment", "medicine", "health", "cancer",
                "dialysis", "hospitali", "matibabu", "dawa", "afya", "upasuaji"),
    "education": ("school", "fees", "tuition", "education", "student", "books", "university", "college",
                  "shule", "elimu", "karo", "mwanafunzi", "wanafunzi", "chuo"),
    "emergency": ("flood", "fire", "emergency", "disaster", "drought", "mafuriko", "moto", "dharura", "ukame"),
    "agriculture": ("farm", "farming", "seeds", "livestock", "crops", "harvest", "shamba", "kilimo", "mbegu",
                    "mifugo", "mavuno"),
    "small_business": ("business", "shop", "kiosk", "tailoring", "biashara", "duka", "kibanda"),
    "housing": ("house", "roof", "rent", "shelter", "housing", "nyumba", "kodi", "makazi", "paa"),
    "water_sanitation": ("water", "borehole", "well", "sanitation", "toilet", "maji", "kisima", "choo"),
    "community": ("community", "village", "church", "mosque", "youth", "women", "jamii", "kijiji", "vijana",
                  "wanawake"),
}

_COUNTRIES = {
    "kenya": "KE", "uganda": "UG", "tanzania": "TZ", "rwanda": "RW", "burundi": "BI", "ethiopia": "ET",
    "somalia": "SO", "nigeria": "NG", "ghana": "GH", "malawi": "MW", "zambia": "ZM", "south sudan": "SS",
}

_STOPWORDS = frozenset(
    "a an the and or for of to in on at with by from about help helping support supporting people person "
    "who that this those these is are be want looking find show me i we my our some any need needs "
    "campaign campaigns fundraiser fundraisers please kenya uganda tanzania rwanda ethiopia "
    "na ya wa kwa za la cha vya katika kwenye kusaidia msaada nataka tafuta watu mtu".split()
)

_WORD_RE = re.compile(r"[a-zA-ZÀ-ÿ]{3,30}")


def fallback_search_filters(query: str) -> SearchFilters:
    lowered = query.lower()
    category = None
    best = 0
    for cat, words in _CATEGORY_KEYWORDS.items():
        hits = sum(1 for w in words if re.search(rf"\b{re.escape(w)}", lowered))
        if hits > best:
            category, best = cat, hits
    country = next((code for name, code in _COUNTRIES.items() if name in lowered), None)
    keywords: list[str] = []
    for word in _WORD_RE.findall(lowered):
        if word in _STOPWORDS or word in keywords:
            continue
        keywords.append(word)
        if len(keywords) == 6:
            break
    return SearchFilters(keywords=tuple(keywords), category=category, country_code=country)


def fallback_draft(req: CampaignDraftRequest, redacted_notes: str) -> dict:
    lang = req.language if req.language in CATEGORY_LABELS else "en"
    category = req.category or fallback_search_filters(req.story_notes).category or "other"
    label = CATEGORY_LABELS[lang][category]
    name = (req.beneficiary_first_name or "").strip()
    notes = sanitize_text(strip_placeholders(redacted_notes), max_length=3200)
    first_sentence = re.split(r"(?<=[.!?])\s+", notes, maxsplit=1)[0]

    if lang == "sw":
        who = name or "mwanajamii"
        title = f"Msaidie {who} kupata {label}"
        place = f" kutoka {req.location}" if req.location else ""
        closing = (
            "Michango yote hupitia FundBridge. Fedha hutolewa kwa mnufaika baada tu ya ukaguzi wa "
            "malipo wa FundBridge."
        )
        goal_line = f"Lengo la kampeni hii ni {req.goal.amount} {req.goal.currency}." if req.goal else ""
        story = "\n\n".join(p for p in (f"{who}{place}.", notes, goal_line, closing) if p)
    else:
        who = name or "a community member"
        title = f"Help {who} with {label}"
        place = f" from {req.location}" if req.location else ""
        closing = (
            "Every donation goes through FundBridge, and FundBridge reviews each payout before releasing it "
            "to the beneficiary."
        )
        goal_line = f"The goal of this campaign is {req.goal.amount} {req.goal.currency}." if req.goal else ""
        story = "\n\n".join(p for p in (f"This campaign supports {who}{place}.", notes, goal_line, closing) if p)

    missing = []
    if not req.goal:
        missing.append("Fundraising goal and currency")
    if not req.location:
        missing.append("General location (town or region)")
    if len(req.story_notes) < 200:
        missing.append("How the funds will be used, item by item")
    if not name:
        missing.append("How the beneficiary would like to be named publicly")

    return {
        "title": title[:80],
        "summary": sanitize_text(first_sentence, max_length=280),
        "story": story,
        "suggested_category": category,
        "missing_information": missing,
    }


_ASSISTANT_INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("security", ("lost", "stolen", "sim", "fraud", "scam", "threat", "hacked", "change number", "changed number",
                  "nimeibiwa", "wizi", "ulaghai", "tapeli", "imepotea", "laini", "tishio")),
    ("payout", ("payout", "withdraw", "paid", "pay me", "money", "transfer", "m-pesa", "mpesa", "malipo",
                "pesa", "kulipwa", "kutoa")),
    ("fees", ("fee", "charge", "cost", "deduct", "ada", "gharama", "makato")),
    ("donation", ("donat", "donor", "paypal", "give", "mchango", "michango", "changia")),
    ("verify", ("verify", "verification", "code", "otp", "thibitisha", "nambari ya siri")),
    ("campaign", ("campaign", "kampeni", "publish", "review", "draft", "story", "hadithi")),
)

_ASSISTANT_REPLIES = {
    "en": {
        "security": ("Please contact your community agent now. For your safety, any change to your phone "
                     "or payout number needs an identity check before it takes effect."),
        "payout": ("I cannot see your balance or payouts. Open Payout status for the confirmed details. "
                   "If a payout says 'awaiting confirmation', please wait and do not request it again."),
        "fees": ("Fees are shown to donors before they pay and in your campaign's payout breakdown. "
                 "Open your campaign to see the confirmed amounts."),
        "donation": ("Donors give online through PayPal. A donation counts only after the payment provider "
                     "confirms it. Share your campaign link so people can donate."),
        "verify": ("To verify your phone, request a code from the app or your community agent and enter it "
                   "within 10 minutes. Never share the code with anyone."),
        "campaign": ("Your campaign is reviewed by FundBridge before it is published. You can check its "
                     "status in My campaigns or by dialing the FundBridge USSD code."),
        "general": ("I can explain how campaigns, donations, payouts and fees work. For your own balance or "
                    "payout, open the status pages or contact your community agent."),
    },
    "sw": {
        "security": ("Tafadhali wasiliana na wakala wako wa jamii sasa. Kwa usalama wako, kubadilisha nambari "
                     "ya simu au ya malipo kunahitaji uthibitisho wa utambulisho kwanza."),
        "payout": ("Siwezi kuona salio au malipo yako. Fungua Hali ya malipo kwa taarifa zilizothibitishwa. "
                   "Ikiwa malipo yanasema 'yanasubiri uthibitisho', subiri na usiombe tena."),
        "fees": ("Ada huonyeshwa kwa wachangiaji kabla ya kulipa na kwenye muhtasari wa malipo wa kampeni yako."),
        "donation": ("Wachangiaji hutoa mtandaoni kupitia PayPal. Mchango huhesabiwa tu baada ya mtoa huduma "
                     "wa malipo kuuthibitisha. Shiriki kiungo cha kampeni yako."),
        "verify": ("Ili kuthibitisha simu yako, omba nambari kupitia programu au wakala wako na uiweke ndani "
                   "ya dakika 10. Usimpe mtu yeyote nambari hiyo."),
        "campaign": ("Kampeni yako hukaguliwa na FundBridge kabla ya kuchapishwa. Angalia hali yake kwenye "
                     "Kampeni zangu au kwa kupiga msimbo wa USSD wa FundBridge."),
        "general": ("Ninaweza kueleza jinsi kampeni, michango, malipo na ada zinavyofanya kazi. Kwa salio au "
                    "malipo yako, fungua kurasa za hali au wasiliana na wakala wako."),
    },
}

_INTENT_ACTIONS = {
    "security": ["contact_community_agent"],
    "payout": ["view_payout_status", "learn_about_payouts"],
    "fees": ["learn_about_fees"],
    "donation": ["learn_about_donating", "view_campaign_status"],
    "verify": ["verify_phone_number"],
    "campaign": ["view_campaign_status", "edit_campaign_draft"],
    "general": ["learn_about_payouts", "contact_community_agent"],
}

_TOPIC_INTENT = {"payouts": "payout", "campaign": "campaign", "donations": "donation", "account": "verify"}


def classify_intent(message: str, topic: str = "general") -> str:
    lowered = message.lower()
    for intent, words in _ASSISTANT_INTENTS:
        if any(word in lowered for word in words):
            return intent
    return _TOPIC_INTENT.get(topic, "general")


def fallback_assistant(message: str, language: str, topic: str = "general") -> dict:
    intent = classify_intent(message, topic)
    lang = language if language in _ASSISTANT_REPLIES else "en"
    return {
        "reply": _ASSISTANT_REPLIES[lang][intent],
        "language": lang,
        "suggested_actions": list(_INTENT_ACTIONS[intent]),
        "escalate_to_human": intent == "security",
    }


def safe_status_reply(language: str) -> str:
    lang = language if language in _ASSISTANT_REPLIES else "en"
    return _ASSISTANT_REPLIES[lang]["payout"]
