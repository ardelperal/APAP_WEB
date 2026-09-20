---
name: access-vba-tdd-fundamentos
description: Trigger: pruebas VBA, TDD Access, contrato JSON del runner, manifest de tests de Dysflow, Reglas de oro, contrato del runner JSON, contrato Dysflow, puerta de fixture, esquema-primero, convención de nombres, aislamiento entre tests, estructura de módulo, auditoría pre-compilación, protocolo de firma. Cargar al implementar TDD, helpers testeables, o debatir la forma del test. Patrones de código en references/tdd-patterns.md.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 2.7.0
  last_verified: 2026-09-16
  scope: ['vba', 'runtime']
  auto_invoke: ['running TDD in Access VBA projects']
  tiers: ['vba', 'runtime']
---

# TDD Access VBA — Fundamentos

> **Dysflow tool references.** This skill uses Dysflow tools (schema inspector `get_schema`, drift/verify `verify_code`, etc.) for fixture design and pre-compile audits. Tool names, flag shapes, error codes, and invocation patterns are maintained by `dysflow-usage` — that skill is the canonical source of truth. If a tool is renamed or its signature changes there, this skill's references should be re-aligned in the same change. Inline references below intentionally keep tool names visible for readability; do not duplicate flag shapes, error codes, or argument schemas here — see `dysflow-usage` for those.

Part of `access-vba-tdd-fundamentos`: §0 golden rules + §1 reglas de oro + §2 JSON runner contract. Sandbox /
isolation / safety → `access-vba-tdd-sandbox`; coverage / telemetry → `access-vba-tdd-quality`;
TDD loop / checklist / where tests live → `access-vba-tdd-loop`. Code patterns:
`references/tdd-patterns.md`.

## Activation

A professional test always meets 5 conditions:

1. **`Public Function` returning JSON** `{ok, value, payload, error, logs}` — never `Sub`, never
   `Debug.Print`, never UI.
2. **Seeds its own data** in the sandbox (`m_BackendSandboxURL`) with IDs `>= 900000`. Never
   depends on existing rows.
3. **Schema-first:** before any `INSERT`, it knows which fields are `Required`/`NOT NULL` in the
   real table (ERD or DAO inspection).
4. **Injects the dependency the unit under test actually needs.** For tests of business logic,
   inject a repository interface (use an in-memory fake implementing it). For tests of the
   data boundary (`Obtener*` / `Guardar*` / `Borrar*` / `Listar*` / `Existe*`), inject the
   sandbox `DAO.Database` explicitly via `TestHelper.GetTestDb()`. Passing `Nothing` and
   forcing internal `getdb()` tests the wrong path either way.
5. **Cardinality before/after** any mutation (`countBefore`/`countAfter`), not just "it didn't
   throw".

Violate any of the 5 and it's a hypothesis, not a test. **Refactor-safety:** a test MUST survive
any behavior-preserving refactor; if an innocuous refactor breaks it, the test is the defect.

## Hard Rules

### HR-1 — MUST follow the runner contract (was §1.1)

| Rule | Why | Anti-pattern |
|---|---|---|
| `Public Function Test_X() As String` | COM only captures `String` | `Public Sub` |
| Returns canonical JSON (Output Contract) | Single parseable source of truth | free concat / `Debug.Print` |
| Globally-unique name in Dysflow manifests | `Application.Run` resolves unqualified globals | `Module.Procedure`, `RunAll`, generic names |
| Zero `MsgBox`/`InputBox` | Blocks unattended COM | `MsgBox "ok?"` |
| Zero `Debug.Print` as output | COM can't see it | `Debug.Print "passed"` |
| No `EVE()` in individual tests | Resets TempVars, can switch active backend | `EVE()` in Arrange |

`EVE()` is used only in suite lifecycle (`BeginTestSession`/`EndTestSession`, see sandbox §3.4);
tests whose explicit purpose is to test `EVE()` are the only exception.

**Dysflow discovery (hard rule):** the manifest `procedure` MUST be a global, unique,
argument-less, unqualified `Public Function` (`Test_Cache_RunAll`, `Test_DTM_AllMappedFields`).
Forbidden: `Module.Procedure`, generic `RunAll`, parentheses. Wrap a generic aggregator (see
references). If Dysflow says "procedure not found", first verify the manifest follows this
convention and the exported function exists in the ACCDB — only then suspect tooling. For
current tool name resolution and invocation patterns, see `dysflow-usage` skill.

### HR-2 — MUST enforce the fixture gate before any data test (was §1.2)

