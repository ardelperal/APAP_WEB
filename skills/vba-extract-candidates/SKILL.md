---
name: vba-extract-candidates
description: Trigger: qué helpers extraigo de X, divide X en helpers, planifica extracción de X, X es muy largo. Identifica candidatos a extracción en un procedure VBA largo y propone 2-3 helpers respetando boundaries de statements (With/End With, If/End If, For/Next).
license: Apache-2.0
status: active
requires: dysflow MCP, codegraph; for current tool names and flags → see `dysflow-usage` skill.
supersedes: v1.0.0 (2026-06-30, leía cuerpos vía export_modules + Read + regex)
metadata:
  author: Andrés Román
  version: 2.0.0
  last_verified: 2026-08-22
  scope: ['vba', 'runtime']
  auto_invoke: ['finding VBA extraction candidates']
  tiers: ['vba', 'runtime']
---



# vba-extract-candidates

Propone 2-3 helpers extraíbles de un procedure VBA largo, respetando boundaries de statements. Read-only: propone plan, no edita.

## Activation Contract

- Inputs: `procedure_name` (calificado o no), `access_path` (opcional si dysflow MCP configurado), `threshold_lines` (default 80).
- Output: `extract_candidates_json` — ver Output Contract.
- No edita código; el análisis de impacto corresponde a `vba-source-impact`.

## División de la verdad

dysflow es la verdad del binario (.accdb real); codegraph es la verdad del grafo de source (árbol exportado). Si difieren, hay drift: ejecutar `vba-binary-sync` antes de confiar en cualquier análisis. `find_references symbol=X scope=all` es la sonda de drift por símbolo.

## Hard Rules

- **HR-1.** Leer el cuerpo con `get_procedure module=X procedure=Y` (verbatim, con startLine/endLine). NO exportar el módulo entero + Read + regex: ese flujo es ~10x más caro y está obsoleto.
- **HR-2.** Si no se conoce el módulo: `list_procedures module=X` sobre los módulos candidatos para localizar el procedure (nombre, kind, visibilidad, línea).
- **HR-3.** Boundaries inviolables: nunca proponer un corte que parta `With/End With`, `If/End If`, `For/Next`, `Select Case/End Select`, `Sub/End Sub`.
- **HR-4.** Cobertura: la unión de los helpers propuestos cubre el cuerpo completo sin huecos ni solapamientos; si es imposible, reportar `boundary_respected: false` y `gaps > 0` — decide el humano.
- **HR-5.** Colisión de nombres: verificar cada nombre de helper propuesto con `find_references symbol=<nombre> scope=all` (typed error si no existe = nombre libre) o con `codegraph_explore`.

## Decision Gates

| Situación | Acción |
| --- | --- |
| `body_size_lines <= threshold_lines` | Devolver `suggested_helpers: null`; no forzar extracción |
| Procedure sin boundaries naturales claros | `boundary_respected: false`; humano decide |
| Nombre de helper ya existe en el proyecto | Reportar conflicto antes de proponer |
| Procedure no existe en el binario | Hard-fail (typed error de dysflow) |

## Execution Steps

1. Localizar: `list_procedures module=<module>` si hace falta desambiguar; obtener firma y línea.
2. `get_procedure module=<module> procedure=<name>` → cuerpo verbatim + startLine/endLine.
3. Contar líneas reales del cuerpo (sin comentarios ni blancos). Si ≤ threshold → terminar con `suggested_helpers: null`.
4. Buscar boundaries naturales (bloques With/If/For/Select, comentarios banner) y proponer 2-3 helpers que cubran todo el cuerpo sin solaparse.
5. Sanity de nombres: `find_references` sobre cada nombre propuesto (nombre libre = typed error "no existe").
6. Emitir el plan con `name`, `line_range`, `rationale`, `boundary_respected`.

## Output Contract

`extract_candidates_json`:

```json
{
  "target": { "module": "...", "name": "...", "line": 0 },
  "current_signature": "Public Function ...",
  "body_size_lines": 0,
  "suggested_helpers": [
    { "name": "...", "line_range": [0, 0], "rationale": "...", "boundary_respected": true }
  ],
  "coverage": { "total_helper_lines": 0, "overlap": 0, "gaps": 0 }
}
```

## References

- `references/examples-and-failure-modes.md` — ejemplo completo con helpers propuestos, acceptance scenarios y failure modes.
- Skills relacionados: `vba-source-impact` (impacto en el source tree), `vba-symbol-rename` (si la extracción implica renombrar).

## Anti-patterns

| Symptom | Fix |
|---|---|
| Proponer un corte de extracción que parte un bloque `With/End With`, `If/End If`, `For/Next` o `Select Case/End Select` | Reordenar los helpers propuestos para respetar los boundaries; si es imposible, reportar `boundary_respected: false` y dejar al humano decidir |
| Forzar extracción cuando `body_size_lines <= threshold_lines` | Devolver `suggested_helpers: null`; no inventar helpers para un cuerpo ya pequeño |
| Nombrar un helper sin verificar primero con `find_references` que el nombre está libre | Correr `find_references symbol=<nombre> scope=all`; un typed error "no existe" confirma que el nombre está libre |
| Exportar el módulo entero + Read + regex para leer el cuerpo del procedure | Usar `get_procedure module=X procedure=Y` (verbatim, con startLine/endLine); el flujo viejo es ~10x más caro y está obsoleto |
