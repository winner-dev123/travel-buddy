# Contracts

This folder holds the **normative, contract-first** interface definitions for Travel Buddy. Code conforms to the contracts, not the other way round ([ADR-0002](../docs/adr/)).

| Path | What | Human-readable companion |
|---|---|---|
| [`openapi/openapi.yaml`](openapi/openapi.yaml) | REST API, OpenAPI **3.1** (217 operations, phases 0–7) | [docs/05 — REST API specification](../docs/05-rest-api-specification.md) |
| [`realtime/envelope.schema.json`](realtime/envelope.schema.json) | Realtime frame envelope and shared `$defs` (JSON Schema **2020-12**) | [docs/06 — Realtime messaging protocol](../docs/06-realtime-messaging-protocol.md) |
| `realtime/client.<type>.schema.json` | One schema per client → server frame (10) | docs/06 §4.1 |
| `realtime/server.<type>.schema.json` | One schema per server → client frame (18) | docs/06 §4.2 |
| [`realtime/catalog.json`](realtime/catalog.json) | Machine-readable list of frame types per direction | — |

## Rules

1. **Change the contract first.** A feature PR that adds or changes an endpoint or frame edits the files here in the same PR, before or alongside the implementation. Reviewers check the contract diff first.
2. **The contract wins.** If a doc and the contract disagree, fix the doc. If the implementation and the contract disagree, CI fails.
3. **Additive by default.** Breaking changes need `/v2` and an ADR (docs/05 §9). CI runs a breaking-change diff against `main`.
4. **Traceability.** Every operation carries `x-phase` and `x-requirements` (PRD IDs). Requirement IDs connect PRD → contract → code → tests.
5. **Privacy is part of the contract.** Schemas for *other users* (`PublicProfile`, `UserSummary`, `TravelerCard`, `GroupMember` …) must never contain coordinates, distances, email, birth data, phone, IP or session identifiers, including through `$ref`s. Device positions appear only as write-only request inputs (`near`, `InputGeoPoint`), and coordinates appear only for public places (`GeoPoint`).
6. **Secrets never in responses.** Challenge answers are write-only (`accepted_answers`) and readable only via the judge-only audited endpoint. Reward secrets appear only in `MyReward`. Invitation tokens are returned once.

## How the contracts are consumed

### Backend (FastAPI)

* `backend/tests/contract/test_openapi_contract.py` runs in CI and asserts that:
  * `openapi.yaml` is a valid OpenAPI 3.1 document (`openapi-spec-validator`);
  * every route the FastAPI app implements (method + path) **exists in the contract**, so implemented routes are a subset of the contract and unimplemented phases are fine;
  * every `realtime/*.schema.json` is a valid JSON Schema 2020-12 document;
  * person schemas never expose location or private identity fields (rule 5).
* Planned additions as modules land:
  * response validation in API tests: responses from the test client are validated against the operation's response schema;
  * realtime contract tests: frames emitted by the gateway in tests are validated against `realtime/*.schema.json`, and `envelope.schema.json#/$defs/Message` must match the OpenAPI `Message` property for property;
  * a lint asserting that member-facing challenge schemas contain no answer fields, and that `ErrorCode` does not include the reserved client-only codes.

### Mobile and web (TypeScript)

TypeScript types are **generated, never hand-written**, with [`openapi-typescript`](https://github.com/openapi-ts/openapi-typescript):

```bash
npx openapi-typescript contracts/openapi/openapi.yaml --default-non-nullable false -o <app>/src/api/schema.d.ts
```

Always pass `--default-non-nullable false`. By default openapi-typescript marks every property that has a `default` as required, which makes request fields such as `LogoutRequest.all_sessions` mandatory and breaks requests. Web (`npm run gen:types` in `packages/domain-types`) and mobile must generate the same way.

* Use them with a typed fetch client (e.g. `openapi-fetch`), so paths, parameters, bodies and responses are checked at compile time.
* CI regenerates the file and fails if the committed output differs (`git diff --exit-code`).
* Realtime frame types are generated from `realtime/*.schema.json` with `json-schema-to-typescript` into `<app>/src/realtime/frames.d.ts`, with the same drift check.
* Clients must tolerate unknown response fields and unknown enum values (docs/05 §9).

### Validating locally

```bash
python -m venv .venv-contracts && .venv-contracts/bin/pip install openapi-spec-validator jsonschema pyyaml
.venv-contracts/bin/python -c "import yaml; from openapi_spec_validator import validate; validate(yaml.safe_load(open('contracts/openapi/openapi.yaml', encoding='utf-8'))); print('OpenAPI OK')"
.venv-contracts/bin/python -c "import json, glob; from jsonschema import Draft202012Validator as V; [V.check_schema(json.load(open(f, encoding='utf-8'))) for f in glob.glob('contracts/realtime/*.schema.json')]; print('realtime OK')"
```

Or, from `backend/`: `python -m pytest tests/contract -q`.

### Tooling (`contracts/tools/`)

Run these with the backend venv (they need `pyyaml`, `jsonschema` and `openapi-spec-validator`):

| Script | Purpose |
|---|---|
| `lint_oas.py contracts/openapi/openapi.yaml` | Spec validation, plus unresolved refs, missing `x-phase`/`x-requirements`/`x-rate-limit-class`, `Idempotency-Key` ↔ `x-idempotency` consistency, `If-Match` → 412/428, duplicate operationIds, and privacy and answer-leak lints |
| `gen_realtime.py contracts/realtime` | **Generates** `realtime/*.schema.json` and `catalog.json`. Edit the generator, not the JSON output |
| `validate_realtime.py contracts/realtime` | Metaschema check, plus sample valid and invalid frames |
| `gen_resource_map.py contracts/openapi/openapi.yaml` | Prints the endpoint tables for docs/05 §3 (paste over the existing tables) |

Requirement IDs in `x-requirements` must exist in the PRD. `python scripts/trace_requirements.py` fails on unknown IDs and shows contract coverage per requirement.

## Conventions inside `openapi.yaml`

| Extension | Meaning |
|---|---|
| `x-phase` | Delivery phase (0–7) from the phased plan |
| `x-requirements` | PRD requirement IDs the operation implements |
| `x-rate-limit-class` | Rate-limit class (docs/05 §5) |
| `x-idempotency: required` | `Idempotency-Key` header required |
| `x-entitlement` | Billing feature key checked server-side (docs/07) |
| `x-platform-permission` | Platform RBAC permission for admin operations |
| `x-dev-only: true` | Exists only when `APP_ENV ∈ {development, test}`. 404 elsewhere |
| `x-reserved-codes` (on `ErrorCode`) | Client-only error codes the backend never emits |

Nullable fields use `type: [T, 'null']`, or `anyOf: [{$ref}, {type: 'null'}]` for references. Request bodies set `additionalProperties: false`.
