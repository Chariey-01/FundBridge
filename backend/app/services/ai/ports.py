"""Seams between the AI/messaging modules and the core backend (owned by Codex).

The core backend supplies:
- an ``actor_resolver`` that returns the authenticated ``Actor`` for the current request;
- a ``CampaignCatalog`` that searches publicly visible campaigns, with raised totals
  derived from the ledger.

``InMemoryCampaignCatalog`` exists for tests and the labelled offline demo only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence


@dataclass(frozen=True)
class Actor:
    id: str
    role: str  # donor | creator | beneficiary | community_agent | reviewer | admin


ActorResolver = Callable[[], "Actor | None"]


@dataclass(frozen=True)
class Money:
    amount: str  # decimal string, never float
    currency: str

    def to_dict(self) -> dict[str, str]:
        return {"amount": self.amount, "currency": self.currency}


@dataclass(frozen=True)
class SearchFilters:
    keywords: tuple[str, ...] = ()
    category: str | None = None
    country_code: str | None = None

    def to_dict(self) -> dict:
        return {"keywords": list(self.keywords), "category": self.category, "country_code": self.country_code}


@dataclass(frozen=True)
class PublicCampaignSummary:
    id: str
    slug: str
    title: str
    summary: str
    category: str
    country_code: str | None
    goal: Money
    raised: Money  # authoritative, from the ledger; never computed by AI or the client

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "summary": self.summary,
            "category": self.category,
            "country_code": self.country_code,
            "goal": self.goal.to_dict(),
            "raised": self.raised.to_dict(),
        }


class CampaignCatalog(Protocol):
    def search(self, filters: SearchFilters, limit: int) -> Sequence[PublicCampaignSummary]:
        """Return publicly visible campaigns only, best match first."""
        ...


@dataclass
class InMemoryCampaignCatalog:
    campaigns: list[PublicCampaignSummary] = field(default_factory=list)

    def search(self, filters: SearchFilters, limit: int) -> Sequence[PublicCampaignSummary]:
        scored: list[tuple[int, int, PublicCampaignSummary]] = []
        for index, campaign in enumerate(self.campaigns):
            if filters.category and campaign.category != filters.category:
                continue
            if filters.country_code and campaign.country_code != filters.country_code:
                continue
            haystack = f"{campaign.title} {campaign.summary} {campaign.category}".lower()
            score = sum(1 for kw in filters.keywords if kw.lower() in haystack)
            if filters.keywords and score == 0:
                continue
            scored.append((-score, index, campaign))
        scored.sort(key=lambda item: (item[0], item[1]))
        return [c for _, _, c in scored[:limit]]