Schema verification is the entry point — see `vba-access` SKILL.md §BEFORE WRITING VBA rule #2
(ERD/schema) for the canonical Dysflow schema inspection discipline (tool: `get_schema`, per
`dysflow-usage`). Then design the fixture graph (parents before children; teardown reverse) →
seed explicitly with controlled `INSERT` in the sandbox → never depend on existing rows,
`SELECT TOP 1` without a test filter, user data, or global counts → if you can't seed legally,
inspect the schema, don't improvise. A test green by luck of existing data is invalid.

### HR-3 — MUST verify schema before any INSERT (was §1.3)

Schema-first is the same rule as `vba-access` SKILL.md §BEFORE WRITING VBA rule #2 (ERD/schema)
applied to TDD fixtures. Before any `INSERT`, identify required fields via el tool canónico de
inspección de schema (current: `get_schema`, per `dysflow-usage`) — PK, FKs, `Required`/`NOT
NULL`, types, domain. Omitting a `Required` field yields a cryptic DAO error indistinguishable
from a logic failure. Helper `InspectarCamposObligatorios` in references; full detail:
`access-vba-tdd-sandbox` §5.

### HR-4 — MUST NOT share names between a module and its public function (was §1.6)

A standard module and a public function inside it can NOT share the exact same name (VBE rejects
the call site: "se esperaba una variable o un procedimiento, no un módulo"). Use a distinct module
name: `modPipeFlatten`/`PipeFlatten`, `PipeFlattenHelper`/`PipeFlatten`, or a different CamelCase.
Exception: `TestHelper.bas` legitimately holds `Test_*` functions (module name ≠ functions).

### HR-5 — MUST isolate tests between runs (was §1.7, hard rule)

`SeedAll`/`Seed_X` cover idempotency WITHIN a test, not BETWEEN tests in a shared persistent
sandbox. Rows from prior runs (incl. mid-test crashes) survive; content-filtered tests (`LIKE`,
date ranges) get phantom rows and fail for the wrong reason. Call `EnsureTableClean` (references)
on working tables before each mutating test.

| Table type | Clean before each test? |
|---|---|
| Shared parent graph (`SeedAll`) | **NO** — persistent common base |
| Working table (mutated by tests) | **YES** — each test builds its own rows |
| Config / globals | **YES** — save previous, restore at end |
| Listing / cache tables (mutated via Sync) | **YES** — cache accumulates prior runs |

Ideal solution: a fresh temp `.accdb` per test (sandbox §5.5) — prefer it over `EnsureTableClean`.

### HR-6 — MUST order declarations with Privates before Publics (was §1.8)

Same declaration-ordering rule as [`vba-access` §10.1](../vba-access/SKILL.md). Order in every
`Test_*.bas`: `Attribute VB_Name` + `Option`s → header comment → all `Private Const` → local JSON
wrappers (`BuildOk`/`BuildFail`, references) → other `Private Function` → `Private Sub` fixtures →
`Public Function` atoms (Happy/Sad/Edge/Adversarial). A `Private Const`/`Sub` between two `Public
Function`s causes source↔binary drift and repeated compile errors.

### HR-7 — MUST run pre-compile audit before importing (was §1.9)

| Check | PASS criterion |
|---|---|
| Referenced helpers exist | every called function is defined in source AND binary |
| Call sites match signature | correct types/order per the current signature |
| Declarations at the top | all `Private Const/Sub/Function` before the first `Public Function` |
| No VBA landmines | zero matches (see below) |
| Binary in sync | tool canónico de drift/verify (current: `verify_code`, per `dysflow-usage`) retorna `actionableOk: true`, `actionableDifferent: []` |

**Landmines:** (1) inline comment after `, _` line-continuation → "Syntax error" (the `_` must be
the last non-space char); (2) `Nothing` passed to `ByVal As String` → "invalid object use" (pass
`""` or make the param `Variant`); (3) accented chars shown corrupt (`S?` for `Sí`) are usually a
PowerShell display artifact — check the file bytes (`ó` = `0xC3 0xB3`) before "fixing";
(4) `export_all` writes to disk and can re-export hundreds of files with the binary's cosmetic
normalization (e.g. `Err` → `err`, `riesgo` → `Riesgo`) — use only for explicit binary→source
sync, not as a verification step. For sync validation use el tool de drift/verify (current:
`verify_code`, per `dysflow-usage`); es read-only.

### HR-8 — MUST match atom signatures to helper signatures exactly (was §1.10)

