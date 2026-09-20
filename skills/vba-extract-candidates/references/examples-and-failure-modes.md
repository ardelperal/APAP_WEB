# vba-extract-candidates — ejemplos y failure modes (relocated from SKILL.md v1.0.0)

## Ejemplo de output

```json
{
  "target": { "module": "Form_FormRiesgosGestionRiesgo", "name": "EstablecerDatos", "line": 173 },
  "current_signature": "Public Function EstablecerDatos(Optional ByRef p_Error As String) As String",
  "body_size_lines": 142,
  "suggested_helpers": [
    {
      "name": "EstablecerDatos_CargarRiesgo",
      "line_range": [173, 210],
      "rationale": "Primera mitad del procedure: carga de BD. Logica pura, facil de mockear.",
      "boundary_respected": true
    },
    {
      "name": "EstablecerDatos_AplicarEstado",
      "line_range": [213, 270],
      "rationale": "Segunda mitad: aplicar estado segun rol.",
      "boundary_respected": true
    }
  ],
  "coverage": { "total_helper_lines": 95, "overlap": 0, "gaps": 0 }
}
```

## Acceptance scenarios

- Procedure de 142 líneas → propone 2-3 helpers con `boundary_respected: true` y `gaps: 0`.
- Procedure de 60 líneas (bajo threshold) → `suggested_helpers: null`, NO fuerza extracción.
- Procedure con `With x.Browser ... End With` largo → respeta el bloque entero, no propone partirlo.

## Failure modes

- Procedure sin boundaries naturales claros → `boundary_respected: false`; el humano decide.
- Helpers ya existentes de nombre similar → conflicto detectado vía `find_references`/`codegraph_explore` antes de proponer.
- Procedure inexistente → typed error de dysflow; verificar módulo con `list_procedures`.

## Criterios v1.0.0 preservados

- Latencia: ≤2s incluso en proyectos con 300+ archivos.
- Precisión: source verbatim exacto, file:line resuelto.
- Dry-run: NO escribe al binario ni al source tree.
- Ahorro: con `get_procedure` la lectura es ~10x más barata que export_modules + Read + regex.
