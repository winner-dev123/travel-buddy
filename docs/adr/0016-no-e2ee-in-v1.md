# ADR-0016: No end-to-end encryption for messages in v1

- **Status:** Accepted
- **Date:** 2026-11-09
- **Requirements:** DM-013

## Context
The master prompt states E2EE is not assumed initially and requires a separate threat model and key-management specification if introduced. The platform also needs report-based moderation of messages between strangers.

## Decision
Messages are encrypted in transit (TLS) and at rest (storage encryption), and are readable by the service. Moderators see message content **only** through report evidence snapshots. Users are told plainly in the privacy policy.

## Consequences
Moderation and multi-device sync are simpler. A future E2EE ADR must address key management, multi-device, backups, reporting (message franking), and group key rotation.
