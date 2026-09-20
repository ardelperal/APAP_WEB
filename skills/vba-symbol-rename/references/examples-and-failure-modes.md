# vba-symbol-rename — ejemplos y failure modes (relocated from SKILL.md v1.0.0)

## Ejemplo de output — modo `plan`

```json
{
  "target": {
    "kind": "function",
    "module": "Form_FormX",
    "name": "OldName",
    "qualified": "Form_FormX.OldName"
  },
  "impact_entries": [
    { "file": "src/forms/Form_FormX.cls", "line": 165, "current_text": "OldName m_Error", "qualified": "Form_FormX.Form_Load" },
    { "file": "src/modules/modY.bas", "line": 87, "current_text": "Call OldName()", "qualified": "modY.SomeCaller" }
  ],
  "total_changes": 2,
  "warnings": []
}
```

## Ejemplo de output — modo `apply`

```json
{
  "target": {
    "kind": "function",
    "module": "Form_FormX",
    "name": "OldName",
    "qualified": "Form_FormX.OldName"
  },
  "changed": [
    { "file": "src/forms/Form_FormX.cls", "line": 165, "before": "OldName m_Error", "after": "NewName m_Error" }
  ],
  "skipped": [],
  "errors": [],
  "post_validation": { "import_gate": "passed", "compile_check": "verified", "verify_code": "clean" }
}
```

## Acceptance scenarios

- Procedure con 3 callers cross-module → plan retorna 3 entries con `file:line:context:qualified` resuelto.
- Procedure con 0 callers → plan retorna `impact_entries: []` + `warnings: [{ reason_code: "NO_CALLERS" }]`.
- Procedure ambigua (`Sub X()` y `Sub X(ByVal i As Long)`) → hard-fail `PROCEDURE_AMBIGUOUS` + lista de candidatos.
- apply con source cambiado desde el plan → hard-fail `SOURCE_CHANGED` con diff resumido.
- apply con binario que no compila (v1.19.0+) → hard-fail `BINARY_NOT_COMPILED` + sugerencia de **compilar en Access** (Debug ▸ Compile) primero. Antes la sugerencia era `dysflow.compile_vba`; ya no existe.
- apply con colisión (new_name ya existe) → hard-fail `NAME_COLLISION` sin aplicar nada.
- Símbolo con drift binario vs source (`find_references scope=all` reporta discrepancia) → abortar y ejecutar `vba-binary-sync`.

## Failure modes tipados

| Código | Causa | Acción |
| --- | --- | --- |
| `SYMBOL_NOT_FOUND` | typed error de `find_references` | Verificar nombre/qualifier |
| `PROCEDURE_AMBIGUOUS` | overloads o símbolo en múltiples módulos | Pedir `module_qualifier` |
| `SOURCE_CHANGED` | source mutó entre plan y apply | Re-plan |
| `BINARY_NOT_COMPILED` | humano no compiló en Access (Debug ▸ Compile) o el compile de Access falló | Compilar/arreglar primero (v1.19.0+; antes era `dysflow.compile_vba`) |
| `NAME_COLLISION` | new_name ya en uso en el scope | Elegir otro nombre |
| `INVALID_NEW_NAME` | caracteres inválidos VBA (espacios, símbolos) | Corregir nombre |
| `LATE_BOUND_RISK` (warning) | hits de grep en strings — posible `CallByName` | Revisión humana |

## Idempotencia y latencia (criterios v1.0.0 preservados)

- Aplicar plan dos veces seguidas produce el mismo `impact_list` mientras el source no cambie.
- Latencia objetivo: <2s en proyectos con 300+ archivos (mode=plan).
- Token estimate: ~500 tokens (plan), ~600 (apply) vs ~3-4k del flujo manual.
