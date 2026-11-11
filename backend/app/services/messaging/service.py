"""Deterministic USSD menu, SMS commands and outbound notifications.

None of these flows need AI. The only AI use is an optional auto-reply to free-text
SMS that matches no command, and it goes through the same guarded AI service as the
web assistant (falling back to fixed replies when AI is unavailable).

The phone channels are read-only with respect to money: they show status, open
support requests and set language/opt-out preferences. They cannot request,
approve or redirect a payout.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from typing import Callable

from app.services.ai.fallback import fallback_search_filters
from app.services.ai.ports import CampaignCatalog, Money, SearchFilters

from .text import USSD_MAX, fit, gsm7_length, shorten, to_gsm7
from .i18n import campaign_status_label, payout_status_label, phone_language, t
from .phone import normalize_msisdn
from .pins import PinService
from .ports import BeneficiaryDirectory, BeneficiaryRecord, CampaignStatusView, MessagingStore

log = logging.getLogger("fundbridge.messaging")
_PROCESS_SECRET = secrets.token_hex(16)  # used only when no app secret is configured


@dataclass(frozen=True)
class MessagingSettings:
    public_base_url: str = "http://localhost:3000"
    ussd_code: str = "*384*123#"
    default_country: str = "KE"
    # Keys the HMAC that identifies a USSD step for retry detection (the step text contains the PIN).
    dedup_secret: str = ""


@dataclass(frozen=True)
class UssdReply:
    text: str
    end: bool

    def render(self) -> str:
        # Every screen is GSM 7-bit and at most 182 characters, whatever titles or URLs it contains.
        return ("END " if self.end else "CON ") + fit(self.text, USSD_MAX)


def fmt_money(money: Money) -> str:
    return f"{money.currency} {money.amount}"


def _short(text: str, limit: int) -> str:
    return shorten(text, limit)


def _fit_menu(header: str, items: list[str], *, number_fmt: str = "{i}. ", limit: int = USSD_MAX) -> str:
    """A numbered menu whose item titles are shortened just enough to fit one screen."""
    overhead = gsm7_length(to_gsm7(header)) + sum(len(number_fmt.format(i=i)) + 1 for i in range(1, len(items) + 1))
    width = max(8, (limit - overhead) // max(1, len(items)))
    lines = [number_fmt.format(i=i) + shorten(item, width) for i, item in enumerate(items, 1)]
    return header + "\n" + "\n".join(lines)


def parse_steps(text: str | None) -> list[str]:
    """Turn Africa's Talking's cumulative ``text`` (e.g. "1*2*1234") into menu steps.

    "0" goes back one step and "00" returns to the main menu.
    """
    steps: list[str] = []
    for token in (text or "").split("*"):
        token = token.strip()
        if token == "":
            continue
        if token == "00":
            steps.clear()
        elif token == "0" and steps:
            steps.pop()
        else:
            steps.append(token)
    return steps


AssistantReply = Callable[[str, str, str], "str | None"]  # (msisdn, text, lang) -> reply


class MessagingService:
    def __init__(
        self,
        *,
        directory: BeneficiaryDirectory,
        store: MessagingStore,
        catalog: CampaignCatalog,
        gateway,
        settings: MessagingSettings | None = None,
        assistant: AssistantReply | None = None,
    ) -> None:
        self.directory = directory
        self.store = store
        self.catalog = catalog
        self.gateway = gateway
        self.settings = settings or MessagingSettings()
        self.pins = PinService(store)
        self.assistant = assistant

    # ------------------------------------------------------------------ helpers

    def _language(self, msisdn: str, beneficiary: BeneficiaryRecord | None) -> str:
        pref = self.store.get_preference(msisdn)
        if pref.language:
            return phone_language(pref.language)
        return phone_language(beneficiary.preferred_language if beneficiary else None)

    def _search_screen(self, lang: str, results) -> str:
        """Up to three results with the donate link; fewer results or shorter titles when the screen is full."""
        url = self._url("/campaigns")
        for count in range(min(3, len(results)), 0, -1):
            for width in (34, 28, 22, 18):
                lines = "\n".join(f"{i}) {shorten(c.title, width)}: {fmt_money(c.raised)}"
                                   for i, c in enumerate(results[:count], 1))
                screen = t(lang, "search_results", lines=lines, url=url)
                if gsm7_length(to_gsm7(screen)) <= USSD_MAX:
                    return screen
        return screen  # render() still caps it

    def _campaign_line(self, lang: str, c: CampaignStatusView, *, limit: int = 40) -> str:
        return t(lang, "campaign_status", title=_short(c.title, limit), status=campaign_status_label(lang, c.status),
                 raised=fmt_money(c.raised), goal=fmt_money(c.goal))

    def _search(self, query: str, limit: int = 3):
        filters = fallback_search_filters(query)
        results = list(self.catalog.search(filters, limit))
        if not results and filters.keywords:
            results = list(self.catalog.search(SearchFilters(keywords=filters.keywords), limit))
        return results

    def _url(self, path: str = "") -> str:
        return self.settings.public_base_url.rstrip("/") + path

    # --------------------------------------------------------------------- USSD

    def handle_ussd(self, *, phone_number: str, text: str | None, session_id: str | None = None) -> UssdReply:
        msisdn = normalize_msisdn(phone_number, self.settings.default_country)
        if msisdn is None:
            return UssdReply(t("en", "unavailable"), True)
        step_key = None
        if session_id:
            secret = (self.settings.dedup_secret or _PROCESS_SECRET).encode()
            step_key = hmac.new(secret, f"{session_id}\x1f{text or ''}".encode(), hashlib.sha256).hexdigest()[:40]
        try:
            return self._ussd(msisdn, parse_steps(text), step_key)
        except Exception:  # never leak internals to a handset; log and end the session
            log.exception("USSD flow failed (session %s)", session_id)
            return UssdReply(t("en", "unavailable"), True)

    def _ussd(self, msisdn: str, steps: list[str], step_key: str | None = None) -> UssdReply:
        beneficiary = self.directory.find_by_phone(msisdn)
        lang = self._language(msisdn, beneficiary)
        if not steps:
            return UssdReply(t(lang, "main_menu"), False)
        choice, rest = steps[0], steps[1:]
        if choice == "1":
            return self._ussd_campaigns(lang, beneficiary, rest)
        if choice == "2":
            return self._ussd_payout(lang, beneficiary, rest, step_key)
        if choice == "3":
            if not rest:
                return UssdReply(t(lang, "search_prompt"), False)
            query = _short(" ".join(rest), 40)
            results = self._search(query)
            if not results:
                return UssdReply(t(lang, "search_none", query=query), True)
            return UssdReply(self._search_screen(lang, results), True)
        if choice == "4":
            return UssdReply(t(lang, "donate_info", url=self._url()), True)
        if choice == "5":
            return self._ussd_help(lang, msisdn, beneficiary, rest)
        if choice == "6":
            if not rest:
                return UssdReply(t(lang, "language_menu"), False)
            new_lang = {"1": "en", "2": "sw"}.get(rest[0])
            if not new_lang:
                return UssdReply(t(lang, "invalid"), True)
            pref = self.store.get_preference(msisdn)
            pref.language = new_lang
            self.store.save_preference(msisdn, pref)
            return UssdReply(t(new_lang, "language_set"), True)
        return UssdReply(t(lang, "invalid"), True)

    @staticmethod
    def _verified(beneficiary: BeneficiaryRecord) -> bool:
        # A phone number only identifies a beneficiary once that profile is verified. After a phone or
        # payout-destination change the profile is "reverification_required" and the new number gets nothing
        # beneficiary-specific (no campaign or payout details, no PIN setup) until an agent re-verifies it.
        return beneficiary.verification_status == "verified"

    def _ussd_campaigns(self, lang: str, beneficiary: BeneficiaryRecord | None, rest: list[str]) -> UssdReply:
        if beneficiary is None:
            return UssdReply(t(lang, "not_linked"), True)
        if not self._verified(beneficiary):
            return UssdReply(t(lang, "not_verified"), True)
        campaigns = list(self.directory.campaigns_for(beneficiary.id))[:5]
        if not campaigns:
            return UssdReply(t(lang, "no_campaigns"), True)
        if len(campaigns) == 1:
            return UssdReply(self._campaign_line(lang, campaigns[0]), True)
        if not rest:
            return UssdReply(_fit_menu(t(lang, "choose_campaign"), [c.title for c in campaigns]), False)
        if rest[0].isdigit() and 1 <= int(rest[0]) <= len(campaigns):
            return UssdReply(self._campaign_line(lang, campaigns[int(rest[0]) - 1]), True)
        return UssdReply(t(lang, "invalid"), True)

    def _ussd_payout(self, lang: str, beneficiary: BeneficiaryRecord | None, rest: list[str],
                     step_key: str | None = None) -> UssdReply:
        if beneficiary is None:
            return UssdReply(t(lang, "not_linked"), True)
        if not self._verified(beneficiary):
            return UssdReply(t(lang, "not_verified"), True)
        if self.pins.has_pin(beneficiary.id):
            if not rest:
                return UssdReply(t(lang, "pin_enter"), False)
            # A gateway retry of the same step must not count as a second wrong attempt.
            fresh = step_key is None or self.store.first_delivery("ussd-pin", step_key)
            check = self.pins.verify(beneficiary.id, rest[0], count_failure=fresh)
            if check.outcome == "locked":
                return UssdReply(t(lang, "pin_locked", minutes=check.minutes_locked), True)
            if check.outcome != "ok":
                return UssdReply(t(lang, "pin_invalid", left=check.attempts_left), True)
            return self._payout_status(lang, beneficiary)
        # No PIN yet: create one (trust on first use; an agent can reset it).
        if not rest:
            return UssdReply(t(lang, "pin_create"), False)
        first = rest[0]
        if not PinService.is_valid_format(first) or PinService.is_weak(first):
            return UssdReply(t(lang, "pin_weak"), True)
        if len(rest) == 1:
            return UssdReply(t(lang, "pin_confirm"), False)
        if rest[1] != first:
            return UssdReply(t(lang, "pin_mismatch"), True)
        if not self.pins.create(beneficiary.id, first):
            return UssdReply(t(lang, "invalid"), True)
        return self._payout_status(lang, beneficiary)

    def _payout_status(self, lang: str, beneficiary: BeneficiaryRecord) -> UssdReply:
        payout = self.directory.latest_payout(beneficiary.id)
        if payout is None:
            return UssdReply(t(lang, "no_payouts"), True)
        return UssdReply(
            t(lang, "payout_status", amount=fmt_money(payout.amount), status=payout_status_label(lang, payout.status),
              date=payout.updated_at.strftime("%d %b %Y")),
            True,
        )

    def _ussd_help(self, lang: str, msisdn: str, beneficiary: BeneficiaryRecord | None, rest: list[str]) -> UssdReply:
        if not rest:
            return UssdReply(t(lang, "help_menu"), False)
        topic = {"1": "callback", "2": "problem", "3": "sim_change"}.get(rest[0])
        if topic is None:
            return UssdReply(t(lang, "invalid"), True)
        ref = self.store.open_support_request(
            msisdn=msisdn,
            beneficiary_id=beneficiary.id if beneficiary else None,
            channel="ussd",
            topic=topic,
            priority="high" if topic == "sim_change" else "normal",
        )
        return UssdReply(t(lang, "help_sim" if topic == "sim_change" else "help_opened", ref=ref), True)

    # ---------------------------------------------------------------------- SMS

    def handle_inbound_sms(self, *, phone_number: str, text: str | None, message_id: str | None = None) -> list[str]:
        """Process an inbound SMS and send the replies. Returns the reply texts.

        ``message_id`` is the gateway's id; a retried delivery of the same message is ignored, so a person never
        gets duplicate replies or duplicate support requests.
        """
        msisdn = normalize_msisdn(phone_number, self.settings.default_country)
        if msisdn is None:
            return []
        if message_id and not self.store.first_delivery("sms", str(message_id)[:200]):
            log.info("Duplicate inbound SMS %s ignored", str(message_id)[:40])
            return []
        try:
            replies = self._sms(msisdn, (text or "").strip()[:480])
        except Exception:
            log.exception("SMS handling failed")
            replies = [t("en", "unavailable")]
        for reply in replies:
            self.gateway.send(msisdn, reply)
        return replies

    def _sms(self, msisdn: str, text: str) -> list[str]:
        beneficiary = self.directory.find_by_phone(msisdn)
        lang = self._language(msisdn, beneficiary)
        words = text.split()
        command = words[0].upper() if words else "HELP"
        args = words[1:]

        if command in ("STOP", "UNSUBSCRIBE", "SITISHA"):
            pref = self.store.get_preference(msisdn)
            pref.opted_out = True
            self.store.save_preference(msisdn, pref)
            return [t(lang, "sms_stop")]
        if command in ("START", "ANZA"):
            pref = self.store.get_preference(msisdn)
            pref.opted_out = False
            self.store.save_preference(msisdn, pref)
            return [t(lang, "sms_start")]
        if command in ("HELP", "MENU", "MSAADA", "MENYU"):
            return [t(lang, "sms_help", ussd=self.settings.ussd_code)]
        if command in ("LANG", "LUGHA", "LANGUAGE"):
            new_lang = (args[0].lower() if args else "")[:2]
            if new_lang in ("en", "sw"):
                pref = self.store.get_preference(msisdn)
                pref.language = new_lang
                self.store.save_preference(msisdn, pref)
                return [t(new_lang, "language_set")]
            return [t(lang, "sms_help", ussd=self.settings.ussd_code)]
        if command in ("PAYOUT", "MALIPO", "BALANCE", "SALIO", "PIN"):
            return [t(lang, "sms_payout_redirect", ussd=self.settings.ussd_code)]
        if command in ("STATUS", "HALI"):
            if beneficiary is None:
                return [t(lang, "not_linked")]
            if not self._verified(beneficiary):
                return [t(lang, "not_verified")]
            campaigns = list(self.directory.campaigns_for(beneficiary.id))[:3]
            if not campaigns:
                return [t(lang, "no_campaigns")]
            lines = " | ".join(self._campaign_line(lang, c, limit=30).replace("\n", ", ") for c in campaigns)
            return [t(lang, "sms_status", lines=lines)]
        if command in ("FIND", "SEARCH", "TAFUTA"):
            if not args:
                return [t(lang, "sms_find_usage")]
            query = " ".join(args)[:60]
            results = self._search(query)
            if not results:
                return [t(lang, "search_none", query=query)]
            lines = "; ".join(f"{_short(c.title, 40)} ({fmt_money(c.raised)})" for c in results)
            return [t(lang, "sms_find_results", lines=lines, url=self._url("/campaigns"))]
        if command in ("AGENT", "WAKALA", "CALL"):
            ref = self.store.open_support_request(
                msisdn=msisdn, beneficiary_id=beneficiary.id if beneficiary else None, channel="sms",
                topic="callback", priority="normal",
            )
            return [t(lang, "help_opened", ref=ref)]

        # Free text: optional guarded assistant, otherwise the command list.
        if self.assistant is not None and re.search(r"[A-Za-z]{3}", text):
            reply = self.assistant(msisdn, text, lang)
            if reply:
                return [t(lang, "sms_assistant", reply=_short(reply, 300))]
        return [t(lang, "sms_help", ussd=self.settings.ussd_code)]

    # ------------------------------------------------------------ notifications

    def notify(self, *, msisdn: str, template: str, language: str | None = None, essential: bool = False,
               **params) -> bool:
        """Send a templated notification. Opted-out numbers only receive essential messages."""
        target = normalize_msisdn(msisdn, self.settings.default_country)
        if target is None:
            return False
        pref = self.store.get_preference(target)
        if pref.opted_out and not essential:
            return False
        lang = phone_language(pref.language or language)
        if "status" in params and template == "notify_payout":
            params["status"] = payout_status_label(lang, params["status"])
        params.setdefault("ussd", self.settings.ussd_code)
        result = self.gateway.send(target, t(lang, template, **params))
        return result.status in ("simulated", "submitted")
