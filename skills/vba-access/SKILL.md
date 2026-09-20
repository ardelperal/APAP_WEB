---
name: vba-access
description: Trigger: write or review Access VBA, DAO repositories, form code, VBA signatures, error handling, source and binary separation. Defines mandatory Access VBA authoring and review rules with verifiable runtime boundaries.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 2.0.0
  last_verified: 2026-08-28
  scope: ['vba', 'runtime']
  auto_invoke: ['writing Access VBA code', 'reviewing Access VBA code']
  tiers: ['vba', 'runtime']
---



## §1 Activation

Load before writing or reviewing `.bas`, `.cls`, form code-behind, DAO access, API declarations, or public VBA signatures. Use `references/vba-patterns.md` and `examples/` for code depth; use companion skills and live runtime discovery for Dysflow operations.

## §2 Hard Rules

- **HR-1** — Place `Option Compare Database` and `Option Explicit` at the top of every module, class, and form code-behind.
- **HR-2** — Declare one variable per line with the narrowest correct explicit type.
- **HR-3** — Use `Long` for identifiers, counters, row counts, and 32-bit integral API values unless a different type is evidenced.
- **HR-4** — Verify public members, parameters, `ByVal`/`ByRef`, and return types before adding or changing a call site.
- **HR-5** — Verify every referenced table and column against the live target schema before writing SQL.
- **HR-6** — Use DAO by default for native Access/ACE data access and justify any alternative explicitly.
- **HR-7** — Parameterize `QueryDef` input and never concatenate untrusted values into SQL.
- **HR-8** — Handle errors with a scoped `On Error GoTo` path, deterministic cleanup, and contextual propagation.
- **HR-9** — Restrict `On Error Resume Next` to the smallest expected-failure block and inspect `Err` immediately.
- **HR-10** — Keep forms thin, domain/workflow logic in classes, and persistence logic in DAO modules.
- **HR-11** — Keep module-level declarations before the first procedure and avoid hidden shared state.
- **HR-12** — Treat `.cls` as behavior source and `.form.txt` as UI/layout source; never edit serialized behavior in `.form.txt`.
- **HR-13** — Route source/binary operations through Dysflow
  runtime guidance (`dysflow.import_modules { moduleNames: [...],
  apply: true }` + `dysflow.export_modules { moduleNames: [...],
  exportPath: <safe>, mutateBinary: false }`) instead of
  duplicating operational flags here. `vba-binary-sync` y
  `dysflow.sync` son legacy; ver la skill `vba-workflow` Gate 2
  para el flujo canonico.

## §3 Decision Gates

| Condition | Action |
|---|---|
| A class member or cross-module procedure is referenced | Verify its exact signature with CodeGraph or targeted source evidence. |
| SQL references a table or column | Query the live schema before authoring or approving the SQL. |
| Native Access data is accessed | Use typed DAO objects and deterministic cleanup. |
| User-controlled data enters SQL | Use a parameterized `QueryDef`; block concatenation. |
| Long Text exceeds reliable parameter handling | Use an editable DAO recordset with explicit field assignment. |
| Repeated object access is substantial | Use a bounded `With` block; otherwise keep direct access. |
| Form behavior changes | Edit the `.cls` and follow source/binary synchronization. |
| Form layout or properties change | Edit the `.form.txt` through the supported form workflow and keep code-behind separate. |
| External API pointers or handles are declared | Use `PtrSafe`, `LongPtr`, and conditional compilation appropriate to supported bitness. |

## §4 Execution Steps

1. Use CodeGraph to inspect affected symbols, callers, signatures, and blast radius.
2. Query the live Access schema for every table and column used by changed SQL.
3. Confirm filesystem/config dependencies instead of hardcoding paths.
4. Author explicit declarations, typed DAO objects, parameterized SQL, and scoped error handling.
5. Keep UI orchestration, domain logic, and persistence in their respective boundaries.
6. Audit VBA parser hazards: non-short-circuit boolean expressions, declaration order, continuation syntax, and identifier validity.
7. Separate behavior changes in `.cls` from UI/layout changes in `.form.txt`.
8. Delegate source/binary synchronization and human compilation gates to companion skills/runtime.
9. Return every Output Contract key, including empty arrays and null values.

