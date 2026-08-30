[← Back to roadmap hub](../roadmap.md)

# Fase 6 — Salud, Terapias e Inventario de Material (Feature 03)

Esta página posee el estado de la Fase 6: registro sanitario con periodicidad, terapias con recomendaciones, inventario de material con disponibilidad e historial de asignaciones. Fase pendiente. Depende de Fases 3–4.

## Estado

pendiente — pendiente de crear issues (uno por sub-flujo). Próximos: HEALTH-02..06 (#51–#55).

## Slices

| Sub-fase | Slice | Estado | Issue |
|---|---|---|---|
| 6a SALUD | HEALTH-01 modelo base de sanidad | pendiente | #50 |
| 6a SALUD | HEALTH-02 batch API (eventos múltiples) | pendiente | #51 |
| 6a SALUD | HEALTH-03 summary API (últimos valores por chip) | pendiente | #52 |
| 6a SALUD | HEALTH-04 therapies CRUD | pendiente | #53 |
| 6a SALUD | HEALTH-05 periodicity engine | pendiente | #54 |
| 6a SALUD | HEALTH-06 prueba-catalog migration | pendiente | #55 |
| 6a SALUD | Informe de próximas pruebas | pendiente | — |
| 6b TERAPIAS | `feat(therapies): terapias y recomendaciones` | pendiente | — |
| 6c MATERIAL | `feat(material): inventario de material y asignaciones` | pendiente | — |

## Issues abiertas relacionadas

- #50 HEALTH-01 modelo base de sanidad.
- #51 HEALTH-02 batch API.
- #52 HEALTH-03 summary API.
- #53 HEALTH-04 therapies CRUD.
- #54 HEALTH-05 periodicity engine.
- #55 HEALTH-06 prueba-catalog migration.

## Issues pendientes de crear

- `feat(therapies): terapias y recomendaciones` (Fase 6b — depende de Fases 3–4).
- `feat(material): inventario de material y asignaciones` (Fase 6c — depende de Fases 3–4).

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
| `test_sanidad_5tipos.py` | Crear cada tipo: Analítica, Desparasitación, Vacuna, Esterilización, Otros + validar fecha PostMortem | `sanidad` ❌ pendiente |
| `test_sanidad_date_validation.py` | Fecha posterior al nacimiento, anterior a defunción, 422 en rango inválido | `sanidad` ❌ pendiente |
| `test_sanidad_no_duplicates.py` | Mismo chip + prueba + fecha → 409 | `sanidad` ❌ pendiente |
| `test_sanidad_auth.py` | 302 sin sesión, 403 con rol reader en POST | `sanidad` ❌ pendiente |
| `test_sanidad_lifecycle.py` | Crear evento sanitario; verificar que Incoherente/Fallecido bloquean nuevo evento | `sanidad` ❌ pendiente |

### 6b — Terapias

| Fichero E2E | Casos | Slice |
|---|---|---|
| `test_salud_terapias.py` | List, create, detail, edit, soft-delete, recomendaciones create/patch/delete, 409 con recomendaciones pendientes (7 tests) | `salud` ✅ hecho |
| `test_terapias_crud_full.py` | CRUD completo de terapias con todos los campos opcionales + recomendaciones completas | `salud` ❌ pendiente |
| `test_terapias_lifecycle.py` | Crear terapia; verificar que Incoherente/Fallecido bloquean nueva terapia | `salud` ❌ pendiente |
| `test_terapias_auth.py` | 302 sin sesión, 403 con rol reader en POST | `salud` ❌ pendiente |

### 6c — Material

| Fichero E2E | Casos | Slice |
|---|---|---|
| `test_materiales_crud.py` | List, create, detail, edit, deactivate, duplicate (material+tamano+color) → 409 (5 tests) | `materiales` ✅ hecho (PR #628 E2E batch 1) |
| `test_materiales_assignment.py` | Asignar material a estancia; desasignar; verificar disponibilidad decrece | `materiales` / `foster` ❌ pendiente |
| `test_materiales_auth.py` | 302 sin sesión, 403 con rol reader en POST | `materiales` ❌ pendiente |

### Periodicidad (HEALTH-05)

| Fichero E2E | Casos | Slice |
|---|---|---|
| `test_periodicity_engine.py` | Registrar periodicidad; verificar que genera tarea pendiente; simular fecha futura; verificar alerta | `tasks` / `sanidad` ❌ pendiente |

### Informe de próximas pruebas

| Fichero E2E | Casos | Slice |
|---|---|---|
| `test_proximas_pruebas.py` | List con chip + tipo + última fecha + próxima fecha; filtro por animal; export | `sanidad` ❌ pendiente |

**Total pendiente:** 7 ficheros E2E nuevos (terapias full/lifecycle/auth, materiales assignment, periodicity engine, proximas-pruebas, sanidad lifecycle).

## Navigation

Previous: [fase-5-flujos-operativos.md](fase-5-flujos-operativos.md) | Next: [fase-7-documentos-contratos-informes.md](fase-7-documentos-contratos-informes.md)
