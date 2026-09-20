---
name: access-vba-tdd-loop
description: Trigger: implementar feature nueva con TDD, escribir el primer test, ejecutar runner, abrir PR con tests, manifest de dysflow. Contiene §8 (TDD Loop para la IA), §9 (Checklist Legacy), §8.3 (dónde van los tests). Load cuando se arranca un fix o feature nueva, o se debate manifests vs allowlist.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 2.8.0
  last_verified: 2026-09-16
  scope: ['vba', 'runtime']
  auto_invoke: ['running the Access VBA TDD cycle']
  tiers: ['vba', 'runtime']
---

# TDD Access VBA — TDD Loop y Checklist

> **Dysflow tool references.** This skill uses Dysflow tools (`test_vba`, `import_modules`, `verify_code`, `list_access_operations`, `cleanup_access_operation`, etc.). Tool names, flag shapes, error codes, and invocation patterns are maintained by `dysflow-usage` — that skill is the canonical source of truth. If a tool is renamed or its signature changes there, this skill's references should be re-aligned in the same change. Inline references below intentionally keep tool names visible for readability; do not duplicate flag shapes, error codes, or argument schemas here — see `dysflow-usage` for those.

## Activation

Cargue esta skill cuando se vaya a:

- Implementar una feature nueva con TDD (red → green → refactor) sobre un módulo VBA existente.
- Escribir el primer test atómico antes del código de producción.
- Ejecutar el runner de tests VBA (tool canónico de test runner: `test_vba`, per `dysflow-usage`) contra el binario Access.
- Decidir dónde van los tests (manifests `tests/*.json` vs allowlist en `.dysflow/project.json`).
- Auditar una suite legacy contra el checklist de migración v2.5.

**Do NOT load when:**

- La duda es de fundamentos del runner JSON, contrato Dysflow, pre-compile audit o landmines → ver `access-vba-tdd-fundamentos`.
- La duda es de sandbox, `m_BackendSandboxURL`, fixtures o seguridad → ver `access-vba-tdd-sandbox`.
- La duda es de cobertura, cardinalidad o pirámide de tests → ver `access-vba-tdd-quality`.

Skills padre / hermanas: `access-vba-tdd-fundamentos`, `access-vba-tdd-sandbox`, `access-vba-tdd-quality`.

---

## Hard Rules

> Promovido de §9 Checklist Legacy + §8.2 Nuncas + §8.3 REGLA DURA. Cada HR arranca con verbo observable.

- **HR-1 — Declarar `m_TestingMode` en `Variables Globales.bas`.** No resetear en `ResetGlobals`.
- **HR-2 — Modificar `getdb()` con branch `If m_TestingMode Then ...`.** Toda ruta de lectura de BD debe pasar por ese branch.
- **HR-3 — Implementar `BeginTestSession` / `EndTestSession` / `ResetTestSession` con nomenclatura canónica.** No usar nombres como `SetupTest` o variantes locales.
- **HR-4 — Llamar `Test_EVE(True)` en `BeginTestSession` y `Test_EVE(False)` en `EndTestSession`.** El flip de flag es contractual, no decorativo.
- **HR-5 — Endurecer el pre-check de sandbox**: rechazar UNC, validar fingerprint, ejecutar FSO + DAO check antes de tocar el backend.
- **HR-6 — Hacer que `ResetTestSession` limpie exhaustivamente**: flags, sandbox URL, password, TempVars, caches. Un subset suelto es contract violation.
- **HR-7 — Prohibir `EVE()` o `SetTestBackend` dentro de tests individuales.** Toda conmutación de entorno vive en `BeginTestSession`/`EndTestSession`.
- **HR-8 — Limitar fixture IDs al rango `900000+` y filtrar `DELETE`, nunca global.** DELETE global es contract violation.
- **HR-9 — Medir cardinalidad antes/después en cada test de mutación.** Sin baseline no hay forma de saber si mutó de más.
- **HR-10 — Inyectar la dependencia que la unidad bajo test necesita de verdad.** Para business
  logic, inyectar una interfaz de repositorio (`IRepositorioX`) y probarla con un in-memory fake.
  Para tests de data boundary (repositorios: `Obtener*` / `Guardar*` / `Borrar*` / `Listar*` /
  `Existe*`), inyectar el `DAO.Database` del sandbox vía `TestHelper.GetTestDb()`. Prohibido
  `Nothing` como `db` en repositorios; el harness siempre resuelve `db`. Esta HR es la
  combinación honesta de `access-vba-e2e-methodology` HR-2 y HR-12 (interface seams +
  sandbox solo en data boundary).
