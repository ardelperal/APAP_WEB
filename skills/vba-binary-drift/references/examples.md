# RED tests — vba-binary-drift

Failing tests (RED) that `vba-binary-drift` MUST satisfy before production.

## Test 1: Source sin cambios, binario sin cambios → todo limpio

**Input**:
```json
{ "access_path": "<Gestion_Riesgos.accdb bench copy>" }
```

**Expected output**:
```json
{
  "target": "<full binary>",
  "drift": false,
  "binary_chksum_changed": false,
  "recompile_needed": false,
  "zombie_msaccess_present": 0,
  "diff_summary": []
}
```

**Pass criteria**: todos los flags en false/0.

## Test 2: `.cls` modificado, binario NO recompilado → drift + recompile_needed

**Input**:
```json
{ "target": "Form_FormRiesgosGestionRiesgo", "access_path": "<.accdb>" }
```
(`Form_FormRiesgosGestionRiesgo.cls` modificado en disk; binario NO recompilado.)

**Expected**:
- `drift: true`
- `binary_chksum_changed: true`
- `recompile_needed: true`
- `diff_summary: [{ file: "Form_FormRiesgosGestionRiesgo", source_size: 1234, binary_size: 1230, matches: false }]`

**Pass criteria**: drift detectado + recompilación flagged.

## Test 3: 3 zombies MSACCESS.EXE lockeando el .accdb → reporta 3

**Input**:
```json
{ "access_path": "<.accdb>" }
```
(3 procesos MSACCESS.EXE con nuestro `access_path` lockeado.)

**Expected**:
- `zombie_msaccess_present: 3`
- Emite `action_suggested: "access_force_cleanup_orphaned"` con nota de `pid` + confirmación explícita
- El skill NO mata los zombies (eso es otra herramienta)

**Pass criteria**: cuenta correcta, sin matar nada.

## Test 4: Binario lockado por proceso activo → hard-fail

**Input**:
```json
{ "access_path": "<.accdb with active lock>" }
```

**Expected**:
- Hard-fail con mensaje claro
- Sugiere `access_force_cleanup_orphaned` con `pid`, `implements_check:"orphans_msaccess"` y confirmación explícita
- Exit code != 0

**Pass criteria**: error tipado, no respuesta vacía ni crash.

## Test 5: dysflow < v1.11.2 → hard-fail con acción sugerida

**Input**:
```json
{ "access_path": "<.accdb>" }
```

(Edge case donde el MCP server tiene versión vieja.)

**Expected**:
- Hard-fail con mensaje: `"dysflow < v1.11.2; run dysflow update"`
- Exit code != 0

**Pass criteria**: skill NO asume versión vieja silenciosamente.
