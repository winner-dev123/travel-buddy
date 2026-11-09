# ADR-0001: Modular monolith with enforced module boundaries

- **Status:** Accepted
- **Date:** 2026-11-09
- **Requirements:** NFR-005, NFR-012

## Context
The platform has 20 domains, but the team is small and the traffic is unknown. Microservices from day one would add network failure modes, distributed transactions, and deployment and observability overhead before there is any scale need. A plain monolith tends to decay into a tangle that can never be split.

## Decision
Build one backend codebase (`backend/app`) organized as domain modules (`app/modules/<domain>`). It deploys as several **process roles** (api, realtime, worker, scheduler) from the same image.

* Each module exposes a public `service.py` (application interface) and `events.py`. Its `models.py`, `repository.py` and `domain.py` are private.
* Cross-module reactions go through domain events via the transactional outbox ([ADR-0004](0004-postgres-outbox-and-job-queue.md)).
* An AST-based architecture test in CI (`backend/tests/unit/test_architecture_boundaries.py`) enforces the layering and "no private imports" rules. import-linter was considered, but it cannot express "public submodules only".
* Each module owns its tables. No module writes to another module's tables. Cross-module reads go through services (for joins on hot paths, a module may expose a read-only SQL view as part of its public interface).

## Consequences
* Local transactions stay simple (one database), and refactoring is cheap.
* A module can be extracted into a service later by replacing its service facade with a client. Events already flow through the outbox.
* Engineers must respect the boundaries, and CI enforces them.

## Alternatives considered
* **Microservices per domain**: rejected for now (cost, latency, team size).
* **Unstructured monolith**: rejected (boundary decay, hard extraction).
