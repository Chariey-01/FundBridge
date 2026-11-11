from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pytest
from flask import Flask, request

from app.api.v1.ai import init_ai
from app.integrations.ai.base import StructuredRequest, StructuredResult
from app.services.ai.ports import Actor, InMemoryCampaignCatalog, Money, PublicCampaignSummary


@dataclass
class FakeProvider:
    """Scripted provider. ``responses`` maps task name -> dict, Exception, or callable(request)."""

    responses: dict[str, Any] = field(default_factory=dict)
    calls: list[StructuredRequest] = field(default_factory=list)
    name: str = "fake"
    model: str | None = "fake-model"
    live: bool = True

    def generate_structured(self, req: StructuredRequest) -> StructuredResult:
        self.calls.append(req)
        response = self.responses.get(req.task)
        if response is None:
            raise AssertionError(f"FakeProvider has no response for task {req.task}")
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(req)
        return StructuredResult(data=response, provider=self.name, model=self.model, latency_ms=5)


def sample_catalog() -> InMemoryCampaignCatalog:
    usd = lambda a: Money(a, "USD")  # noqa: E731
    return InMemoryCampaignCatalog(
        [
            PublicCampaignSummary("c1", "school-fees-amina", "School fees for Amina", "Secondary school fees in Kisumu",
                                  "education", "KE", usd("400.00"), usd("120.00")),
            PublicCampaignSummary("c2", "clinic-roof-repair", "Repair the village clinic roof",
                                  "A clinic in Turkana needs a new roof", "medical", "KE", usd("1500.00"), usd("900.00")),
            PublicCampaignSummary("c3", "borehole-gulu", "Borehole for Gulu families", "Clean water for 40 families",
                                  "water_sanitation", "UG", usd("3000.00"), usd("50.00")),
        ]
    )


def make_app(provider: Any = None, *, config: dict | None = None, recorder: Callable | None = None,
             status_reader: Any = None) -> Flask:
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret", **(config or {}))

    def resolver() -> Actor | None:
        raw = request.headers.get("X-Test-Actor")  # test-only seam; production uses real auth
        if not raw:
            return None
        actor_id, _, role = raw.partition(":")
        return Actor(actor_id, role or "creator")

    init_ai(app, actor_resolver=resolver, campaign_catalog=sample_catalog(), provider=provider,
            interaction_recorder=recorder, status_reader=status_reader)
    return app


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def records() -> list[dict]:
    return []


@pytest.fixture
def client(fake_provider, records):
    return make_app(fake_provider, recorder=records.append).test_client()


@pytest.fixture
def fallback_client():
    return make_app(None).test_client()


AUTH = {"X-Test-Actor": "user-1:creator"}
