[← Back to roadmap hub](../roadmap.md)

# Fase 6 — Salud, Terapias e Inventario de Material (Feature 03)

Esta página posee el estado de la Fase 6: registro sanitario con periodicidad, terapias con recomendaciones, inventario de material con disponibilidad e historial de asignaciones. Fase cerrada. Depende de Fases 3–4.

## Estado

Cerrado. HEALTH-01..06, el informe de próximas pruebas, el gate de
lifecycle de terapias y el refactor hexagonal de materiales están en
`main`.

La batería E2E de Fase 6 existe completa en `tests/e2e/`. Los tests con
seed pendiente mantienen skip explícito y documentado, sin ocultar deuda
de implementación del slice.

## Slices

| Sub-fase | Slice | Estado | Issue |
|---|---|---|---|
| 6a SALUD | HEALTH-01 modelo base de sanidad | cerrado | #50 |
| 6a SALUD | HEALTH-02 batch API (eventos múltiples) | cerrado | #51 |
| 6a SALUD | HEALTH-03 summary API (últimos valores por chip) | cerrado | #52 |
| 6a SALUD | HEALTH-04 therapies CRUD | cerrado | #53 |
| 6a SALUD | HEALTH-05 periodicity engine | **cerrado** | #54 |
| 6a SALUD | HEALTH-06 prueba-catalog migration | cerrado | #55 |
| 6a SALUD | Informe de próximas pruebas | **cerrado** | #652 |
| 6b TERAPIAS | terapias y recomendaciones | **cerrado (con lifecycle gate)** | #53, #653 |
| 6c MATERIAL | dominio + port abstracto | **cerrado** | #753 |
| 6c MATERIAL | LocalBackend adapter (MaterialesPort) | **cerrado** | #755 (merge `e95e8ef`) |
| 6c MATERIAL | capa application (use cases) | **cerrado** | #752 PR 3 (merge `db6626c`) |
| 6c MATERIAL | DI wiring del adapter | **cerrado** | #752 PR 4 (merge `9064186`) |
| 6c MATERIAL | remoción de `service.py` legacy | **cerrado** | #752 PR 5 |

## Issues abiertas relacionadas

No quedan issues abiertas de Fase 6 en este documento. La siguiente fase
funcional es Fase 7.

## Decisiones relacionadas

- [d-24-validacion-fechas-sanidad.md](../architecture/decisiones/d-24-validacion-fechas-sanidad.md) — regla de validación de fechas en actuaciones sanitarias.

## Documentación de referencia

- [docs/discovery/feature-03-health-care.md](../discovery/feature-03-health-care.md).
- [docs/legacy-health-ui-workflow.md](../legacy-health-ui-workflow.md) — flujo de UI legacy de la ficha sanitaria.
- [docs/architecture/decisiones-proyecto.md](../architecture/decisiones-proyecto.md) § "Pestaña Salud del animal" / "Pestaña Terapias del animal" / "Terapias: inventario de material y asignación".

## Core invariants

- **Cinco tipos de evento sanitario**: Analítica, Desparasitación, Vacuna, Esterilización, Otros ([legacy-health-ui-workflow.md §3](../legacy-health-ui-workflow.md)).
- **Fecha del evento posterior al nacimiento y anterior a la defunción**: regla de validación de fechas (D-24).
- **No duplicados por chip + prueba + fecha**: `MismaPruebaYFechaParaNChip` bloquea el alta.
- **Fallecido e Incoherente bloquean nuevos eventos**: el motor de estado del animal (§Fase 4) impide altas sanitarias en esos estados.
- **Periodicidad declarativa**: HEALTH-05 modela el calendario de próximas pruebas sin recalcular en cada lectura.

## Contributor checklist

- [ ] Si abre un slice de Fase 6, cite la sub-fase (6a/6b/6c) y la issue correspondiente.
- [ ] Si implementa HEALTH-02..06, cubra con tests los seis invariantes de [legacy-health-ui-workflow.md](../legacy-health-ui-workflow.md) §"Core invariants".
- [ ] Si implementa el informe de próximas pruebas, preserve el formato chip + tipo de prueba + fecha última + fecha próxima ([legacy-health-ui-workflow.md §10](../legacy-health-ui-workflow.md)).
- [ ] Si descubre un tipo de evento o validación del legacy no listado en [legacy-health-ui-workflow.md](../legacy-health-ui-workflow.md), abra issue `type:bug gap:legacy` (P1).

## Batería E2E

Baterías E2E con Playwright para cada sub-slice de Fase 6. Las baterías se escriben al mismo tiempo que el slice; solo se ejecutan en CI en el primer prototipo funcional y en releases ([transversales.md §Batería E2E](transversales.md)).

### 6a — Salud (sanidad actuaciones)

