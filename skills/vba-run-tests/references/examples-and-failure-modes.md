# vba-run-tests — ejemplos, failure modes y nota histórica

## Ejemplo de output

```json
{
  "preflight": { "manifest_valid": true, "errors": [], "warnings": [] },
  "tests_run": [
    { "name": "GetCachedRiesgoFresh W1-S1 Happy Cold", "procedure": "Test_GetCachedRiesgoFresh_W1_S1_Happy_Cold", "status": "passed", "duration_ms": 6852, "payload": null }
  ],
  "summary": { "total": 6, "passed": 6, "failed": 0, "skipped": 0, "duration_ms": 41200 },
  "zombie_msaccess": 0
}
```

## Acceptance scenarios

- Pre-flight limpio, 6 tests corrieron → `summary.total: 6`, `zombie_msaccess: 0`.
- 1 test falló → `summary.failed: 1`, el procedure afectado con `status: failed` y `payload` con detalle.
- Test crasheó el proceso Access → `zombie_msaccess: 1` reportado + cleanup automático sin force.
- Mismo subset corrido dos veces seguidas → resultados idénticos, `zombie_msaccess: 0` en ambas.
- Manifest inválido → errores tipados de `validate_manifest`, cero invocaciones a `test_vba`.

## Failure modes

- Binario sin compilar → `BINARY_NOT_COMPILED` tipado (detectado en pre-flight).
- Test que tira excepción no capturada → `status: errored` con `payload.error` (distinto de `failed`).
- Zombie pre-existente ajeno al run → warning aparte, no cuenta en `zombie_msaccess`.
- Subset corrido en los últimos N minutos sin cambios de source → warning de cache-hit (no fail).

## Nota histórica — bypass proceduresJson (OBSOLETO)

La v1.0.0 de este skill mandaba pasar `proceduresJson` inline SIEMPRE, como workaround del bug de dysflow v1.10.2 que construía el path del manifest como `[PATH]\<projectRoot>\tests.vba.json` sin resolver. Ese bug está corregido hace tiempo: `test_vba` con `testsPath` funciona y es el camino primario. Si encuentras instrucciones que exigen el bypass inline "por el bug v1.10.2", son obsoletas. El subset inline sigue existiendo como opción de granularidad (correr 1-3 tests sin manifest), nada más.

## Criterios v1.0.0 preservados

- Zombie check: 0 MSACCESS.EXE huérfanos al terminar.
- Idempotencia: ejecutable N veces sin acumular imports.
- Latencia: ≤10s para subset de 5 tests.
