# Propuesta: preservación de features web-only en round-trip web↔legacy

## Intención

Features web-only de APAP (`estado_actual_animal`, `eventos_ciclo_vida_animal`, `DNI` en `voluntarios`) pierden valores en cada sync de MIGRATION-01. Este change introduce shadow state + derivation engine + capa semántica + hook de reconciliación + CLI para cerrarlos.

## Alcance

**Dentro**: schema y CRUD `web_only_feature_shadow` (T1-T5); derivation `estado_actual_animal` con priority cascade (T6); hook `post_apply_diff()` (T7); CLI `apap-migrate reconcile` (T8); tests round-trip y perf (T9); docs.
**Fuera**: consola UX `needs_review` (resuelto a CLI interactivo en Q8); auto-detección de features web-only; tablas fuera de las 5 MIGRATION-01.

## Capacidades

**Nueva**: `web-only-feature-preservation`. **Modificadas**: ninguna.

## Enfoque

**Derivation Engine** aplica la priority cascade de `DameSituacion()` (`Funciones Generales.bas:1116-1321`) tras cada legacy→web write sobre las 4 tablas del ciclo de vida; marca `matched`/`divergent`/`needs_review`. **Shadow State** (tabla SQL `web_only_feature_shadow`) preserva valores sin source legacy (`DNI`, audit logs) con estrategias por columna en YAML (`preserve | fixed | derived`). **Capa semántica** (P0 explore §4.2) traduce diffs legacy a eventos en `animal_lifecycle_events`. Trigger: hook `post_apply_diff()` llamado por el applier. Tabla convive con `sync_state.json`. Bootstrap: VACÍA; primera ejecución popula filas `preserve`.

## Áreas afectadas

- `app/core/migration/shadow_state.py` (nuevo): CRUD atómico con `derived_value`/`derived_at`
- `app/core/migration/derivation.py` (nuevo): cascade + comparador
- `app/core/migration/semantic_events.py` (nuevo): diff→eventos
- `app/core/migration/reconcile.py` (modificado): hook `post_apply_diff` + dispatcher per-row
- `app/core/migration/cli.py` (modificado): `reconcile --check-only --interactive --table --since`
- `app/core/migration/applier.py` (modificado): invoca hook tras cada batch
- `mappings/*.yaml` + `__init__.py` (modificado): `web_only_strategy` por columna

## Riesgos

- **Stale state** (M): tests 25 casos parametrizados; diff canario staging.
- **Shadow crece** (M): tabla SQL con índices; cleanup 90 días.
- **Pérdida override** (B): `updated_at > last_legacy_snapshot_at` + divergencia → `needs_review`.
- **Conflicto MIGRATION-01** (B): módulos nuevos sin tocar firmas.

## Plan de rollback

Módulos nuevos sin efectos sobre MIGRATION-01 hasta que `applier.py` invoque el hook. Si falla: revertir merge; `reconcile --check-only` para diagnóstico; tabla aditiva (sin rollback destructivo).

## Dependencias

- MIGRATION-01 PR 4/6 (diff engine) mergeado a `main` y `staging`.
- Tablas `animal_current_state` y `animal_lifecycle_events` creadas en PR 1/6 de este change.
- `web_only_feature_shadow` con columnas `preserved_value`, `reconciliation_status`, `last_legacy_snapshot_at`, `derived_value`, `derived_at`.

## Criterios de éxito

- [ ] Schema + CRUD `web_only_feature_shadow` con pytest ≥80%.
- [ ] Derivation engine cubre 11 casos parametrizados (de `lifecycle-state-resolver-extraction.md §4`).
- [ ] Applier re-deriva y marca `reconciliation_status` en E2E.
- [ ] Round-trip preserva `DNI` (estrategia `preserve`); re-deriva estado sin perder shadow.
- [ ] Perf: 10k × 5 cols → O(1), medido <10s.

## Asumidas y resueltas

- **Q1** (DNI initial migration): NULL post-migración; el voluntario rellena en su primer acceso web (decidido 2026-06-21).
- **Q2** (detección de override): `updated_at > last_legacy_snapshot_at` + divergencia → `needs_review`.
- **Q3** (capa semántica): `semantic_events.py` propia; NO extensión del diff engine de MIGRATION-01.
- **Q4** (shadow state): tabla SQL con índices (volumen esperado 10k animales × 5 cols).
- **Q5** (configuración): YAML declarativo por columna, sin auto-detección.
- **Q6** (separación de stores): `sync_state.json` (infra) y `web_only_feature_shadow` (business) son archivos/tablas separadas.
- **Q7** (matched): si ambos producen el mismo valor, verdict = `matched`.
- **Q8** (resolución de needs_review): CLI interactivo `apap-migrate reconcile --interactive` (decidido 2026-06-21).
- **Q9** (diseño genérico): la solución cubre features web-only futuras vía YAML + derivation rules, sin cambios de código.

## Decisiones pendientes del usuario

(Ninguna — las 9 preguntas del explore están resueltas.)

## Discovery docs

`web-only-feature-preservation-explore.md` · `lifecycle-event-log-design.md` · `lifecycle-state-resolver-extraction.md` · `migration-helper-contracts.md` · `mappings/voluntario.yaml`.