# ADR-0007: UUIDv7 keys, text+CHECK enums, UTC timestamps

- **Status:** Accepted
- **Date:** 2026-11-09

## Decision
* **UUIDv7** primary keys generated in the application (`app/core/ids.py`). They are time-ordered (good B-tree locality, a natural sort for outbox and messages), non-enumerable in public APIs, and generated without a DB round trip.
* **Enums as `text` + `CHECK`** constraints mirrored by Python `StrEnum`. Adding a value is a fast constraint swap, avoiding `ALTER TYPE` limitations inside transactions.
* **`timestamptz` in UTC**. Calendar dates are stored as `date` and interpreted in the destination's IANA time zone.
* Constraint and index naming conventions are defined in the SQLAlchemy `MetaData(naming_convention=...)`, so Alembic autogenerate produces stable names.

## Consequences
UUIDs are 16 bytes compared with 8 for bigint. The cost is acceptable. UUIDv7 leaks creation time, which is acceptable for our entities (messages and posts show timestamps anyway). Invitation tokens and realtime tickets are **not** UUIDs: they are 256-bit random values stored hashed.