Signature verification is the same rule as `vba-access` SKILL.md §BEFORE WRITING VBA rule #3
(Function signature) applied to TDD atom-vs-helper coupling. When a helper's signature changes
(param type, order, added/removed), update every calling atom in the same change or the binary
compiles but atoms fail at runtime. Change protocol + failure example: `references/tdd-patterns.md`.
Detect drift with el tool de drift canónico (current: `verify_code`, per `dysflow-usage`) en modo
`diff:true`: usar `summaryStructured` para counts, `bulkImportable[]` / `bulkExportable[]` para
planificación de sync, y `classification` + `reason` por entrada para explicar differences
actionable vs non-actionable.

## Decision Gates

| Condición | Acción |
|---|---|
| Cannot seed the fixture legally (Required fields, FK chains, sandbox missing). | Inspect the schema first (tool: `get_schema`, per `dysflow-usage`), redesign the fixture graph, seed in dependency order; do NOT improvise against user data. |
| Table is a shared parent graph seeded by `SeedAll` (e.g. `Config`, `Tipos`). | Do NOT clean before each test — it is the persistent common base. |
| Table is a working table mutated by tests (e.g. `Pedidos`, `Log`). | MUST call `EnsureTableClean` before each mutating test (or use a fresh temp `.accdb` per test — preferred). |
| Table is config / globals (`Parametros`, `Settings`). | MUST save previous state and restore at end; tests mutate in isolation. |
| Table is a listing / cache table mutated via Sync. | MUST clean — the cache accumulates prior runs and produces phantom rows. |
| Refactor-safe assertion: a behavior-preserving refactor breaks the test. | The test is the defect — fix the test (over-coupling to implementation details), not the refactor. |

## Execution Steps

> **Known gap (2026-08-23).** This section is required by the canonical order
> (`Activation → Hard Rules → Decision Gates → Execution Steps → Output Contract`)
> but no procedural content could be promoted into it from the existing skill.
> The 5 numbered conditions in §Activation are test-quality criteria, not a
> procedure; the procedural workflow is currently scattered across
> `HR-2 → HR-3 → HR-5 → HR-7 → HR-8` as in-place guidance. A future revision
> should rewrite those as a single ordered sequence here.

## Output Contract

Return an object with the following keys:

| Key | Type | Description |
|---|---|---|
| `status` | `"success" \| "blocked" \| "failed"` | Outcome of the TDD fundamentals reference. |
| `ok` | boolean | Required boolean — `false` indicates functional failure (not necessarily a COM error). |
| `value` | unknown | Test-defined return value. |
| `payload` | unknown | Test-defined payload (often an array of records). |
| `error` | string \| null | Escaped, useful text when `ok:false`. |
| `logs` | string[] | JSON array of Arrange/Act/Assert trace strings; never sourced from `Debug.Print`. |
| `manifest_procedure` | string | Global, unique, argument-less, unqualified `Public Function` name (e.g. `Test_X_RunAll`). |
| `next_recommended` | `"write_atom" \| "audit_signatures" \| "compile" \| "none"` | Next step. |

Canonical JSON shape: `{ "ok": true, "value": 42, "payload": null, "error": null, "logs": ["1. Arrange…", "2. Act…", "3. Assert…"] }`. `ok` is a required boolean (`ok:false` = functional failure, not necessarily a COM error); `error` is escaped, useful text when `ok:false`; `logs` is a JSON array of strings, never sourced from `Debug.Print`. Build with `BuildJsonOk`/`BuildJsonFail` (canonical implementation in `assets/test-helper-canonical.md`) or `Dictionary` + `JsonConverter` — never JSON inline (see references).

## Anti-patterns

| Symptom | Fix |
|---|---|
| `Public Sub Test_X()` returning nothing | Use `Public Function Test_X() As String` returning canonical JSON `{ok, value, payload, error, logs}`. |
| Test that selects `SELECT TOP 1` from a populated table | Seed the sandbox with IDs `>= 900000` in Arrange; never depend on existing rows. |
| Test that omits `countBefore`/`countAfter` on a mutation | Assert cardinality before/after every mutating call; "didn't throw" is not coverage. |
| Production `m_TestingMode = False` reached during a test run | Confirm `getdb()` branches on `m_TestingMode` and the sandbox URL is correct before declaring ready to import. |

## Companion references

- `dysflow-usage` — canonical source for current Dysflow tool names, flag shapes, error codes, and invocation patterns.
- `dysflow-arnes` — operating harness for Dysflow; bootstrap, schema, capabilities.
- `assets/test-helper-canonical.md` — canonical JSON helpers and test-session primitives.
- `assets/interface-seams.md` — `Implements` seams for logic tests and sandbox boundaries for DAO tests.
- `../access-vba-tdd-loop/assets/tdd-loop.md` — executable TDD workflow and runner calls.
