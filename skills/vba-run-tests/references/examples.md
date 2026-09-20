# RED tests — vba-run-tests

Failing tests (RED) that `vba-run-tests` MUST satisfy before production.

## Test 1: 6 tests válidos → 6 passed, 0 zombies

**Input**:
```json
{
  "tests": [
    { "procedure": "Test_X_1", "args": [] },
    { "procedure": "Test_X_2", "args": [] },
    { "procedure": "Test_X_3", "args": [] },
    { "procedure": "Test_X_4", "args": [] },
    { "procedure": "Test_X_5", "args": [] },
    { "procedure": "Test_X_6", "args": [] }
  ],
  "access_path": "<.accdb>"
}
```

**Expected output**:
```json
{
  "tests_run": [
    { "name": "X_1", "procedure": "Test_X_1", "status": "passed", "duration_ms": 6852, "payload": null },
    ... (6 entries)
  ],
  "summary": { "total": 6, "passed": 6, "failed": 0, "skipped": 0, "duration_ms": ~41200 },
  "zombie_msaccess": 0
}
```

**Pass criteria**: `summary.total == 6`, `passed == 6`, `failed == 0`, `zombie_msaccess == 0`.

## Test 2: 1 test falla → summary.failed == 1, procedure marcado failed

**Input**:
```json
{
  "tests": [{ "procedure": "Test_X_Sad_AssertFails", "args": [] }],
  "access_path": "<.accdb>"
}
```

**Expected**:
- `summary.failed: 1`
- `tests_run[0].status: "failed"`
- `tests_run[0].payload` contiene el `expected_outcome` violado y el assertion error

**Pass criteria**: failure explícita con `payload` estructurado, no opaque.

## Test 3: Test crashea el Access process → cleanup automático

**Input**:
```json
{
  "tests": [{ "procedure": "Test_X_AccessCrash", "args": [] }],
  "access_path": "<.accdb>"
}
```
(Test dispara un crash que deja 1 zombie.)

**Expected**:
- `tests_run[0].status: "errored"` (no failed)
- `zombie_msaccess: 1` con operation ID
- El skill llamó `cleanup_access_operation` con `force: false` para limpiar
- Output incluye `cleanup_performed: true`

**Pass criteria**: cleanup automático, no leak de zombies.

## Test 4: dysflow < v1.10.3 → hard-fail

**Input**:
```json
{ "tests": [{"procedure": "Test_X", "args": []}], "access_path": "<.accdb>" }
```
(Edge case con versión vieja de dysflow.)

**Expected**:
- Hard-fail con `reason_code: "DYSFLOW_VERSION_TOO_OLD"`
- Mensaje: `"dysflow < v1.10.3; update required (re-introduced script-load order bug)"`
- Exit code != 0

**Pass criteria**: skill NO asume versión vieja silenciosamente.

## Test 5: Idempotencia — correr 2 veces seguidas → mismos resultados, 0 zombies acumulados

**Input**:
```json
{ "tests": [...3 tests válidos...], "access_path": "<.accdb>" }
```
(Correr el mismo subset 2 veces.)

**Expected (ambos runs)**:
- `summary.total: 3, passed: 3, failed: 0`
- `zombie_msaccess: 0` en ambos runs (no accumulation)
- Resultados idénticos módulo timing

**Pass criteria**: skill no acumula imports, no deja zombies residuales.

## Test 6: 1 zombie pre-existente de otro proceso → no se cuenta en este run

**Input**:
```json
{ "tests": [...], "access_path": "<.accdb>" }
```
(Ya hay 1 zombie de una sesión previa del usuario.)

**Expected**:
- Output emite `pre_existing_zombies: 1` con PID (informativo)
- `zombie_msaccess: 0` (cuenta solo los generados por este run)
- No intenta matarlos (`access_force_cleanup_orphaned` con `pid`, `implements_check:"orphans_msaccess"` y confirmación explícita es la herramienta correcta)

**Pass criteria**: skill diferencia "mis zombies" de "los del sistema".
