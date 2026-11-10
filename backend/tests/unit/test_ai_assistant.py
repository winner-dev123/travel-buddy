"""AI provider port, pricing and itinerary rules (BL-4.02; AI-001..004, AI-008, AI-009)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import anthropic
import httpx2
import pytest

from app.modules.ai_assistant.domain import (
    DISCLAIMER,
    DRAFT_SCHEMA,
    SYSTEM_PROMPT,
    Candidate,
    ItineraryContext,
    ItineraryDraft,
    build_prompt,
    build_proposal,
    repair_feedback,
    semantic_errors,
)
from app.modules.ai_assistant.provider import (
    PRICES,
    AITask,
    AnthropicProvider,
    FakeAIProvider,
    Prompt,
    ProviderError,
    TaskConfig,
    Usage,
    cost_micros,
    fake_itinerary,
)
from app.modules.ai_assistant.schemas import ItineraryProposal

CONFIG = TaskConfig(model="claude-opus-5-5", max_tokens=16000, effort="medium", timeout_seconds=30)
PLACE = "0192f0c0-0000-7000-8000-000000000001"


def _context(**overrides: Any) -> ItineraryContext:
    values: dict[str, Any] = {
        "destination_name": "Lisbon",
        "destination_path": "portugal/lisbon",
        "country_name": "Portugal",
        "time_zone": "Europe/Lisbon",
        "start_date": date(2026, 12, 4),
        "end_date": date(2026, 12, 5),
        "interests": ("food", "viewpoints"),
        "travel_styles": ("culture",),
        "pace": "moderate",
        "budget_level": "moderate",
        "adults": 2,
        "children": 0,
        "preferences": None,
        "include_social_opportunities": False,
        "locale": "pt-BR",
        "candidates": (Candidate(PLACE, "Miradouro da Graça", "viewpoint"),),
    }
    values.update(overrides)
    return ItineraryContext(**values)


def _item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "activity",
        "title": "Graça viewpoint",
        "description": "Sunset over the old town.",
        "place_id": None,
        "suggested_start_time": "09:00",
        "estimated_duration_minutes": 60,
        "category": "viewpoint",
        "confidence": 0.8,
        "rationale": "Matches the viewpoints interest.",
        "social_opportunity": False,
    }
    item.update(overrides)
    return item


def _draft(days: list[list[dict[str, Any]]]) -> ItineraryDraft:
    return ItineraryDraft.model_validate(
        {
            "days": [
                {"day_index": i, "theme": None, "items": items} for i, items in enumerate(days)
            ],
            "warnings": [],
            "confidence": 0.7,
        }
    )


# ─────────────────────────────── pricing ───────────────────────────────


def test_cost_counts_cache_writes_and_reads_and_overcharges_unknown_models() -> None:
    usage = Usage(
        input_tokens=1000, output_tokens=500, cache_read_tokens=2000, cache_write_tokens=400
    )
    # 1000*4 + 500*20 + 400*4*1.25 + 2000*4*0.1 micro-USD
    assert cost_micros("claude-opus-5-5", usage) == 4000 + 10000 + 2000 + 800
    assert cost_micros("claude-haiku-5-5", Usage(input_tokens=10)) == 1  # rounded up
    priciest = max(PRICES.values())
    assert cost_micros("some-future-model", Usage(output_tokens=1)) == priciest[1]


def test_usage_adds_up() -> None:
    assert Usage(1, 2, 3, 4) + Usage(10, 20, 30, 40) == Usage(11, 22, 33, 44)


# ─────────────────────────────── prompt & schema ───────────────────────────────


@pytest.mark.req("AI-004")
def test_draft_schema_has_no_fields_for_hours_prices_availability_or_safety() -> None:
    text = json.dumps(DRAFT_SCHEMA).lower()
    for forbidden in ("price", "opening", "hours", "ticket", "availability", "safety", "cost"):
        assert forbidden not in text


@pytest.mark.req("AI-008")
def test_prompt_contains_only_typed_trip_parameters() -> None:
    prompt = build_prompt(_context(preferences="No museums please"))
    payload = json.loads(prompt.user)
    assert set(payload) == {"destination", "trip", "locale", "candidates"}
    assert payload["trip"]["days"] == 2
    assert payload["locale"] == "pt-BR"
    assert payload["candidates"] == [
        {"id": PLACE, "name": "Miradouro da Graça", "category": "viewpoint"}
    ]
    assert prompt.system == SYSTEM_PROMPT  # fixed per version: the cacheable prefix
    assert build_prompt(_context()).user == build_prompt(_context()).user  # deterministic


def test_repair_feedback_lists_the_failed_checks() -> None:
    feedback = repair_feedback(["day 0: items 0 and 1 overlap"])
    assert "- day 0: items 0 and 1 overlap" in feedback


# ─────────────────────────────── semantic checks ───────────────────────────────


@pytest.mark.req("AI-002", "AI-003")
def test_semantic_checks_catch_days_unknown_places_overlaps_and_midnight() -> None:
    context = _context()
    assert semantic_errors(_draft([[_item(place_id=PLACE)], [_item()]]), context) == []

    errors = semantic_errors(_draft([[_item()]]), context)
    assert any("day_index 0 to 1" in e for e in errors)

    overlapping = [_item(), _item(suggested_start_time="09:30")]
    errors = semantic_errors(_draft([overlapping, [_item()]]), context)
    assert errors == ["day 0: items 0 and 1 overlap"]

    late = [_item(suggested_start_time="23:30", estimated_duration_minutes=60)]
    assert semantic_errors(_draft([late, [_item()]]), context) == [
        "day 0: item 0 runs past midnight"
    ]

    invented = [_item(place_id="not-a-candidate")]
    [error] = semantic_errors(_draft([invented, [_item()]]), context)
    assert "not a candidate" in error
    assert "not-a-candidate" not in error  # model output is never echoed into stored errors


@pytest.mark.req("AI-002", "AI-003", "AI-007")
def test_proposal_joins_dates_attribution_and_flags_unverified_items() -> None:
    context = _context(include_social_opportunities=False)
    draft = _draft([[_item(place_id=PLACE, social_opportunity=True)], [_item()]])
    proposal = build_proposal(
        draft,
        context,
        destination={
            "id": "0192f0c0-0000-7000-8000-0000000000aa",
            "kind": "city",
            "slug": "lisbon",
            "path": "portugal/lisbon",
            "name": "Lisboa",
            "country_code": "PT",
            "country_name": "Portugal",
            "continent": "europe",
            "tagline": None,
            "cover": None,
        },
        destination_id="0192f0c0-0000-7000-8000-0000000000aa",
        generated_at=datetime(2026, 11, 10, 12, 0, tzinfo=UTC),
    )
    ItineraryProposal.model_validate(proposal)  # the contract shape
    day0, day1 = proposal["itinerary"]["days"]
    assert [day0["date"], day1["date"]] == ["2026-12-04", "2026-12-05"]
    grounded, guessed = day0["items"][0], day1["items"][0]
    assert grounded["unverified"] is False
    assert grounded["source_attribution"] == [{"kind": "catalog_place", "ref_id": PLACE}]
    assert grounded["social_opportunity"] is False  # not requested
    assert guessed["unverified"] is True
    assert guessed["source_attribution"] == [{"kind": "ai_general_knowledge"}]
    assert proposal["disclaimer"] == DISCLAIMER["pt-BR"]
    assert any("não verificadas" in w for w in proposal["warnings"])


# ─────────────────────────────── fake adapter ───────────────────────────────


async def test_fake_provider_plans_from_the_prompt_and_follows_its_script() -> None:
    fake = FakeAIProvider()
    prompt = build_prompt(_context())
    completion = await fake.complete(
        task=AITask.ITINERARY_GENERATE, config=CONFIG, prompt=prompt, schema=DRAFT_SCHEMA
    )
    draft = ItineraryDraft.model_validate_json(completion.text or "")
    assert semantic_errors(draft, _context()) == []
    assert draft.days[0].items[0].place_id == PLACE
    assert completion.usage.input_tokens > 0

    fake.script("refuse", ProviderError("down", retryable=True))
    refused = await fake.complete(
        task=AITask.ITINERARY_GENERATE, config=CONFIG, prompt=prompt, schema=DRAFT_SCHEMA
    )
    assert refused.refused
    assert refused.text is None
    with pytest.raises(ProviderError):
        await fake.complete(
            task=AITask.ITINERARY_GENERATE, config=CONFIG, prompt=prompt, schema=DRAFT_SCHEMA
        )
    assert len(fake.calls) == 3


def test_fake_itinerary_is_valid_for_every_trip_length() -> None:
    context = _context(end_date=date(2026, 12, 24), candidates=())
    draft = ItineraryDraft.model_validate_json(fake_itinerary(build_prompt(context)))
    assert len(draft.days) == 21
    assert semantic_errors(draft, context) == []


# ─────────────────────────────── Claude adapter ───────────────────────────────


def _claude(handler: Any, **kwargs: Any) -> AnthropicProvider:
    return AnthropicProvider(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
        **kwargs,
    )


def _message(text: str, stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": text},
        ],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 800,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 900,
        },
    }


@pytest.mark.req("AI-001", "AI-009")
async def test_claude_adapter_sends_structured_output_effort_and_cacheable_system() -> None:
    seen: list[dict[str, Any]] = []
    headers: list[httpx2.Headers] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        headers.append(request.headers)
        return httpx2.Response(
            200, json=_message('{"ok": true}'), headers={"request-id": "req_123"}
        )

    provider = _claude(handler)
    prompt = Prompt(system="sys", user='{"trip": 1}', feedback="fix day 0")
    completion = await provider.complete(
        task=AITask.ITINERARY_GENERATE, config=CONFIG, prompt=prompt, schema=DRAFT_SCHEMA
    )
    [body] = seen
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == 16000
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["system"] == [
        {"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}
    ]
    assert [b["text"] for b in body["messages"][0]["content"]] == ['{"trip": 1}', "fix day 0"]
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in headers[0]["anthropic-beta"]
    assert "thinking" not in body
    assert "temperature" not in body
    assert completion.text == '{"ok": true}'  # thinking blocks are skipped
    assert completion.usage == Usage(1200, 800, 0, 900)
    assert completion.model == "claude-opus-5-5"
    assert completion.provider_request_id == "req_123"


async def test_claude_adapter_can_skip_the_refusal_fallback_and_reports_refusals() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=_message("", stop_reason="refusal"))

    completion = await _claude(handler, refusal_fallback=False).complete(
        task=AITask.ITINERARY_GENERATE, config=CONFIG, prompt=Prompt("s", "u"), schema=DRAFT_SCHEMA
    )
    assert "fallbacks" not in seen[0]
    assert completion.refused
    assert completion.text is None


@pytest.mark.parametrize(
    ("status", "retryable"), [(429, True), (529, True), (500, True), (400, False), (401, False)]
)
async def test_claude_adapter_maps_http_failures(status: int, retryable: bool) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": "x", "message": "nope"}}
        )

    with pytest.raises(ProviderError) as caught:
        await _claude(handler).complete(
            task=AITask.ITINERARY_GENERATE,
            config=CONFIG,
            prompt=Prompt("s", "u"),
            schema=DRAFT_SCHEMA,
        )
    assert caught.value.retryable is retryable
    assert caught.value.status == status


async def test_claude_adapter_maps_network_failures() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(ProviderError) as caught:
        await _claude(handler).complete(
            task=AITask.ITINERARY_GENERATE,
            config=CONFIG,
            prompt=Prompt("s", "u"),
            schema=DRAFT_SCHEMA,
        )
    assert caught.value.retryable is True
