# ADR-0004: Transactional outbox and Postgres-backed job queue

- **Status:** Accepted
- **Date:** 2026-11-09

## Context
Notifications, media processing, fanout, indexing and analytics must be asynchronous and **durable**. Publishing to a broker after a DB commit can lose events (crash between commit and publish), and publishing before commit can emit events for rolled-back work.

## Decision
* Domain changes write `outbox_events` in the same transaction. A relay process publishes them (Redis fanout for realtime, job enqueue for consumers) and marks them published.
* The `asynchronous_jobs` table is the initial durable queue (`FOR UPDATE SKIP LOCKED`, retries with backoff, dead-letter, dedupe keys), behind a `JobQueue` port.
* Consumers are idempotent (keyed by event ID / dedupe key).

## Consequences
* There is no extra infrastructure at launch, and enqueueing is transactional.
* Postgres carries queue load. Expected to be fine up to roughly hundreds of jobs per second. Beyond that, swap the adapter for SQS, RabbitMQ or Kafka without changing producers.
* The relay adds small latency (poll interval 100–250 ms, or LISTEN/NOTIFY wake-ups).

## Alternatives considered
* **Celery + Redis broker**: Redis isn't durable by default, and enqueue isn't transactional.
* **Kafka from day one**: operational cost not justified.
* **procrastinate** (a Postgres queue library): viable. Kept as an implementation option for the port.
