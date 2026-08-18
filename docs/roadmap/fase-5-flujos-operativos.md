[← Back to roadmap hub](../roadmap.md)

# Fase 5 — Voluntarios + Entradas + Acogidas + Adopciones (Feature 02)

Esta página posee el estado de la Fase 5: flujos operativos centrales con asistentes por pasos y snapshots históricos de personas. Fase en curso, ejecutada en cuatro sub-fases (5a INTAKE, 5b FOSTER, 5c ADOPT, 5d VOL).

## Estado

en curso — Fases 5a INTAKE y 5b FOSTER cerradas; Fases 5c ADOPT y 5d VOL en curso.

## Slices

| Sub-fase | Slice | Estado | Issue / PR |
|---|---|---|---|
| 5a INTAKE | Alta / edición / listado de entradas individuales | cerrado | #87, #88, #89 |
| 5a INTAKE | Entradas múltiples transaccional | en curso | `openspec/changes/intake-batch-entradas-transaccional/` |
| 5b FOSTER | `app/modules/foster/` (assignment + routes + service) | cerrado | ver `app/modules/foster/README.md` |
| 5b FOSTER | `feat(foster) override→estancia atomicity` | pendiente (follow-up) | #142 |
| 5b FOSTER | FOSTER-04 material assignment | pendiente | #46 |
| 5c ADOPT | ADOPT-01..02 (alta y edición de adopción) | cerrado | ver `app/modules/adopciones/` |
| 5c ADOPT | ADOPT-03 4-state follow-up state machine | pendiente | #49 |
| 5d VOL | VOL-01 modelo base de voluntarios | cerrado | #26 |
| 5d VOL | VOL-02..05 roles_voluntario junction + dedup + FK + active validation | pendiente | #35, #36, #37, #38 |

## Issues abiertas relacionadas

- #35 VOL-02 roles_voluntario junction table.
- #36 VOL-03 pipeline de deduplicación fuzzy.
- #37 VOL-04 migración FK free-text → FK estructurada.
- #38 VOL-05 active validation gate.
- #46 FOSTER-04 material assignment.
- #49 ADOPT-03 4-state follow-up state machine.
- #142 feat(foster) override→estancia atomicity (follow-up).

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

## Contributor checklist

- [ ] Si abre un slice de Fase 5, cite la sub-fase (5a/5b/5c/5d) y la issue correspondiente.
- [ ] Si implementa VOL-02..05, lea primero [legacy-volunteer-roles.md](../legacy-volunteer-roles.md) §1 y §2.1–§2.4.
- [ ] Si implementa entradas múltiples, siga el spec de `openspec/changes/intake-batch-entradas-transaccional/specs/`.
- [ ] Si descubre un campo contextual del legacy sin mapeo en el modelo nuevo, abra issue `type:bug gap:legacy` (P1).

## Navigation

Previous: [fase-4-animal-crud.md](fase-4-animal-crud.md) | Next: [fase-6-salud-terapias-material.md](fase-6-salud-terapias-material.md)
