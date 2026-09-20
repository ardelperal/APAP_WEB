---
name: access-vba-tdd-sandbox
description: Trigger: Access test sandbox, test data isolation, fixture lifecycle, injectable database, production safety. Defines mandatory sandbox routing and deterministic isolation for Access VBA tests.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 3.0.0
  last_verified: 2026-08-28
  scope: ['vba', 'runtime']
  auto_invoke: ['running tests in Access VBA sandbox']
  tiers: ['vba', 'runtime']
---



## §1 Activation

Load when configuring Access test data, selecting a DAO database in tests, designing fixtures, or diagnosing cross-test contamination. Combine with `access-vba-tdd-fundamentos`, `access-vba-tdd-loop`, and `access-vba-tdd-quality` as required.

## §2 Hard Rules

- **HR-1** — Block every test write until the sandbox identity and path are verified as non-production.
- **HR-2** — Use `CurrentDb` only for tables physically local to the frontend.
- **HR-3** — Access linked tables through their current frontend binding; never assume the source backend can be opened directly.
- **HR-4** — Access backend or sandbox business tables through an injectable project helper such as `getdb` or its project equivalent.
- **HR-5** — Route the injectable helper to sandbox in test mode and never to production.
- **HR-6** — Invalidate cached database handles when entering or leaving test mode.
- **HR-7** — Verify sandbox availability before setting test mode or seeding data.
- **HR-8** — Stop with `TESTS BLOCKED` when sandbox verification fails.
- **HR-9** — Inject `DAO.Database` explicitly into repositories and services under test where isolation is required.
- **HR-10** — Seed deterministic fixtures with reserved test identifiers and explicit dependencies.
- **HR-11** — Delete only rows owned by the current fixture or reserved test range.
- **HR-12** — Teardown per-test state and suite state even after failures.
- **HR-13** — Prove isolation with cardinality or location assertions against the same injected database.

## §3 Decision Gates

| Condition | Action |
|---|---|
| Table is physically local to the frontend | Use `CurrentDb`. |
| Table is linked in the frontend | Use the current linked-table binding; do not infer or bypass its source. |
| Table is a backend/sandbox business table | Use an injectable `getdb`-equivalent configured for sandbox. |
| Test verifies dependency injection itself | Inject a separate temporary database and assert no write reached the sandbox. |
| Sandbox path is missing, unreachable, ambiguous, or production-like | Return `TESTS BLOCKED`; perform no data mutation. |
| Fixture can be rolled back safely | Use a DAO transaction and rollback. |
| Fixture requires committed state | Use guarded seed/teardown with reserved identifiers. |
| Teardown cannot prove ownership of rows | Block deletion and report the fixture defect. |

## §4 Execution Steps

1. Identify every table as frontend-local, linked, or backend/sandbox business data.
2. Select the database path from the matrix in §3; do not mix categories.
3. Verify the sandbox identity, path, accessibility, and non-production fingerprints.
4. Enter test mode, invalidate caches, and open the injectable sandbox database.
5. Seed parent-first deterministic fixtures using reserved identifiers.
6. Inject the selected `DAO.Database` into the code under test where supported.
7. Assert behavior, cardinality, and the physical database that received each mutation.
8. Teardown child-first fixture rows, close handles, clear temporary state, and leave test mode.
9. Apply the complete lifecycle, reset, production-blocking, and temporary-database recipe in `references/test-session-safety.md`.
10. Return every Output Contract key, including empty arrays and null values.

## §5 Output Contract

| Key | Type | Description |
|---|---|---|
| `status` | `"success" \| "blocked" \| "failed"` | Overall sandbox operation result. |
| `sandbox_verified` | `boolean` | Whether the sandbox passed all safety checks. |
| `table_routing` | `object[]` | Per-table classification and selected access path. |
| `database_helper` | `string \| null` | Injectable project helper used for business data. |
| `fixtures_seeded` | `string[]` | Fixture identifiers seeded; empty when none. |
| `fixtures_removed` | `string[]` | Fixture identifiers removed; empty when none. |
| `isolation_assertions` | `object[]` | Cardinality/location assertions; empty when none. |
| `production_writes` | `number` | Must remain zero. |
| `blocked_reasons` | `string[]` | Blocking safety reasons; empty on success. |
| `next_recommended` | `string` | Next action, or `"none"`. |
| `risks` | `string[]` | Remaining isolation risks; empty when none. |

## Anti-patterns

| Symptom | Fix |
|---|---|
| `CurrentDb` is used for every table category | Classify the table and apply the routing matrix. |
| A linked table is bypassed by guessing its source database | Respect the current binding unless the test explicitly owns an injectable backend helper. |
| Test mode reuses a cached production handle | Invalidate caches before opening the sandbox. |
| Fixture cleanup uses an unbounded delete | Restrict deletion to owned identifiers or rollback the transaction. |

## Companion references

- `references/test-session-safety.md` — session lifecycle, complete reset contract, six production checks, and isolated `.accdb` proof.
