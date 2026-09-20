# vba-binary-drift — ejemplos y failure modes (relocated from SKILL.md v1.0.0)

## Ejemplo de output

```json
{
  "target": "Form_FormRiesgosGestionRiesgo",
  "drift": false,
  "symbol_drift": null,
  "binary_chksum_changed": false,
  "recompile_needed": false,
  "zombie_msaccess_present": 0,
  "diff_summary": []
}
```

## Acceptance scenarios

- Source sin cambios, binario sin cambios → `drift: false`, `recompile_needed: false`.
- Source modificado en `Form_X.cls`, binario no recompilado → `drift: true`, `recompile_needed: true`.
- Zombies presentes (3 procesos MSACCESS.EXE lockeando el .accdb) → `zombie_msaccess_present: 3` (NO los mata, solo reporta).
- Binario lockado por proceso activo → hard-fail con acción sugerida (`access_force_cleanup_orphaned` con `pid`, `implements_check:"orphans_msaccess"` y confirmación explícita).
- Sonda por símbolo: `find_references symbol=X scope=all` reporta 5 refs en binario y 3 en source → `symbol_drift.divergent` lista los 2 faltantes; recomendar `vba-binary-sync`.

## Failure modes

- 1 zombie de un proceso externo (no lockea nuestro .accdb) → warning, no lo cuenta.
- Binario corrupto (`verify_code` falla) → hard-fail con mensaje claro.
- Símbolo inexistente → typed error de `find_references` (verificar nombre antes de concluir "sin refs").

## Criterios v1.0.0 preservados

- Drift detection correcta vía `verify_code`.
- Zombie check solo cuenta procesos que lockean el `accessPath` objetivo.
- `recompile_needed: true` si el source de código cambió y el binario no se recompiló.
- Latencia: ≤5s en proyectos con 300+ archivos.
