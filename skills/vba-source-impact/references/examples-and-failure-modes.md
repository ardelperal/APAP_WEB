# vba-source-impact — ejemplos y failure modes (relocated from SKILL.md v1.0.0)

## Ejemplo de output (formato v1.0.0, aún válido como referencia de campos base)

```json
{
  "target": "Form_FormRiesgosGestionRiesgo.EstablecerDatos",
  "parsed": { "kind": "function", "module": "Form_FormRiesgosGestionRiesgo", "line": 173 },
  "direct_callers": [
    { "module": "Form_FormRiesgosGestionRiesgo", "name": "Form_Load", "line": 165, "context": "EstablecerDatos m_Error" }
  ],
  "direct_callees": [
    { "module": "Form_FormRiesgosGestionRiesgo", "name": "EstablecerDatos_CargarRiesgo", "line": 204 }
  ],
  "ui_refs": [],
  "data_bindings": [],
  "affected_files": ["src/forms/Form_FormRiesgosGestionRiesgo.cls"],
  "related_tests": [
    { "name": "Block1 Forms coverage", "procedure": "Test_Block2a_2b_3Forms_Cobertura", "tag": "block-2a" }
  ],
  "warnings": []
}
```

## Acceptance scenarios

- Antes de un merge: emite el resumen de impacto en formato PR-friendly.
- Antes de refactor largo: lista `affected_files` + `related_tests` para presupuestar.
- Durante SDD apply: confirma que el archivo a tocar no tiene refs UI ocultas (bang refs cross-form ahora vienen del grafo, no de grep).
- Hard-fail si el accessPath no responde (cuando se pasa): bloquear antes de empezar con mensaje claro.

## Failure modes

- Wildcard que matchea >100 nodos → no expande, devuelve `wildcard_match_count`.
- Codegraph index stale → warning + sugerir `vba-binary-sync`.
- Refs circulares (A → B → A) → `cycle_detected: true`.
- Referencias `CallByName` late-bound → solo detectables por grep manual de strings (warning `LATE_BOUND_RISK`).

## Nota histórica

La v1.0.0 detectaba refs `Me.X` y event handlers por convención de nombre con heurísticas regex porque codegraph no modelaba esos edges. Desde codegraph v1.5.0 los edges UI (bang refs, With-blocks), los bindings RecordSource/RowSource, TempVars, DoCmd targets y el impacto SQL de tablas son parte del grafo: la heurística de convención de nombre queda solo como detector de handlers huérfanos.

## Criterios v1.0.0 preservados

- Cobertura: todos los refs directos + todos los refs UI + tests que llaman al área (no solo los que importan el módulo).
- Latencia: ≤2s en proyectos con 300+ archivos.
- Ahorro: 1 invocación (~400-500 tokens) vs ~2-3k del flujo manual.
