# TDD ⇄ UAT ⇄ Capability Doc Traceability Template

Una sola página que ata los 3 artefactos: el átomo TDD, el escenario UAT, y la entrada en el §5 ledger del capability doc. Cualquier defecto detectado por calidad debe poder trazarse hasta el átomo TDD que lo cubre.

## Tabla

| # | Workflow step | TDD atom | UAT card (`ref` interno) | Commit | Cap-doc §5 ledger entry |
|---|---|---|---|---|---|
| 1 | AltaSolicitud PC_SUB | `Test_PCSUB_AltaSolicitud_CreaSolicitudPCSUB_Happy` | UAT-1 "Crear PC_SUB desde AltaSolicitud" | `<sha>` | CAP-001 §5 row |
| 2 | EsDictamenRACCompleto | `Test_PCSUB_EsDictamenRACCompleto_BlankDecision_ReturnsFalse` | UAT-2 "Dictamen RAC exige racDecision" | `<sha>` | CAP-001 §5 row |
| 3 | (sad) DictamenRAC vacío | `Test_PCSUB_GuardarDictamenRAC_MissingCode_NonRejected` | UAT-3 "Dictamen RAC sin código NO se persiste como rechazado" | `<sha>` | CAP-001 §5 row |
| 4 | Adversarial — special chars | `Test_PCSUB_GuardarXxx_ConCaracteresEspeciales_NoCorrompe` | (sin card — interno) | `<sha>` | CAP-001 §5 internal |
| ... | ... | ... | ... | ... | ... |

## Reglas

- **Columnas obligatorias**: las 6 (workflow step, atom, UAT card, commit, cap-doc row, más el # correlativo).
- **Una fila por átomo TDD verde**. Átomos rojos NO van al UAT (se arreglan primero).
- **Una fila puede NO tener UAT card**: tests internos (harness, performance, fixture) son evidencia interna, no van al usuario. Igual van al capability doc §5 con label `internal`.
- **Un UAT card tiene al menos UN átomo verde que lo respalde**. Sin átomo, el UAT es inválido (es humo en la capa de validación).
- **El `ref` que va en el downloaded record del UAT** es el SHA del commit + el nombre del átomo. Esto congela qué versión del código se validó.
- **El cap-doc §5 ledger** debe actualizarse con cada cambio: staging version (git tag/commit), validation status per axis (`usuario`: signed? `desarrollo`: signed?), prod release date.

## Ejemplo de fila completa (PCSUB Es*Completa fix, commit `bd319a2`)

```markdown
| 7 | EsAprobacionSuministradorCompleta exige decisionFinal | `Test_PCSUB_EsAprobacionSuministradorCompleta_BlankDecisionFinal_ReturnsFalse` | UAT-3 "Aprobación Suministrador exige decisionFinal" (BR-APROB-001) | `bd319a2` | CAP-001 §5 row "Es*Completa 3er campo" — staging 2026-06-18 |
```

## Cómo regenerarla

1. Listar todos los átomos verdes del manifest atómico (`tests/tests.pcsub.json`).
2. Mapear cada átomo a un workflow step leyendo `DatosPCSUBServicio.cls`.
3. Para cada workflow step, decidir si tiene card UAT (regla de los 2 ejes de `feature-acceptance-uat`: usuario observable → UAT card; interno → solo ledger).
4. Para cada card UAT, escribir el `ref` = SHA del commit que arregla el step + nombre del átomo.
5. Pegar la tabla en `archive/<change>/traceability.md` al cerrar el SDD.

## Anti-patrones

- Tabla con átomos rojos marcados como "verde" → mentira; corregir primero.
- UAT card sin átomo que lo respalde → invalidar el card hasta tener evidencia.
- Commit no reachable desde la rama de staging → usar `git merge-base --is-ancestor` para verificar (regla `gentle-ai:sdd-commit-traceability`).
- Ledger §5 no actualizado tras cada cambio al cierre de un cambio SDD → deuda documental; reportar.