- **HR-11 — Mantener manifests en `tests/` con separación atómico/smoke.** `tests.vba.json` para átomos; `tests.vba.smoke.json` solo para agregadores (`*_RunAll`).
- **HR-12 — Prohibir `Debug.Print` / `MsgBox` dentro de `Test_*.bas`.** Toda traza se devuelve por el JSON string.
- **HR-13 — Prohibir mutación de la tabla de configuración del backend desde tests.** La configuración de backends se hace en `BeginTestSession` con rollback.
- **HR-14 — Mantener una sola forma de configurar el sandbox en todo el proyecto.** Más de un mecanismo es contract violation.
- **HR-15 — Colocar todas las declaraciones de módulo al inicio** (no `Private Const`/`Sub` entre `Public Function`) — ref `access-vba-tdd-fundamentos` §1.8.
- **HR-16 — Incluir wrappers JSON locales `BuildOk`/`BuildFail` en todo módulo que los use** — ref `access-vba-tdd-fundamentos` §1.8.
- **HR-17 — Correr pre-compile audit antes de declarar "listo para importar"** — ref `access-vba-tdd-fundamentos` §1.9.
- **HR-18 — Prohibir landmines VBA**: comentarios después de `, _`, `Nothing` a parámetros `String` — ref `access-vba-tdd-fundamentos` §1.9.
- **HR-19 — Actualizar TODOS los call sites cuando cambia la firma de un helper** — ref `access-vba-tdd-fundamentos` §1.10.
- **HR-20 — Auditar cross-file cuando se agregan fixtures con `REQ-CAL-NN`** — mismo ID en otros `Test_*.bas` debe ser consistente.
- **HR-21 — Definir tests en `tests/*.json` (manifests), NO en `.dysflow/project.json` allowlist.** El allowlist es un gate de runtime, no un registro de tests.
- **HR-22 — Prohibir `Stop-Process MSACCESS` genérico.** Puede cerrar otro proyecto Access del usuario; usar el tool canónico de cleanup de operaciones (current: `cleanup_access_operation`, per `dysflow-usage`) solo si `diagnostics.cleanupSafe: true`.

## Decision Gates

| Condition | Action |
|---|---|
| Si la operación la dispara un usuario y el arranque del frontend (AutoExec/StartupForm) es parte explícita del caso | Pasar el flag de arranque explícito al runtime Dysflow (current: `--allow-startup-execution`, per `dysflow-usage`). **Nunca como default**. |
| Si `MCP error -32001: Request timed out` aparece en `test_vba` | NO tocar código por intuición; reintentar con el tool de tests y payload compacto (invocación per `dysflow-usage`: `summaryOnly` + `includeLogs: "failures"` + `maxPayloadChars`). |
| Si sospecha Access huérfano y `diagnostics.cleanupSafe: true` | Tool canónico de cleanup de operaciones (current: `cleanup_access_operation`, per `dysflow-usage`) con `operationId`. |
| Si `cleanupSafe: false` | Pedir revisión manual o aislar por `accessPath` — nunca `Stop-Process MSACCESS`. |
| Si el usuario reporta error de compile tras `import_modules` | Volver al paso 5 (sync de formularios) del Execution Steps — NO al paso 1. |
| Si el runner compila pero falla en assertions | Leer `results[*].failures`, `run.payload`, `run.logs`; corregir comportamiento y reimportar (per `dysflow-usage`). |
| Si cobertura de tests < 80% | Adjuntar reporte de deuda técnica antes de declarar "listo". |
| Si necesitás ejecutar un subset explícito de tests por nombre | Pasar `proceduresJson` al tool de tests (per `dysflow-usage`). NO modificar el allowlist de `.dysflow/project.json` para esto; el allowlist es gate de runtime, no selector de subset (HR-21). |

## Execution Steps

> Antes era §8 TDD Loop para la IA. Misma secuencia, ahora formalizada bajo el header canónico.

Flujo exacto al implementar una feature:

1. **Test primero** → `src/modules/Test_<Feature>.bas` (debe fallar porque producción no existe).
2. **Actualizar manifests** → test atómico en `tests/tests.vba.json`; `*_RunAll` solo en `tests/tests.vba.smoke.json` si lo tocás. Ver §8.3 sobre dónde van los manifests.
3. **Código de producción** → `src/modules/<Feature>.bas`.
4. **Pre-compile audit** → correr los checks de `access-vba-tdd-fundamentos` §1.9. Si cambia la firma del helper, ejecutar el protocolo de `access-vba-tdd-fundamentos` §1.10 en TODOS los call sites.
5. **Sync de formularios** (si aplica) → tool canónico de drift/verify (current: `verify_code`, per `dysflow-usage`).
6. **Importar a Access** → tool canónico de import (current: `import_modules`, per `dysflow-usage`). **Notificar al usuario** que compile manualmente. Para el contrato de compile humano, ver `dysflow-usage` skill.
7. **Correr runner** → tool canónico de tests (current: `test_vba`, per `dysflow-usage`) con `tests/tests.vba.json` solo después de que el usuario confirme compile OK. Smoke solo si tocás agregadores.
8. **Analizar y refactorizar** — ver Decision Gates para las ramas compile-error vs assertion-fail.

Implementación detallada y comandos en `assets/tdd-loop.md`.

### 8.1 Apertura COM y AutoExec

AutoExec y StartupForm pueden bloquear la apertura COM. Patrón:

