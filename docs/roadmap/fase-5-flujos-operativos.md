[← Back to roadmap hub](../roadmap.md)

# Fase 5 — Voluntarios + Entradas + Acogidas + Adopciones (Feature 02)

Esta página posee el estado de la Fase 5: flujos operativos centrales con asistentes por pasos y snapshots históricos de personas. Fase en curso, ejecutada en cuatro sub-fases (5a INTAKE, 5b FOSTER, 5c ADOPT, 5d VOL).

## Estado

cerrado — Fase 5 completa. Todas las sub-fases 5a/5b/5c/5d cerradas sobre main. El epic #420 hexagonal (VOL-02..05 + LIFECYCLE-02) mergeado con PR #627.

## Slices

| Sub-fase | Slice | Estado | Issue / PR |
|---|---|---|---|
| 5a INTAKE | Alta / edición / listado de entradas individuales | cerrado | #87, #88, #89 |
| 5a INTAKE | Entradas múltiples transaccional (INTAKE-02) | cerrado | #40 (c7b69ec) |
| 5b FOSTER | `app/modules/foster/` (assignment + routes + service) | cerrado | ver `app/modules/foster/README.md` |
| 5b FOSTER | `feat(foster) override→estancia atomicity` | cerrado | #142 (2bbcfa3 + 28d04e9 follow-up, PR #155) |
| 5b FOSTER | FOSTER-04 material assignment | cerrado | #46 (c1b73f3 catalog + b490e2c junction, PR #170 + #171) |
| 5c ADOPT | ADOPT-01..02 (alta y edición de adopción) | cerrado | ver `app/modules/adopciones/` |
| 5c ADOPT | ADOPT-03 4-state follow-up state machine | cerrado | #49 (96ec631) |
| 5d VOL | VOL-01 modelo base de voluntarios | cerrado | #26 |
| 5d VOL | VOL-02 roles_voluntario junction (assign/remove use cases) | cerrado | #35 (epic #420 PR-A hexagonal, PR #627) |
| 5d VOL | VOL-03 fuzzy dedup pipeline | cerrado | #36 (d322e7d, PR #321) |
| 5d VOL | VOL-04 FK free-text → estructurada (migration) | cerrado | #37 (cd56ba4) |
| 5d VOL | VOL-05 active validation gate (entradas / acogidas / adopciones) | cerrado | #38 (gate `activo = true` aplicado en `entradas/queries.py`, `acogidas/queries.py` y `adopciones/queries.py` como parte de #44/#47) |

## Issues abiertas relacionadas

Ninguna — todas las issues de Fase 5 están cerradas y reflejadas en la tabla de slices con SHA + PR.

## Decisiones relacionadas

- [d-03-dominio-animal.md](../architecture/decisiones/d-03-dominio-animal.md) — dominio centrado en animal.
- [d-05-fidelidad-legacy-superset.md](../architecture/decisiones/d-05-fidelidad-legacy-superset.md) — superset funcional.
- [d-25-rapidfuzz-fuzzy-match.md](../architecture/decisiones/d-25-rapidfuzz-fuzzy-match.md) — librería de fuzzy match para VOL-03.

## Documentación de referencia

- [docs/discovery/feature-02-intake-foster-adoption.md](../discovery/feature-02-intake-foster-adoption.md).
- [docs/discovery/data-model-notes.md](../discovery/data-model-notes.md).
- [docs/legacy-volunteer-roles.md](../legacy-volunteer-roles.md) — modelo plano legacy de voluntarios.
- [docs/legacy-lifecycle-transition-rules.md](../legacy-lifecycle-transition-rules.md) — transiciones entre estados.
- `app/modules/foster/README.md`, `app/modules/entradas/README.md`, `app/modules/voluntarios/README.md`.

## Core invariants

- **Casa de acogida no es voluntario**: `app/modules/foster/` modela la casa de acogida; `app/modules/voluntarios/` modela a la persona ([legacy-volunteer-roles.md §3](../legacy-volunteer-roles.md)).
- **Entradas múltiples son transaccionales**: el alta por lote valida antes de commit y rechaza atómicamente si una fila falla (`openspec/changes/intake-batch-entradas-transaccional/`).
- **Estado del animal cierra situaciones previas**: cada nueva entrada / acogida / adopción cierra la anterior (`CerrarSituacionNoEjecutivas`).
- **VOL-03 usa rapidfuzz, no thefuzz** ([d-25](../architecture/decisiones/d-25-rapidfuzz-fuzzy-match.md)).

## Batería E2E

Baterías E2E con Playwright para cada slice. Las baterías se escriben al mismo tiempo que el slice; solo se ejecutan en CI en el primer prototipo funcional y en releases ([transversales.md §Batería E2E](transversales.md)).

| Slice | Tests E2E | Estado |
|---|---|---|
| `animals` | `test_animales_crud.py` (9 tests) | ✅ hecho |
| `entradas` | `test_entradas_crud.py` (7) + `test_entradas_batch.py` (6) | ✅ hecho |
| `acogidas` | `test_acogidas_crud.py` (8) | ✅ hecho |
| `foster` (casas de acogida) | `test_casas_acogida_crud.py` (7) + `test_casas_acogida_asignar.py` (6) | ✅ hecho |
| `adopciones` | `test_adopciones_crud.py` (7) + `test_adopciones_seguimiento.py` (6) | ✅ hecho |
| `voluntarios` | `test_voluntarios_crud.py` (5) + `test_voluntarios_roles.py` (4) | ✅ hecho |
| `cesiones` | `test_cesiones_crud.py` + `test_cesiones_conflicts.py` + `test_cesiones_auth.py` | ❌ pendiente — slice en `feat/cesiones-hex-migration` |
| Auth ( transversal) | `test_login_form.py`, `test_logout.py`, `test_public_redirects.py`, `test_admin_authenticated.py` | ✅ hecho |
| Layout / nav | `test_landing.py`, `test_nav_layout.py`, `test_layout_responsive_extended.py` | ✅ hecho |
| Seguridad (transversal) | `test_security_headers.py` | ✅ hecho |

**Baterías pendientes:** `cesiones` es el único slice de Fase 5 sin E2E. La batería mínima es `test_cesiones_crud.py` (happy-path POST + GET + soft-delete) + `test_cesiones_conflicts.py` (409 UNIQUE + 422 validación) + `test_cesiones_auth.py` (302 / 403 por rol). Se crea al cerrar `feat/cesiones-hex-migration`.

## Contributor checklist

- [ ] Si abre un slice de Fase 5, cite la sub-fase (5a/5b/5c/5d) y la issue correspondiente.
- [ ] Si implementa VOL-02..05, lea primero [legacy-volunteer-roles.md](../legacy-volunteer-roles.md) §1 y §2.1–§2.4.
- [ ] Si implementa entradas múltiples, siga el spec de `openspec/changes/intake-batch-entradas-transaccional/specs/`.
- [ ] Si descubre un campo contextual del legacy sin mapeo en el modelo nuevo, abra issue `type:bug gap:legacy` (P1).

## Navigation

Previous: [fase-4-animal-crud.md](fase-4-animal-crud.md) | Next: [fase-6-salud-terapias-material.md](fase-6-salud-terapias-material.md)