## §5 Output Contract

| Key | Type | Description |
|---|---|---|
| `status` | `"success" \| "blocked" \| "failed"` | Authoring or review result. |
| `files_reviewed` | `string[]` | VBA/UI files inspected; empty when none. |
| `files_changed` | `string[]` | VBA/UI files changed; empty when none. |
| `signature_evidence` | `object[]` | Verified public signatures and call sites. |
| `schema_evidence` | `object[]` | Verified tables, columns, and types. |
| `dao_findings` | `string[]` | DAO resource, query, or transaction findings. |
| `error_handling_findings` | `string[]` | Error-path and cleanup findings. |
| `source_binary_state` | `"unchanged" \| "sync-required" \| "verified" \| "unknown"` | Separation/synchronization state. |
| `blocked_reasons` | `string[]` | Blocking reasons; empty on success. |
| `next_recommended` | `string` | Next action, or `"none"`. |
| `risks` | `string[]` | Remaining risks; empty when none. |

## Anti-patterns

| Symptom | Fix |
|---|---|
| A public call is authored from memory | Verify the exact signature and update every caller consistently. |
| SQL assumes sibling tables share columns | Query each live table schema independently. |
| `Dim first, second As Long` is treated as two `Long` values | Declare one variable per line with an explicit type. |
| An object null-check and member access share one boolean expression | Split the checks because VBA does not short-circuit. |
| Dysflow flags or tool inventories are copied into this skill | Reference `dysflow-usage`, `vba-binary-sync`, and live runtime discovery. |

## Procedencia y fuente canonica

Esta skill enuncia **reglas de autoria y revision** para codigo
VBA. Las **reglas invariantes** del entorno (forma desacoplada,
datos y SQL, disciplina TDD, manejo de errores, antipatrones) viven
como fuente canonica en:

```
C:\Users\adm1\personal-skills\slices\partials\vba-access.md
```

Cuando una regla de esta skill entra en conflicto con una regla
del partial, **el partial gana**: es la fuente canonica de
invariantes y esta skill lo refleja. Si descubre una contradiccion
no documentada, anada una entrada al partial primero y luego
actualice esta skill para que apunte al partial en lugar de
duplicar la regla.

Las reglas de **workflow procedural** (cuando invocar dysflow,
como usar `dysflow.import_modules`, que triggers del `auto_invoke`
cargan esta skill, etc.) viven en la skill canonica del workflow:

```
C:\Users\adm1\personal-skills\skills\vba-workflow\SKILL.md
```

Esa skill tiene los gates (1: antes de tocar, 2: al modificar,
3: al correr tests), las hard rules y las plantillas de codigo
VBA. Si esta skill (`vba-access`) describe **que** debe cumplir
el codigo, `vba-workflow` describe **como** lo cumple usted en
el dia a dia.

## References

- `references/vba-patterns.md` (en este mismo skill) — patrones
  de codigo Access/VBA con profundidad mayor que esta skill.
- `C:\Users\adm1\personal-skills\skills\vba-workflow\SKILL.md`
  — workflow procedural con gates, dysflow imports/exports,
  plantillas de propagacion de errores.
- `C:\Users\adm1\personal-skills\slices\partials\vba-access.md`
  — invariantes del entorno VBA/Access; fuente canonica para
  reglas durables.
- `dysflow-usage` — fuente canonica de los nombres de tools,
  flags y codigos de error del binario Dysflow.
- `access-vba-tdd-fundamentos`, `access-vba-tdd-loop`,
  `access-vba-tdd-quality`, `access-vba-tdd-sandbox`,
  `access-vba-capability-docs`, `access-vba-e2e-methodology`
  — skills especificas del ciclo TDD, runner contract, sandbox,
  fixtures y planes E2E.
