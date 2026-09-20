---
name: vba-form-repair
description: Trigger: arregla el form X, el form está roto, controles descolocados, handler huérfano, form inconsistente, repara este formulario. Diagnostica y repara forms de Access rotos o inconsistentes: controles perdidos, handlers huérfanos, propiedades corruptas, bindings rotos.
license: Apache-2.0
status: active
requires: dysflow MCP, codegraph v1.5.0+; for current tool names, flags, defaults and error codes → see `dysflow-usage` skill.
metadata:
  author: Andrés Román
  version: 1.0.0
  last_verified: 2026-08-22
  scope: ['vba', 'runtime']
  auto_invoke: ['diagnosing Access form breakage']
  tiers: ['vba', 'runtime']
---



# vba-form-repair

Workflow de diagnóstico y reparación de forms Access: inspeccionar → decidir la vía de fix (primitivas de mutación vs edición de IR) → verificar antes/después → gates de compilación y grafo.

## Activation Contract

- Inputs: `form` (nombre del form), `access_path`, `symptom` (descripción del problema: control perdido, handler que no dispara, layout roto, binding vacío...), `dry_run` (default true: solo diagnóstico + plan).
- Output: `repair_report_json` — diagnóstico, plan de fix, resultado y verificación.
- No rediseña el form (solo repara consistencia), no crea forms nuevos (eso es `create_form_from_template` / `generate_form`).

## División de la verdad

dysflow es la verdad del binario (.accdb real); codegraph es la verdad del grafo de source (árbol exportado). Si difieren, hay drift: ejecutar `vba-binary-sync` antes de confiar en cualquier análisis. `find_references symbol=X scope=all` es la sonda de drift por símbolo.

## Hard Rules

- **HR-1. Split código/UI**: el código del form vive en el `.cls`; la definición UI vive en el `.form.txt`. Un fix de comportamiento suele ser del `.cls` (import normal); un fix estructural/visual es del lado form (primitivas o IR). No mezclar las vías en un mismo paso.
- **HR-2. Write-gate**: `form_serialize` es read-only (seguro siempre); `form_deserialize` escribe al binario vía LoadFromText y está gated — requiere confirmación explícita antes de invocarlo. Nunca deserializar sin un `compare_form` planificado para verificar el resultado.
- **HR-3.** Preferir primitivas de mutación (`form_add_control`, `form_move_control`, `form_rename_control`) para fixes puntuales de propiedades/posición/nombre: son quirúrgicas y no reescriben el form entero. La vía serialize → editar IR → deserialize es solo para fixes estructurales que las primitivas no cubren.
- **HR-4.** Siempre capturar el estado ANTES (`form_serialize` + `inspect_form`) para poder hacer `compare_form` antes/después y detectar efectos colaterales.
- **HR-5.** Gate final obligatorio: **humano compila** en Access (Debug ▸ Compile) tras cualquier cambio que toque el `.cls` o los nombres de controles/handlers. → See `dysflow-usage` skill for current human-compile contract.
- **HR-6.** Un rename de control dentro de una reparación sigue las reglas de `vba-control-rename-safe` (handlers en sync, refs cross-form).

## Decision Gates

| Diagnóstico | Vía de fix |
| --- | --- |
| Propiedad puntual mal (posición, tamaño, nombre de control) | Primitivas: `form_move_control` / `form_rename_control` |
| Control referenciado en `.cls` pero ausente en el form | `form_add_control` (o `catalog_add_control` si existe en el catálogo) |
| Handler `X_Click` en `.cls` sin control X | Decidir: añadir control, renombrar handler, o borrar código muerto — decisión humana con evidencia |
| Estructura corrupta / secciones desordenadas / fix multi-control | `form_serialize` → editar IR → `form_deserialize` (write-gated) |
| RecordSource/RowSource apunta a tabla/query inexistente | Verificar con `list_objects`/`get_schema`; fix de la propiedad + validar edge en codegraph |
| Solo problemas de código (lógica de eventos) | Flujo normal de módulos: editar `.cls` → gate de `vba-binary-sync` |
| Drift binario vs source detectado durante el diagnóstico | Parar → `vba-binary-sync` → re-diagnosticar |

## Execution Steps

### Fase 1 — Diagnóstico (siempre, read-only)