```vb
Public Function AutoExec_Startup() As Boolean
    If IsComTestMode() Then
        AutoExec_Startup = True
        Exit Function
    End If
    DoCmd.OpenForm "frmInicio"
    AutoExec_Startup = True
End Function
```

El flag de arranque explícito (current: `--allow-startup-execution`, per `dysflow-usage`) solo cuando necesitás diagnosticar una base cuyo arranque es parte explícita del caso. Ver Decision Gates.

### 8.2 Timeouts MCP — no asumir fallo de tests

`MCP error -32001: Request timed out` **no prueba** que los tests fallaron. Puede ser apertura/cierre COM, serialización JSON, payload gigante o timeout del cliente MCP.

Orden de recuperación:

1. No tocar código por intuición.
2. Reintentar con payload compacto: invocación per `dysflow-usage` (tool de tests con `summaryOnly: true`, `includeLogs: "failures"`, `maxPayloadChars: 20000`).
3. Si sospecha Access huérfano, tool canónico de listado de operaciones (current: `list_access_operations`, per `dysflow-usage`).
4. Solo si `diagnostics.cleanupSafe: true`, tool canónico de cleanup (current: `cleanup_access_operation`, per `dysflow-usage`) con `operationId`.
5. **Nunca** `Stop-Process MSACCESS` genérico — puede cerrar otro proyecto Access del usuario.
6. Si `cleanupSafe: false`, pedir revisión manual o aislar por `accessPath`.

### 8.3 Dónde van los tests (manifests vs allowlist)

> Contenido normativo elevado a HR-21. Esta subsección queda como referencia operativa.

- **Manifests** (`tests/tests.vba.json`, `tests/tests.vba.<feature>.json`, `tests/tests.regression-*.json`): es DONDE se listan y describen los tests. Cada test tiene `{name, procedure, expect, tags}`. Esta es la fuente de verdad de qué tests existen.
- **Allowlist** (`.dysflow/project.json` → `capabilities.procedures.allow`): es un GATE de dysflow runtime, NO es donde se listan tests. Solo se actualiza cuando se va a ejecutar un subset específico de tests via el tool de tests con `proceduresJson` (per `dysflow-usage`). Para el runner normal con `testsPath` o `filter`, el allowlist puede aplicar como gate, pero los tests SIGUEN definiéndose en el manifest.

**Patrón correcto**:

1. Escribir los tests en `src/modules/Test_<Feature>.bas` (código VBA).
2. Agregar las entradas al manifest `tests/tests.vba.json` (o un manifest específico `tests.vba.<feature>.json`).
3. NO tocar `.dysflow/project.json` a menos que se necesite ejecutar el tool de tests con `proceduresJson` explícitamente (per `dysflow-usage`).
4. Para validar el fix, usar el tool de tests con `testsPath` y `filter` por tag (invocación per `dysflow-usage`); el allowlist ya tiene los tests previos mergeados — no es necesario agregar los nuevos para usar `filter`.

---

## Output Contract

Return an object with the following keys:

| Key | Type | Description |
|---|---|---|
| `status` | `"success" \| "blocked" \| "failed"` | Outcome of the TDD loop iteration. |
| `loop_phase` | `"red" \| "green" \| "refactor"` | Last completed TDD phase. |
| `files_changed` | string[] | Source/test files touched in this iteration. |
| `tests_run` | number | Count of atoms executed in the validation step (per `dysflow-usage`). |
| `tests_passed` | number | Count of atoms that returned `ok:true` (per `dysflow-usage`). |
| `manifest_updated` | boolean | Whether `tests/tests.vba.<feature>.json` was updated before the run. |
| `human_compile_confirmed` | boolean | True only if user reported Debug → Compile OK before invoking the test runner. |
| `warnings` | string[] | Non-blocking issues (MCP timeouts, allowlist drift, smoke-skipped aggregators). |
| `next_recommended` | `"red" \| "green" \| "refactor" \| "commit" \| "none"` | Next phase in the loop or commit gate. |

## Anti-patterns

| Symptom | Fix |
|---|---|
| Production code written before the atom | Reverse the order: red atom in `Test_<Feature>.bas` first, then `<Feature>.bas`. |
| Manifest not updated after a new test | Add `{name, procedure, expect, tags}` to `tests/tests.vba.<feature>.json` before invoking the test runner. |
| Test runner invoked against a non-compiled binary | Stop, ask the human to run Debug → Compile in Access, then retry. |
| `.dysflow/project.json` allowlist mutated to add new tests | Tests live in `tests/*.json` manifests; the allowlist is a runtime gate, not a test registry. |

---

## Companion references

- `dysflow-usage` — canonical source for current Dysflow tool names, flag shapes, error codes, and invocation patterns.
- `dysflow-arnes` — operating harness for Dysflow; bootstrap, schema, capabilities.
- `assets/tdd-loop.md` — TDD loop detallado y comandos.
- `assets/legacy-migration.md` — checklist operativo para suites existentes.
- `assets/manifest-runner.md` — manifests atómicos, smoke y slices.
