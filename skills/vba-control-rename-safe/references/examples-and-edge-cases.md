# vba-control-rename-safe — ejemplos y edge cases (relocated from SKILL.md v1.0.0)

## Ejemplo de output — plan

```json
{
  "feasibility": "risky",
  "reasons": ["new_name 'lblTituloPrincipal' esta usado en 2 forms distintos"],
  "impact_in_source": {
    "direct_refs": [
      { "file": "src/forms/Form_FormRiesgosGestionRiesgo.cls", "line": 215, "kind": "Me.X", "context": "Me.lblTitulo.Caption = \"Riesgo \" & .CodigoRiesgo" }
    ],
    "event_handlers": [],
    "docmd_openers": []
  },
  "forms_also_using_this_control_name": [
    { "form": "Form_FormCalidadTareaExplicacion", "line": 875, "count": 1 }
  ],
  "drift_check": { "source_clean": true, "binary_clean": true },
  "rename_steps": [
    { "step_id": 1, "action": "form_rename_control form=Form_FormRiesgosGestionRiesgo control=lblTitulo newName=lblTituloPrincipal", "risk": "low" },
    { "step_id": 2, "action": "edit .cls: Me.lblTitulo -> Me.lblTituloPrincipal (linea 215)", "risk": "low" }
  ],
  "estimated_diff_lines": 7,
  "patch_preview": "--- src/forms/Form_FormRiesgosGestionRiesgo.cls\n+++ ...\n-        Me.lblTitulo.Caption = ...\n+        Me.lblTituloPrincipal.Caption = ...\n"
}
```

## Edge cases

- **Refactor masivo de muchos forms**: si `forms_also_using_this_control_name` lista muchos forms, subir `feasibility` a `risky` automáticamente.
- **Variable VBA local con el mismo nombre que el control**: VBA hace shadowing entre `Me.X` y `Dim X As String`. Heurística: si en el mismo módulo aparece `X` referenciado sin `Me.`/`Me!`, marcar como `false positive probable` y warn.
- **Rename del control implica rename del handler**: la convención `ComandoX_Click` se rompe si renombras X sin renombrar el handler. El plan SIEMPRE incluye los handlers.
- **Refs cross-form via `Forms!FormX!Control`**: codegraph v1.5.0 los modela como edges bang — aparecen en el mapa de refs UI; no hace falta grep.

## Verificación round-trip (apply)

1. `form_serialize` (read-only) del form después del rename → IR textual del estado real del binario.
2. `compare_form` antes/después → el diff debe limitarse al nombre del control y sus handlers.
3. Si aparece cualquier otro cambio estructural → investigar antes de dar por bueno el rename (posible efecto colateral de la mutación).

## Criterios v1.0.0 preservados

- Detecta todos los refs `Me.{control}` y bang refs en el form y cross-form.
- Detecta los 14 handlers por convención de nombre (_Click ... _MouseUp).
- Detecta refs late-bound en strings (warn, no fail).
- Colisión mismo form = hard-fail; otros forms = warn.
- dry_run produce plan sin tocar archivos.
- Ahorro: ~5-10 min vs ~2-3 horas de grep recursivo + updates manuales + reverificación en un proyecto de 300 archivos.
