# Generated API types

This folder will hold TypeScript types **generated** from the contract-first
OpenAPI document at [`contracts/openapi/openapi.yaml`](../../../../contracts/openapi/openapi.yaml).
Do not hand-write request/response schemas here.

Planned generation (added once the contract stabilises in Phase 1):

```sh
npx openapi-typescript ../contracts/openapi/openapi.yaml --default-non-nullable false -o src/api/generated/schema.ts
```

- The generated file is committed so the app builds without the contract
  toolchain. CI regenerates it and fails on a diff, which keeps the client in
  sync with the contract.
- Feature code imports `components['schemas']['…']` / `paths['…']` types from
  `schema.ts` and passes them as type parameters to `ApiClient` (`src/api/client.ts`).
- The hand-written parts of `src/api/` are transport concerns only: headers,
  problem+json parsing and pagination envelopes.
