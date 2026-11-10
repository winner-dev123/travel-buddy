"""The ``AIProvider`` port and its adapters (architecture §13, ADR-0024; AI-001).

An adapter takes a typed prompt and a JSON schema and returns the structured text with token usage.
Validation, the repair retry, quotas, the circuit breakers and telemetry live in the service, so
every adapter is held to the same rules and swapping providers is a configuration change.

* :class:`AnthropicProvider`: Claude through the official SDK, with structured outputs
  (``output_config.format``), an explicit effort level, a cacheable system prompt and the
  server-side refusal fallback.
* :class:`FakeAIProvider`: deterministic, offline answers for development and tests; never allowed
  in production (settings guard). Tests can queue scripted outcomes.
"""

from __future__ import annotations

import json
import math
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol

import anthropic
from anthropic.types.beta import BetaMessageParam, BetaTextBlockParam

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class AITask(StrEnum):
    ITINERARY_GENERATE = "itinerary_generate"
    TRIP_REPLAN = "trip_replan"
    POST_TRANSLATE = "post_translate"


@dataclass(frozen=True, slots=True)
class TaskConfig:
    """Per-task model settings, from configuration (AI-001)."""

    model: str
    max_tokens: int
    effort: Effort
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class Prompt:
    """``system`` is fixed per prompt version (the cacheable prefix); ``user`` is the typed context
    as JSON; ``feedback`` lists what failed validation on the previous attempt (repair)."""

    system: str
    user: str
    feedback: str | None = None


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass(frozen=True, slots=True)
class Completion:
    text: str | None
    stop_reason: str | None  # end_turn, max_tokens, refusal, ...
    model: str  # the model that answered (a refusal fallback may switch it)
    usage: Usage
    provider_request_id: str | None = None

    @property
    def refused(self) -> bool:
        return self.stop_reason == "refusal"


class ProviderError(Exception):
    """The call failed. ``retryable`` failures (network, rate limits, overload, 5xx) count towards
    the provider circuit breaker; others (bad request, auth) are configuration bugs."""

    def __init__(self, message: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class AIProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def complete(
        self, *, task: AITask, config: TaskConfig, prompt: Prompt, schema: Mapping[str, Any]
    ) -> Completion: ...


# USD per million tokens, which is also micro-USD per token: (input, output). Cache writes bill at
# 1.25x input and cache reads at 0.1x (5-minute TTL). Unknown models bill at the most expensive
# known rate, so the spend breaker errs on the safe side.
PRICES: Mapping[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "fake": (4.0, 20.0),  # priced like the default model so budgets can be exercised in tests
}


def cost_micros(model: str, usage: Usage) -> int:
    rate_in, rate_out = PRICES.get(model, max(PRICES.values()))
    return math.ceil(
        usage.input_tokens * rate_in
        + usage.output_tokens * rate_out
        + usage.cache_write_tokens * rate_in * 1.25
        + usage.cache_read_tokens * rate_in * 0.1
    )


# ─────────────────────────────── Claude ───────────────────────────────

_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    """Claude via the Messages API. Thinking is adaptive on current models; depth is set with
    ``effort``. The SDK retries 408/409/429/5xx with backoff before a :class:`ProviderError`."""

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        refusal_fallback: bool = True,
        max_retries: int = 2,
        http_client: anthropic.DefaultAsyncHttpxClient | None = None,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, base_url=base_url, max_retries=max_retries, http_client=http_client
        )
        self._refusal_fallback = refusal_fallback

    async def complete(
        self, *, task: AITask, config: TaskConfig, prompt: Prompt, schema: Mapping[str, Any]
    ) -> Completion:
        content: list[BetaTextBlockParam] = [{"type": "text", "text": prompt.user}]
        if prompt.feedback:
            content.append({"type": "text", "text": prompt.feedback})
        messages: list[BetaMessageParam] = [{"role": "user", "content": content}]
        client = self._client.with_options(timeout=config.timeout_seconds)
        try:
            response = await client.beta.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": prompt.system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=messages,
                output_config={
                    "effort": config.effort,
                    "format": {
                        "type": "json_schema",
                        "schema": anthropic.transform_schema(dict(schema)),
                    },
                },
                betas=[_FALLBACK_BETA] if self._refusal_fallback else anthropic.omit,
                fallbacks="default" if self._refusal_fallback else anthropic.omit,
            )
        except anthropic.RateLimitError as exc:
            raise ProviderError(
                "rate limited by the AI provider", retryable=True, status=429
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                f"AI provider answered {exc.status_code}",
                retryable=exc.status_code >= 500,
                status=exc.status_code,
            ) from exc
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise ProviderError("AI provider unreachable", retryable=True) from exc
        text = "".join(block.text for block in response.content if block.type == "text")
        usage = response.usage
        return Completion(
            text=text or None,
            stop_reason=response.stop_reason,
            model=response.model,
            usage=Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_input_tokens or 0,
                cache_write_tokens=usage.cache_creation_input_tokens or 0,
            ),
            provider_request_id=getattr(response, "_request_id", None),
        )