| Fichero E2E | Casos | Slice |
|---|---|---|
| `test_sanidad_crud.py` | List, filter by animal, create, 422 FK, detail, edit, soft-delete (7 tests) | `sanidad` ✅ hecho |
| `test_sanidad_5tipos.py` | Create each of 5 tipos (Analitica/Desparasitacion/Vacuna/Esterilizacion/Otros) via catalog dropdown (5 tests) | `sanidad` ✅ hecho (PR #628 E2E batch 1) |
| `test_sanidad_auth.py` | 302 without session, 403 reader in POST, reader 200 on GET list (6 tests) | `sanidad` ✅ hecho (PR #628 E2E batch 1) |
| `test_sanidad_date_validation.py` | Future date → 422, non-ISO → 422, fecha before FNacimiento → 422 (3 tests) | `sanidad` ✅ hecho (PR #628 E2E batch 1) |
| `test_sanidad_no_duplicates.py` | Duplicate (animal+fecha+tipo) → 409, different tipos both succeed (2 tests) | `sanidad` ✅ hecho (PR #628 E2E batch 1) |
| `test_sanidad_lifecycle.py` | POST /sanidad bloquea animales Fallecido o Incoherente con 422 | `sanidad` ✅ hecho (#54 follow-up) |

### 6b — Terapias

| Fichero E2E | Casos | Estado | Slice |
|---|---|---|---|
| `test_salud_terapias.py` | List, create, detail, edit, soft-delete, recomendaciones create/patch/delete, 409 con recomendaciones pendientes (7 tests) | hecho | `salud` |
| `test_terapias_auth.py` | GET/POST/GET-detail anónimo devuelven redirect a /login (3 tests) | hecho | `salud` |
| `test_terapias_lifecycle.py` | regression sentinel: terapia sin ``animal_current_state`` row no se over-blocks (303); unit tests en ``tests/test_salud.py`` pin el CTE gate (Fallecido → 422 + 'fallecido', Incoherente → 422 + 'Incoherente') | hecho (gate implementado en PR #54 follow-up; E2E skip limpio sin seed widening) | `salud` |
| `test_terapias_crud_full.py` | CRUD completo con todos los campos opcionales + recomendaciones completas (PATCH completada) | cubierto por ``test_salud_terapias.py`` (7 tests) | `salud` |

Nota sobre lifecycle: el slice 6b ya cierra el CTE gate con el
pattern de sanidad (PR #54 follow-up). La disambiguación en
``_raise_terapia_fk_error`` ahora JOINa ``animal_current_state`` y
raisea 422 con ``"animal_id no admite nuevas terapias
(estado <state>)"`` para ``Incoherente`` o ``Fallecido (*, ...)``;
también raisea 422 con ``"... (fallecido desde <date>)"`` cuando
``animales.f_defuncion IS NOT NULL``. La unit test coverage vive
en ``tests/test_salud.py::test_create_terapia_blocks_fallecido_*
animal`` y ``..._blocks_incoherente_animal``.

### 6c — Material

| Fichero E2E | Casos | Slice |
|---|---|---|
| `test_materiales_crud.py` | List, create, detail, edit, deactivate, duplicate (material+tamano+color) → 409 (5 tests) | `materiales` ✅ hecho (PR #628 E2E batch 1) |
| `test_materiales_assignment.py` | 4 atoms (assign redirect, duplicate 409, unassign redirect, list decreases) | `materiales` ✅ hecho (skip hasta seed de animal+estancia; issue #46 follow-up) |
| `test_materiales_auth.py` | 3 atoms (catalog list/detail, per-stancia assignment list redirect a /login) | `materiales` ✅ hecho (skip sin servidor) |

### Periodicidad (HEALTH-05)

| Fichero E2E | Casos | Slice |
|---|---|---|
| `test_periodicity_engine.py` | Vacuna crea tarea linked via vinculo; Vacuna overdue marca urgente; Esterilización one-shot no crea tarea; Desparasitación crea tarea linked | `tasks` / `sanidad` hecho |

### Informe de próximas pruebas

| Fichero E2E | Casos | Estado | Slice |
|---|---|---|---|
| `test_proximas_pruebas.py` | 200 con ventana válida; 400 con fecha mal-formada; 400 con ventana invertida; shape de las filas (chip, nombre, tipo_codigo, fecha_ultima, fecha_proxima, periodicidad_meses, estado); filtro por animal | hecho (#652) | `sanidad` |

**Total pendiente:** 0 ficheros E2E nuevos. La Fase 6 conserva skips
explícitos solo donde falta seed operativo para ejecutar el caso en CI.

## Navigation

Previous: [fase-5-flujos-operativos.md](fase-5-flujos-operativos.md) | Next: [fase-7-documentos-contratos-informes.md](fase-7-documentos-contratos-informes.md)