> **Token economy (v2.1.7+).** Las form tools de lectura (`inspect_form`, `form_serialize`, `compare_form`, `lint_form_code`, `harvest_form_catalog`) aceptan `outputMode: "summary" | "file" | "full"`. Pasalo en `"summary"` para reconocimiento de patrones; `"full"` solo cuando necesités el detalle exhaustivo de cada propiedad.

1. `inspect_form <form>` → estructura real del binario: controles, propiedades, secciones.
2. `lint_form_code <form>` → problemas en el código del form (`.cls`).
3. `form_serialize <form>` → IR textual de referencia (snapshot ANTES).
4. Cruce con el grafo: `codegraph_explore <form>` → bindings RecordSource/RowSource, handlers, refs cross-form (bang edges). Handlers sin control o controles sin refs → listar.
5. Emitir diagnóstico con la tabla de Decision Gates aplicada a cada hallazgo. Si `dry_run=true`, parar aquí con el plan.

### Fase 2 — Reparación (dry_run=false)

6. Aplicar los fixes por la vía decidida (primitivas primero; IR+deserialize solo si es estructural, con confirmación del write-gate).
7. Si se tocó código: importar el `.cls` actualizado (con gate de `lint_module`). Si el form contiene `DoCmd.OpenForm` con OpenArgs literals o targets un form con `Me.OpenArgs` parser, agregar la rule `openargs-contract-mismatch` (v2.19.0+) al gate para detectar producer/consumer grammar drift antes de que el round-trip oculte el bug.

### Fase 3 — Verificación

8. `compare_form` antes/después → el diff debe corresponder EXACTAMENTE a los fixes planificados; cualquier cambio extra → investigar.
9. **Humano compila** en Access (Debug ▸ Compile) — hard gate. → See `dysflow-usage` skill for current compile contract.
10. Verificación de grafo: reindex de codegraph y confirmar que los bindings RecordSource/RowSource del form resuelven a objetos existentes y los handlers tienen su control.
11. Emitir `repair_report_json`.

## Output Contract

`repair_report_json`:

```json
{
  "form": "...",
  "diagnosis": [
    { "finding": "orphan-handler|missing-control|bad-binding|layout|corrupt-structure|code-only", "detail": "...", "evidence": "...", "fix_route": "primitive|ir-edit|cls-edit|human-decision" }
  ],
  "plan": [{ "step": 1, "tool": "...", "args_summary": "...", "write_gated": false }],
  "applied": false,
  "verification": { "compare_form_clean": null, "compile": null, "graph_bindings_ok": null },
  "warnings": []
}
```

## References

- `references/diagnosis-playbook.md` — síntomas frecuentes con su diagnóstico y vía de fix, y notas sobre el write-gate.
- Skills relacionados: `vba-control-rename-safe` (renames dentro de una reparación), `vba-binary-sync` (drift), `vba-source-impact` (impacto de tocar el form).

## Anti-patterns

| Symptom | Fix |
|---|---|
| Aplicar un fix sin capturar antes el estado con `form_serialize` + `inspect_form` | Hacer snapshot ANTES; sin `compare_form` antes/después es imposible detectar efectos colaterales |
| Mezclar fix de código (`.cls`) con fix de UI (`.form.txt`) en un mismo paso | Partir en dos reparaciones: edición del `.cls` por un lado, primitivas o IR-edit del form por otro; mezclar las vías rompe round-trip |
| Llamar `form_deserialize` sin un `compare_form` planificado para verificar el resultado | Planificar la verificación primero; deserializar sin gate de comparación es write-gate violation (HR-2) |
| Auto-aplicar fixes estructurales cuando el diagnóstico sugiere primitivas | Respetar la decisión de la Decision Gates: `form_move_control` / `form_rename_control` / `form_add_control` para fixes puntuales; IR+deserialize solo para estructura corrupta o fixes multi-control |
| Saltarse el gate de humano-compila (`Debug ▸ Compile`) tras tocar el `.cls` | Tratar `humano compila` como hard gate; el binario puede compilar localmente y romperse al cruzar referencias, y solo el humano lo detecta |
| Corregir un form cuando hay drift binario vs source detectado durante el diagnóstico | Parar, ejecutar `vba-binary-sync`, re-diagnosticar desde cero; aplicar fixes sobre un binario driftado amplifica la corrupción |
