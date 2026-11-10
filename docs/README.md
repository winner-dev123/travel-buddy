# Documentation index

Phase 0 engineering artifacts (master prompt §26), all at **v1.0 draft for approval**.

| # | Artifact | Document |
|---|---|---|
| 1 | Product Requirements Document (requirement IDs) | [01-prd.md](01-prd.md) |
| 2 | System architecture | [02-system-architecture.md](02-system-architecture.md) |
| 3 | Mobile navigation and screen inventory | [03-mobile-navigation-and-screens.md](03-mobile-navigation-and-screens.md) |
| 4 | Database ERD, indexes, retention | [04-database-erd.md](04-database-erd.md) |
| 5 | REST API specification | [05-rest-api-specification.md](05-rest-api-specification.md) + [contracts/openapi/openapi.yaml](../contracts/openapi/openapi.yaml) |
| 6 | Realtime messaging protocol | [06-realtime-messaging-protocol.md](06-realtime-messaging-protocol.md) + [contracts/realtime/](../contracts/realtime/) |
| 7 | Subscription and entitlement policy | [07-subscription-entitlement-policy.md](07-subscription-entitlement-policy.md) |
| 8 | Privacy and security threat model | [08-privacy-security-threat-model.md](08-privacy-security-threat-model.md) |
| 9 | Development backlog with dependencies | [09-development-backlog.md](09-development-backlog.md) |
| 10 | Test strategy | [10-test-strategy.md](10-test-strategy.md) |
| 11 | Infrastructure and deployment plan | [11-infrastructure-deployment.md](11-infrastructure-deployment.md) |
| 12 | Initial repository structure | [12-repository-structure.md](12-repository-structure.md) |
| 13 | DPIA: traveler discovery (draft for review) | [13-dpia-traveler-discovery.md](13-dpia-traveler-discovery.md) |
| 14 | App Store and Google Play readiness | [14-store-readiness.md](14-store-readiness.md) |
| 15 | Records of processing activities (GDPR Art. 30, draft) | [15-records-of-processing.md](15-records-of-processing.md) |
| — | Architecture decision records | [adr/](adr/README.md) |
| — | Web application (web workstream) | [web/](web/01-architecture.md) |

## Change process (master prompt §27)

When a requirement arrives or changes:

1. Add or update PRD rows. New IDs are never reused, and superseded rows are struck through with a pointer to their replacement. Add a version-history line.
2. Identify impacted modules ([architecture §4.2](02-system-architecture.md#42-domain-modules)).
3. Update the contract (`contracts/`), the ERD and the migrations plan.
4. Re-check the threat model and the entitlement policy.
5. Add backlog items with dependencies and acceptance tests.
6. Record significant decisions as ADRs.
