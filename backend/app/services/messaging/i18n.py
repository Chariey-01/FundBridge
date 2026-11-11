"""Deterministic phone-channel text in English and Kiswahili.

USSD screens are kept under ~180 characters. The Kiswahili strings were written
by the development team and need review by a native speaker before launch.
"""

from __future__ import annotations

PHONE_LANGUAGES = ("en", "sw")

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "main_menu": "FundBridge\n1. My campaign\n2. My payout status\n3. Find a campaign\n4. How donors give\n"
                     "5. Get help\n6. Language/Lugha",
        "not_linked": "This number is not linked to a FundBridge beneficiary. Contact your community agent "
                      "or choose 5 for help.",
        "not_verified": "This number is waiting for verification by FundBridge. Contact your community agent "
                        "or choose 5 for help.",
        "no_campaigns": "No campaigns are linked to your number yet.",
        "choose_campaign": "Choose a campaign:",
        "campaign_status": "{title}\nStatus: {status}\nRaised: {raised} of {goal}",
        "pin_create": "Create a 4-digit PIN to protect your payout information:",
        "pin_confirm": "Enter the same PIN again:",
        "pin_mismatch": "The PINs did not match. Please dial again.",
        "pin_weak": "That PIN is too easy to guess. Please dial again and choose another.",
        "pin_enter": "Enter your 4-digit FundBridge PIN:",
        "pin_invalid": "Wrong PIN. {left} attempt(s) left.",
        "pin_locked": "Too many wrong PINs. Try again in {minutes} minutes or contact your agent.",
        "no_payouts": "No payout requests yet.",
        "payout_status": "Payout {amount}\nStatus: {status}\nUpdated: {date}",
        "search_prompt": "Enter a word to search, e.g. school or clinic:",
        "search_none": "No live campaigns match '{query}'.",
        "search_results": "{lines}\nDonate online: {url}",
        "donate_info": "Donors give online with PayPal at {url}. Share your campaign link. FundBridge never "
                       "asks you to send money to receive donations.",
        "help_menu": "Help\n1. Ask an agent to call me\n2. Report a problem\n3. I changed my phone or SIM",
        "help_opened": "Request received. Ref {ref}. An agent will contact you.",
        "help_sim": "Request received. Ref {ref}. An agent will verify your identity before any phone or "
                    "payout details change.",
        "language_menu": "Choose language / Chagua lugha\n1. English\n2. Kiswahili",
        "language_set": "Language set to English.",
        "invalid": "Invalid choice. Please dial again.",
        "unavailable": "Service temporarily unavailable. Please try again later.",
        "sms_help": "FundBridge: STATUS - campaign status. FIND <word> - search. AGENT - request a call. "
                    "LANG SW - Kiswahili. Payout status: dial {ussd}.",
        "sms_payout_redirect": "FundBridge: for your security, payout status is shown only after PIN entry. "
                               "Dial {ussd}.",
        "sms_status": "FundBridge: {lines}",
        "sms_find_usage": "FundBridge: send FIND and a word, e.g. FIND school",
        "sms_find_results": "FundBridge: {lines} Donate: {url}",
        "sms_stop": "FundBridge: you will not receive updates. Send START to resume.",
        "sms_start": "FundBridge: updates resumed. Send HELP for options.",
        "sms_assistant": "FundBridge (auto-reply): {reply} Send HELP for the menu.",
        "notify_donation": "FundBridge: {title} received a confirmed donation of {amount}. Total raised: {raised}.",
        "notify_payout": "FundBridge: payout of {amount}: {status}. Dial {ussd} for details.",
        "notify_published": "FundBridge: your campaign {title} is now live. Share: {url}",
    },
    "sw": {
        "main_menu": "FundBridge\n1. Kampeni yangu\n2. Hali ya malipo\n3. Tafuta kampeni\n4. Jinsi ya kuchangia\n"
                     "5. Msaada\n6. Language/Lugha",
        "not_linked": "Nambari hii haijaunganishwa na mnufaika wa FundBridge. Wasiliana na wakala wako au "
                      "chagua 5 kwa msaada.",
        "not_verified": "Nambari hii inasubiri kuthibitishwa na FundBridge. Wasiliana na wakala wako au "
                        "chagua 5 kwa msaada.",
        "no_campaigns": "Hakuna kampeni iliyounganishwa na nambari yako bado.",
        "choose_campaign": "Chagua kampeni:",
        "campaign_status": "{title}\nHali: {status}\nImechangiwa: {raised} kati ya {goal}",
        "pin_create": "Unda PIN ya tarakimu 4 kulinda taarifa za malipo yako:",
        "pin_confirm": "Weka PIN hiyo tena:",
        "pin_mismatch": "PIN hazikulingana. Tafadhali piga tena.",
        "pin_weak": "PIN hiyo ni rahisi kukisia. Piga tena uchague nyingine.",
        "pin_enter": "Weka PIN yako ya FundBridge ya tarakimu 4:",
        "pin_invalid": "PIN si sahihi. Majaribio {left} yamebaki.",
        "pin_locked": "PIN zisizo sahihi mara nyingi. Jaribu tena baada ya dakika {minutes} au wasiliana na "
                      "wakala wako.",
        "no_payouts": "Bado hakuna ombi la malipo.",
        "payout_status": "Malipo {amount}\nHali: {status}\nYamesasishwa: {date}",
        "search_prompt": "Andika neno la kutafuta, mfano shule au kliniki:",
        "search_none": "Hakuna kampeni hai inayolingana na '{query}'.",
        "search_results": "{lines}\nChangia mtandaoni: {url}",
        "donate_info": "Wachangiaji hutoa kwa PayPal: {url}. Shiriki kiungo cha kampeni yako. "
                       "FundBridge haitakuomba kutuma pesa ili upokee michango.",
        "help_menu": "Msaada\n1. Wakala anipigie\n2. Ripoti tatizo\n3. Nimebadilisha simu au laini",
        "help_opened": "Ombi limepokelewa. Kumb {ref}. Wakala atawasiliana nawe.",
        "help_sim": "Ombi limepokelewa. Kumb {ref}. Wakala atathibitisha utambulisho wako kabla ya kubadilisha "
                    "taarifa za simu au malipo.",
        "language_menu": "Choose language / Chagua lugha\n1. English\n2. Kiswahili",
        "language_set": "Lugha imewekwa: Kiswahili.",
        "invalid": "Chaguo si sahihi. Tafadhali piga tena.",
        "unavailable": "Huduma haipatikani kwa sasa. Tafadhali jaribu tena baadaye.",
        "sms_help": "FundBridge: HALI - hali ya kampeni. TAFUTA <neno> - tafuta. WAKALA - omba kupigiwa. "
                    "LUGHA EN - English. Hali ya malipo: piga {ussd}.",
        "sms_payout_redirect": "FundBridge: kwa usalama wako, hali ya malipo huonyeshwa baada ya kuweka PIN. "
                               "Piga {ussd}.",
        "sms_status": "FundBridge: {lines}",
        "sms_find_usage": "FundBridge: tuma TAFUTA na neno, mfano TAFUTA shule",
        "sms_find_results": "FundBridge: {lines} Changia: {url}",
        "sms_stop": "FundBridge: hutapokea taarifa tena. Tuma START kuendelea.",
        "sms_start": "FundBridge: taarifa zimerejeshwa. Tuma MSAADA kwa machaguo.",
        "sms_assistant": "FundBridge (jibu la kiotomatiki): {reply} Tuma MSAADA kwa menyu.",
        "notify_donation": "FundBridge: {title} imepokea mchango uliothibitishwa wa {amount}. Jumla: {raised}.",
        "notify_payout": "FundBridge: malipo ya {amount}: {status}. Piga {ussd} kwa maelezo.",
        "notify_published": "FundBridge: kampeni yako {title} iko hewani sasa. Shiriki: {url}",
    },
}