# ─────────────────────────────── fake ───────────────────────────────

Responder = Callable[[Prompt], str]
Scripted = str | ProviderError | Literal["refuse"]

_FAKE_SLOTS: tuple[tuple[str, str, int, str], ...] = (
    ("activity", "09:00", 120, "attraction"),
    ("meal", "12:30", 75, "restaurant"),
    ("activity", "15:00", 120, "museum"),
)


def fake_itinerary(prompt: Prompt) -> str:
    """A plausible plan built from the prompt's own context: three slots a day, using catalog
    candidates in order and leaving the rest unverified."""
    context = json.loads(prompt.user)
    trip = context["trip"]
    start = date.fromisoformat(trip["start_date"])
    count = (date.fromisoformat(trip["end_date"]) - start).days + 1
    candidates = [c["id"] for c in context.get("candidates", [])]
    name = context["destination"]["name"]
    days = []
    for index in range(count):
        items = []
        for slot, (kind, at, minutes, category) in enumerate(_FAKE_SLOTS):
            pick = index * len(_FAKE_SLOTS) + slot
            place = candidates[pick] if pick < len(candidates) else None
            items.append(
                {
                    "kind": kind,
                    "title": f"{name}: {'lunch' if kind == 'meal' else 'explore'} ({index + 1})",
                    "description": f"A {trip['pace']} {kind} on {start + timedelta(days=index)}.",
                    "place_id": place,
                    "suggested_start_time": at,
                    "estimated_duration_minutes": minutes,
                    "category": category,
                    "confidence": 0.8 if place else 0.5,
                    "rationale": "Fits the requested pace and interests.",
                    "social_opportunity": False,
                }
            )
        days.append({"day_index": index, "theme": f"Day {index + 1}", "items": items})
    return json.dumps({"days": days, "warnings": [], "confidence": 0.7})


def fake_translation(prompt: Prompt) -> str:
    """Development/test answer: the text, tagged with the target language."""
    payload = json.loads(prompt.user)
    return json.dumps({"text": f"[{payload['target_language']}] {payload['text']}"})


@dataclass
class FakeAIProvider:
    responders: dict[AITask, Responder] = field(
        default_factory=lambda: {
            AITask.ITINERARY_GENERATE: fake_itinerary,
            AITask.POST_TRANSLATE: fake_translation,
        }
    )
    calls: list[Prompt] = field(default_factory=list)
    _script: deque[Scripted] = field(default_factory=deque)

    name = "fake"

    def script(self, *outcomes: Scripted) -> None:
        """Answer the next calls with these outcomes (text, an error to raise, or a refusal)."""
        self._script.extend(outcomes)

    async def complete(
        self, *, task: AITask, config: TaskConfig, prompt: Prompt, schema: Mapping[str, Any]
    ) -> Completion:
        self.calls.append(prompt)
        outcome: Scripted = (
            self._script.popleft() if self._script else self.responders[task](prompt)
        )
        if isinstance(outcome, ProviderError):
            raise outcome
        refused = outcome == "refuse"
        text = None if refused else outcome
        usage = Usage(
            input_tokens=(len(prompt.system) + len(prompt.user) + len(prompt.feedback or "")) // 4,
            output_tokens=len(text or "") // 4,
        )
        return Completion(
            text=text,
            stop_reason="refusal" if refused else "end_turn",
            model="fake",
            usage=usage,
            provider_request_id=f"fake-{len(self.calls)}",
        )
