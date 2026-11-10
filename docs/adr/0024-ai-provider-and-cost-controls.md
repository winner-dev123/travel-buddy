# ADR-0024: AI provider port, Claude adapter and cost controls

- **Status:** Accepted
- **Date:** 2026-11-10
- **Deciders:** Backend
- **Requirements:** AI-001, AI-002, AI-004, AI-008, AI-009, NFR-015

## Context

Phase 4 adds AI itinerary generation (and later replanning, assistant chat, challenge judging and post
translation). The PRD asks for provider independence where swapping providers needs configuration only
(AI-001). It also asks for schema-validated output that never reaches the client invalid (AI-002), no
generated opening hours, prices, availability or safety claims (AI-004), data minimization (AI-008), and
cost controls: per-user quotas, a global spend circuit breaker and per-call telemetry (AI-009).

The backend runs on serverless hosting (ADR-0019) with durable jobs and a cron or inline tick (ADR-0004),
so a provider call (30 s to a few minutes) cannot run inside the request.

## Decision

1. **Port.** `ai_assistant.provider.AIProvider.complete(task, config, prompt, schema) -> Completion`
   returns the structured text plus token usage. Validation, the repair retry, quotas, breakers and
   telemetry live in the service, so every adapter follows the same rules. Each task has its own
   configuration (model, max tokens, effort, timeout).
2. **Adapters.**
   - `AnthropicProvider` uses the official `anthropic` Python SDK and Claude (default model
     `claude-opus-5-5`, effort `medium`). It sends structured outputs (`output_config.format` with the
     draft's JSON schema), a fixed system prompt marked for prompt caching, and the server-side refusal
     fallback (`fallbacks: "default"`, which can be turned off with `AI_REFUSAL_FALLBACK=false` for
     proxies). Thinking is adaptive, the model's default.
   - `FakeAIProvider` gives deterministic, offline answers for development and tests, and tests can
     script failures. The settings guard refuses it outside development and test.
   - With no key in staging or production, the provider is `None` and requests answer
     `503 ai_unavailable`.
3. **Asynchronous lifecycle.** `POST /v1/ai/itineraries/generate` stores a `pending` generation and an
   outbox event, then returns `202` with `Location`. The event's job calls the provider outside any
   database transaction and validates the output in three steps: Pydantic, semantic checks (one day per
   date, place IDs from the candidate set, no overlaps), and one repair retry with the failed checks as
   feedback. It then stores the validated proposal or a typed error (`ai_output_invalid`,
   `ai_unavailable`) and records `ai.generation_completed`, which becomes an `ai_generation_ready`
   notification. Clients poll `GET /v1/ai/generations/{id}`. A generation still pending after
   30 minutes fails when read, and after a day in the retention purge.
4. **The output schema is the guardrail (AI-004).** The model fills `ItineraryDraft`, which has no
   fields for hours, prices, tickets, availability, transit or safety. The server joins dates,
   destination, time zone, attribution and (from BL-4.01) licensed place data, and marks any activity
   without a catalog place as `unverified`.
5. **Data minimization (AI-008).** The context builder takes typed trip parameters only. `params` is
   cleared once a generation finishes. Telemetry stores tokens, cost, latency, model, prompt version,
   attempts and validation-error locations, never the prompt or the raw response. Proposals are kept
   for 30 days and telemetry for 13 months.
6. **Cost controls (AI-009).**
   - Quotas count this month's `pending` and `succeeded` generations through the entitlement
     evaluator (failed ones are free). A per-user advisory lock serializes the check.
   - Two breakers read `ai_generations`, so every serverless instance shares their state. The spend
     breaker trips when today's summed `cost_micros` reaches `AI_DAILY_BUDGET_USD`. The provider breaker
     trips when the last `AI_BREAKER_FAILURES` completions within `AI_BREAKER_COOLDOWN_SECONDS` all
     failed.
   - Cost is computed from a per-model price table (USD per million tokens), with cache writes at
     1.25x and cache reads at 0.1x the input rate. Unknown models are charged at the highest known
     rate.

## Consequences

- Changing models or providers needs configuration (and, for a new vendor, one adapter class) only.
- Generation latency depends on the job runner. A worker or an inline tick after the response
  (`JOBS_INLINE_AFTER_RESPONSE=true`, with a function duration long enough for one provider call)
  starts it at once. A daily cron alone is not enough for AI features.
- The spend breaker is per UTC day and approximate: generations accepted before it trips still finish.
- `ANTHROPIC_API_KEY` becomes a production secret, and spend should also be capped in the Anthropic
  console.

## Alternatives considered

- **Raw HTTP instead of the SDK:** rejected. The SDK brings typed errors, retries with backoff,
  timeouts and schema transformation for structured outputs.
- **Synchronous generation in the request:** rejected because of serverless timeouts and client
  retries that would bill twice.
- **In-memory circuit breaker:** rejected because serverless instances would not share state. The
  database already holds the telemetry the breakers need.
- **Storing prompts for debugging:** deferred. An opt-in `ai_generation_payloads` table with a 30-day
  TTL (docs/04) can be added and stays off in production.
