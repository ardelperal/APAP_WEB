[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Module and route size budgets

Esta página posee las reglas §21 y §28 de AGENTS verbatim: presupuesto de 700 líneas para módulos en `app/` o `migration/` y presupuesto de 50 líneas para handlers de route. Ambas usan una `BASELINE` shrink-only.

## Regla 21 — Presupuesto de módulo: 700 líneas, baseline shrink-only

Ningún módulo Python bajo `app/` o `migration/` puede exceder **700 líneas** (`tests/` y `scripts/` están exentos — el presupuesto apunta al código de producto, donde los god-files esconden violaciones de capas). Los módulos que ya excedían el presupuesto cuando aterrizó la regla (auditoría 2026-07-18: `migration/cli.py`, `migration/reconcile.py`, `migration/apply.py`, `app/modules/materiales/service.py`) viven en un dict `BASELINE` explícito dentro de `scripts/check_module_size.py` que es un **ratchet**: las entradas solo pueden decrecer o desaparecer, nunca crecer, y nunca puede añadirse una entrada nueva. Cuando una feature empujaría un módulo sobre el presupuesto, divídalo (extraiga un `queries.py`, un módulo de subcomando, un módulo de helpers) en lugar de crecerlo.

**Incorrecto** — crecer un god-file "porque ahí están los otros handlers"

```python
# migration/cli.py, line 1072+ — new subcommand appended to the god-file
def cmd_export(...): ...
```

**Correcto** — capacidad nueva en su propio módulo, el god-file solo decrece

```python
# migration/export.py — new module, well under budget
def cmd_export(...): ...
```

**Aplicación**: `python scripts/check_module_size.py` (solo stdlib, sale con código 1 ante violación) corre como su propio paso en el job `lint` de CI — quitar el paso es un cambio bloqueado, pineado por `tests/test_module_size.py::test_ci_workflow_lint_job_runs_module_size_gate` (con scope a las líneas ejecutables del job `lint`). `tests/test_module_size.py::test_baseline_matches_measured_tree` falla ante cualquier drift entre `BASELINE` y el árbol medido, así que reducir un módulo baselinado requiere actualizar su entrada en el mismo PR.

## Regla 28 — Routes delgadas: ratchet de tamaño de handler

La regla §1 ya dice que las routes deben ser solo HTTP. Esta regla añade un ratchet concreto y automatizable para ello. La revisión del 2026-07-20 encontró `app/modules/animals/routes.py::animal_foto` con 103 líneas, mezclando construcción de respuesta HTTP con política fail-closed de foto de dominio (issue #233), cuando la mediana de handler de route en este codebase es 22 líneas. Un handler de route que sigue creciendo suele ser señal de que validación, política de retry/fallback o reglas de negocio se filtraron a la route en lugar de quedarse en la capa de service.

**Incorrecto** — política de dominio decidida inline en la route

```python
@router.get("/{animal_id}/foto")
def animal_foto(animal_id: str, ...):
    try:
        animal = animals_service.get_animal_by_id(client, animal_id)
    except Exception:
        return Response(content=_PLACEHOLDER_PHOTO_PNG, media_type="image/png")
    # ...60+ more lines deciding placeholder-vs-stream fail-closed policy...
```

**Correcto** — la route delega la decisión de política y solo construye la respuesta

```python
@router.get("/{animal_id}/foto")
def animal_foto(animal_id: str, ...):
    outcome = photo_service.resolve_animal_photo(client, animal_id)
    return outcome.to_response()
```

**Aplicación**: `scripts/check_route_size.py` (solo stdlib, espejo de la forma del ratchet de `scripts/check_module_size.py`) parsea cada `app/**/*routes*.py` más `app/main.py` con `ast`, encuentra cada función decorada con `@router.<verb>(...)` o `@application.<verb>(...)`, y enforza un **techo de 50 líneas** para handlers nuevos (calibrado contra la distribución real: mediana 22, media ~32 líneas). Los 15 handlers ya sobre presupuesto cuando aterrizó la regla (`animal_foto` más 14 hermanos, incluyendo `app/main.py::callback` y `foster/assignment_routes.py::asignar_submit`) viven en un dict `BASELINE` shrink-only — crecer un handler baselinado falla el chequeo; nunca puede añadirse una entrada nueva. Cableado al job `lint` de CI inmediatamente después del paso del ratchet de módulos; quitar el paso es un cambio bloqueado. Tests: `tests/test_route_size.py` (espejo de la forma de `tests/test_module_size.py`: baseline-matches-measured-tree, CI-job-runs-the-gate).

## Core invariants

- **700 líneas es el techo para módulos de producto**: `app/` y `migration/` solamente; tests/scripts exentos.
- **50 líneas es el techo para handlers nuevos**: las 15 entradas del BASELINE solo decrecen.
- **Shrink-only ratchet**: las entradas de BASELINE nunca crecen y nunca se añaden nuevas.
- **Razones de split antes que crecer**: extraiga `queries.py`, submódulos o helpers; nunca añada código a un módulo baselinado.

## Contributor checklist

- [ ] Si el módulo nuevo cabe en 700 líneas, declárelo en PR; si excede, divídalo primero.
- [ ] Si su handler pasa de 50 líneas, muévalo a un use case o service; la route solo parsea y renderiza.
- [ ] Si reduce un módulo baselinado, actualice la entrada `BASELINE` correspondiente en el mismo PR.
- [ ] Si descubre un nuevo módulo sobre 700 líneas, árbralo como issue `god-file` antes de hacer crecer el archivo.

## Navigation

Previous: [Quality gates](quality-gates.md) | Next: [Import hygiene](import-hygiene.md)