CAMPAIGN_STATUS = {
    "en": {"draft": "Draft", "submitted": "In review", "published": "Live", "closed": "Closed"},
    "sw": {"draft": "Rasimu", "submitted": "Inakaguliwa", "published": "Iko hewani", "closed": "Imefungwa"},
}

# Labels for the shared payout state machine. "succeeded" is the only state that says money arrived,
# and it is only ever shown when the backend reports that state.
PAYOUT_STATUS = {
    "en": {
        "requested": "Requested, waiting for review",
        "under_review": "Under review",
        "rejected": "Not approved. Contact your agent",
        "approved_for_submission": "Approved, being prepared",
        "submitted": "Sent to the mobile money provider, awaiting confirmation",
        "pending_confirmation": "Awaiting confirmation. Do not request again",
        "succeeded": "Paid to your mobile money account",
        "failed": "Not completed. Your agent will help you",
        "cancelled": "Cancelled",
    },
    "sw": {
        "requested": "Yameombwa, yanasubiri ukaguzi",
        "under_review": "Yanakaguliwa",
        "rejected": "Hayakuidhinishwa. Wasiliana na wakala wako",
        "approved_for_submission": "Yameidhinishwa, yanaandaliwa",
        "submitted": "Yametumwa kwa mtoa huduma, yanasubiri uthibitisho",
        "pending_confirmation": "Yanasubiri uthibitisho. Usiombe tena",
        "succeeded": "Yamelipwa kwenye akaunti yako ya pesa kwa simu",
        "failed": "Hayakukamilika. Wakala wako atakusaidia",
        "cancelled": "Yameghairiwa",
    },
}

UNKNOWN_STATUS = {"en": "Status unavailable. Contact your agent", "sw": "Hali haipatikani. Wasiliana na wakala"}


def phone_language(lang: str | None) -> str:
    return lang if lang in PHONE_LANGUAGES else "en"


def t(lang: str, key: str, **params: object) -> str:
    template = TEXT[phone_language(lang)][key]
    return template.format(**params) if params else template


def campaign_status_label(lang: str, status: str) -> str:
    return CAMPAIGN_STATUS[phone_language(lang)].get(status, UNKNOWN_STATUS[phone_language(lang)])


def payout_status_label(lang: str, status: str) -> str:
    return PAYOUT_STATUS[phone_language(lang)].get(status, UNKNOWN_STATUS[phone_language(lang)])
